"""Fair paper research scheduling; preserves scan_items and purchase ledgers."""
import json
import time


def init(db):
    db.execute('CREATE TABLE IF NOT EXISTS candidate_feeds (id TEXT,price INTEGER,mode TEXT,feed TEXT,PRIMARY KEY(id,price,mode,feed))')
    db.execute('CREATE TABLE IF NOT EXISTS research_health (market TEXT PRIMARY KEY,failures INTEGER,last_id TEXT,cooldown_until REAL)')


def market_key(listing):
    item=listing.get('item') or {}
    return json.dumps([item.get('market_hash_name'),item.get('paint_index')])


def tag(db,lid,price,mode,feed):
    db.execute('INSERT OR IGNORE INTO candidate_feeds VALUES (?,?,?,?)',(lid,price,mode,feed))


def observe(db,listing,result,now=None):
    now=time.time() if now is None else now
    # Only actual matching-sales evidence changes health; sold items/API errors don't.
    if 'sales_count' not in result:return
    key=market_key(listing)
    previous=db.execute('SELECT failures,last_id,cooldown_until FROM research_health WHERE market=?',(key,)).fetchone()
    paper=result.get('paper_purchase') or {}
    thin_local=bool(paper and (paper.get('direct_sales',0)<2 or paper.get('direct_recent_sales',0)<1))
    if result['sales_count']>0 and not thin_local:
        db.execute('INSERT OR REPLACE INTO research_health VALUES (?,?,?,?)',(key,0,listing['id'],0));return
    failures=(previous[0] if previous else 0)
    if not previous or previous[1]!=listing['id']:failures+=1
    until=now+1800 if failures>=2 else 0
    db.execute('INSERT OR REPLACE INTO research_health VALUES (?,?,?,?)',(key,failures,listing['id'],until))


def select(db,c,mode,counts,now=None,readiness=None):
    now=time.time() if now is None else now
    rows=db.execute("SELECT id,price,payload,added,score FROM scan_items WHERE mode=? AND state='queued'",(mode,)).fetchall()
    buckets={feed:[] for feed in ('focus','newest','deals')}
    ranks={}
    for lid,price,raw,added,score in rows:
        listing=json.loads(raw);key=market_key(listing)
        feeds={x[0] for x in db.execute('SELECT feed FROM candidate_feeds WHERE id=? AND price=? AND mode=?',(lid,price,mode))}
        # Preserve older v4 queues without pretending we know their original source.
        if (listing.get('item') or {}).get('market_hash_name') in c['focus_watchlist']:feed='focus'
        elif 'newest' in feeds:feed='newest'
        else:feed='deals'
        counts['queue:'+feed]+=1
        rank=readiness(listing) if readiness else 1
        if rank==0:
            counts['queue:waiting_history']+=1;continue
        ranks[(lid,price)]=rank
        health=db.execute('SELECT failures,last_id,cooldown_until FROM research_health WHERE market=?',(key,)).fetchone()
        if health and health[2]>now:
            counts['queue:cooldown']+=1;continue
        # FIFO within a feed prevents enormous reference discounts monopolizing it.
        from scout import timestamp
        posted=timestamp(listing.get('created_at'))
        # Pagination discovers old pages later. Discovery time would incorrectly
        # rank those older listings ahead of the actual newest listings.
        freshness=posted if feed=='newest' and 0<posted<=now else added
        buckets[feed].append((freshness,lid,price,raw,key))
    rotation_row=db.execute("SELECT payload FROM discovery_state WHERE target='research_rotation'").fetchone()
    aging_turn=(int(json.loads(rotation_row[0])) if rotation_row else 0)%4==3
    # Fresh-first on three turns; oldest-first on every fourth turn. Feed rotation
    # and one exact market per batch remain, without letting huge API discounts win.
    def evidence_priority(candidate):
        key=candidate[4]
        cached=db.execute('SELECT fetched,payload FROM evidence_cache WHERE key=?',('sales:'+key,)).fetchone()
        if not cached or now-cached[0]>1800:return 1  # explore unknown markets
        listing=json.loads(candidate[3])
        value=(listing.get('item') or {}).get('float_value')
        if type(value) in (int,float):
            from paper_portfolio import direct_tolerance
            from review import match_reason
            from scout import timestamp
            tol=direct_tolerance(listing['item']);local=[]
            for row in json.loads(cached[1]):
                if (isinstance(row,dict) and row.get('state')=='sold' and
                    0<=now-timestamp(row.get('sold_at'))<=7*86400 and
                    match_reason(listing,row,tol) is None and
                    not (row.get('item') or {}).get('stickers') and not (row.get('item') or {}).get('keychains')):
                    local.append(row)
            recent=sum(now-timestamp(row['sold_at'])<=3*86400 for row in local)
            return 2 if len(local)>=2 and recent>=1 else 0
        week,recent=db.execute('SELECT COUNT(*),COALESCE(SUM(sold>=?),0) FROM observed_sales WHERE market=? AND sold>=? AND sold<=?',
                               (now-3*86400,key,now-7*86400,now)).fetchone()
        return 2 if week>=4 and recent>=2 else 0
    # Observed liquidity improves priority, never qualifies a deal. The fourth
    # turn still explores older candidates; unseen markets are not excluded.
    for bucket in buckets.values():
        bucket.sort(key=(lambda x:(x[0],x[1])) if aging_turn else
                    (lambda x:(evidence_priority(x),x[0],x[1])),reverse=not aging_turn)
        if readiness:bucket.sort(key=lambda x:ranks[(x[1],x[2])],reverse=True)
    row=db.execute("SELECT payload FROM discovery_state WHERE target='research_rotation'").fetchone()
    rotation=int(json.loads(row[0])) if row else 0
    order=['focus','newest','deals'];order=order[rotation%3:]+order[:rotation%3]
    selected=[];markets=set();history_selected=False
    while len(selected)<c['evaluations_per_cycle']:
        progressed=False
        def allowed(x):
            rank=ranks[(x[1],x[2])]
            if readiness and rank in (1,4) and history_selected:return False
            return x[4] not in markets or (readiness and rank==3)
        best=max((ranks[(x[1],x[2])] for bucket in buckets.values() for x in bucket if allowed(x)),default=0)
        for feed in order:
            candidate=next((x for x in buckets[feed] if allowed(x) and (not readiness or ranks[(x[1],x[2])]==best)),None)
            if candidate is None:continue
            buckets[feed].remove(candidate)
            _,lid,price,raw,key=candidate
            markets.add(key);selected.append((lid,price,raw,feed))
            if readiness and ranks[(lid,price)] in (1,4):history_selected=True
            counts['scheduled:'+feed]+=1;progressed=True
            if len(selected)>=c['evaluations_per_cycle']:break
        if not progressed:break
    db.execute("INSERT OR REPLACE INTO discovery_state VALUES ('research_rotation',?)",(json.dumps(rotation+1),))
    return selected
