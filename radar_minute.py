import os
"""Minute reports are independent of API polling and candidate eligibility."""
import json
import sqlite3
import threading
import time
from pathlib import Path
import email_alerts
from listing_time import describe as listed


def send_update(db,c,now=None,blocked_until=0):
    from radar import evidence,support
    now=time.time() if now is None else now
    if not c.get('email_enabled',True):return False
    db.execute('CREATE TABLE IF NOT EXISTS radar_minute_state (id INTEGER PRIMARY KEY,last_attempt REAL,last_sent REAL,ids TEXT)')
    previous=db.execute('SELECT last_attempt,last_sent,ids FROM radar_minute_state WHERE id=1').fetchone()
    if previous and now-previous[0]<60:return False
    previous_ids=set(json.loads(previous[2])) if previous else set()
    from radar_discovery import select_picks
    picks,reasons=select_picks(db,c,now,previous_ids)
    lines=['MARKDOWN RADAR — scheduled manual-review report. NO PURCHASE.',
           'These are the best available observations in this scanner, NOT necessarily good deals. Best unseen positive reference markdowns observed within the last 10 minutes; lightweight evidence checks apply.']
    if blocked_until>now:lines.append(f'API cooldown: about {int((blocked_until-now+59)//60)} minutes remaining. No requests are made to bypass it.')
    for r in picks:
        discount=f"{r['discount']:.1%}" if r.get('discount_source') else 'UNKNOWN'
        lines.extend(['',f"{r['name']} — ${r['price_cents']/100:.2f} — reference markdown {discount}",
                      ('REPEATED PICK — ' if r['repeated'] else '')+f"Last observed {r['observation_age_seconds']} seconds ago. "+('STALE: availability not recently checked.' if r['observation_age_seconds']>300 else 'Availability can still change.'),
                      r['support']['label'],r['support'].get('negative_reason',''),
                      f"Direct 7-day sales: {r['support'].get('sales',0)}; recent market sales: {r['support'].get('market_recent_sales',0)}; newest market sale age (days): {r['support'].get('newest_market_sale_age_days')}",
                      r.get('reference_warning',''),listed(r,now),r['url']])
    if not picks:lines.append('\nNO NEW REPORTABLE MARKDOWNS in the last 10 minutes. No repeated picks substituted. The scanner continues searching; API waits can leave a reporting minute empty.')
    lines.append('Skipped: '+json.dumps(reasons))
    lines.extend(['','Reference markdown is not ROI; website badge parity is unverified. Sparse sales, float/pattern premiums, and stale estimates can make these poor buys. Manually investigate.'])
    ids=[r['id'] for r in picks];last_sent=previous[1] if previous else 0
    db.execute('INSERT OR REPLACE INTO radar_minute_state VALUES (1,?,?,?)',(now,last_sent,json.dumps(list(previous_ids))))
    report=dict(time=now,picks=picks,api_cooldown_until=blocked_until,kind='fresh_manual_review',skipped=reasons)
    Path('radar-minute.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    subject='Markdown Radar — minute picks' if picks else 'Markdown Radar — minute status: no observations'
    try:email_alerts.send(subject,'\n'.join(lines),os.environ.get('SCOUT_EMAIL_TO','user1@example.com'))
    except Exception as error:
        print('Minute email failed ('+type(error).__name__+'); next attempt in 60 seconds.',flush=True)
        return False
    for r in picks:db.execute('INSERT OR REPLACE INTO radar_reported VALUES (?,?,?)',(r['id'],r['price_cents'],now))
    db.execute('UPDATE radar_minute_state SET last_sent=?,ids=? WHERE id=1',(now,json.dumps(ids)))
    with Path('radar-minute.jsonl').open('a',encoding='utf-8') as f:f.write(json.dumps(report)+'\n')
    print(f'Minute report accepted by SMTP: {len(picks)} observed picks (fresh, deduplicated; manual review required).',flush=True)
    return True


class MinuteReporter:
    def __init__(self,path,c,cooldown=lambda:0):
        self.path=path;self.c=c;self.cooldown=cooldown;self.halt=threading.Event()
        self.thread=threading.Thread(target=self.run,name='radar-minute-mail',daemon=True)
    def start(self):self.thread.start()
    def stop(self):self.halt.set();self.thread.join(timeout=25)
    def run(self):
        db=sqlite3.connect(self.path,isolation_level=None,timeout=5)
        try:
            while not self.halt.is_set():
                try:send_update(db,self.c,blocked_until=self.cooldown())
                except Exception as error:print('Minute reporter error: '+type(error).__name__,flush=True)
                self.halt.wait(1)
        finally:db.close()
