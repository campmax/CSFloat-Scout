pass                                                                              
import json,math,time,html
from pathlib import Path
from listing_time import describe as listed

def init(db):
    db.execute('CREATE TABLE IF NOT EXISTS personal_paper (id TEXT PRIMARY KEY,payload TEXT,mail_at REAL DEFAULT 0,mailed INTEGER DEFAULT 0)')

def markdown(r):
    ref=r.get('reference') or (r.get('item') or {}).get('reference') or {}
    for key in ('predicted_price','base_price'):
        v=ref.get(key);price=r.get('price')
        if type(v) in (int,float) and math.isfinite(v) and v>0 and type(price) is int and price>0:
            return 1-price/v,key,v
    return None,None,None

def within_paper_limits(raw,p):
    f=(raw.get('item') or {}).get('float_value')
    price=raw.get('price')
    return (type(f) in (int,float) and p.get('paper_buy_min_float',0)<=f<=p.get('paper_buy_max_float',1) and
            type(price) is int and price<=p.get('paper_buy_max_price_cents',p['hard_max_price_cents']))


def put(db,r):
    db.execute('INSERT INTO personal_paper(id,payload) VALUES (?,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload',(r['id'],json.dumps(r)))

def observe(db,rows,p,now=None):
    init(db);now=time.time() if now is None else now
    from personal import acceptable
    for raw in rows:
        d,source,ref=markdown(raw)
        if not acceptable(raw,p) or not within_paper_limits(raw,p) or d is None or d+1e-12<p.get('paper_buy_markdown',.09):continue
        lid=str(raw['id']);old=db.execute('SELECT payload FROM personal_paper WHERE id=?',(lid,)).fetchone()
        old=json.loads(old[0]) if old else None
        if old and old['status']=='paper_bought':continue
        if old and old['price_cents']==raw['price']:
            if old['status'] in ('pending','deferred'):old['last_seen']=now;put(db,old)
            continue
        r=dict(id=lid,name=raw['item']['market_hash_name'],created_at=raw.get('created_at'),
               price_cents=raw['price'],float=raw['item']['float_value'],item=raw['item'],
               reference_markdown=d,reference_source=source,reference_price_cents=ref,
               discovered_at=now,last_seen=now,next_check=0,status='pending',url='https://csfloat.com/item/'+lid,
               execution='Not verified; no real purchase request will be made.',threshold=p.get('paper_buy_markdown',.09))
        put(db,r)
        db.execute('UPDATE personal_paper SET mailed=0,mail_at=0 WHERE id=?',(lid,))

def verify(db,api,p,max_checks=2,now=None):
    from scout import Stop,AccessStop,RateLimitStop,QuotaDeferred,HistoryDeferred,RequestBudgetStop
    from personal import acceptable
    fixed_now=now
    init(db);now=time.time() if now is None else now;checks=0
    pending=[json.loads(x[0]) for x in db.execute('SELECT payload FROM personal_paper')]
    for r in sorted(pending,key=lambda r:r['reference_markdown'],reverse=True):
        if r['status'] not in ('pending','deferred') or now<r.get('next_check',0):continue
        if now-r['last_seen']>600:
            r.update(status='unverified_expired',execution='Observation expired before verification; outcome unknown.');put(db,r);continue
        if checks>=max_checks:break
        try:
            checks+=1;fresh=api.detail(r['id'])
        except (QuotaDeferred,HistoryDeferred,RequestBudgetStop) as error:
            r.update(status='deferred',reason=type(error).__name__,next_check=now+60);put(db,r);break
        except (AccessStop,RateLimitStop):raise
        except Stop as error:
            r.update(status='deferred',reason='Detail read unavailable; outcome unknown',next_check=now+300);put(db,r);continue
        checked=time.time() if fixed_now is None else fixed_now
        if not isinstance(fresh,dict):
            r.update(status='deferred',reason='Invalid detail response',next_check=now+300);put(db,r);continue
        d,source,ref=markdown(fresh)
        same_item=all((fresh.get('item') or {}).get(k)==r['item'].get(k) for k in ('market_hash_name','def_index','paint_index','float_value','paint_seed','stickers','keychains'))
        valid=(str(fresh.get('id'))==r['id'] and same_item and acceptable(fresh,p) and within_paper_limits(fresh,p) and
               fresh['price']<=r['price_cents'] and d is not None and d+1e-12>=p.get('paper_buy_markdown',.09))
        r.update(checked_at=checked,discovery_to_check_seconds=max(0,checked-r['discovered_at']),observed_state=fresh.get('state'),checked_price_cents=fresh.get('price'))
        if valid:
            r.update(status='paper_bought',paper_cost_cents=fresh['price'],confirmed_markdown=d,reference_source=source,
                     execution='Still listed at qualifying price when rechecked. SIMULATED entry only; actual fill and Steam delivery UNPROVEN.')
        else:r.update(status='missed_or_changed',execution='No simulated entry: price, item, state, or reference changed. Disappearance is not proof of a sale.')
        put(db,r)
        print(f"Personal paper: {r['status']} | {r['name']} | ${r['price_cents']/100:.2f} | {r['reference_markdown']:.1%} reference markdown",flush=True)
    return checks

def report(db):
    init(db);rows=[json.loads(x[0]) for x in db.execute('SELECT payload FROM personal_paper')]
    rows.sort(key=lambda r:r['discovered_at'],reverse=True)
    data=dict(generated_at=time.time(),paper_only=True,entries=rows,paper_buys=sum(r['status']=='paper_bought' for r in rows))
    Path('personal-paper.json').write_text(json.dumps(data,indent=2),encoding='utf-8')
    lines=['PERSONAL PAPER ENTRIES — no real orders. API-reference markdown is not verified website badge parity.']
    for r in rows:lines.append(f"\n{r['status']} | {r['name']} | ${r['price_cents']/100:.2f} | float {r['float']:.6f} | {r['reference_markdown']:.1%}\n{listed(r)}\n{r['execution']}\nSeconds from discovery to check: {r.get('discovery_to_check_seconds','unknown')}\n{r['url']}")
    Path('personal-paper.html').write_text('<!doctype html><meta charset="utf-8"><title>Personal paper entries</title><pre style="white-space:pre-wrap;font:16px system-ui">'+html.escape('\n'.join(lines))+'</pre>',encoding='utf-8')
    return data

def flush_mail(db,p,enabled):
    if not enabled:return
    import email_alerts
    init(db);now=time.time()
    for lid,raw,last in db.execute('SELECT id,payload,mail_at FROM personal_paper WHERE mailed=0').fetchall():
        r=json.loads(raw)
        if r['status'] in ('pending','deferred') or now-last<300:continue
        db.execute('UPDATE personal_paper SET mail_at=? WHERE id=?',(now,lid))
        text=f"NO REAL PURCHASE. {r['status']}\n{r['name']}\nObserved ${r['price_cents']/100:.2f}; float {r['float']:.6f}; API-reference markdown {r['reference_markdown']:.1%}\n{listed(r)}\n{r['execution']}\nDiscovery-to-check seconds: {r.get('discovery_to_check_seconds','unknown')}\n{r['url']}\nSee personal-paper.html. Reference markdown does not guarantee profit or match the website badge."
        try:email_alerts.send('Personal PAPER — '+r['status']+' — '+r['name'],text,p['email_recipient'])
        except Exception as error:print('Personal paper email failed: '+type(error).__name__,flush=True)
        else:db.execute('UPDATE personal_paper SET mailed=1 WHERE id=?',(lid,))
