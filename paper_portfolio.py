import os
"""Prospective simulation only. This module has no API or real-order capability."""
import copy
import datetime as dt
import html
import json
import math
from pathlib import Path
import statistics
import time
from listing_time import describe as listed

DEFAULTS = dict(enabled=True, initial_cash_cents=100000, min_roi=.03,
                min_net_cents=200, min_direct_sales=2, min_direct_recent=1,
                min_total_sales=3, stress_drop=.03, hold_days=7,
                settlement_days=8, confirmation_max_seconds=30,
                evidence_max_seconds=3600, competition_max_seconds=120)


def settings(c):
    p=dict(DEFAULTS, **c.get('paper_portfolio',{}))
    for key in ('initial_cash_cents','min_net_cents','min_direct_sales','min_direct_recent','min_total_sales'):
        if type(p[key]) is not int or p[key]<1:raise ValueError('Invalid paper_portfolio '+key)
    for key in ('min_roi','stress_drop'):
        if type(p[key]) not in (int,float) or not math.isfinite(p[key]) or not 0<=p[key]<1:raise ValueError('Invalid paper_portfolio '+key)
    for key in ('hold_days','settlement_days','confirmation_max_seconds','evidence_max_seconds','competition_max_seconds'):
        if type(p[key]) not in (int,float) or not math.isfinite(p[key]) or p[key]<=0:raise ValueError('Invalid paper_portfolio '+key)
    return p


def direct_tolerance(item):
    """Local tolerances narrow near wear boundaries and ultra-low FN floats."""
    f=item['float_value'];name=item.get('market_hash_name','')
    bands=[('Factory New',0,.07,.003),('Minimal Wear',.07,.15,.008),
           ('Field-Tested',.15,.38,.015),('Well-Worn',.38,.45,.01),('Battle-Scarred',.45,1,.02)]
    for label,lo,hi,cap in bands:
        if '('+label+')' in name:
            if not lo<=f<=hi:return 0
            return min(cap,max(.000001,min(f-lo,hi-f)*.5))
    return .002


def assess(candidate, asks, sales, c, now=None):
    """Independent purchase-quality screen; never changes broad alert eligibility."""
    from review import collect_sales,match_reason
    from scout import timestamp,cents
    from float_model import FloatModel
    now=time.time() if now is None else now;p=settings(c)
    item=candidate['item'];tol=direct_tolerance(item)
    local_c=copy.deepcopy(c);local_c['paper_review']['float_tolerance']=tol
    local_c['paper_review']['prefer_direct']=True
    kept,recent,evidence=collect_sales(candidate,sales,local_c,now)
    raw_by_id={str(s.get('id')):s for s in sales if isinstance(s,dict)}
    direct=[s for s in kept if match_reason(candidate,raw_by_id[str(s['id'])],tol) is None]
    direct_recent=[s for s in direct if now-timestamp(s['sold_at'])<=3*86400]
    reasons=[]
    r=dict(status='watch',reasons=reasons,direct_tolerance=tol,direct_sales=len(direct),
           direct_recent_sales=len(direct_recent),adjusted_sales=len(kept)-len(direct),
           total_sales=len(kept),float_value=item['float_value'],weekly_trend_verified=False,policy=dict(p))
    if not kept:
        reasons.append('No locally supported comparable sales');return r
    if item.get('stickers') or item.get('keychains') or item.get('market_hash_name','').startswith('Souvenir ') or any(w.lower() in item.get('market_hash_name','').lower() for w in c['exclude_name_contains']):
        reasons.append('Decoration/pattern premium requires manual review')
    if len(direct)<p['min_direct_sales'] or len(direct_recent)<p['min_direct_recent'] or len(kept)<p['min_total_sales']:
        reasons.append('Thin local liquidity: experimental watch only')
    # Use the same independent local model for asks; never fit a curve to asking prices.
    clean=[];seen=set()
    for s in sales:
        if not isinstance(s,dict):continue
        sid=str(s.get('id'));sold=timestamp(s.get('sold_at'));si=s.get('item') or {}
        if (sid not in seen and s.get('id') and s.get('state')=='sold' and cents(s.get('price')) and
            0<=now-sold<=7*86400 and match_reason(candidate,s,1) is None and
            not si.get('stickers') and not si.get('keychains')):
            seen.add(sid);clean.append(s)
    model=FloatModel(clean,item['float_value'],timestamp)
    ask_values=[];ask_audit=[]
    for a in asks:
        ai=a.get('item') or {}
        if (a.get('id')==candidate.get('id') or a.get('state')!='listed' or a.get('type')!='buy_now' or
            not cents(a.get('price')) or match_reason(candidate,a,1) is not None or ai.get('stickers') or ai.get('keychains')):continue
        if match_reason(candidate,a,tol) is None:
            value=a['price'];kind='direct'
        else:
            adjustment,_=model.adjust(a)
            if adjustment is None:continue
            value=adjustment['uncertainty_price_cents'];kind='float_adjusted_lower_scenario'
        ask_values.append(value);ask_audit.append(dict(id=a.get('id'),raw_price_cents=a['price'],equivalent_price_cents=value,method=kind))
    patient=math.floor(min(statistics.median([s['price'] for s in kept]),statistics.median([s['price'] for s in recent or kept])))
    conservative=math.floor(min(statistics.median([s.get('uncertainty_price_cents',s['price']) for s in kept]),statistics.median([s.get('uncertainty_price_cents',s['price']) for s in recent or kept])))
    # Undercut one cent; ask availability isn't a promise of executable resale.
    competitive=min(conservative,min(ask_values)-1) if ask_values else conservative
    if not ask_values:reasons.append('No supported competing ask: competitive exit unverified')
    cost=math.ceil(candidate['price']*(1+c['buy_fee_rate']))+c['extra_cost_cents']
    multiplier=(1-c['resale_fee_rate'])*(1-c['withdrawal_fee_rate'])*.99
    net=math.floor(competitive*multiplier)-cost
    daily={}
    for s in kept:daily.setdefault(int(timestamp(s['sold_at'])//86400),[]).append(s['price'])
    days=sorted(daily);weekly=None
    if len(days)>=5 and days[-1]-days[0]>=6:
        medians=[statistics.median(daily[d]) for d in days]
        weekly=statistics.median(medians[-2:])/statistics.median(medians[:2])-1
    drop=max(p['stress_drop'],max(0,-weekly) if weekly is not None else 0)
    downside=math.floor(competitive*(1-drop)*multiplier)-cost
    profitable_direct=sum(s['price']*multiplier>cost for s in direct_recent)
    if profitable_direct<p['min_direct_recent']:reasons.append('Insufficient recent direct sales above break-even')
    if net<p['min_net_cents'] or net/cost<p['min_roi']:reasons.append(f"Competitive net below configured {p['min_roi']:.1%} ROI / ${p['min_net_cents']/100:.2f} floors")
    if downside<0:reasons.append('Downside scenario loses money')
    r.update(status='paper_buy_candidate' if not reasons else 'watch',cost_cents=cost,
             fees=dict(buy=c['buy_fee_rate'],sell=c['resale_fee_rate'],withdrawal=c['withdrawal_fee_rate'],slippage=.01,fixed_cents=c['extra_cost_cents']),
             patient_resale_cents=patient,patient_net_cents=math.floor(patient*multiplier)-cost,
             competitive_resale_cents=competitive,estimated_net_cents=net,estimated_roi=net/cost,
             stressed_net_cents=downside,stress_drop=drop,weekly_change_estimate=weekly,
             weekly_trend_verified=weekly is not None,comparable_asks=ask_audit,
             direct_profitable_recent=profitable_direct,assumptions='Estimates, not guaranteed returns. 1% resale slippage; current configured fees. Weekly trend '+('estimated from normalized completed sales.' if weekly is not None else 'unknown; downside is an assumed scenario.'))
    return r


def init(db,c):
    p=settings(c)
    db.execute('CREATE TABLE IF NOT EXISTS paper_wallet (id INTEGER PRIMARY KEY CHECK(id=1),initial INTEGER,cash INTEGER)')
    db.execute('INSERT OR IGNORE INTO paper_wallet VALUES (1,?,?)',(p['initial_cash_cents'],p['initial_cash_cents']))
    db.execute('CREATE TABLE IF NOT EXISTS paper_positions (id TEXT PRIMARY KEY,opened REAL,cost INTEGER,unlock REAL,status TEXT,proceeds INTEGER,settle REAL,payload TEXT)')
    db.execute('CREATE TABLE IF NOT EXISTS paper_decisions (id TEXT,price INTEGER,decided REAL,payload TEXT,PRIMARY KEY(id,price))')
    db.execute('CREATE TABLE IF NOT EXISTS paper_mail (id TEXT PRIMARY KEY,payload TEXT,status TEXT,attempts INTEGER,last_attempt REAL)')
    db.execute('CREATE TABLE IF NOT EXISTS paper_marks (id TEXT PRIMARY KEY,observed REAL,payload TEXT)')


def consider(db,record,c,confirmed_at,now=None):
    now=time.time() if now is None else now;init(db,c);p=settings(c)
    r=copy.deepcopy(record.get('paper_purchase') or {})
    if not r:return None
    previous=db.execute('SELECT payload FROM paper_decisions WHERE id=? AND price=?',(record['id'],record['price_cents'])).fetchone()
    if previous and json.loads(previous[0])['paper_purchase']['status'] in ('paper_bought','already_owned'):return None
    status=r.get('status','watch');reasons=list(r.get('reasons',[]))
    if status=='paper_buy_candidate':
        if confirmed_at is None or not 0<=now-confirmed_at<=p['confirmation_max_seconds']:
            status='missed_fill';reasons.append('No fresh active listing confirmation')
        elif (record.get('paper_history_age_seconds') if record.get('paper_history_age_seconds') is not None else math.inf)>p['evidence_max_seconds'] or (record.get('paper_competition_age_seconds') if record.get('paper_competition_age_seconds') is not None else math.inf)>p['competition_max_seconds']:
            status='watch';reasons.append('History or competing asks are stale')
        elif not record.get('eligible'):
            status='missed_fill';reasons.append('Listing no longer eligible at confirmation')
    db.execute('BEGIN IMMEDIATE')
    try:
        if status=='paper_buy_candidate':
            if db.execute('SELECT 1 FROM paper_positions WHERE id=?',(record['id'],)).fetchone():status='already_owned'
            elif db.execute('SELECT cash FROM paper_wallet WHERE id=1').fetchone()[0]<r['cost_cents']:status='insufficient_virtual_cash'
            else:
                status='paper_bought'
                payload=dict(record,paper_purchase=dict(r,status=status,reasons=reasons),paper_confirmed_at=confirmed_at)
                db.execute('UPDATE paper_wallet SET cash=cash-? WHERE id=1',(r['cost_cents'],))
                db.execute('INSERT INTO paper_positions VALUES (?,?,?,?,?,?,?,?)',(record['id'],now,r['cost_cents'],now+p['hold_days']*86400,'held',None,None,json.dumps(payload)))
                db.execute('INSERT INTO paper_mail VALUES (?,?,?,0,0)',(record['id'],json.dumps(payload),'pending'))
        r.update(status=status,reasons=reasons)
        saved=dict(record,paper_purchase=r,decision_at=now)
        db.execute('INSERT OR REPLACE INTO paper_decisions VALUES (?,?,?,?)',(record['id'],record['price_cents'],now,json.dumps(saved)))
        db.execute('COMMIT')
    except Exception:
        db.execute('ROLLBACK');raise
    if status=='paper_bought':print(f"PAPER BUY — {record['name']} | ${r['cost_cents']/100:.2f} | estimated net ${r['estimated_net_cents']/100:.2f} ({r['estimated_roi']:.1%}); no real purchase.",flush=True)
    return r


def record_sale(db,c,lid,price,now=None):
    """Explicit manual simulation assumption, not inferred from disappearance."""
    now=time.time() if now is None else now;init(db,c)
    if type(price) is not int or price<=0:raise ValueError('Sale cents must be a positive integer')
    db.execute('BEGIN IMMEDIATE')
    try:
        row=db.execute('SELECT unlock,status,payload FROM paper_positions WHERE id=?',(lid,)).fetchone()
        if not row or row[1]!='held':raise ValueError('No open paper position with that ID')
        if now<row[0]:raise ValueError('Simulated acquisition hold has not ended')
        proceeds=math.floor(price*(1-c['resale_fee_rate'])*(1-c['withdrawal_fee_rate']))
        payload=json.loads(row[2]);payload['simulated_sale']=dict(gross_cents=price,sold_at=now,source='user-assumed paper fill, NOT observed execution')
        db.execute("UPDATE paper_positions SET status='settling',proceeds=?,settle=?,payload=? WHERE id=?",(proceeds,now+payload['paper_purchase'].get('policy',settings(c))['settlement_days']*86400,json.dumps(payload),lid))
        db.execute('COMMIT')
    except Exception:db.execute('ROLLBACK');raise


def settle(db,now):
    db.execute('BEGIN IMMEDIATE')
    try:
        for lid,proceeds in db.execute("SELECT id,proceeds FROM paper_positions WHERE status='settling' AND settle<=?",(now,)).fetchall():
            db.execute('UPDATE paper_wallet SET cash=cash+? WHERE id=1',(proceeds,))
            db.execute("UPDATE paper_positions SET status='closed' WHERE id=?",(lid,))
        db.execute('COMMIT')
    except Exception:db.execute('ROLLBACK');raise


def flush_mail(db,c,now):
    if not c.get('email_enabled'):return
    import email_alerts
    from runtime_log import event
    for lid,raw,attempts,last in db.execute("SELECT id,payload,attempts,last_attempt FROM paper_mail WHERE status!='sent' AND attempts<6").fetchall():
        if attempts and now-last<300:continue
        row=json.loads(raw);p=row['paper_purchase']
        db.execute("UPDATE paper_mail SET status='attempting',attempts=attempts+1,last_attempt=? WHERE id=?",(now,lid))
        try:
            email_alerts.send('CSFloat PAPER BUY — '+row['name'],
                f"SIMULATED ONLY — no real purchase. Recorded at {row.get('time')}.\n{row['name']}\nVirtual cost: ${p['cost_cents']/100:.2f}\nEstimated competitive net: ${p['estimated_net_cents']/100:.2f} ({p['estimated_roi']:.2%})\nDownside net: ${p['stressed_net_cents']/100:.2f}\nDirect sales: {p['direct_sales']}; adjusted: {p['adjusted_sales']}\n{p['assumptions']}\n{listed(row)}\n{row['url']}\nSee paper-portfolio.html. Delivery may be delayed; do not assume availability.",os.environ.get('SCOUT_EMAIL_TO','user1@example.com'))
        except Exception as e:event('paper_buy_email_failed',listing_id=lid,error_type=type(e).__name__)
        else:
            db.execute("UPDATE paper_mail SET status='sent' WHERE id=?",(lid,));event('paper_buy_email_accepted',listing_id=lid)


def tick(db,c,now=None):
    now=time.time() if now is None else now
    if not settings(c)['enabled']:return
    init(db,c);settle(db,now);flush_mail(db,c,now)
    # Mark from shared cached completed sales without adding any API requests.
    tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    positions=[]
    for lid,opened,cost,unlock,status,proceeds,settlement,raw in db.execute('SELECT * FROM paper_positions ORDER BY opened DESC'):
        row=json.loads(raw);mark=None
        if status=='held' and 'evidence_cache' in tables:
            key='sales:'+json.dumps([row['name'],row.get('paper_item',{}).get('paint_index')])
            cached=db.execute('SELECT fetched,payload FROM evidence_cache WHERE key=?',(key,)).fetchone()
            if cached and 0<=now-cached[0]<=settings(c)['evidence_max_seconds']:
                from review import collect_sales
                local_c=copy.deepcopy(c);local_c['paper_review']['float_tolerance']=direct_tolerance(row['paper_item']);local_c['paper_review']['prefer_direct']=True
                candidate=dict(id=lid,item=row['paper_item'],price=row['price_cents'])
                kept,_,_=collect_sales(candidate,json.loads(cached[1]),local_c,now)
                from scout import timestamp
                exits=[s for s in kept if timestamp(s['sold_at'])>=max(opened,unlock)]
                mark=dict(cached_at=cached[0],post_unlock_comparable_sales=len(exits),median_gross_cents=int(statistics.median(s['price'] for s in exits)) if exits else None,note='Comparable completed sales only; not a sale of our position.')
                db.execute('INSERT OR REPLACE INTO paper_marks VALUES (?,?,?)',(lid,now,json.dumps(mark)))
        if mark is None:
            old=db.execute('SELECT payload FROM paper_marks WHERE id=?',(lid,)).fetchone()
            if old:mark=json.loads(old[0])
        positions.append(dict(created_at=row.get('created_at'),id=lid,name=row['name'],opened=opened,cost_cents=cost,unlock_at=unlock,status=status,proceeds_cents=proceeds,settlement_at=settlement,estimate=row['paper_purchase'],mark=mark,simulated_sale=row.get('simulated_sale')))
    decisions=[json.loads(r[0]) for r in db.execute('SELECT payload FROM paper_decisions WHERE decided>=? ORDER BY decided DESC',(now-86400,))]
    ranked=sorted([r for r in decisions if 'estimated_roi' in r['paper_purchase']],key=lambda r:r['paper_purchase']['estimated_roi'],reverse=True)[:10]
    initial,cash=db.execute('SELECT initial,cash FROM paper_wallet WHERE id=1').fetchone()
    data=dict(generated_at=now,initial_cash_cents=initial,available_cash_cents=cash,committed_cost_cents=sum(p['cost_cents'] for p in positions if p['status']!='closed'),realized_simulated_net_cents=sum(p['proceeds_cents']-p['cost_cents'] for p in positions if p['status']=='closed'),positions=positions,retrospective_best_observed_24h=ranked,decisions_last_24h=decisions)
    Path('paper-portfolio.json').write_text(json.dumps(data,indent=2),encoding='utf-8')
    lines=['PAPER PORTFOLIO — simulation only',f'Virtual starting cash ${initial/100:.2f} | available ${cash/100:.2f}',f"Committed cost ${data['committed_cost_cents']/100:.2f} | realized simulated net ${data['realized_simulated_net_cents']/100:.2f}",
           'Prospective decisions use only evidence available then. No guaranteed fills, profits, or liquidity.',
           'Hold, time waiting for a buyer, and settlement all tie up cash. Disappearance never counts as a sale.']
    for p in positions:
        lines.append(f"\n{p['name']} [{p['id']}] — {p['status']} | cost ${p['cost_cents']/100:.2f}\n{listed(p)}\nEarliest simulated resale: {dt.datetime.fromtimestamp(p['unlock_at'],dt.timezone.utc).isoformat()}\nEstimated net at entry: ${p['estimate']['estimated_net_cents']/100:.2f} ({p['estimate']['estimated_roi']:.2%})")
        if p['mark']:lines.append('Exit evidence: '+json.dumps(p['mark']))
    lines.append('\nBEST OBSERVED IN LAST 24 HOURS — retrospective ranking, NOT historical buys:')
    for r in ranked:
        p=r['paper_purchase'];lines.append(f"{r['name']} | {listed(r)} | ${r['price_cents']/100:.2f} | estimated {p['estimated_roi']:.2%} / ${p['estimated_net_cents']/100:.2f} | {p['status']} | "+'; '.join(p['reasons']))
    if not positions:lines.append('\nNo paper buys yet. Review ranked watches above; no purchase quota forces weak trades.')
    Path('paper-portfolio.html').write_text('<!doctype html><meta charset="utf-8"><meta http-equiv="refresh" content="60"><title>Paper portfolio</title><pre style="white-space:pre-wrap;font:16px system-ui">'+html.escape('\n'.join(lines))+'</pre>',encoding='utf-8')
    return data
