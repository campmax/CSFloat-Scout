import datetime as dt
import time

def fields(raw,now=None):
    now=time.time() if now is None else now
    try:
        if not isinstance(raw,str):raise ValueError()
        value=dt.datetime.fromisoformat(raw.replace('Z','+00:00'))
        if value.tzinfo is None:raise ValueError()
        ts=value.timestamp()
        if not 0<ts<=now:raise ValueError()
        age=int(now-ts)
        return dict(created_at=raw,listed_at_utc=value.astimezone(dt.timezone.utc).isoformat(),listing_age_seconds=age)
    except (ValueError,TypeError,OverflowError):
        return dict(created_at=raw,listed_at_utc=None,listing_age_seconds=None)

def describe(r,now=None):
    f=fields(r.get('created_at'),now);age=f['listing_age_seconds']
    if age is None:return 'Listed: unknown (creation timestamp unavailable)'
    days,rem=divmod(age,86400);hours,rem=divmod(rem,3600);minutes=rem//60
    return f"Listed: {f['listed_at_utc']} UTC | age: {days}d {hours}h {minutes}m (current listing)"
