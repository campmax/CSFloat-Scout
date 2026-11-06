pass                                                                            
                                                                                        
   
import argparse
import html
import json
import math
import os
from pathlib import Path
import sqlite3
import statistics
import time

from scout import API,Stop,AccessStop,RateLimitStop,QuotaDeferred,HistoryDeferred,RequestBudgetStop,rows,cents,timestamp
from instance_lock import InstanceLock
import email_alerts
from listing_time import describe as listed, fields as listing_fields

DEFAULTS=dict(min_price_cents=2000,max_price_cents=100000,min_markdown=.05,
              always_alert_markdown=.20,top_fraction=.25,window_seconds=3600,
              poll_seconds=90,request_interval_seconds=15,requests_per_cycle=4,
              emails_per_cycle=2,observation_max_age_seconds=300,
              history_enabled=True,history_cache_seconds=3600,email_enabled=True,
              min_reference_quantity=3,emails_per_hour=8,older_emails_per_hour=2,
              email_spacing_seconds=120,new_listing_seconds=3600,ranked_interval_seconds=600,
              longshots_per_hour=4,adaptive_ceiling=.10,strategy_version=14,minute_updates=True)

class ReadOnlyAPI(API):
    def call(self,path,params=None,body=None):
        if body is not None or not (path=='/listings' or path.startswith('/history/')):
            raise Stop('Markdown Radar permits listing/history reads only.')
        return super().call(path,params,body)


def config(path):
    raw=json.loads(Path(path).read_text(encoding='utf-8'));c=dict(DEFAULTS,**raw)
    if raw.get('strategy_version',0)<12:
        for key,old,new in [('min_markdown',.08,.05),('emails_per_hour',6,8),('email_spacing_seconds',300,120)]:
            if c[key]==old:c[key]=new
    c['strategy_version']=14
    for k in ('min_price_cents','max_price_cents','window_seconds','poll_seconds','requests_per_cycle','emails_per_cycle','observation_max_age_seconds','history_cache_seconds','min_reference_quantity','emails_per_hour','older_emails_per_hour','email_spacing_seconds','new_listing_seconds','ranked_interval_seconds','longshots_per_hour'):
        if type(c[k]) is not int or c[k]<=0:raise ValueError('Invalid '+k)
    if c['min_price_cents']>c['max_price_cents']:raise ValueError('Invalid price range')
    for k in ('min_markdown','always_alert_markdown','top_fraction','adaptive_ceiling'):
        if type(c[k]) not in (int,float) or not math.isfinite(c[k]) or not 0<c[k]<1:raise ValueError('Invalid '+k)
    if type(c['request_interval_seconds']) not in (int,float) or not math.isfinite(c['request_interval_seconds']) or c['request_interval_seconds']<15:raise ValueError('Request spacing must be at least 15 seconds')
    if c['requests_per_cycle']<2:raise ValueError('At least two listing requests per cycle required')
                                                                                
    c['emails_per_cycle']=min(c['emails_per_cycle'],2)
    return c


def connect(path='radar.sqlite3'):
    db=sqlite3.connect(path,isolation_level=None)
    db.execute('CREATE TABLE IF NOT EXISTS radar_items (id TEXT PRIMARY KEY,seen REAL,price INTEGER,discount REAL,payload TEXT)')
    db.execute('CREATE TABLE IF NOT EXISTS radar_mail (id TEXT,price INTEGER,status TEXT,attempts INTEGER,last REAL,PRIMARY KEY(id,price))')
    db.execute('CREATE TABLE IF NOT EXISTS radar_history (market TEXT PRIMARY KEY,fetched REAL,payload TEXT)')
    db.execute('CREATE TABLE IF NOT EXISTS radar_state (key TEXT PRIMARY KEY,value INTEGER)')
    db.execute('CREATE TABLE IF NOT EXISTS radar_delivery (id TEXT,price INTEGER,sent REAL,older INTEGER)')
    version=db.execute("SELECT value FROM radar_state WHERE key='policy_version'").fetchone()
    if not version or version[0]<11:
        db.execute("INSERT INTO radar_delivery (id,price,sent,older) SELECT id,price,last,1 FROM radar_mail WHERE status='sent'")
        db.execute('DELETE FROM radar_items')                                              
        db.execute("INSERT OR REPLACE INTO radar_state VALUES ('policy_version',11)")
    if 'longshot' not in {r[1] for r in db.execute('PRAGMA table_info(radar_delivery)')}:
        db.execute('ALTER TABLE radar_delivery ADD COLUMN longshot INTEGER NOT NULL DEFAULT 0')
    db.execute('CREATE TABLE IF NOT EXISTS radar_negative (market TEXT PRIMARY KEY,checked REAL,reason TEXT)')
    return db


def lead(row,c):
    if not isinstance(row,dict) or row.get('state')!='listed' or row.get('type')!='buy_now':return None
    price=row.get('price');item=row.get('item') or {}
    if not row.get('id') or not item.get('market_hash_name') or not cents(price) or not c['min_price_cents']<=price<=c['max_price_cents']:return None
    ref=row.get('reference') or item.get('reference') or {}
    discounts={k:1-price/ref[k] for k in ('base_price','predicted_price') if cents(ref.get(k))}
                                                                                          
                                                                            
    quantity=ref.get('quantity')
    source=min(discounts,key=discounts.get) if discounts else None;score=discounts[source] if source else -1
    return dict(id=str(row['id']),name=item['market_hash_name'],price_cents=price,discount=score,
                discount_source=source,reference_discounts=discounts,item=item,created_at=row.get('created_at'),
                reference_warning='Sparse/unreported reference quantity' if type(quantity) is not int or quantity<c['min_reference_quantity'] else '',
                url='https://csfloat.com/item/'+str(row['id']),reference=ref)


def ingest(db,data,c,now):
    new=0
    for row in data:
        r=lead(row,c)
        if not r:
            if isinstance(row,dict) and row.get('id'):db.execute('DELETE FROM radar_items WHERE id=?',(str(row['id']),))
            continue
        prior=db.execute('SELECT price,payload FROM radar_items WHERE id=?',(r['id'],)).fetchone()
        previous=json.loads(prior[1]) if prior else {}
        r.update(listing_fields(r.get('created_at'),now))
        r['repriced_at']=now if prior and r['price_cents']<prior[0] else previous.get('repriced_at',0)
        if not prior or prior[0]!=r['price_cents']:new+=1
        db.execute('INSERT OR REPLACE INTO radar_items VALUES (?,?,?,?,?)',(r['id'],now,r['price_cents'],r['discount'],json.dumps(r)))
    return new


def cutoff(db,c,now):
    scores=sorted(r[0] for r in db.execute('SELECT discount FROM radar_items WHERE seen>=?',(now-c['window_seconds'],)))
    if not scores:return c['min_markdown']
    return max(c['min_markdown'],min(c['adaptive_ceiling'],scores[min(len(scores)-1,math.floor((1-c['top_fraction'])*len(scores)))]))


def market(r):return json.dumps([r['name'],r['item'].get('paint_index')])


def evidence(db,r,c,now):
    key=market(r)
    row=db.execute('SELECT fetched,payload FROM radar_history WHERE market=?',(key,)).fetchone()
                                                                                         
    if (not row or now-row[0]>c['history_cache_seconds']) and Path('scout.sqlite3').exists():
        main=None
        try:
            main=sqlite3.connect(Path('scout.sqlite3').resolve().as_uri()+'?mode=ro',uri=True)
            row=main.execute('SELECT fetched,payload FROM evidence_cache WHERE key=?',('sales:'+key,)).fetchone()
        except sqlite3.Error:pass
        finally:
            if main:main.close()
    if not row or not 0<=now-row[0]<=c['history_cache_seconds']:return None,None
    return json.loads(row[1]),row[0]


def support(r,sales,fetched,now):
    result=dict(label='UNKNOWN — history unchecked; manual long shot',sales=0,recent=0,above_break_even=0,
                weekly_above_break_even=0,market_recent_sales=0,newest_market_sale_age_days=None)
    if sales is None:return result
    from review import match_reason
    matched=[];seen=set()
    for s in sales:
        if not isinstance(s,dict):continue
        si=s.get('item') or {};sold=timestamp(s.get('sold_at'));sid=str(s.get('id'))
        if (s.get('id') and sid not in seen and s.get('state')=='sold' and cents(s.get('price')) and
            0<sold<=now and si.get('market_hash_name')==r['name']):
            matched.append(s);seen.add(sid)
    dates=[timestamp(s['sold_at']) for s in matched]
    result.update(market_recent_sales=sum(now-d<=7*86400 for d in dates),
                  newest_market_sale_age_days=(now-max(dates))/86400 if dates else None,
                  cache_age_seconds=round(now-fetched),history_checked=True)
    if not dates:result['negative_reason']='History returned no usable completed sales'
    elif now-max(dates)>30*86400:result['negative_reason']='Newest returned market sale is over 30 days old'
    value=r['item'].get('float_value')
    if type(value) not in (int,float) or not math.isfinite(value) or not 0<=value<=1:
        result['label']='UNASSESSED — item lacks float; recent market activity is not comparable-price validation'
        return result
    candidate=dict(item=r['item']);tol=.015
    for label,lo,hi,cap in [('Factory New',0,.07,.003),('Minimal Wear',.07,.15,.008),('Field-Tested',.15,.38,.015),('Well-Worn',.38,.45,.01),('Battle-Scarred',.45,1,.02)]:
        if '('+label+')' in r['name']:
            tol=min(cap,max(.000001,min(value-lo,hi-value)*.5));break
    kept=[s for s in matched if now-timestamp(s['sold_at'])<=7*86400 and match_reason(candidate,s,tol) is None
          and not s['item'].get('stickers') and not s['item'].get('keychains')]
    recent=[s for s in kept if now-timestamp(s['sold_at'])<=3*86400]
    above=sum(s['price']*.98*.99>r['price_cents'] for s in recent)
    weekly_above=sum(s['price']*.98*.99>r['price_cents'] for s in kept)
    result.update(label='LOCAL SUPPORT — one or more recent comparable sales above illustrative break-even' if weekly_above else
                  'RECENT MARKET ACTIVITY — target float/price NOT validated' if result['market_recent_sales'] else 'WEAK — no recent market sales in fetched history',
                  sales=len(kept),recent=len(recent),above_break_even=above,weekly_above_break_even=weekly_above,
                  median_cents=int(statistics.median(s['price'] for s in kept)) if kept else None,direct_float_tolerance=tol)
    if kept and not weekly_above:result['negative_reason']='Recent direct comparables do not exceed break-even'
    return result


def classify(r,c,now):
    e=r['support']
    if e.get('negative_reason'):return None,e['negative_reason']
    if e.get('weekly_above_break_even',0):return 'supported',None
                                                                             
    if e.get('market_recent_sales',0):return 'longshot',None
    if r['older']:return None,'Older listing without recent market support'
    if r['name'].startswith('Souvenir ') or r['item'].get('is_souvenir'):
        return None,'Unresearched Souvenir premium: report only'
    if r['discount']>.50:return None,'Over 50% markdown without recent support: suspicious reference'
    updated=timestamp(r['reference'].get('last_updated'))
    if updated and now-updated>7*86400:return None,'Reference has not updated within seven days'
    return 'longshot',None


def already_sent(db,r):
    return bool(db.execute("SELECT 1 FROM radar_mail WHERE id=? AND status='sent' AND price<=?",(r['id'],r['price_cents'])).fetchone())


def body(r,threshold,seen,now):
    e=r['support'];refs='\n'.join(f'{k}: {v:.1%}' for k,v in r['reference_discounts'].items())
    return (f"MANUAL INVESTIGATION LEAD — NO PURCHASE.\n{r['name']}\nPrice: ${r['price_cents']/100:.2f}\n"
            f"Conservative API-reference markdown: {r['discount']:.1%} ({r['discount_source']})\n{refs}\n"
            f"Reference quantity: {r['reference'].get('quantity','unknown')}; {r.get('reference_warning','')}\n"
            f"Recent adaptive markdown cutoff: {threshold:.1%} (sample, not whole market).\n"
            f"{e['label']}\nLocal sales / 3-day sales / recent above illustrative break-even: {e['sales']} / {e['recent']} / {e['above_break_even']}\n"
            f"Category: {'NEW / RECENT PRICE DROP' if not r.get('older',True) else 'OLDER BEST-OBSERVED PICK'}; weekly sales above break-even: {e.get('weekly_above_break_even',0)}\nFloat: {r['item'].get('float_value','unknown')}; observations {int(now-seen)} seconds old.\n"
            'Markdown is NOT ROI. API reference estimates can be inflated; exact website badge parity is unverified.\n'
            f"Alert tier: {r.get('alert_tier','unknown')}. Recent market sales: {e.get('market_recent_sales',0)}; newest sale age (days): {e.get('newest_market_sale_age_days')}.\n"
            'Supported means a recent local sale exceeds illustrative break-even. LONGSHOT does not establish comparable value or profit.\n'
            'Illustrative break-even uses 2% selling fee + 1% slippage, no buying/withdrawal fees; verify your actual costs.\n'
            +listed(r,now)+'\n'+'Pattern, phase, stickers and float premiums may be misleading. Listing was observed active; it may now be sold or repriced.\n\n'+r['url'])


def alerts(db,c,now=None,send=True):
    now=time.time() if now is None else now;threshold=cutoff(db,c,now);eligible=[];sent=0;withheld=[]
    for seen,raw in db.execute('SELECT seen,payload FROM radar_items WHERE seen>=? ORDER BY discount DESC',(now-c['observation_max_age_seconds'],)):
        r=json.loads(raw)
        if r['discount']<c['min_markdown'] or (r['discount']<threshold and r['discount']<c['always_alert_markdown']):
            r['support']=support(r,None,None,now);r['older']=True
            r['withheld_reason']='Below markdown floor' if r['discount']<c['min_markdown'] else 'Below adaptive markdown cutoff'
            withheld.append(r);continue
        sales,fetched=evidence(db,r,c,now);r['support']=support(r,sales,fetched,now);r['observed_at']=seen
        posted=timestamp(r.get('created_at'));repriced=r.get('repriced_at',0)
        r['older']=not (0<=now-posted<=c['new_listing_seconds'] or (repriced>0 and 0<=now-repriced<=c['new_listing_seconds']))
        negative=r['support'].get('negative_reason')
        if negative:db.execute('INSERT OR REPLACE INTO radar_negative VALUES (?,?,?)',(market(r),fetched,negative))
        elif sales is not None:db.execute('DELETE FROM radar_negative WHERE market=?',(market(r),))
        prior=db.execute('SELECT checked,reason FROM radar_negative WHERE market=?',(market(r),)).fetchone()
        if sales is None and prior and 0<=now-prior[0]<=86400:
            r['support']['negative_reason']=prior[1]+' (cached finding; awaiting refresh)'
        r['alert_tier'],reason=classify(r,c,now)
        if reason:
            r['withheld_reason']=reason;withheld.append(r);continue
        eligible.append(r)
                                                                                      
    eligible.sort(key=lambda r:(not r['older'],r.get('alert_tier')=='supported',r['discount'],r['support']['above_break_even']),reverse=True)
    for r in eligible:
        if not send or c.get('minute_updates',True):break
        if already_sent(db,r):
            r['delivery_status']='already emailed';continue
        delivered=db.execute('SELECT COUNT(*),COALESCE(SUM(older),0),COALESCE(MAX(sent),0),COALESCE(SUM(longshot),0) FROM radar_delivery WHERE sent>?',(now-3600,)).fetchone()
        if delivered[0]>=c['emails_per_hour']:
            r['delivery_status']='hourly email cap';continue
        if delivered[2] and now-delivered[2]<c['email_spacing_seconds']:
            r['delivery_status']='email spacing';continue
        if r['older'] and delivered[1]>=c['older_emails_per_hour']:
            r['delivery_status']='older-item email cap';continue
        if r['alert_tier']=='longshot' and delivered[3]>=c['longshots_per_hour']:
            r['delivery_status']='longshot email cap';continue
        if sent>=c['emails_per_cycle']:
            r['delivery_status']='cycle email limit';continue
        prev=db.execute('SELECT attempts,last FROM radar_mail WHERE id=? AND price=?',(r['id'],r['price_cents'])).fetchone()
        if prev and (prev[0]>=3 or now-prev[1]<300):continue
        if not c['email_enabled']:continue
                                                                                   
        if time.time()-r['observed_at']>c['observation_max_age_seconds']:continue
        attempts=prev[0]+1 if prev else 1
        db.execute('INSERT OR REPLACE INTO radar_mail VALUES (?,?,?,?,?)',(r['id'],r['price_cents'],'attempting',attempts,now))
        try:email_alerts.send(f"Markdown Radar [{r['alert_tier'].upper()}] {r['discount']:.0%} — ${r['price_cents']/100:.2f} — {r['name']}",body(r,threshold,r['observed_at'],time.time()),os.environ.get('SCOUT_EMAIL_TO','user1@example.com'))
        except Exception as error:
            db.execute("UPDATE radar_mail SET status='failed' WHERE id=? AND price=?",(r['id'],r['price_cents']))
            print('Radar email failed: '+type(error).__name__+'; retries only while freshly observed.',flush=True)
            break
        else:
            db.execute("UPDATE radar_mail SET status='sent' WHERE id=? AND price=?",(r['id'],r['price_cents']))
            with Path('radar-alerts.jsonl').open('a',encoding='utf-8') as f:f.write(json.dumps(dict(r,email_accepted_at=time.time()))+'\n')
            db.execute('INSERT INTO radar_delivery (id,price,sent,older,longshot) VALUES (?,?,?,?,?)',(r['id'],r['price_cents'],time.time(),int(r['older']),int(r['alert_tier']=='longshot')))
            r['delivery_status']='SMTP accepted'
            sent+=1
    report=dict(strategy_version=12,settings_summary={k:c[k] for k in ('min_markdown','adaptive_ceiling','emails_per_hour','longshots_per_hour','older_emails_per_hour','email_spacing_seconds')},generated_at=now,cutoff=threshold,range_cents=[c['min_price_cents'],c['max_price_cents']],leads=eligible,withheld=withheld,emails_accepted=sent)
    Path('radar-best.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    cards=''.join('<section><h2>'+html.escape(f"{r['discount']:.1%} — ${r['price_cents']/100:.2f} — {r['name']}")+'</h2><p>'+html.escape(r['support']['label']+' | '+listed(r))+'</p><a href="'+html.escape(r['url'],quote=True)+'">Open listing</a></section>' for r in eligible[:100])
    Path('radar-best.html').write_text('<!doctype html><meta charset="utf-8"><title>Markdown Radar</title><style>body{font:16px system-ui;max-width:1000px;margin:35px auto;background:#101826;color:#eee}section{padding:18px;border-bottom:1px solid #456}a{color:#6fe0ff}</style><h1>Markdown Radar</h1><p>Manual-review long shots. Reference markdown is not profit. Availability and reference estimates may be wrong.</p>'+cards,encoding='utf-8')
    return eligible+withheld,sent,threshold


def cycle(api,db,c):
    before=api.request_count;api.budget_end=before+c['requests_per_cycle'];total=0;new=0
    state=db.execute("SELECT value FROM radar_state WHERE key='cycle'").fetchone();turn=state[0] if state else 0
    try:
        from radar_discovery import queries
        for params in queries(db,c,turn,time.time()):
            try:
                found=rows(api.listings(**params))
                total+=len(found);new+=ingest(db,found,c,time.time())
            except QuotaDeferred:break
        leads,sent,threshold=alerts(db,c)
                                                                              
        if c['history_enabled'] and api.policy.history_due():
            for r in sorted(leads,key=lambda r:(not r['older'],r['discount']),reverse=True):
                if r.get('withheld_reason'):continue
                cached,_=evidence(db,r,c,time.time())
                if cached is not None:continue
                try:
                    sales=api.sales(r['name'],r['item'].get('paint_index'))
                    db.execute('INSERT OR REPLACE INTO radar_history VALUES (?,?,?)',(market(r),time.time(),json.dumps(sales)))
                except (HistoryDeferred,QuotaDeferred,RequestBudgetStop):pass
                except AccessStop:raise
                except Stop as error:print('History unavailable: '+str(error),flush=True)
                break
                                                                                           
        db.execute("INSERT OR REPLACE INTO radar_state VALUES ('cycle',?)",(turn+1,))
        db.execute('DELETE FROM radar_items WHERE seen<?',(time.time()-86400,))
        supported=sum(r['support'].get('weekly_above_break_even',0)>=1 for r in leads)
        print(f"Radar: {total} returned / {new} new or repriced / {supported} lightly supported / {sum(r.get('alert_tier')=='longshot' for r in leads)} longshots / {sum(bool(r.get('withheld_reason')) for r in leads)} withheld / {sent} legacy alerts; minute emails logged separately. Adaptive cutoff {threshold:.1%}. Requests {api.request_count-before}/{c['requests_per_cycle']}.",flush=True)
    finally:api.budget_end=None


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',default='radar-config.json');parser.add_argument('--once',action='store_true')
    parser.add_argument('--test-email',action='store_true');parser.add_argument('--no-email',action='store_true')
    args=parser.parse_args();c=config(args.config)
    if args.test_email:
        email_alerts.send('Markdown Radar email test','Read-only manual-review alerts. No purchase was made.',os.environ.get('SCOUT_EMAIL_TO','user1@example.com'));print('SMTP accepted the test email.');return
    if args.no_email:c['email_enabled']=False
    if c['email_enabled']:email_alerts.settings()
    key=os.environ.get('CSFLOAT_API_KEY')
    if not key:raise Stop('Set CSFLOAT_API_KEY in this PowerShell session.')
    lock=InstanceLock('scout.lock');reporter=None
    try:
        api=ReadOnlyAPI(key,c['request_interval_seconds'],state_file='request-state.json')
        api.policy.configure_routes(c['request_interval_seconds'],900)
        db=connect()
        if c.get('minute_updates',True) and c['email_enabled'] and not args.once:
            from radar_minute import MinuteReporter
            reporter=MinuteReporter('radar.sqlite3',c,lambda:api.policy.state.get('blocked_until',0))
            reporter.start()
        print(f"MARKDOWN RADAR v1.5 — manual review ONLY | ${c['min_price_cents']/100:.0f}–${c['max_price_cents']/100:.0f} | no purchases",flush=True)
        while True:
            if Path('STOP').exists():raise Stop('STOP file present.')
            try:
                api.policy.await_cooldown(Stop)
                cycle(api,db,c)
            except RateLimitStop as error:
                print(str(error),flush=True)
            except (HistoryDeferred,QuotaDeferred,RequestBudgetStop) as error:print(type(error).__name__+': waiting; quota state retained.',flush=True)
            except AccessStop:raise
            except Stop as error:
                print(str(error),flush=True)
            if args.once:
                if c.get('minute_updates',True) and c['email_enabled']:
                    from radar_minute import send_update
                    send_update(db,c,time.time(),api.policy.state.get('blocked_until',0))
                break
            for _ in range(c['poll_seconds']):
                if Path('STOP').exists():raise Stop('STOP file present.')
                time.sleep(1)
    finally:
        if reporter:reporter.stop()
        lock.close()

if __name__=='__main__':
    try:main()
    except KeyboardInterrupt:print('Radar stopped; observations and email history saved.')
    except (Stop,ValueError,RuntimeError) as error:print(str(error));raise SystemExit(1)
