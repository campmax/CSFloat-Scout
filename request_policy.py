pass                                                                   
import datetime as dt
from email.utils import parsedate_to_datetime
import json
import math
from pathlib import Path
import time


def retry_seconds(value,now):
    try:
        seconds=float(value)
        if math.isfinite(seconds) and seconds>=0:return seconds
    except (ValueError,TypeError):pass
    try:return max(0,parsedate_to_datetime(value).timestamp()-now)
    except (ValueError,TypeError,OverflowError):return None


class Policy:
    def __init__(self,path,interval):
        self.path=Path(path) if path else None
        self.state=dict(next_allowed=0,blocked_until=0,interval=interval,
                        route_mode=0,history_next=0,history_interval=900,history_backoff=0)
        if self.path and self.path.exists():
            data=json.loads(self.path.read_text())
            for key in self.state:
                value=data.get(key,0)
                if type(value) not in (int,float) or not math.isfinite(value) or value<0:
                    raise ValueError('Invalid request-state file; inspect before restarting.')
            self.state.update({k:data.get(k,self.state[k]) for k in self.state})
            if 'history_backoff' not in data and self.state['history_interval']>900:
                self.state['history_backoff']=self.state['history_interval']
        self.state['interval']=max(interval,self.state['interval'])
        from quota import Quotas
        self.quotas=Quotas(self.path.with_name('quota-state.json') if self.path else None)

    def configure_routes(self,interval,history_interval):
        if not self.state['route_mode']:
            self.state['history_interval']=max(history_interval,self.state['interval'])
            self.state['interval']=interval
            self.state['route_mode']=1
        else:
            self.state['interval']=max(interval,self.state['interval'])
            self.state['history_interval']=max(history_interval,self.state['history_interval'])
                                                                             
        self.save()

    def history_due(self):
        return time.time()>=max(self.state['history_next'],self.quotas.deadline('history'))

    def start_history(self):
        self.state['history_next']=time.time()+self.state['history_interval'];self.save()

    def observe_quota(self,route,headers):
        if not self.state['route_mode']:return
        now=time.time();group='history' if route.startswith('history_') else route
        self.quotas.observe(group,headers,now)
        interval=self.quotas.interval(group,now)
        if group=='history' and interval is not None:
            self.state['history_next']=max(self.quotas.deadline(group),
                now+self.state['history_backoff'],self.state['blocked_until'])
            self.save()

    def save(self):
        if self.path:
            tmp=self.path.with_suffix('.tmp')
            tmp.write_text(json.dumps(self.state,indent=2))
            tmp.replace(self.path)

    def blocked(self,now=None):
        return self.state['blocked_until']>(time.time() if now is None else now)

    def wait(self,stop):
        if self.blocked():
            until=dt.datetime.fromtimestamp(self.state['blocked_until'],dt.timezone.utc).isoformat()
            raise stop('Rate-limit cooldown saved until '+until+'. No request sent; do not repeatedly restart.')
        if self.path is None:return
        while self.state['next_allowed']>time.time():
            if Path('STOP').exists():raise stop('STOP file present.')
            time.sleep(min(1,self.state['next_allowed']-time.time()))

    def await_cooldown(self,stop):
        pass                                                                       
        announced=False
        next_notice=0
        while self.blocked():
            if Path('STOP').exists():raise stop('STOP file present.')
            now=time.time()
            if now>=next_notice:
                until=dt.datetime.fromtimestamp(self.state['blocked_until']).astimezone().isoformat(timespec='seconds')
                remaining=max(1,math.ceil((self.state['blocked_until']-now)/60))
                print(f'Paper scanner paused for rate limit: {remaining} minute(s) remaining; resumes after {until}. No API requests. Ctrl+C to stop.',flush=True)
                status_path=Path('status.json')
                try:status=json.loads(status_path.read_text()) if status_path.exists() else {}
                except (ValueError,OSError):status={}
                status.update(process_state='waiting_rate_limit',blocked_until=self.state['blocked_until'],
                              heartbeat_at=dt.datetime.now(dt.timezone.utc).isoformat())
                status_path.write_text(json.dumps(status,indent=2))
                announced=True;next_notice=now+60
            time.sleep(min(1,max(0,self.state['blocked_until']-time.time())))
        if Path('STOP').exists():raise stop('STOP file present.')
        if announced:print('Cooldown complete; resuming paper scanning with saved request spacing.',flush=True)

    def start(self,interval):
        self.state['interval']=max(interval,self.state['interval'])
        self.state['next_allowed']=time.time()+self.state['interval'];self.save()

    def throttle(self,header,history=False):
        now=time.time();delay=retry_seconds(header,now)
        if history and self.state['route_mode']:
            self.state['history_interval']=max(self.state['history_interval'],min(86400,self.state['history_interval']*2))
            self.state['history_backoff']=self.state['history_interval']
            self.state['history_next']=now+max(3600,delay or 0,self.state['history_interval'])
        else:self.state['interval']=max(self.state['interval'],min(300,max(30,self.state['interval']*2)))
        self.state['blocked_until']=now+max(3600,delay or 0)
        self.state['next_allowed']=self.state['blocked_until'];self.save()
