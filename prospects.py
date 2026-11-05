import os
"""Cached prospect reporting: no market requests and no purchase capability."""
import datetime as dt
import json
import math
from pathlib import Path
import sqlite3
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import email_alerts
from listing_time import describe as listed

SUBJECT='CSFloat — current top 10 prospects'

def number(v):return type(v) in (int,float) and math.isfinite(v)
def stamp(t):return dt.datetime.fromtimestamp(t,dt.timezone.utc).isoformat()
def collect(db,c,now=None):
    now=time.time() if now is None else now
    # Latest snapshot per listing, with a bounded recent window. No network reads.
    rows=db.execute('''SELECT s.id,s.price,s.seen,s.payload FROM listing_snapshots s
        JOIN (SELECT id,MAX(seen) seen FROM listing_snapshots WHERE seen>=? GROUP BY id) latest
        ON latest.id=s.id AND latest.seen=s.seen WHERE s.seen>=?
        ORDER BY s.seen DESC LIMIT 2000''',(now-900,now-900)).fetchall()
    research={}
    if db.execute("SELECT 1 FROM sqlite_master WHERE name='review_shortlist'").fetchone():
        for lid,price,raw in db.execute('SELECT r.id,r.price,r.payload FROM review_shortlist r JOIN listing_snapshots s ON s.id=r.id AND s.price=r.price WHERE s.seen>=?',(now-900,)):
            research[(lid,price)]=json.loads(raw)
    picks={}
    for lid,price,seen,raw in rows:
        r=json.loads(raw);item=r.get('item') or {};ref=r.get('reference') or item.get('reference') or {}
        if not str(lid).isdigit() or r.get('state')!='listed' or r.get('type')!='buy_now':continue
        if price<c.get('min_price_cents',0) or (c.get('max_price_cents') is not None and price>c['max_price_cents']):continue
        v=next((ref.get(k) for k in ('predicted_price','base_price') if number(ref.get(k)) and ref[k]>0),None)
        d=1-price/v if v else None
        if d is None or d<=0:continue
        evidence=research.get((lid,price),{})
        reason=str(evidence.get('reason',''))
        if any(x in reason.lower() for x in ('sold,','withdrawn','listing changed','not active')):continue
        row=db.execute('SELECT reason FROM scan_items WHERE id=? AND price=? AND mode=?',(lid,price,'paper_review_v4')).fetchone()
        if row and any(x in (row[0] or '').lower() for x in ('sold,','withdrawn','not active')):continue
        pp=evidence.get('paper_purchase') or {}
        net=pp.get('estimated_net_cents',evidence.get('estimated_net_cents'))
        cost=pp.get('cost_cents')
        if not number(cost) or cost<=0:cost=math.ceil(price*(1+c.get('buy_fee_rate',0)))+c.get('extra_cost_cents',0)
        roi=net/cost if number(net) and cost>0 else None
        p=dict(id=lid,name=item.get('market_hash_name','Unknown'),price_cents=price,float=item.get('float_value'),
            paint_seed=item.get('paint_seed'),markdown=d,net_cents=net if number(net) else None,roi=roi,
            downside_net_cents=evidence.get('stressed_net_cents'),sales=evidence.get('sales_count'),
            recent_sales=evidence.get('recent_sales_count'),created_at=r.get('created_at'),
            listed=listed(r,now),last_seen=stamp(seen),age_seconds=round(now-seen),
            evidence_time=evidence.get('time'),history=evidence.get('history_source'),
            research='Researched' if evidence else 'Awaiting research',reason=reason or 'Reference only; value, sales and availability unverified',
            warnings=evidence.get('warnings',[]),url='https://csfloat.com/item/'+lid)
        # Equal timestamps can exist across versions: prefer lower price, one card per ID.
        if lid not in picks or price<picks[lid]['price_cents']:picks[lid]=p
    ranked=sorted(picks.values(),key=lambda p:(p['markdown'],-p['age_seconds']),reverse=True)
    from prospect_status import enrich
    return enrich(db,dict(generated_at=stamp(now),ranking='API-reference markdown, not profit',freshness_seconds=900,
                observed_candidates=len(ranked),picks=ranked[:40],availability='Last observed listed; not rechecked for this report.'),now)


def email_text(data):
    lines=['MANUAL REVIEW — this email places no orders.',
        'Top observed positive API-reference markdowns, including unresearched leads. These are not guaranteed good deals.',
        'Generated '+data['generated_at']+' | ranking: '+data['ranking'],
        'Repeated listings are intentional: each email is the current shortlist. Website percentages may differ.']
    for i,r in enumerate(data['picks'][:10],1):
        roi='Unknown — no completed estimate' if r['roi'] is None else f"{r['roi']:.1%}; modeled net ${r['net_cents']/100:.2f} (not guaranteed)"
        lines.extend(['',f"{i}. {r['name']} | ${r['price_cents']/100:.2f} | API markdown {r['markdown']:.1%}",
            f"Status: {r.get('availability_status','pending').upper()} | Float {r['float']} | pattern {r['paint_seed']} | {r['research']}",f"Estimated ROI: {roi}",
            f"Comparable sales / recent: {r['sales']} / {r['recent_sales']} | estimate dated: {r['evidence_time'] or 'unknown'}",
            r['listed'],f"Last observed {r['last_seen']} ({r['age_seconds']}s ago); availability unconfirmed.",
            r['reason'],'; '.join(r['warnings']),r['url']])
    if not data['picks']:lines.append('No positive-markdown observations within the last 15 minutes. Check scanner status; old picks are not substituted.')
    lines.append('\nLocal dashboard on the scanner PC: http://127.0.0.1:8765/ (only while the scanner runs).')
    return '\n'.join(lines)


def send_digest(db,c,data,now=None):
    if not c.get('email_enabled',True):return False
    now=time.time() if now is None else now
    db.execute('CREATE TABLE IF NOT EXISTS minute_thread (id INTEGER PRIMARY KEY,root TEXT,last_id TEXT,last_attempt REAL)')
    row=db.execute('SELECT root,last_id,last_attempt FROM minute_thread WHERE id=1').fetchone()
    if row and now-row[2]<60:return False
    root=row[0] if row else '<'+str(uuid.uuid4())+'@csfloat-scout.local>'
    message_id='<'+str(uuid.uuid4())+'@csfloat-scout.local>' if row and row[1] else root
    last=row[1] if row else None
    db.execute('INSERT OR REPLACE INTO minute_thread VALUES(1,?,?,?)',(root,last,now))
    headers={'Message-ID':message_id}
    if last:headers.update({'In-Reply-To':last,'References':root if last==root else root+' '+last})
    try:email_alerts.send(SUBJECT,email_text(data),os.environ.get('SCOUT_EMAIL_TO','user1@example.com'),thread_headers=headers)
    except Exception as e:print('Prospect email failed: '+type(e).__name__+'; retry in next minute.',flush=True);return False
    db.execute('UPDATE minute_thread SET last_id=? WHERE id=1',(message_id,))
    print(f"Minute prospect email accepted: {min(10,len(data['picks']))} cached picks; no extra API requests.",flush=True)
    return True


class Reporter:
    def __init__(self,path,c):
        self.path=path;self.c=c;self.halt=threading.Event();self.mutex=threading.Lock()
        self.data=dict(generated_at=stamp(time.time()),picks=[],observed_candidates=0,ranking='Starting scanner')
        self.server=None;self.thread=threading.Thread(target=self.run,daemon=True,name='prospect-reporting')
    def start(self):
        owner=self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_GET(self):
                if self.path.split('?')[0]=='/':
                    payload=Path(__file__).with_name('prospects-dashboard.html').read_bytes();kind='text/html; charset=utf-8'
                elif self.path.split('?')[0]=='/graveyard.json':
                    with owner.mutex:payload=json.dumps(owner.data.get('graveyard',[]),indent=2).encode()
                    kind='application/json'
                elif self.path.split('?')[0]=='/data.json':
                    with owner.mutex:payload=json.dumps(owner.data).encode()
                    kind='application/json'
                else:self.send_error(404);return
                self.send_response(200);self.send_header('Content-Type',kind);self.send_header('Cache-Control','no-store')
                self.send_header('X-Content-Type-Options','nosniff');self.send_header('Content-Length',str(len(payload)));self.end_headers();self.wfile.write(payload)
        try:
            self.server=ThreadingHTTPServer(('127.0.0.1',int(self.c.get('prospects_port',8765))),Handler)
            threading.Thread(target=self.server.serve_forever,daemon=True,name='local-prospect-dashboard').start()
            print('Prospect dashboard: http://127.0.0.1:'+str(self.server.server_port)+'/',flush=True)
        except OSError:print('Dashboard port unavailable. Minute emails and prospects-latest.json still work.',flush=True)
        self.thread.start()
    def stop(self):
        self.halt.set()
        if self.server:self.server.shutdown();self.server.server_close()
        self.thread.join(timeout=25)
    def run(self):
        state=sqlite3.connect('prospects-state.sqlite3',isolation_level=None,timeout=.25)
        db=sqlite3.connect(self.path,isolation_level=None,timeout=.25)
        try:
            while not self.halt.is_set():
                try:
                    data=collect(db,self.c)
                    with self.mutex:self.data=data
                    tmp=Path('prospects-latest.json.tmp');tmp.write_text(json.dumps(data,indent=2),encoding='utf-8');tmp.replace('prospects-latest.json')
                    send_digest(state,self.c,data)
                except Exception as e:print('Prospect reporting deferred: '+type(e).__name__,flush=True)
                self.halt.wait(5)
        finally:db.close();state.close()
