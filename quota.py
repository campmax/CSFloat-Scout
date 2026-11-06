pass                                                                         

                                                                           
                                                                                         
                                                                           
   
import json
import math
from pathlib import Path


class Quotas:
    def __init__(self, path=None):
        self.path = Path(path) if path else None
        self.buckets = {}
        if self.path and self.path.exists():
            data = json.loads(self.path.read_text())
            if not isinstance(data, dict):
                raise ValueError('Invalid quota-state file; inspect before restarting.')
            for group, bucket in data.items():
                if group not in ('history', 'reads', 'listings_page', 'listing_detail', 'other') or not isinstance(bucket, dict):
                    raise ValueError('Invalid quota-state bucket.')
                if any(type(bucket.get(k)) not in (int, float) or not math.isfinite(bucket[k]) or bucket[k] < 0
                       for k in ('limit', 'remaining', 'reset', 'next')):
                    raise ValueError('Invalid quota-state values.')
                if bucket['limit'] <= 0 or bucket['remaining'] > bucket['limit']:
                    raise ValueError('Invalid quota-state balance.')
            self.buckets = data

    def save(self):
        if self.path:
            tmp = self.path.with_suffix('.tmp')
            tmp.write_text(json.dumps(self.buckets, indent=2))
            tmp.replace(self.path)

    def deadline(self, group):
        return self.buckets.get(group, {}).get('next', 0)

    def interval(self, group, now):
        b = self.buckets.get(group)
        if not b or b['reset'] <= now:
            return None
                                                                            
        spendable = b['remaining'] - max(1, math.ceil(b['limit'] * .10))
        if spendable <= 0:
            return max(0, b['reset'] + 5 - now)
        return max(60 if group == 'history' else 15,
                   (b['reset'] - now) / spendable * 1.15)

    def start(self, group, now):
        b = self.buckets.get(group)
        if b:
                                                                              
            b['remaining'] = max(0, b['remaining'] - 1)
            interval = self.interval(group, now)
            b['next'] = now + (interval if interval is not None else
                               (900 if group == 'history' else 60))
            self.save()

    def observe(self, group, headers, now):
        keys = ('x-ratelimit-limit', 'x-ratelimit-remaining', 'x-ratelimit-reset')
        values = [headers.get(k) for k in keys]
        if any(type(v) is not int for v in values):
            return False
        limit, remaining, reset = values
        if not (0 < limit and 0 <= remaining <= limit and now < reset <= now + 7*86400):
            return False
        old = self.buckets.get(group)
        if old and old['reset'] > now:
                                                                            
                                                                               
            remaining = min(remaining, old['remaining'])
            reset = max(reset, old['reset'])
            limit = max(limit, old['limit'])
        self.buckets[group] = dict(limit=limit, remaining=remaining, reset=reset, next=0)
        self.buckets[group]['next'] = now + self.interval(group, now)
        self.save()
        return True
