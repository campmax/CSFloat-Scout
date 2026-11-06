import json

def queries(db,c,turn,now):
    from radar import timestamp
    common=dict(limit=50,type='buy_now',min_price=c['min_price_cents']-1,max_price=c['max_price_cents']+1)
    yield dict(common,sort_by='most_recent')
    bands=[(2000,5000),(5000,10000),(10000,20000),(20000,40000),(40000,70000),(70000,100000)]
    if turn%7==0:yield dict(common,sort_by='best_deal')
    else:
        lo,hi=bands[(turn-1)%6];lo=max(lo,c['min_price_cents']);hi=min(hi,c['max_price_cents'])
        if lo<=hi:yield dict(common,sort_by='best_deal',min_price=lo-1,max_price=hi+1)

    active=[]
    for key,fetched,payload in db.execute('SELECT market,fetched,payload FROM radar_history'):
        if not 0<=now-fetched<=c['history_cache_seconds']:continue
        name,paint=json.loads(key);sales=json.loads(payload)
        ids={str(s['id']) for s in sales if isinstance(s,dict) and s.get('id') and s.get('state')=='sold' and
             (s.get('item') or {}).get('market_hash_name')==name and 0<=now-timestamp(s.get('sold_at'))<=7*86400}
        if ids:active.append((len(ids),name))
    if active and turn%2==0:
        active.sort(reverse=True);name=active[(turn//2)%min(10,len(active))][1]
        yield dict(common,sort_by='best_deal',market_hash_name=name)

def select_picks(db,c,now,previous_ids):
    from radar import evidence,support
    db.execute('CREATE TABLE IF NOT EXISTS radar_reported (id TEXT PRIMARY KEY,price INTEGER,sent REAL)')

    for item_id in previous_ids:
        row=db.execute('SELECT price FROM radar_items WHERE id=?',(item_id,)).fetchone()
        if row:db.execute('INSERT OR IGNORE INTO radar_reported VALUES (?,?,?)',(item_id,row[0],now))
    candidates=[];reasons={}
    for seen,raw in db.execute('SELECT seen,payload FROM radar_items WHERE seen>=? AND price BETWEEN ? AND ?',
                              (now-600,c['min_price_cents'],c['max_price_cents'])):
        r=json.loads(raw);prior=db.execute('SELECT price FROM radar_reported WHERE id=?',(r['id'],)).fetchone()
        reason=None
        if (prior and r['price_cents']>=prior[0]) or (not prior and r['id'] in previous_ids):reason='already emailed; no price drop'
        elif not r.get('discount_source') or r['discount']<=0:reason='no positive reference markdown'
        sales,fetched=evidence(db,r,c,now);e=support(r,sales,fetched,now)
        qty=r.get('reference',{}).get('quantity')
        if not reason and e.get('history_checked') and not e.get('market_recent_sales'):reason='no recent sales in fetched history'
        if not reason and not e.get('market_recent_sales') and (type(qty) is not int or qty<3):reason='sparse reference and no recent sales evidence'
        if reason:reasons[reason]=reasons.get(reason,0)+1;continue
        r.update(support=e,observation_age_seconds=max(0,int(now-seen)),repeated=False)
        candidates.append(r)
    candidates.sort(key=lambda r:(r['discount'],r['support'].get('market_recent_sales',0)),reverse=True)

    picks=[];names=set()
    for r in candidates:
        if r['name'] in names:continue
        names.add(r['name']);picks.append(r)
        if len(picks)==3:break
    return picks,reasons
