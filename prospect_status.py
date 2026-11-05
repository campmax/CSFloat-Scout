"""Durable availability observations. Probes only run in the scanner's API budget."""
import json
import time
from datetime import datetime,timezone

HOLD=900

def init(db):
    db.execute('''CREATE TABLE IF NOT EXISTS prospect_status (
        id TEXT PRIMARY KEY,payload TEXT NOT NULL,first_seen REAL NOT NULL,last_listed REAL,
        status TEXT NOT NULL DEFAULT 'pending',last_probe REAL DEFAULT 0,next_probe REAL NOT NULL,
        sold_detected REAL,sold_at REAL,error TEXT DEFAULT '',slot INTEGER,displayed REAL NOT NULL)''')
    db.execute('CREATE TABLE IF NOT EXISTS prospect_probe_clock (id INTEGER PRIMARY KEY,next_probe REAL NOT NULL)')

def ts(value):
    try:return datetime.fromisoformat(str(value).replace('Z','+00:00')).timestamp()
    except (ValueError,TypeError):return None

def stamp(value):return datetime.fromtimestamp(value,timezone.utc).isoformat() if value is not None else None

def observe_detail(db,lid,raw,now=None):
    init(db);now=time.time() if now is None else now
    row=db.execute('SELECT status,last_listed FROM prospect_status WHERE id=?',(str(lid),)).fetchone()
    if not row or row[0]=='sold':return
    if not isinstance(raw,dict) or str(raw.get('id'))!=str(lid):
        db.execute("UPDATE prospect_status SET error='Invalid detail response',last_probe=?,next_probe=? WHERE id=?",(now,now+300,str(lid)));return
    state=raw.get('state')
    if state=='sold':
        sold=ts(raw.get('sold_at'))
        if sold is not None and (sold>now or (row[1] is not None and sold<row[1])):sold=None
        db.execute("UPDATE prospect_status SET status='sold',sold_detected=?,sold_at=?,last_probe=?,error='' WHERE id=?",(now,sold,now,str(lid)))
    elif state=='listed':
        db.execute("UPDATE prospect_status SET status='listed',last_listed=?,last_probe=?,next_probe=?,error='' WHERE id=?",(now,now,now+300,str(lid)))
    else:
        db.execute("UPDATE prospect_status SET status='unavailable',last_probe=?,next_probe=?,error=? WHERE id=?",(now,now+300,'Not confirmed sold: '+str(state),str(lid)))

def probe(api,db,counts,now=None):
    from scout import Stop,AccessStop,RateLimitStop,QuotaDeferred,HistoryDeferred,RequestBudgetStop
    fixed_now=now
    init(db);now=time.time() if now is None else now
    if api.budget_end is not None and api.request_count>=api.budget_end:return
    clock=db.execute('SELECT next_probe FROM prospect_probe_clock WHERE id=1').fetchone()
    if clock and now<clock[0]:return
    row=db.execute("SELECT id FROM prospect_status WHERE status!='sold' AND next_probe<=? AND displayed>=? ORDER BY last_probe ASC,next_probe ASC LIMIT 1",(now,now-1800)).fetchone()
    if not row:return
    lid=row[0]
    try:
        fresh=api.detail(lid)
    except (QuotaDeferred,HistoryDeferred,RequestBudgetStop):return
    except (AccessStop,RateLimitStop):raise
    except Stop:
        # 404, timeout, and other failures are NOT proof of a sale.
        db.execute("UPDATE prospect_status SET error='Check failed; sale unconfirmed',last_probe=?,next_probe=? WHERE id=?",(now,now+300,lid))
    else:observe_detail(db,lid,fresh,time.time() if fixed_now is None else fixed_now)
    db.execute('INSERT OR REPLACE INTO prospect_probe_clock VALUES(1,?)',(time.time()+60 if fixed_now is None else fixed_now+60,))
    counts['availability_probes']+=1

def enrich(db,data,now):
    init(db)
    held=db.execute("SELECT id,payload,slot,sold_detected FROM prospect_status WHERE status='sold' AND sold_detected>? ORDER BY slot",(now-HOLD,)).fetchall()
    sold_ids={x[0] for x in db.execute("SELECT id FROM prospect_status WHERE status='sold'")}
    live=[r for r in data['picks'] if r['id'] not in sold_ids]
    held=held[:20];selected=live[:max(0,20-len(held))]
    for lid,payload,slot,detected in held:
        selected.insert(min(max(0,slot or 0),len(selected)),json.loads(payload))
    for slot,r in enumerate(selected):
        lid=r['id'];seen=ts(r.get('last_seen'))
        if lid not in sold_ids:
            db.execute('''INSERT INTO prospect_status(id,payload,first_seen,last_listed,next_probe,slot,displayed)
                VALUES(?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload,
                last_listed=MAX(COALESCE(prospect_status.last_listed,0),COALESCE(excluded.last_listed,0)),slot=excluded.slot,displayed=excluded.displayed''',
                (lid,json.dumps(r),now,seen,now+60,slot,now))
        status=db.execute('SELECT status,last_probe,next_probe,sold_detected,sold_at,error,last_listed,first_seen FROM prospect_status WHERE id=?',(lid,)).fetchone()
        r.update(availability_status=status[0],availability_checked_at=stamp(status[1]) if status[1] else None,
            next_probe_at=stamp(status[2]),sold_detected_at=stamp(status[3]),sold_at=stamp(status[4]),availability_note=status[5],
            last_confirmed_listed_at=stamp(status[6]),first_tracked_at=stamp(status[7]),void_at=stamp(status[3]+HOLD) if status[3] else None)
    graveyard=[]
    for lid,payload,first,last,detected,sold in db.execute("SELECT id,payload,first_seen,last_listed,sold_detected,sold_at FROM prospect_status WHERE status='sold' ORDER BY sold_detected DESC"):
        r=json.loads(payload)
        graveyard.append(dict(id=lid,name=r['name'],price_cents=r['price_cents'],markdown=r['markdown'],
            markdown_value_cents=round(r['price_cents']*r['markdown']),url=r['url'],float=r.get('float'),
            first_tracked_at=stamp(first),last_confirmed_listed_at=stamp(last),sold_detected_at=stamp(detected),sold_at=stamp(sold),
            void_at=stamp(detected+HOLD),void=now>=detected+HOLD,
            first_seen_to_confirmation_seconds=round(max(0,detected-first)),
            sale_window_seconds=round(max(0,detected-last)) if last else None))
    data.update(picks=selected,graveyard=graveyard,availability='Status from paced detail checks; pending/unknown is not confirmed sold.')
    return data
