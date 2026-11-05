"""Personal-item observation sessions with explicit one-pair --live mode."""
import argparse
import datetime as dt
import html
import json
import math
import os
from pathlib import Path
import statistics
import time

from scout import API,Ledger,Stop,AccessStop,RateLimitStop,QuotaDeferred,HistoryDeferred,RequestBudgetStop,rows
from scanner import defaults,init,sales_evidence
from review import collect_sales
from instance_lock import InstanceLock
import email_alerts
from listing_time import describe as listed, fields as listing_fields


def stamp(t):return dt.datetime.fromtimestamp(t,dt.timezone.utc).isoformat()


def validate(p):
    allowed={'★ Sport Gloves | Amphibious (Minimal Wear)','★ Sport Gloves | Amphibious (Field-Tested)'}
    if not p['names'] or any(n not in allowed for n in p['names']):raise Stop('This version supports Amphibious MW and FT only.')
    for k in ('target_price_cents','hard_max_price_cents','poll_seconds','history_cache_seconds','email_interval_seconds'):
        if type(p[k]) is not int or p[k]<=0:raise Stop('Invalid personal setting: '+k)
    if p['hard_max_price_cents']<p['target_price_cents']:raise Stop('Hard ceiling must cover target price.')
    if p['poll_seconds']<60 or p['history_cache_seconds']<900 or p['email_interval_seconds']<60:raise Stop('Personal pacing settings are too short.')
    for k in ('minimum_discount','over_target_discount','at_ceiling_discount'):
        if type(p[k]) not in (int,float) or not math.isfinite(p[k]) or not 0<=p[k]<1:raise Stop('Invalid discount setting.')
    if not p['minimum_discount']<=p['over_target_discount']<=p['at_ceiling_discount']:raise Stop('Discount requirements must increase with budget.')
    if type(p.get('paper_buy_markdown',.09)) not in (int,float) or not 0<p.get('paper_buy_markdown',.09)<1:raise Stop('Invalid paper buy markdown')
    if not isinstance(p['email_recipient'],str) or p['email_recipient'].count('@')!=1:raise Stop('Configure a valid email_recipient.')


def acceptable(r,p):
    item=r.get('item') or {};f=item.get('float_value');price=r.get('price');name=item.get('market_hash_name')
    if r.get('state')!='listed' or r.get('type')!='buy_now' or name not in p['names']:return False
    if type(price) is not int or not 0<price<=p['hard_max_price_cents']:return False
    if type(f) not in (int,float) or not math.isfinite(f):return False
    low,high=(.07,.15) if name.endswith('(Minimal Wear)') else (.15,.38)
    return low<=f<high and all(item.get(k) is not None for k in ('def_index','paint_index'))


def assess(r,sales,c,p,now):
    if not acceptable(r,p):return None
    c=dict(c,paper_review=dict(c['paper_review'],sales_window_days=7,recent_window_days=3))
    kept,recent,evidence=collect_sales(r,sales,c,now)
    fair=math.floor(min(statistics.median([x['price'] for x in kept]),statistics.median([x['price'] for x in recent]))) if kept and recent else None
    price=r['price'];cost=math.ceil(price*(1+c['buy_fee_rate']))+c['extra_cost_cents']
    discount=1-cost/fair if fair else None
    name=r['item']['market_hash_name'];f=r['item']['float_value']
    low,high=(.07,.15) if name.endswith('(Minimal Wear)') else (.15,.38)
    # A maximum 0.1 percentage point bonus: deal quality dominates float preference.
    float_bonus=.1*(high-f)/(high-low)
    threshold=p['minimum_discount']
    if cost>p['target_price_cents']:
        fraction=(cost-p['target_price_cents'])/max(1,p['hard_max_price_cents']-p['target_price_cents'])
        threshold=p['over_target_discount']+fraction*(p['at_ceiling_discount']-p['over_target_discount'])
    supported=len(kept)>=2 and len(recent)>=1
    budget_fit=cost<=p['hard_max_price_cents'] and (cost<=p['target_price_cents'] or (supported and discount>=threshold))
    warnings=['Personal-use comparison, not a resale-profit estimate. Weekly trend not evaluated. Availability not confirmed.']
    if not supported:warnings.append('Insufficient comparable recent sales; reference-only or thin evidence.')
    if cost>p['target_price_cents']:warnings.append('Over $300 target; higher discount required.')
    if not budget_fit:warnings.append('Does not meet flexible-budget rule; shown for comparison only.')
    ref=r.get('reference') or r.get('item',{}).get('reference') or {};v=ref.get('predicted_price') or ref.get('base_price')
    return dict(id=r['id'],name=name,price_cents=price,total_cost_cents=cost,float=f,fair_cents=fair,
        savings_cents=fair-cost if fair else None,discount=discount,
        reference_discount=1-price/v if type(v) in (int,float) and v>0 else None,
        sales_count=len(kept),recent_sales_count=len(recent),supported=supported,budget_fit=budget_fit,
        target_match=bool(supported and budget_fit and discount>=threshold),required_discount=threshold,
        deal_score=(discount*100 if discount is not None else -1000)+float_bonus,
        float_bonus=float_bonus,warnings=warnings,float_model=evidence['float_model'],
        **listing_fields(r.get('created_at'),now),first_seen=now,last_seen=now,observed_at=stamp(now),url='https://csfloat.com/item/'+str(r['id']))


def setup(db,hours,new=False):
    db.execute('CREATE TABLE IF NOT EXISTS personal_sessions (id TEXT PRIMARY KEY,payload TEXT)')
    db.execute('CREATE TABLE IF NOT EXISTS personal_observations (session TEXT,id TEXT,price INTEGER,payload TEXT,PRIMARY KEY(session,id,price))')
    row=db.execute("SELECT payload FROM personal_sessions WHERE id='current'").fetchone()
    state=json.loads(row[0]) if row and not new else dict(id=str(time.time_ns()),start=time.time(),end=time.time()+hours*3600,last_email=0,final_email=False,cycles=0)
    save(db,state);return state


def save(db,state):db.execute("INSERT OR REPLACE INTO personal_sessions VALUES ('current',?)",(json.dumps(state),))


def record(db,state,result):
    old=db.execute('SELECT payload FROM personal_observations WHERE session=? AND id=? AND price=?',(state['id'],result['id'],result['price_cents'])).fetchone()
    if old:result['first_seen']=json.loads(old[0])['first_seen']
    db.execute('INSERT OR REPLACE INTO personal_observations VALUES (?,?,?,?)',(state['id'],result['id'],result['price_cents'],json.dumps(result)))
    if not old:
        with Path('personal-observations.jsonl').open('a',encoding='utf-8') as f:f.write(json.dumps(dict(session=state['id'],**result))+'\n')


def ranked(db,state):
    data=[json.loads(x[0]) for x in db.execute('SELECT payload FROM personal_observations WHERE session=?',(state['id'],))]
    from personal_strategy import rank
    return rank(data,state.get('preferences',{}))


def report(db,state):
    data=ranked(db,state);esc=lambda x:html.escape(str(x))
    money=lambda x:'Unknown' if x is None else f'${x/100:,.2f}'
    info=dict(paper_only=not state.get("preferences",{}).get("_live",False),session=state,generated_at=stamp(time.time()),observations=data)
    Path('personal-report.json').write_text(json.dumps(info,indent=2),encoding='utf-8')
    page='''<!doctype html><meta charset="utf-8"><title>Amphibious personal monitor</title><style>body{font:15px system-ui;background:#101827;color:#eef;margin:25px}table{border-collapse:collapse}td,th{padding:12px;border-bottom:1px solid #456;text-align:left}a{color:#7df}</style><h1>Amphibious — personal paper monitor</h1><p>No purchases. Ranked among observed listings, not guaranteed market-wide best. Past offers may be sold or repriced. Check last-seen time and current listing. Reload to update.</p>'''
    if state.get('preferences',{}).get('_live'):
        page=page.replace('personal paper monitor','personal LIVE monitor').replace('No purchases.', 'LIVE mode: one-pair authorization; see personal-live.json for order status.')
    page+='<p>Session: '+esc(stamp(state['start']))+' to '+esc(stamp(state['end']))+' · '+str(len(data))+' listing-price observations</p><table><tr><th>Item</th><th>Total cost</th><th>Float</th><th>API markdown / preference</th><th>Sales discount</th><th>Sales / recent</th><th>Target match</th><th>Listed / age</th><th>Last seen UTC</th><th>Warnings</th></tr>'
    for r in data[:50]:
        page+='<tr><td><a href="'+esc(r['url'])+'">'+esc(r['name'])+'</a></td>'+''.join('<td>'+esc(v)+'</td>' for v in [money(r['total_cost_cents']),f"{r['float']:.5f}",('Unknown' if r.get('reference_discount') is None else f"{r['reference_discount']:.1%}")+' / '+r.get('preference',''), 'Unknown' if r['discount'] is None else f"{r['discount']:.1%}",f"{r['sales_count']} / {r['recent_sales_count']}",'Yes' if r['target_match'] else 'No',listed(r),stamp(r['last_seen']),'; '.join(r['warnings'])])+'</tr>'
    Path('personal-report.html').write_text(page+'</table>',encoding='utf-8')
    return data


def email_summary(db,state,p,enabled,final=False):
    if not enabled or (final and state['final_email']):return
    data=ranked(db,state)
    fingerprint=json.dumps([(r['id'],r['price_cents'],r.get('ranking_discount')) for r in data[:5]])
    changed=fingerprint!=state.get('email_fingerprint')
    interval=60 if changed else p['email_interval_seconds']
    if time.time()-state['last_email']<interval and not final:return
    # Persist attempt before SMTP; no rapid repeated sends after interruption.
    state['last_email']=time.time();save(db,state)
    lines=[('LIVE monitor — check personal-live.json and separate order emails for purchase status.' if p.get('_live') else 'PAPER ONLY — no purchase made.'),'Session ends '+stamp(state['end']),
           'Best observed offers; may already be sold/repriced. Dollar savings compare personal purchase cost with recent sales, not resale profit.']
    for r in data[:5]:
        discount='unknown' if r['discount'] is None else f"{r['discount']:.1%}"
        reference='unknown' if r.get('reference_discount') is None else f"{r['reference_discount']:.1%}"
        lines.append(f"\n{r['name']} | ${r['total_cost_cents']/100:.2f} | float {r['float']:.5f}\nAPI reference markdown: {reference}; preference: {r.get('preference','unknown')}\nSales-estimate discount: {discount}; sales {r['sales_count']} / recent {r['recent_sales_count']}; strict sales-model target {r['target_match']} (separate from personal ranking)\n{listed(r)}\nLast seen: {stamp(r['last_seen'])}\n{r['url']}\n"+'; '.join(r['warnings']))
    if not data:lines.append('No recently observed matching listings. Check quota/status messages. No stale listing substituted.')
    if not changed:lines.append('Unchanged shortlist: these are the same best observed options, not new discoveries.')
    try:email_alerts.send('Amphibious personal monitor — '+('final report' if final else 'best observed'), '\n'.join(lines),p['email_recipient'])
    except Exception as error:print('Summary email failed ('+type(error).__name__+'); local report saved.',flush=True)
    else:
        print(f'Personal email accepted by SMTP: {min(5,len(data))} picks; next unchanged summary in {p["email_interval_seconds"]}s.',flush=True)
        state['email_fingerprint']=fingerprint
        if final:state['final_email']=True
        save(db,state)


def cycle(api,ledger,state,c,p):
    db=ledger.db;seen={};api.budget_end=api.request_count+8;paper_checks=0
    import personal_paper
    try:
        from personal_strategy import queries
        for params in queries(p,state['cycles']):
            try:batch=rows(api.listings(**params))
            except QuotaDeferred:continue
            if p.get('_live'):
                import personal_live
                personal_live.attempt(db,api,batch,c,p,state['end'])
            personal_paper.observe(db,batch,p)
            paper_checks+=personal_paper.verify(db,api,p,max_checks=max(0,2-paper_checks))
            personal_paper.report(db)
            personal_paper.flush_mail(db,p,p.get('_email_enabled',False))
            for r in batch:
                if acceptable(r,p):
                    seen[(r['id'],r['price'])]=r
                    old=db.execute('SELECT payload FROM personal_observations WHERE session=? AND id=? AND price=?',(state['id'],r['id'],r['price'])).fetchone()
                    observed=json.loads(old[0]) if old else assess(r,[],c,p,time.time())
                    ref=r.get('reference') or r.get('item',{}).get('reference') or {}
                    v=ref.get('predicted_price') or ref.get('base_price')
                    observed.update(reference_discount=1-r['price']/v if type(v) in (int,float) and v>0 else None,
                                    last_seen=time.time(),observed_at=stamp(time.time()),**listing_fields(r.get('created_at')))
                    record(db,state,observed)
        groups={}
        for r in seen.values():groups[(r['item']['market_hash_name'],r['item']['paint_index'])]=r
        # Alternate MW/FT history priority; one group must not starve the other.
        keys=list(groups);keys=keys[state['cycles']%max(1,len(keys)):]+keys[:state['cycles']%max(1,len(keys))]
        evidence={}
        for name,paint in keys:
            try:evidence[(name,paint)]=sales_evidence(api,db,name,paint,14,p['history_cache_seconds'])
            except (HistoryDeferred,QuotaDeferred,RequestBudgetStop):evidence[(name,paint)]=None
        for r in seen.values():
            sales=evidence.get((r['item']['market_hash_name'],r['item']['paint_index']))
            if sales is None:continue  # Preserve prior evidence instead of replacing it with zero sales.
            result=assess(r,sales,c,p,time.time())
            key='sales:'+json.dumps([r['item']['market_hash_name'],r['item']['paint_index']])
            source=db.execute('SELECT fetched FROM evidence_cache WHERE key=?',(key,)).fetchone()
            result['history_fetched_at']=stamp(source[0]) if source else None
            record(db,state,result)
    except RequestBudgetStop:print('Cycle request budget reached; continuing next cycle.',flush=True)
    finally:
        api.budget_end=None
        personal_paper.report(db)
    state['preferences']=p
    state['cycles']+=1;save(db,state)
    data=report(db,state)
    print(f"Personal: {len(seen)} matching listing versions this cycle / {len(data)} recorded / {sum((r.get('reference_discount') or 0)>0 for r in data)} positive API markdowns / {sum(r['target_match'] for r in data)} strict sales-model targets. Report: personal-report.html",flush=True)


def main():
    parser=argparse.ArgumentParser(description='Amphibious monitor; --live enables one $330 maximum purchase')
    parser.add_argument('--hours',type=int,choices=(12,24),default=24)
    parser.add_argument('--new-session',action='store_true')
    parser.add_argument('--once',action='store_true')
    parser.add_argument('--no-email',action='store_true')
    parser.add_argument('--live',action='store_true',help='Buy ONE Amphibious FT: >=10%% API markdown, float 0.15–0.20, max $330 total estimated cost')
    args=parser.parse_args()
    if args.live and args.no_email:raise Stop('Live mode requires purchase emails.')
    p=json.loads(Path('personal-config.json').read_text(encoding='utf-8'));validate(p)
    c=defaults(json.loads(Path('config.json').read_text(encoding='utf-8')))
    lock=InstanceLock('scout.lock');ledger=Ledger('personal.sqlite3');init(ledger.db)
    state=setup(ledger.db,args.hours,args.new_session)
    p['_live']=args.live
    state['preferences']=p;save(ledger.db,state)
    print(('PERSONAL v2.2.1 LIVE — ONE pair; >=10% API markdown; float 0.15–0.20; max $330. ' if args.live else 'PERSONAL v2.2.1 PAPER MONITOR — no real purchases. ')+ 'Session ends '+stamp(state['end']),flush=True)
    import personal_live
    if args.live:
        personal_live.validate_costs(c)
        prior=personal_live.report(ledger.db)
        if prior:print('Live buying LOCKED by saved order ('+prior['status']+'); monitoring only.',flush=True)
    enabled=not args.no_email
    p['_email_enabled']=enabled
    if enabled:email_alerts.settings()
    key=os.environ.get('CSFLOAT_API_KEY')
    if not key and time.time()<state['end']:raise Stop('Set CSFLOAT_API_KEY locally.')
    api=API(key or '',15,'request-state.json');api.policy.configure_routes(15,900)
    try:
        while time.time()<state['end']:
            if Path('STOP').exists():break
            if api.policy.blocked():
                print('Saved server cooldown active; report retained, no API requests.',flush=True)
            else:
                try:cycle(api,ledger,state,c,p)
                except RateLimitStop as error:print(str(error),flush=True)
                except AccessStop:raise
                except Stop as error:print(str(error),flush=True)
            import personal_paper
            personal_paper.report(ledger.db);personal_paper.flush_mail(ledger.db,p,enabled)
            if args.live:
                personal_live.report(ledger.db);personal_live.flush_mail(ledger.db,p)
            report(ledger.db,state);email_summary(ledger.db,state,p,enabled)
            if args.once:break
            until=min(time.time()+p['poll_seconds'],state['end'])
            while time.time()<until:
                if Path('STOP').exists():break
                time.sleep(min(1,until-time.time()))
    except KeyboardInterrupt:print('Stopped; observations saved.',flush=True)
    finally:
        report(ledger.db,state)
        if time.time()>=state['end']:
            email_summary(ledger.db,state,p,enabled,final=True)
            print('Monitoring finished. Final report: personal-report.html',flush=True)
        ledger.db.close();lock.close()


if __name__=='__main__':
    try:main()
    except (Stop,RuntimeError) as error:print(str(error),flush=True)
