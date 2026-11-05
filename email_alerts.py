"""SMTP alerts. Configuration through environment; encrypted transport only."""
from email.message import EmailMessage
import os
import json
import smtplib
import ssl
import time
import uuid
from listing_time import describe as listed


def settings():
    names = ('SCOUT_SMTP_HOST','SCOUT_SMTP_USER','SCOUT_SMTP_PASSWORD','SCOUT_EMAIL_FROM')
    values = {name: os.environ.get(name,'').strip() for name in names}
    if not all(values.values()):
        raise ValueError('Email enabled: set SMTP host/user/password and FROM environment variables.')
    values['port'] = int(os.environ.get('SCOUT_SMTP_PORT','465'))
    values['mode'] = os.environ.get('SCOUT_SMTP_MODE','ssl')
    if values['mode'] not in ('ssl','starttls'):
        raise ValueError('SMTP mode must be ssl or starttls.')
    return values


def send(subject, text, recipient, thread_headers=None):
    s = settings()
    message = EmailMessage()
    message['From'], message['To'] = s['SCOUT_EMAIL_FROM'], recipient
    message['Subject'] = subject
    message['Message-ID'] = (thread_headers or {}).get('Message-ID',f'<{uuid.uuid4()}@csfloat-scout.local>')
    for header in ('In-Reply-To','References'):
        if thread_headers and header in thread_headers:message[header]=thread_headers[header]
    message.set_content(text)
    context = ssl.create_default_context()
    if s['mode'] == 'ssl':
        client = smtplib.SMTP_SSL(s['SCOUT_SMTP_HOST'],s['port'],timeout=20,context=context)
    else:
        client = smtplib.SMTP(s['SCOUT_SMTP_HOST'],s['port'],timeout=20)
    with client:
        if s['mode'] == 'starttls':
            client.ehlo(); client.starttls(context=context); client.ehlo()
        client.login(s['SCOUT_SMTP_USER'], s['SCOUT_SMTP_PASSWORD'])
        refused = client.send_message(message)
        if refused:
            raise RuntimeError('Recipient refused')


def recipients(c):
    addresses = c['email_recipients']
    if not isinstance(addresses,list) or not addresses or any(not isinstance(a,str) or a.count('@') != 1 or any(ch.isspace() for ch in a) or ',' in a or ';' in a for a in addresses):
        raise ValueError('email_recipients must contain individual email addresses.')
    return list(dict.fromkeys(addresses))


def notify(db, record, c):
    if c['email_enabled']:
        for recipient in recipients(c):
            _notify_one(db, record, c, recipient)


def _notify_one(db, record, c, recipient):
    if not c['email_enabled']:
        return
    db.execute('CREATE TABLE IF NOT EXISTS emails (id TEXT PRIMARY KEY, last_attempt REAL, attempts INTEGER, status TEXT)')
    key = record['id'] + ':' + recipient
    now = time.time()
    db.execute('BEGIN IMMEDIATE')
    try:
        previous = db.execute('SELECT last_attempt,attempts,status FROM emails WHERE id=?',(key,)).fetchone()
        if previous and (previous[2]=='sent' or previous[1]>=3 or now-previous[0]<c['email_retry_seconds']):
            db.execute('COMMIT'); return
        recent = db.execute('SELECT COUNT(*) FROM emails WHERE last_attempt>?',(now-86400,)).fetchone()[0]
        if not previous and recent >= c['max_emails_per_day']*len(recipients(c)):
            db.execute('COMMIT'); return
        db.execute('INSERT INTO emails VALUES (?,?,1,?) ON CONFLICT(id) DO UPDATE SET last_attempt=excluded.last_attempt,attempts=attempts+1,status=excluded.status',
                   (key,now,'attempting'))
        db.execute('COMMIT')
    except BaseException:
        db.execute('ROLLBACK'); raise
    weekly='UNVERIFIED' if record.get('weekly_change') is None else f"{record['weekly_change']:.1%}"
    drawdown='UNVERIFIED' if record.get('weekly_drawdown') is None else f"{record['weekly_drawdown']:.1%}"
    base_discount=record.get('csfloat_base_discount',record.get('csfloat_discount'))
    predicted_discount=record.get('csfloat_predicted_discount')
    refs='API base reference: '+('unavailable' if base_discount is None else f'{base_discount:.1%}')+'; float-adjusted reference: '+('unavailable' if predicted_discount is None else f'{predicted_discount:.1%}')
    model=record.get('float_model',{})
    float_text=f"Float model: {model.get('status','not used')}; adjusted comparisons: {sum(a.get('accepted_after_outlier_check',False) for a in record.get('float_adjustments',[]))}.\n"
    warning_text='\n'.join(record.get('warnings',[])) or 'None recorded.'
    text = (f"MANUAL PURCHASE ALERT — no purchase was made by this alert.\n\n{record['name']}\n"
            f"Tier: {record.get('tier','paper')}\nPrice: ${record['price_cents']/100:.2f}\nSales-based reference value: ${record['fair_cents']/100:.2f}\n"
            f"Uncertainty scenario value: ${record.get('uncertainty_fair_cents',record['fair_cents'])/100:.2f}\n"
            f"{refs} (website badge may differ)\n"
            f"Independent discount: {record['discount']:.1%}\nSeven-day change: {weekly}\n"
            f"Recent drawdown: {drawdown}\nStress scenario: another {record['stress_drop']:.1%} drop\n"
            f"Modeled stressed profit: ${record['stressed_net_cents']/100:.2f} ({record['stressed_roi']:.1%})\n"
            f"{float_text}Review warnings: {warning_text}\n\n"
            f"{listed(record)}\nObserved: {record['time']}\n{record['url']}\n\n"
            "Listing availability and prices can change before you read this. Recheck before buying.\n"
            "After a manual purchase, use --record-manual ID PRICE_CENTS so the capital ledger includes it.\n"
            "These are modeled margins, not guaranteed profits.")
    try:
        send(f"CSFloat {record.get('tier','paper')}: {record['discount']:.0%} off — {record['name']}",text,recipient)
    except Exception as error:
        db.execute("UPDATE emails SET status='failed' WHERE id=?",(key,))
        # Do not log exception bodies: mail providers may include account details.
        print(f'Email failed ({type(error).__name__}); console alert remains available. Retry only on a fresh eligible evaluation.',flush=True)
    else:
        db.execute("UPDATE emails SET status='sent' WHERE id=?",(key,))


def init_receipts(db):
    db.execute('CREATE TABLE IF NOT EXISTS purchase_emails (id TEXT, recipient TEXT, payload TEXT, status TEXT, attempts INTEGER, last_attempt REAL, PRIMARY KEY(id,recipient))')


def queue_purchase(db, record, c):
    # Caller inserts this in the same transaction as confirming the purchase.
    for recipient in recipients(c):
        db.execute('INSERT OR IGNORE INTO purchase_emails VALUES (?,?,?,?,0,0)',
                   (record['id'],recipient,json.dumps(record),'pending'))


def flush_purchases(db, c):
    if not c['email_enabled']:
        return
    init_receipts(db)
    now = time.time()
    pending = db.execute("SELECT id,recipient,payload FROM purchase_emails WHERE status NOT IN ('sent','cancelled') AND last_attempt<=?", (now-c['email_retry_seconds'],)).fetchall()
    for listing_id,recipient,payload in pending:
        if recipient not in recipients(c):
            db.execute("UPDATE purchase_emails SET status='cancelled' WHERE id=? AND recipient=?",(listing_id,recipient))
            continue  # Recipient removed: suppress previously queued receipts too.
        # Claim each recipient durably. A crashed SMTP send may be retried later,
        # since delivery cannot be proven after a network timeout.
        result = db.execute("UPDATE purchase_emails SET last_attempt=?,attempts=attempts+1,status='sending' WHERE id=? AND recipient=? AND status!='sent' AND last_attempt<=?",
                            (now,listing_id,recipient,now-c['email_retry_seconds']))
        if not result.rowcount:
            continue
        r=json.loads(payload)
        body=(f"PURCHASE ACKNOWLEDGED — do not buy this listing again.\n\n{r['name']}\n"
              f"{listed(r)}\nPrice: ${r['price_cents']/100:.2f}\n{r['url']}\nRecorded: {r['time']}\n\n"
              "CSFloat acknowledged the purchase and the account balance debit was observed. "
              "Delivery and profit are NOT confirmed. Wait for the seller's Steam trade offer, "
              "then verify the item and accept the trade manually. This email does not mean a trade offer has arrived. "
              "Open Steam or CSFloat directly; do not share credentials or confirmation codes.\n")
        try:
            send('CSFloat purchased: '+r['name'],body,recipient)
        except Exception as error:
            db.execute("UPDATE purchase_emails SET status='failed' WHERE id=? AND recipient=?",(listing_id,recipient))
            print(f'Purchase email failed ({type(error).__name__}); saved for retry. Purchase will NOT be retried.',flush=True)
        else:
            db.execute("UPDATE purchase_emails SET status='sent' WHERE id=? AND recipient=?",(listing_id,recipient))
