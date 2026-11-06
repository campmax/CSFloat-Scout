pass                                                                               
import collections
import datetime as dt
import json
import math
from pathlib import Path
import time


def defaults(c):
    from paper_portfolio import settings
    c['paper_portfolio']=settings(c)
    c.setdefault('paper_listing_interval_seconds',15)
    c.setdefault('history_request_interval_seconds',900)
    c.setdefault('paper_history_cache_seconds',3600)
    c.setdefault('slow_paper_mode',True)
    c.setdefault('paper_snapshot_seconds',180)
    c.setdefault('paper_requests_per_cycle',12)
    c.setdefault('paper_research_limit',6)
    c.setdefault('newest_check_seconds',120)
    c.setdefault('side_feed_queue_limit',12)
    c.setdefault('paper_queue_max_age_seconds',3600)
    c.setdefault('deals_interval_seconds',300)
    c.setdefault('focus_interval_seconds',600)
    c.setdefault('paper_poll_seconds',15)
    c.setdefault('discovery_pages_per_cycle',12)
    c.setdefault('evaluations_per_cycle',3)
    c.setdefault('discovery_overlap_seconds',120)
    c.setdefault('prefilter_discount',.08)
    c.setdefault('recent_pages_per_cycle',3)
    c.setdefault('deal_pages_per_cycle',2)
    c.setdefault('focus_watchlist',['★ Sport Gloves | Amphibious (Field-Tested)'])
    c.setdefault('paper_review',{})
    for key,value in dict(watch_enabled=True,watch_discount=.04,watch_net_cents=100,enabled=True,min_discount=.06,high_discount=.15,max_weekly_loss=.06,min_sales=4,min_recent_sales=2,sales_window_days=7,recent_window_days=3,float_tolerance=.05,max_listing_age_seconds=2592000,prefilter_discount=.04,min_good_net_cents=200,min_good_stressed_cents=100,min_good_stressed_roi=.01).items():
        c['paper_review'].setdefault(key,value)
    c.setdefault('paper_profile',{})
    p=c['paper_profile']
    for key,value in dict(min_discount=.15,stable_discount=.10,min_independent_sellers=3,
                          min_sales=5,min_recent_sales=3,float_tolerance=.03,
                          min_net_profit_cents=1000,min_stressed_profit_cents=1000,
                          min_stressed_roi=.03,min_stress_drop=.03,resale_slippage_rate=.02,
                          max_listing_age_seconds=3600,stable_max_change=.03,
                          stable_max_drawdown=.03,stable_max_iqr=.15,
                          stable_min_profit_cents=500,stable_min_stressed_roi=.015).items():
        p.setdefault(key,value)
    return c


def paper_runtime_config(c):
    pass                                                                          
    c=dict(c)
    c['request_interval_seconds']=max(15,c['paper_listing_interval_seconds'])
    c['paper_review']=dict(c['paper_review'])
    c['paper_review'].setdefault('best_available',True)
    c['paper_review'].setdefault('hourly_ranking',True)
    c['paper_review'].update(min_sales=min(c['paper_review']['min_sales'],3),
                            min_discount=min(c['paper_review']['min_discount'],.05),
                            prefilter_discount=min(c['paper_review']['prefilter_discount'],.03))
    if c['paper_review'].get('best_available',True):
        c['paper_review'].update(min_sales=2,min_recent_sales=1,watch_enabled=True,
                                watch_discount=.02,watch_net_cents=1,prefilter_discount=.02)
    if c.get('slow_paper_mode',True):
        for key,floor in dict(paper_poll_seconds=60,newest_check_seconds=300,
                              deals_interval_seconds=900,focus_interval_seconds=1800).items():
            c[key]=max(c[key],floor)
        for key,ceiling in dict(paper_requests_per_cycle=8,paper_research_limit=3,
                                recent_pages_per_cycle=3,deal_pages_per_cycle=1).items():
            c[key]=min(c[key],ceiling)
    return c


def profile(c,live,chart=None,now=None):
    from scout import timestamp
    from risk import chart_trend
    effective=dict(c)
    if live:
        return effective,'live_strict'
    if c['paper_review']['enabled']:
        effective.update(c['paper_review'])
        effective['_paper_review']=True
        return effective,'paper_review'
    p=c['paper_profile']
    for key in ('min_discount','min_independent_sellers','min_sales','min_recent_sales',
                'float_tolerance','min_net_profit_cents','min_stressed_profit_cents',
                'min_stressed_roi','min_stress_drop','resale_slippage_rate','max_listing_age_seconds'):
        effective[key]=p[key]
    tier='paper_15'
    if chart is not None:
        trend=chart_trend(chart,now or time.time(),effective,timestamp)
        if (trend['risk_ok'] and abs(trend['weekly_change'])<=p['stable_max_change'] and
                trend['weekly_drawdown']<=p['stable_max_drawdown'] and trend['trend_days']>=7):
            tier='stable_10'
            effective.update(min_discount=p['stable_discount'],
                max_sales_iqr_ratio=min(c['max_sales_iqr_ratio'],p['stable_max_iqr']),
                min_net_profit_cents=p['stable_min_profit_cents'],
                min_stressed_profit_cents=p['stable_min_profit_cents'],
                min_stressed_roi=p['stable_min_stressed_roi'])
    return effective,tier


def queue_mode(c,live):
    return 'live' if live else ('paper_review_v4' if c['paper_review']['enabled'] else 'paper')


def init(db):
    from scheduling import init as init_schedule
    init_schedule(db)
    db.execute('CREATE TABLE IF NOT EXISTS discovery_state (target TEXT PRIMARY KEY, payload TEXT)')
    db.execute('CREATE TABLE IF NOT EXISTS scan_seen (id TEXT PRIMARY KEY, first_seen REAL, last_seen REAL)')
    db.execute('CREATE TABLE IF NOT EXISTS scan_items (id TEXT,price INTEGER,mode TEXT,state TEXT,reason TEXT,score REAL,added REAL,payload TEXT,PRIMARY KEY(id,price,mode))')
    db.execute('CREATE TABLE IF NOT EXISTS evidence_cache (key TEXT PRIMARY KEY, fetched REAL, payload TEXT)')
    db.execute('CREATE TABLE IF NOT EXISTS listing_snapshots (id TEXT,price INTEGER,seen REAL,payload TEXT,PRIMARY KEY(id,price))')
    db.execute('CREATE INDEX IF NOT EXISTS snapshot_seen_idx ON listing_snapshots(seen)')
    db.execute('CREATE TABLE IF NOT EXISTS observed_sales (market TEXT,id TEXT,sold REAL,payload TEXT,PRIMARY KEY(market,id))')


def cached(db,key,ttl,fetch):
    previous=db.execute('SELECT fetched,payload FROM evidence_cache WHERE key=?',(key,)).fetchone()
    if previous and 0<=time.time()-previous[0]<ttl:
        return json.loads(previous[1])
    value=fetch()
    db.execute('INSERT OR REPLACE INTO evidence_cache VALUES (?,?,?)',(key,time.time(),json.dumps(value)))
    return value


def screen(listing,c,now):
    from scout import cents,timestamp
    item=listing.get('item') or {}
    price=listing.get('price')
    if not listing.get('id') or not cents(price):return 'invalid ID or price',0
    if listing.get('state')!='listed' or listing.get('type')!='buy_now':return 'not active buy-now',0
    if price<c['min_price_cents'] or (c['max_price_cents'] is not None and price>c['max_price_cents']):return 'price range',0
    if not 0<=now-timestamp(listing.get('created_at'))<=c['max_listing_age_seconds']:return 'listing too old or invalid date',0
    name=item.get('market_hash_name','')
    if not name:return 'missing market name',0
    review=c.get('_paper_review',False)
    f=item.get('float_value')
    if type(f) not in (int,float) or not math.isfinite(f) or not 0<=f<=1:return 'unsupported item / invalid float',0
    if not review and any(x.lower() in name.lower() for x in c['exclude_name_contains']):return 'pattern-sensitive finish',0
    if not review and (item.get('stickers') or item.get('keychains')):return 'decorated item',0
    ref=listing.get('reference') or {}
                                                                                   
    reference=max([v for v in (ref.get('predicted_price'),ref.get('base_price')) if cents(v)],default=None) if review else ref.get('predicted_price')
    if not cents(reference):reference=ref.get('base_price')
    if not cents(reference):return (None,0) if review else ('missing reference for cheap prefilter',0)
    discount=round(1-price/reference,12)
    if discount<c['prefilter_discount']:return 'reference discount below prefilter',discount
    return None,discount


def ingest(db,listings,c,mode,counts,feed=None):
    from scout import cents
    now=time.time()
    for listing in listings:
        if not isinstance(listing,dict):continue
        lid=listing.get('id');price=listing.get('price')
        counts['returned']+=1
        if not isinstance(lid,str) or not cents(price):
            counts['malformed']+=1;continue
        new=db.execute('INSERT OR IGNORE INTO scan_seen VALUES (?,?,?)',(lid,now,now)).rowcount
        counts['new_unique']+=new
        db.execute('UPDATE scan_seen SET last_seen=? WHERE id=?',(now,lid))
        if feed:
            db.execute('INSERT OR REPLACE INTO listing_snapshots VALUES (?,?,?,?)',(lid,price,now,json.dumps(listing)))
            from scheduling import tag
            tag(db,lid,price,mode,feed)
        if db.execute('SELECT 1 FROM scan_items WHERE id=? AND price=? AND mode=?',(lid,price,mode)).fetchone():
            counts['duplicate_versions']+=1;continue
        if db.execute('SELECT 1 FROM purchases WHERE id=?',(lid,)).fetchone():
            reason,score='already purchased/reserved',0
        else:reason,score=screen(listing,c,now)
        if mode=='paper_review_v4':
            counts['queue_superseded']+=db.execute("UPDATE scan_items SET state='superseded',reason='newer listing price observed' WHERE id=? AND price!=? AND mode=? AND state='queued'",(lid,price,mode)).rowcount
        state='screened_out' if reason else 'queued'
        db.execute('INSERT INTO scan_items VALUES (?,?,?,?,?,?,?,?)',(lid,price,mode,state,reason or '',score,now,json.dumps(listing) if not reason else '{}'))
        counts['new_candidates' if not reason else 'screened_out']+=1
        if reason:counts['screen:'+reason]+=1


def discover(api,db,c,live,counts):
    if not live and c['paper_review']['enabled']:
        from discovery import discover as ranked_discovery
        return ranked_discovery(api,db,c,live,counts)
    from scout import rows,timestamp,Stop
    effective,_=profile(c,live)
    targets=c['watchlist'] or [None]
                                                                                  
    row=db.execute("SELECT payload FROM discovery_state WHERE target='__rotation__'").fetchone()
    index=int(json.loads(row[0])) if row else 0
    target=targets[index%len(targets)]
    db.execute("INSERT OR REPLACE INTO discovery_state VALUES ('__rotation__',?)",(json.dumps(index+1),))
    key=json.dumps([target,c['min_price_cents'],c['max_price_cents'],queue_mode(c,live)])
    previous=db.execute('SELECT payload FROM discovery_state WHERE target=?',(key,)).fetchone()
    state=json.loads(previous[0]) if previous else {'watermark':time.time()-effective['max_listing_age_seconds'],'cursor':None}
    params=dict(limit=50,sort_by='most_recent',type='buy_now',min_price=c['min_price_cents'])
    if c['max_price_cents'] is not None:params['max_price']=c['max_price_cents']
    if target:params['market_hash_name']=target
    mode=queue_mode(c,live)
                                                                           
    head=api.listings(**params);listings=rows(head)
    counts['discovery_pages']+=1
    ingest(db,listings,effective,mode,counts)
    if not state.get('cursor'):
        state['boundary']=state['watermark']-c['discovery_overlap_seconds']
        state['anchor']=max([timestamp(x.get('created_at')) for x in listings]+[state['watermark']])
        payload=head
    else:
        payload=None
    visited=set()
    while True:
        if Path('STOP').exists():raise Stop('STOP file present.')
        if payload is not None:
            page=rows(payload)
            times=[timestamp(x.get('created_at')) for x in page]
            reached=bool(times) and all(times) and min(times)<=state['boundary']
            cursor=payload.get('cursor') if isinstance(payload,dict) else None
            exhausted=len(page)<50
            if reached or exhausted:
                state.update(watermark=state['anchor'],cursor=None)
                counts['coverage_boundary_reached']=1
                break
            if not cursor:
                counts['coverage_unknown_no_cursor']=1
                                                                    
                state.update(cursor=None,watermark=state['anchor'])
                counts['coverage_gap']=1
                break
            if cursor in visited:
                raise Stop('Repeated discovery cursor; stop rather than loop API requests.')
            visited.add(cursor)
            state['cursor']=cursor
        if counts['discovery_pages']>=c['discovery_pages_per_cycle']:
            counts['backlog_continues']=1
            break
        payload=api.listings(**params,cursor=state['cursor'])
        counts['discovery_pages']+=1
        ingest(db,rows(payload),effective,mode,counts)
                                                                                     
                                                                               
        db.execute('INSERT OR REPLACE INTO discovery_state VALUES (?,?)',(key,json.dumps(state)))
    db.execute('INSERT OR REPLACE INTO discovery_state VALUES (?,?)',(key,json.dumps(state)))
    counts['target']=target or 'all names in price range'


def sales_evidence(api,db,name,paint,lookback,ttl=600):
    from scout import timestamp
    key=json.dumps([name,paint])
    data=cached(db,'sales:'+key,ttl,lambda:api.sales(name,paint))
    for sale in data:
        sold=timestamp(sale.get('sold_at'))
        if sale.get('id') and sold and sale.get('state')=='sold':
            db.execute('INSERT OR REPLACE INTO observed_sales VALUES (?,?,?,?)',(key,sale['id'],sold,json.dumps(sale)))
    dates=[timestamp(x.get('sold_at')) for x in data if timestamp(x.get('sold_at'))]
    cache_row=db.execute('SELECT fetched FROM evidence_cache WHERE key=?',('sales:'+key,)).fetchone()
    source=dict(api_rows=len(data),dated_api_rows=len(dates),oldest_api_sale=min(dates) if dates else None,newest_api_sale=max(dates) if dates else None,api_history_complete=False,
                fetched_at=cache_row[0] if cache_row else None,cache_age_seconds=round(time.time()-cache_row[0]) if cache_row else None)
    metadata=getattr(api,'sales_metadata',{})
    if isinstance(metadata,dict):source.update(metadata.get((name,paint),{}))
    db.execute('INSERT OR REPLACE INTO evidence_cache VALUES (?,?,?)',('sales_source:'+key,time.time(),json.dumps(source)))
    cutoff=time.time()-lookback*86400
    db.execute('DELETE FROM observed_sales WHERE sold<?',(cutoff,))
    return [json.loads(x[0]) for x in db.execute('SELECT payload FROM observed_sales WHERE market=? AND sold>=?',(key,cutoff))]


def evaluate_queue(api,ledger,c,live,counts):
    from scout import rows,timestamp,evaluate,acquisition_cost,purchase,Stop,AccessStop,RequestBudgetStop,HistoryDeferred,QuotaDeferred,API
    import email_alerts
    db=ledger.db
    mode=queue_mode(c,live)
    base,_=profile(c,live)
                                                                                     
    for lid,price,raw in db.execute("SELECT id,price,payload FROM scan_items WHERE mode=? AND state='queued'",(mode,)).fetchall():
        listing=json.loads(raw)
        if time.time()-timestamp(listing.get('created_at'))>base['max_listing_age_seconds']:
            db.execute("UPDATE scan_items SET state='expired',reason='queue age exceeded' WHERE id=? AND price=? AND mode=?",(lid,price,mode))
            counts['queue_expired']+=1
    if not live and c['paper_review']['enabled']:
        counts['queue_deadline_expired']+=db.execute("UPDATE scan_items SET state='expired',reason='paper research queue deadline exceeded' WHERE mode=? AND state='queued' AND added<?",(mode,time.time()-c.get('paper_queue_max_age_seconds',3600))).rowcount
        from scheduling import select
        research_config=dict(c,evaluations_per_cycle=c.get('paper_research_limit',c['evaluations_per_cycle']))
        if isinstance(api,API) and api.policy.state['route_mode']:
            def readiness(listing):
                from scheduling import market_key
                key=market_key(listing);now=time.time();ttl=c['paper_history_cache_seconds']
                def fresh(prefix):
                    row=db.execute('SELECT fetched FROM evidence_cache WHERE key=?',(prefix+key,)).fetchone()
                    return bool(row and 0<=now-row[0]<ttl)
                if not fresh('sales:'):return 1 if api.policy.history_due() else 0
                wait=db.execute('SELECT payload FROM discovery_state WHERE target=?',
                                ('history_wait:'+json.dumps([listing['id'],listing['price']]),)).fetchone()
                if wait and not fresh('chart:') and not c['paper_review'].get('best_available'):
                    return 4 if api.policy.history_due() else 0
                return 3
            pending=select(db,research_config,mode,counts,readiness=readiness)
            counts['history_deferred']+=counts['queue:waiting_history']
        else:pending=select(db,research_config,mode,counts)
    else:
        pending=[(*row,'legacy') for row in db.execute("SELECT id,price,payload FROM scan_items WHERE mode=? AND state='queued' ORDER BY score DESC,added DESC LIMIT ?",(mode,c['evaluations_per_cycle'])).fetchall()]
    last_head_check=time.monotonic()
    for pending_index,(lid,price,raw,research_feed) in enumerate(pending):
        if pending_index and not live and c['paper_review']['enabled'] and time.monotonic()-last_head_check>=c.get('newest_check_seconds',120):
            from discovery import discover as fresh_discovery
            try:fresh_discovery(api,db,c,False,counts,newest_only=True,head_only=True)
            except QuotaDeferred:counts['discovery_quota_wait']+=1
            last_head_check=time.monotonic()
        if Path('STOP').exists():raise Stop('STOP file present.')
        listing=json.loads(raw);item=listing['item'];name=item['market_hash_name'];paint=item.get('paint_index')
        started=time.monotonic()
        paper_assessment=None;confirmed_wall=None;paper_history_age=None;paper_ask_age=None;evidence_checked_at=None
        try:
            if not live and isinstance(api,API) and api.policy.state['route_mode']:
                wait_key='history_wait:'+json.dumps([lid,price])
                waiting=db.execute('SELECT payload FROM discovery_state WHERE target=?',(wait_key,)).fetchone()
                chart_row=db.execute('SELECT fetched FROM evidence_cache WHERE key=?',('chart:'+json.dumps([name,paint]),)).fetchone()
                chart_ready=bool(chart_row and 0<=time.time()-chart_row[0]<c['paper_history_cache_seconds'])
                if waiting and not chart_ready and not api.policy.history_due() and not c['paper_review'].get('best_available'):
                    counts['history_deferred']+=1;continue
                source=db.execute('SELECT fetched FROM evidence_cache WHERE key=?',('sales:'+json.dumps([name,paint]),)).fetchone()
                if (not source or not 0<=time.time()-source[0]<c['paper_history_cache_seconds']) and not api.policy.history_due():
                    counts['history_deferred']+=1;continue
                                                                                
            snapshot=db.execute('SELECT seen,payload FROM listing_snapshots WHERE id=? AND price=?',(lid,price)).fetchone()
            if not live and snapshot and 0<=time.time()-snapshot[0]<=c.get('paper_snapshot_seconds',180):
                fresh=json.loads(snapshot[1]);counts['detail_requests_saved']+=1
            else:
                try:fresh=api.detail(lid)
                except QuotaDeferred:
                                                                           
                                                                              
                    if not live and api.policy.history_due():
                        before=api.request_count
                        if waiting and not chart_ready:
                            cached(db,'chart:'+json.dumps([name,paint]),c['paper_history_cache_seconds'],lambda:api.graph(name,paint))
                        else:
                            sales_evidence(api,db,name,paint,base['sales_lookback_days'],c['paper_history_cache_seconds'])
                        counts['history_prefetched']+=api.request_count-before
                    raise
            if not isinstance(fresh,dict) or fresh.get('id')!=lid:raise Stop('Detail identity mismatch.')
            if fresh.get('state')!='listed' or fresh.get('type')!='buy_now' or fresh.get('price')!=price:
                result={'eligible':False,'reason':'sold, withdrawn or price changed before evaluation'};tier='not_evaluated'
            else:
                value=item.get('float_value')
                if type(value) not in (int,float) or not math.isfinite(value) or not 0<=value<=1:
                    result={'eligible':False,'reason':'missing valid float'};tier='not_evaluated'
                else:
                                                                                    
                                                                                        
                    params=dict(limit=50,sort_by='lowest_price',type='buy_now',market_hash_name=name,
                                min_float=max(0,value-base['float_tolerance']),max_float=min(1,value+base['float_tolerance']))
                    if paint is not None:params['paint_index']=paint
                    ask_key='asks:'+json.dumps(params,sort_keys=True)
                    judge=evaluate
                    if not live and c['paper_review']['enabled']:
                        from review import evaluate_review
                        judge=evaluate_review
                        effective,tier=profile(c,False)
                        sales=sales_evidence(api,db,name,paint,base['sales_lookback_days'],c['paper_history_cache_seconds'])
                                                                                  
                                                                              
                                                                   
                        asks=[];chart=[]
                        result=judge(fresh,asks,sales,effective,chart=chart)
                        plausible=(result.get('estimated_net_cents',0)>0 and
                                   result.get('discount',0)>=min(c['paper_review']['min_discount'],c['paper_review']['watch_discount']))
                        if plausible:
                            chart_key='chart:'+json.dumps([name,paint])
                            chart_row=db.execute('SELECT fetched,payload FROM evidence_cache WHERE key=?',(chart_key,)).fetchone()
                            if c['paper_review'].get('best_available'):
                                                                                     
                                                                                   
                                chart=json.loads(chart_row[1]) if chart_row and 0<=time.time()-chart_row[0]<c['paper_history_cache_seconds'] else []
                                counts['chart_requests_saved']+=1
                            else:chart=cached(db,chart_key,c['paper_history_cache_seconds'],lambda:api.graph(name,paint))
                            result=judge(fresh,asks,sales,effective,chart=chart)
                            if result['eligible']:
                                asks=cached(db,ask_key,120,lambda:rows(api.listings(**params)))
                                result=judge(fresh,asks,sales,effective,chart=chart)
                            else:counts['competition_requests_saved']+=1
                        else:
                            result['research_stage']='sales_only'
                            counts['chart_requests_saved']+=1;counts['competition_requests_saved']+=1
                    else:
                        asks=cached(db,ask_key,60,lambda:rows(api.listings(**params)))
                        sales=sales_evidence(api,db,name,paint,base['sales_lookback_days'])
                        chart=cached(db,'chart:'+json.dumps([name,paint]),900,lambda:api.graph(name,paint))
                        effective,tier=profile(c,live,chart)
                        result=judge(fresh,asks,sales,effective,chart=chart)
                    tier=result.get('review_tier',tier)
                    if result['eligible'] and not live:
                        strict=evaluate(fresh,asks,sales,c,chart=chart)
                        if strict['eligible']:tier='strict_20'
                    if not live and c['paper_review']['enabled'] and c.get('paper_portfolio',{}).get('enabled',True):
                        from paper_portfolio import assess
                        paper_assessment=assess(fresh,asks,sales,c)
                        for prefix,key in (('history','sales:'+json.dumps([name,paint])),('asks',ask_key)):
                            evidence_row=db.execute('SELECT fetched FROM evidence_cache WHERE key=?',(key,)).fetchone()
                            age=max(0,time.time()-evidence_row[0]) if evidence_row else None
                            if prefix=='history':paper_history_age=age
                            else:paper_ask_age=age
                        evidence_checked_at=time.time()
                    if result['eligible']:
                                                                                  
                                                                                    
                        final=api.detail(lid)
                        confirmed_at=time.monotonic()
                        confirmed_wall=time.time()
                        if final.get('id')!=lid or final.get('price')!=price:
                            result={'eligible':False,'reason':'listing changed during validation'}
                        elif paper_assessment is not None and any((final.get('item') or {}).get(k)!=(fresh.get('item') or {}).get(k) for k in ('market_hash_name','def_index','paint_index','float_value','paint_seed','stickers','keychains')):
                            result={'eligible':False,'reason':'listing item changed during validation'}
                        else:
                            fresh=final;result=judge(fresh,asks,sales,effective,chart=chart)
                    freshness_start=started if live or not result['eligible'] else confirmed_at
                    if time.monotonic()-freshness_start>c['max_validation_seconds'] and (live or result['eligible']):
                        result={'eligible':False,'reason':'validation exceeded freshness budget'}
            if paper_assessment is not None:
                result['paper_purchase']=paper_assessment
                result['paper_item']=fresh.get('item',{})
                elapsed=max(0,time.time()-evidence_checked_at) if evidence_checked_at is not None else 0
                result['paper_history_age_seconds']=paper_history_age+elapsed if paper_history_age is not None else None
                result['paper_competition_age_seconds']=paper_ask_age+elapsed if paper_ask_age is not None else None
            if result.get('float_model'):
                counts['float_model:'+result['float_model']['status']]+=1
                counts['float_adjusted_sales']+=sum(a['accepted_after_outlier_check'] for a in result.get('float_adjustments',[]))
            counts['evaluated']+=1
            counts['researched:'+research_feed]+=1
            if not live and c['paper_review']['enabled']:
                from scheduling import observe
                observe(db,fresh,result)
            source_row=db.execute('SELECT payload FROM evidence_cache WHERE key=?',('sales_source:'+json.dumps([name,paint]),)).fetchone()
            if source_row:result['history_source']=json.loads(source_row[0])
            record=dict(time=dt.datetime.now(dt.timezone.utc).isoformat(),id=lid,name=name,
                        url='https://csfloat.com/item/'+lid,mode=mode,tier=tier,research_feed=research_feed,**result)
            from listing_time import fields
            record.update(fields(fresh.get('created_at')))
            record.setdefault('price_cents',price)
            queued_at=db.execute('SELECT added FROM scan_items WHERE id=? AND price=? AND mode=?',(lid,price,mode)).fetchone()
            if queued_at:record['discovery_to_decision_seconds']=round(max(0,time.time()-queued_at[0]),1)
            if paper_assessment is not None:
                from paper_portfolio import consider
                paper_result=consider(db,record,c,confirmed_wall)
                if paper_result:
                    record['paper_purchase']=paper_result
                    counts['paper_purchase:'+paper_result['status']]+=1
                    if paper_result['status']=='paper_bought':
                        from paper_portfolio import flush_mail
                        flush_mail(db,c,time.time())
            with open('decisions.jsonl','a',encoding='utf-8') as f:f.write(json.dumps(record)+'\n')
            if not live:
                from shortlist import remember
                remember(db,record)
            db.execute('UPDATE scan_items SET state=?,reason=? WHERE id=? AND price=? AND mode=?',
                       ('qualified' if result['eligible'] else 'rejected',result['reason'],lid,price,mode))
            counts['decision:'+result['reason']]+=1
            if not live:
                with open('paper-review.jsonl','a',encoding='utf-8') as f:f.write(json.dumps(record)+'\n')
            if result['eligible']:
                counts['qualified']+=1
                counts['paper_watch' if result.get('review_tier')=='paper_watch' else 'stronger_alerts']+=1
                if live:
                    purchase(api,ledger,fresh,c,record)
                    email_alerts.flush_purchases(db,c)
                else:
                    if ledger.alert_once(fresh):print('\a'+json.dumps(record),flush=True)
                    if not c['paper_review'].get('hourly_ranking'):email_alerts.notify(db,record,c)
            if not live and c['paper_review'].get('hourly_ranking'):
                from hourly import remember as hourly_remember
                hourly_remember(db,record,c)
        except HistoryDeferred:
            counts['history_deferred']+=1
            db.execute('INSERT OR REPLACE INTO discovery_state VALUES (?,?)',
                       ('history_wait:'+json.dumps([lid,price]),json.dumps(api.policy.state['history_next'])))
            continue
        except QuotaDeferred:
            if live:raise
            counts['research_quota_wait']+=1
            continue
        except (AccessStop,RequestBudgetStop):raise
        except Stop as error:
                                                                                     
                                                                                 
            if live:raise
            from runtime_log import event
            event('candidate_read_error',error,listing_id=lid)
            counts['api_errors']+=1
            print(str(error),flush=True)
            break


def scan(api,ledger,c,live=False):
    import email_alerts
    init(ledger.db)
    email_alerts.flush_purchases(ledger.db,c)
    counts=collections.Counter()
    started=time.monotonic()
    from scout import API,RequestBudgetStop,QuotaDeferred
    metered=isinstance(api,API) and not live and c['paper_review']['enabled']
    before_requests=api.request_count if metered else 0
    if metered:api.budget_end=api.request_count+c['paper_requests_per_cycle']
    try:
        if not live and c['paper_review']['enabled']:
            from discovery import discover as fresh_discovery
            try:fresh_discovery(api,ledger.db,c,False,counts,newest_only=True)
            except QuotaDeferred:counts['discovery_quota_wait']+=1
            if metered:
                from prospect_status import probe
                probe(api,ledger.db,counts)
            evaluate_queue(api,ledger,c,False,counts)
            try:fresh_discovery(api,ledger.db,c,False,counts,secondary_only=True)
            except QuotaDeferred:counts['discovery_quota_wait']+=1
        else:
            discover(api,ledger.db,c,live,counts)
            evaluate_queue(api,ledger,c,live,counts)
    except RequestBudgetStop:
        counts['request_budget_reached']+=1
    finally:
        if metered:
            counts['api_requests']=api.request_count-before_requests
            api.budget_end=None
    counts['queue_remaining']=ledger.db.execute("SELECT COUNT(*) FROM scan_items WHERE state='queued' AND mode=?",(queue_mode(c,live),)).fetchone()[0]
    counts['unique_discovered_total']=ledger.db.execute('SELECT COUNT(*) FROM scan_seen').fetchone()[0]
    if metered and api.policy.state['route_mode']:
        counts['read_quota_wait_seconds']=max(0,math.ceil(max(api.policy.quotas.deadline('listings_page'),api.policy.quotas.deadline('listing_detail'))-time.time()))
        counts['history_wait_seconds']=max(0,math.ceil(api.policy.state['history_next']-time.time()))
        interval=api.policy.quotas.interval('history',time.time())
        if interval is not None:
            counts['history_quota_interval_seconds']=math.ceil(max(interval,api.policy.state['history_backoff']))
            counts['history_quota_remaining']=api.policy.quotas.buckets['history']['remaining']
    summary=dict(time=dt.datetime.now(dt.timezone.utc).isoformat(),mode=queue_mode(c,live),
                 cycle_seconds=round(time.monotonic()-started,1),process_state='running',**counts)
    with open('scan-stats.jsonl','a',encoding='utf-8') as f:f.write(json.dumps(summary)+'\n')
    Path('status.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
    if not live and c['paper_review']['enabled']:
        from paper_portfolio import tick as portfolio_tick
        portfolio_tick(ledger.db,c)
        from shortlist import export
        export(ledger.db)
        if c['paper_review'].get('hourly_ranking'):
            from hourly import tick
            tick(ledger.db,c)
    print(f"Scan: {counts['returned']} total searched / {counts['new_unique']} NEW unique / "
          f"{counts['new_candidates']} candidates / {counts['evaluated']} researched / "
          f"{counts['qualified']} passed / {counts['queue_remaining']} queued. "
          f"Total unique seen: {counts['unique_discovered_total']}.",flush=True)
    screen_counts={k[7:]:v for k,v in counts.items() if k.startswith('screen:')}
    distribution={k:v for k,v in counts.items() if k.startswith('researched:') or k=='queue:cooldown'}
    if distribution:print('Research distribution: '+json.dumps(distribution),flush=True)
    reasons={k[9:]:v for k,v in counts.items() if k.startswith('decision:')}
    if reasons:print('Research outcomes: '+json.dumps(reasons),flush=True)
    paper_counts={k.split(':',1)[1]:v for k,v in counts.items() if k.startswith('paper_purchase:')}
    if paper_counts:print('Paper portfolio: '+json.dumps(paper_counts)+'; see paper-portfolio.html.',flush=True)
    if counts['paper_watch']:print(f"Paper watch leads: {counts['paper_watch']} (manual review; downside may be negative).",flush=True)
    if counts['availability_probes']:print(f"Availability probes: {counts['availability_probes']} (within cycle budget).",flush=True)
    if counts['history_deferred']:print(f"History pacing: {counts['history_deferred']} candidates waiting; runnable cached candidates selected first.",flush=True)
    if counts['discovery_quota_wait'] or counts['research_quota_wait']:
        print(f"Listing/read quota waiting: {counts['read_quota_wait_seconds']}s remaining; available history and cached work still considered. Not a cycle-budget stop.",flush=True)
    if counts['history_prefetched']:
        print(f"Shared history requests completed: {counts['history_prefetched']}; listing confirmation still waiting (not a passed candidate).",flush=True)
    if counts['history_wait_seconds']:print(f"Next history slot in {counts['history_wait_seconds']}s; cached evidence can be used meanwhile.",flush=True)
    if counts['history_quota_interval_seconds']:
        print(f"History quota: {counts['history_quota_remaining']} remaining; paced at about {counts['history_quota_interval_seconds']}s/request including reserve. This is requests, not completed candidates.",flush=True)
    if counts['discovery_pages']:
        print(f"Discovery yield: {counts['new_unique']/counts['discovery_pages']:.1f} new IDs/request; {counts['duplicate_versions']} unchanged listing versions skipped.",flush=True)
    if screen_counts:print('Early filters: '+json.dumps(screen_counts),flush=True)
    if counts['backlog_continues']:print('Coverage: backlog saved; next cycle resumes it and checks the newest page.',flush=True)
    if metered:print(f"API requests: {counts['api_requests']}/{c['paper_requests_per_cycle']} cycle budget; minimum spacing {api.policy.state['interval']:g}s.",flush=True)
    if counts['request_budget_reached']:print('Request budget reached; unfinished candidates remain queued.',flush=True)
    if counts['coverage_gap']:print('Coverage gap recorded; see scan-stats.jsonl for cursor details.',flush=True)
    if counts['chart_requests_saved'] or counts['detail_requests_saved']:
        print(f"Requests saved: {counts['detail_requests_saved']} detail / {counts['chart_requests_saved']} chart / {counts['competition_requests_saved']} competition.",flush=True)
    if counts['coverage_unknown_no_cursor']:print('Coverage unknown: full page without a next cursor; cannot claim full-market coverage.',flush=True)
