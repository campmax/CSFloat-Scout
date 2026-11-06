pass                                                                                      
import json
import math
import time
from pathlib import Path
from scout import Stop, acquisition_cost
from personal_paper import markdown

NAME = '★ Sport Gloves | Amphibious (Field-Tested)'
MAX_COST = 33000
MIN_MARKDOWN = .10
MIN_FLOAT, MAX_FLOAT = .15, .20


def init(db):
    db.execute('CREATE TABLE IF NOT EXISTS personal_live_order (slot INTEGER PRIMARY KEY CHECK(slot=1), payload TEXT NOT NULL, mailed INTEGER DEFAULT 0, mail_at REAL DEFAULT 0)')


def status(db):
    init(db)
    row = db.execute('SELECT payload FROM personal_live_order WHERE slot=1').fetchone()
    return json.loads(row[0]) if row else None


def put(db, r):
    db.execute('UPDATE personal_live_order SET payload=? WHERE slot=1', (json.dumps(r),))


def eligible(raw, c):
    if not isinstance(raw, dict): return False
    item = raw.get('item') or {}
    f, price = item.get('float_value'), raw.get('price')
    d, _, _ = markdown(raw)
    return (str(raw.get('id', '')).isdigit() and raw.get('state') == 'listed' and
            raw.get('type') == 'buy_now' and raw.get('is_seller') is not True and
            item.get('market_hash_name') == NAME and item.get('def_index') is not None and
            item.get('paint_index') is not None and type(f) in (int, float) and
            math.isfinite(f) and MIN_FLOAT <= f <= MAX_FLOAT and
            type(price) is int and 0 < price <= MAX_COST and
            acquisition_cost(price, c) <= MAX_COST and d is not None and d + 1e-12 >= MIN_MARKDOWN)


def validate_costs(c):
    fee, extra = c.get('buy_fee_rate'), c.get('extra_cost_cents')
    if type(fee) not in (int, float) or not math.isfinite(fee) or not 0 <= fee <= 1 or type(extra) is not int or extra < 0:
        raise Stop('Invalid buying fee configuration; live buying disabled.')


def attempt(db, api, rows, c, p, session_end):
    if not p.get('_live') or status(db): return
    validate_costs(c)
    candidates = sorted((r for r in rows if eligible(r, c)), key=lambda r: markdown(r)[0], reverse=True)
    if not candidates: return
                                                                                               
    if api.budget_end is not None and api.budget_end - api.request_count < 4: return
    observed = candidates[0]
    balance = api.available_balance()
    fresh = api.detail(observed['id'])
    identity = ('market_hash_name','def_index','paint_index','float_value','paint_seed','asset_id')
    if not eligible(fresh, c) or str(fresh['id']) != str(observed['id']): return
    if any(fresh['item'].get(k) != observed['item'].get(k) for k in identity): return
    if fresh['price'] > observed['price'] or acquisition_cost(fresh['price'], c) > balance: return
    verified_at = time.time()
    r = dict(id=str(fresh['id']), name=NAME, price_cents=fresh['price'],
             estimated_total_cents=acquisition_cost(fresh['price'], c), float=fresh['item']['float_value'],
             reference_markdown=markdown(fresh)[0], created_at=fresh.get('created_at'),
             time=verified_at, status='unknown', url='https://csfloat.com/item/'+str(fresh['id']),
             message='Order intent saved. Outcome unknown; no automatic retry or second purchase.')
                                                                            
    def before_write():
        if Path('STOP').exists() or time.time() >= session_end:
            raise Stop('STOP/session end reached before purchase; no order submitted.')
        if time.time() - verified_at > 60:
            raise Stop('Live detail check expired before submission; no order submitted.')
        db.execute('BEGIN IMMEDIATE')
        try:
            if status(db): raise Stop('Personal order already reserved; no second purchase.')
            db.execute('INSERT INTO personal_live_order(slot,payload) VALUES (1,?)', (json.dumps(r),))
            db.execute('COMMIT')
        except BaseException:
            db.execute('ROLLBACK')
            raise
    api.before_write = before_write
    try:
        response = api.buy(fresh['id'], fresh['price'])
        if not isinstance(response, dict) or response.get('message') != 'all listings purchased':
            raise Stop('Purchase response ambiguous; inspect CSFloat purchases. No automatic retry.')
        r.update(status='acknowledged', message='CSFloat acknowledged the purchase. Balance reconciliation pending; delivery not confirmed.')
        put(db, r)
        after = api.available_balance()
        if after > balance - fresh['price']:
            raise Stop('Purchase acknowledged but debit not reconciled. Inspect CSFloat; no second purchase.')
        r.update(status='confirmed', message='CSFloat acknowledged purchase and balance debit was observed. Verify and accept the seller Steam trade manually; delivery is not confirmed.')
        put(db, r)
    except BaseException:
                                                                                     
        raise
    finally:
        api.before_write = None
        report(db)
        flush_mail(db, p)
    print('PERSONAL LIVE PURCHASE: '+r['status']+' | $'+format(r['price_cents']/100,'.2f')+' | '+r['url'], flush=True)


def report(db):
    r = status(db)
    Path('personal-live.json').write_text(json.dumps(dict(generated_at=time.time(),order=r,
        purchase_limit=1,buying_locked=bool(r)),indent=2),encoding='utf-8')
    return r


def flush_mail(db, p):
    import email_alerts
    from listing_time import describe
    r = status(db)
    if not r: return
    mailed, last = db.execute('SELECT mailed,mail_at FROM personal_live_order WHERE slot=1').fetchone()
    if mailed or time.time()-last < 300: return
    db.execute('UPDATE personal_live_order SET mail_at=? WHERE slot=1',(time.time(),))
    body=(f"PERSONAL LIVE ORDER: {r['status']}\n{r['message']}\n"
          f"{r['name']}\nPrice ${r['price_cents']/100:.2f}; float {r['float']:.6f}\n"
          f"API-reference markdown {r['reference_markdown']:.2%} (website badge may differ).\n"
          f"{describe(r)}\n{r['url']}\nAutomatic buying is now locked, including after restart. Reports continue.\n"
          'Do not buy again if outcome is unknown: check your CSFloat purchase history first.')
    try: email_alerts.send('Personal LIVE '+r['status']+' — Amphibious',body,p['email_recipient'])
    except Exception as error: print('Live receipt email failed: '+type(error).__name__+'; saved for retry.',flush=True)
    else: db.execute('UPDATE personal_live_order SET mailed=1 WHERE slot=1')
