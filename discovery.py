"""Newest-first paper discovery with durable continuations and timed side feeds."""
import json
import time
from pathlib import Path


def load(db,key,default):
    row=db.execute('SELECT payload FROM discovery_state WHERE target=?',(key,)).fetchone()
    return json.loads(row[0]) if row else default


def save(db,key,value):
    db.execute('INSERT OR REPLACE INTO discovery_state VALUES (?,?)',(key,json.dumps(value)))


def discover(api,db,c,live,counts,newest_only=False,secondary_only=False,head_only=False):
    from scanner import profile,ingest,queue_mode
    from scout import rows,Stop,CursorStop
    effective,_=profile(c,False);mode=queue_mode(c,False)
    targets=c['watchlist'] or [None]
    index=load(db,'fresh_rotation',0)
    target=targets[index%len(targets)]
    base=dict(limit=50,type='buy_now',min_price=c['min_price_cents'])
    if c['max_price_cents'] is not None:base['max_price']=c['max_price_cents']

    def fetch(label,name,ordering,cursor=None):
        if Path('STOP').exists():raise Stop('STOP file present.')
        params=dict(base,sort_by=ordering)
        if name:params['market_hash_name']=name
        if cursor:params['cursor']=cursor
        payload=api.listings(**params);page=rows(payload)
        before=counts['new_candidates'];before_unique=counts['new_unique']
        before_duplicates=counts['duplicate_versions']
        ingest(db,page,effective,mode,counts,feed=label)
        counts['discovery_pages']+=1;counts[label+':pages']+=1
        counts[label+':new_candidates']+=counts['new_candidates']-before
        counts[label+':new_unique']+=counts['new_unique']-before_unique
        counts[label+':new_versions']+=len(page)-(counts['duplicate_versions']-before_duplicates)
        return payload,page

    if not secondary_only:
        # Seen boundaries belong to this exact query, not to ranked/focus feeds.
        scope=json.dumps([target,c['min_price_cents'],c['max_price_cents'],mode])
        key='fresh_backlog:'+scope
        db.execute('CREATE TABLE IF NOT EXISTS newest_seen (scope TEXT,id TEXT,price INTEGER,PRIMARY KEY(scope,id,price))')
        pending=load(db,key,[])
        # Stacked historical traversals can consume every spare request. Retire
        # them explicitly, keeping their cursors for audit and reporting the gap.
        now=time.time();retired=[];active=[]
        for task in pending:
            task.setdefault('started',now)
            (retired if now-task['started']>1800 or len(active)>=8 else active).append(task)
        pending=active
        if retired:
            save(db,'retired:'+scope,(load(db,'retired:'+scope,[])+retired)[-128:])
            counts['newest:retired_traversals']+=len(retired);counts['coverage_gap']+=1
            save(db,key,pending)
        budget=1 if head_only else max(2,c['recent_pages_per_cycle'])

        def page_step(task):
            payload,page=fetch('newest',target,'most_recent',task['cursor'])
            known=bool(page) and all(isinstance(x,dict) and db.execute(
                'SELECT 1 FROM newest_seen WHERE scope=? AND id=? AND price=?',
                (scope,x.get('id'),x.get('price'))).fetchone() for x in page)
            for row in page:
                if isinstance(row,dict) and row.get('id') is not None and type(row.get('price')) is int:
                    db.execute('INSERT OR IGNORE INTO newest_seen VALUES (?,?,?)',(scope,row['id'],row['price']))
            if known:
                counts['newest:known_page_reached']+=1;return None
            if len(page)<50:
                counts['newest:end_of_results']+=1;return None
            cursor=payload.get('cursor') if isinstance(payload,dict) else None
            if not cursor:
                counts['coverage_unknown_no_cursor']+=1;counts['newest:missing_cursor']+=1;return None
            if cursor==task['cursor'] or cursor in task['visited']:
                counts['newest:repeated_cursor']+=1;counts['coverage_gap']+=1;return None
            return dict(cursor=cursor,visited=(task['visited']+[cursor])[-128:],started=task.get('started',time.time()))

        # Always sample the head before resuming the oldest unfinished traversal.
        head=page_step(dict(cursor=None,visited=[]));used=1
        if head and not any(t['cursor']==head['cursor'] for t in pending):pending.insert(0,head)
        save(db,key,pending)

        def advance(task):
            try:continuation=page_step(task)
            except CursorStop:
                continuation=None;counts['coverage_gap']+=1;counts['newest:expired_cursors']+=1
            pending[:]=[t for t in pending if t['cursor']!=task['cursor']]
            if continuation and not any(t['cursor']==continuation['cursor'] for t in pending):
                pending.insert(0,continuation)
            save(db,key,pending)
            return continuation

        # Finish recent overlap first, then spend ALL spare pages draining saved
        # continuations. Never start dozens of chains and reserve only one page
        # for clearing them. Pending cursors are deduplicated without inventing one.
        while pending and used<budget:
            advance(pending[0]);used+=1
            counts['newest:resumed_pages']+=1
        save(db,key,pending)
        if pending:
            counts['backlog_continues']+=1;counts['newest:page_budget_reached']+=1
        counts['newest:pending_traversals']=len(pending)
        save(db,'fresh_rotation',index+1)
        counts['target']=target or 'all names above minimum'
    if not newest_only:
        queued=db.execute("SELECT COUNT(*) FROM scan_items WHERE mode=? AND state='queued'",(mode,)).fetchone()[0]
        if queued>=c.get('side_feed_queue_limit',12):
            counts['secondary:deferred_for_research']+=1
            counts['discovery_strategy']='newest first; budgeted research; side feeds deferred; partial coverage'
            return
        # Timers advance only after successful completion. Side-feed queries retain
        # their bounded depth; they detect repricing, not full historical coverage.
        for label,seconds in [('deals',c['deals_interval_seconds']),('focus',c['focus_interval_seconds'])]:
            state_key='timed_feed:'+json.dumps([label,targets,c['focus_watchlist'],base,mode],sort_keys=True)
            state=load(db,state_key,dict(last=0,index=0))
            interval=min(seconds*2**min(state.get('empty_runs',0),3),seconds*8)
            if 0<=time.time()-state['last']<interval:
                counts[label+':skipped_not_due']+=1;continue
            n=state['index']
            if label=='focus':
                if not c['focus_watchlist']:continue
                name=c['focus_watchlist'][n%len(c['focus_watchlist'])];ordering='best_deal';budget=1
            else:
                name=targets[n%len(targets)];ordering=('best_deal','highest_discount')[n%2];budget=c['deal_pages_per_cycle']
            cursor=None;visited=set();before_versions=counts[label+':new_versions']
            for i in range(budget):
                before_page=counts[label+':new_versions']
                try:payload,page=fetch(label,name,ordering,cursor)
                except CursorStop:
                    counts['coverage_gap']+=1;counts[label+':rejected_cursor']+=1;break
                if counts[label+':new_versions']==before_page:
                    counts[label+':unchanged_page_stop']+=1;break
                if len(page)<50:counts[label+':end_of_results']+=1;break
                next_cursor=payload.get('cursor') if isinstance(payload,dict) else None
                if not next_cursor:
                    counts['coverage_unknown_no_cursor']+=1;counts[label+':missing_cursor']+=1;break
                if next_cursor==cursor or next_cursor in visited:
                    counts[label+':repeated_cursor']+=1;counts['coverage_gap']+=1;break
                visited.add(next_cursor);cursor=next_cursor
                if i==budget-1:counts[label+':page_budget_reached']+=1
            empty_runs=state.get('empty_runs',0)+1 if counts[label+':new_versions']==before_versions else 0
            save(db,state_key,dict(last=time.time(),index=n+1,empty_runs=empty_runs))
    counts['discovery_strategy']='newest first with durable backlog; timed deals/focus; partial coverage'
