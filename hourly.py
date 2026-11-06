import os
import html
import json
from pathlib import Path
import time
import email_alerts
from listing_time import describe as listed


def init(db):
    db.execute('CREATE TABLE IF NOT EXISTS hourly_state (id INTEGER PRIMARY KEY,payload TEXT)')
    db.execute('CREATE TABLE IF NOT EXISTS hourly_observations (id TEXT PRIMARY KEY,seen REAL,payload TEXT)')
    db.execute('CREATE TABLE IF NOT EXISTS immediate_emails (id TEXT,price INTEGER,status TEXT,attempts INTEGER,first_attempt REAL,last_attempt REAL,PRIMARY KEY(id,price))')


def state(db,now):
    init(db)
    row=db.execute('SELECT payload FROM hourly_state WHERE id=1').fetchone()
    return json.loads(row[0]) if row else dict(start=now,cutoff=None,instant_ids=[],last_attempt=0)


def save(db,s):db.execute('INSERT OR REPLACE INTO hourly_state VALUES (1,?)',(json.dumps(s),))


def viable(r):
    return (r.get('estimated_net_cents',0)>0 and r.get('sales_count',0)>=2 and
            r.get('recent_sales_count',0)>=1 and r.get('recent_sales_above_break_even',0)>=1 and
            r.get('discount',0)>=.02 and r.get('price_cents',0)>0 and
            not any(x in r.get('reason','').lower() for x in ('sold,','withdrawn','listing changed','not active')))


def score(r):return 100*r['estimated_net_cents']/r['price_cents']


def describe(r):
    p=r.get('paper_purchase') or {}
    extra=('\nPaper-purchase assessment: '+p.get('status','watch')+'; '+ '; '.join(p.get('reasons',[]))) if p else ''
    if 'estimated_roi' in p:
        extra+=f"\nCompetitive net: ${p['estimated_net_cents']/100:.2f} ({p['estimated_roi']:.2%}); direct sales {p['direct_sales']}, adjusted {p['adjusted_sales']}."
    return (f"{r.get('name','Unknown')} | ${r.get('price_cents',0)/100:.2f}\n"
            f"Estimated net: ${r.get('estimated_net_cents',0)/100:.2f}; estimated ROI: {score(r):.2f}%\n"
            f"Sales: {r.get('sales_count',0)} / recent: {r.get('recent_sales_count',0)}; observed: {r.get('time','unknown')}\n"
            f"{listed(r)}\nAssessment: {r.get('reason','')}\n"+'; '.join(r.get('warnings',[]))+'\n'+r.get('url','')+extra)


def remember(db,r,c,now=None):
    now=time.time() if now is None else now;s=state(db,now)
    db.execute('INSERT OR REPLACE INTO hourly_observations VALUES (?,?,?)',(r['id'],now,json.dumps(r)))
    if viable(r) and r.get('eligible') and c['email_enabled']:
        immediate(db,r,now)
    save(db,s)


def immediate(db,r,now):
    lid=r['id'];price=r['price_cents']


    if db.execute("SELECT 1 FROM immediate_emails WHERE id=? AND status='sent' AND price<=?",(lid,price)).fetchone():return
    previous=db.execute('SELECT status,attempts,first_attempt,last_attempt FROM immediate_emails WHERE id=? AND price=?',(lid,price)).fetchone()
    if previous and (previous[1]>=3 or now-previous[3]<300 or now-previous[2]>900):return
    attempts=(previous[1]+1) if previous else 1;first=previous[2] if previous else now
    db.execute('INSERT OR REPLACE INTO immediate_emails VALUES (?,?,?,?,?,?)',(lid,price,'attempting',attempts,first,now))
    from runtime_log import event
    try:
        email_alerts.send('CSFloat opportunity — '+r.get('name','item'),
            'PAPER ONLY — no purchase. Validated just before this alert; availability can change.\n\n'+describe(r),os.environ.get('SCOUT_EMAIL_TO','user1@example.com'))
    except Exception as e:
        db.execute("UPDATE immediate_emails SET status='failed' WHERE id=? AND price=?",(lid,price))
        event('opportunity_email_failed',listing_id=lid,price_cents=price,attempt=attempts,error_type=type(e).__name__)
        print('Opportunity email failed ('+type(e).__name__+'); retry requires fresh evaluation.',flush=True)
    else:
        db.execute("UPDATE immediate_emails SET status='sent' WHERE id=? AND price=?",(lid,price))
        event('opportunity_email_accepted',listing_id=lid,price_cents=price,attempt=attempts)
        print('Opportunity email accepted by SMTP: '+r.get('name',lid),flush=True)


def tick(db,c,now=None):
    now=time.time() if now is None else now;s=state(db,now)
    if c['email_enabled']:
        for lid,price in db.execute("SELECT id,price FROM immediate_emails WHERE status IN ('failed','attempting') AND attempts<3 AND last_attempt<=? AND first_attempt>=?",(now-300,now-900)).fetchall():
            db.execute("UPDATE scan_items SET state='queued',reason='fresh evaluation required for email retry' WHERE id=? AND price=? AND mode='paper_review_v4' AND state='qualified'",(lid,price))
    observed=[json.loads(x[0]) for x in db.execute('SELECT payload FROM hourly_observations WHERE seen>=?',(max(s['start'],now-3600),))]
    supported=sorted([r for r in observed if viable(r)],key=lambda r:(score(r),r.get('recent_sales_count',0)),reverse=True)[:5]
    provisional=sorted([r for r in observed if not viable(r)],key=lambda r:r.get('discount',-1),reverse=True)[:max(0,5-len(supported))]
    leads=[]
    if len(supported)+len(provisional)<5:
        for lid,price,raw in db.execute("SELECT id,price,payload FROM scan_items WHERE mode='paper_review_v4' AND state='queued' AND added>=? ORDER BY score DESC LIMIT 5",(now-3600,)):
            listing=json.loads(raw)
            leads.append(dict(id=lid,name=listing.get('item',{}).get('market_hash_name','Unknown'),price_cents=price,created_at=listing.get('created_at'),url='https://csfloat.com/item/'+lid))
    lines=['PAPER HOURLY REVIEW — no real purchases. Simulated positions: paper-portfolio.html.',
           'Ranked by estimated net ROI among observed candidates, not the whole market. Prices/availability must be rechecked.',
           f'Supported options: {len(supported)} (target 3–7, never a guarantee).']
    if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='paper_wallet'").fetchone():
        wallet=db.execute('SELECT cash FROM paper_wallet WHERE id=1').fetchone()
        positions=db.execute("SELECT COUNT(*) FROM paper_positions WHERE status!='closed'").fetchone()[0]
        if wallet:lines.append(f'Paper portfolio: ${wallet[0]/100:.2f} virtual cash available; {positions} open/settling positions. See paper-portfolio.html for simulated buys and the best observed in 24 hours.')
    for r in supported:lines.append('\n'+describe(r))
    if provisional:
        lines.append('\nINCOMPLETE OR REJECTED — not supported good deals:')
        for r in provisional:lines.append(f"{r.get('name','Unknown')} | {r.get('reason','No completed assessment')}\n{listed(r)}\n{r.get('url','')}")
    if leads:
        lines.append('\nUNRESEARCHED — reference-ranked only:')
        for r in leads[:max(0,5-len(supported)-len(provisional))]:lines.append(f"{r['name']} | ${r['price_cents']/100:.2f}\n{listed(r)}\n{r['url']}")
    if not observed and not leads:lines.append('No fresh observations this hour. Check quota/status messages; no deals can be ranked.')
    text='\n'.join(lines)
    Path('hourly-best.txt').write_text(text,encoding='utf-8')
    Path('hourly-best.json').write_text(json.dumps(dict(start=s['start'],generated_at=now,supported=supported,provisional=provisional,unresearched=leads),indent=2),encoding='utf-8')
    Path('hourly-best.html').write_text('<!doctype html><meta charset="utf-8"><title>Hourly shortlist</title><h1>Hourly shortlist</h1><pre style="white-space:pre-wrap;font:16px system-ui">'+html.escape(text)+'</pre>',encoding='utf-8')
    save(db,s)
    if now-s['start']<3600:return
    if c['email_enabled']:
        if now-s['last_attempt']<300:return
        s['last_attempt']=now;save(db,s)
        try:email_alerts.send('CSFloat — best observed this hour',text,os.environ.get('SCOUT_EMAIL_TO','user1@example.com'))
        except Exception as e:
            print('Hourly email failed ('+type(e).__name__+'); report saved; retry after five minutes.',flush=True);return
    with Path('hourly-archive.jsonl').open('a',encoding='utf-8') as f:f.write(json.dumps(dict(end=now,supported=supported,provisional=provisional))+'\n')
    s.update(start=now,cutoff=min(map(score,supported)) if supported else None,instant_ids=[],last_attempt=0);save(db,s)
    db.execute('DELETE FROM hourly_observations WHERE seen<?',(now-86400,))
    print(f'Hourly review saved: {len(supported)} supported options. See hourly-best.html.',flush=True)
