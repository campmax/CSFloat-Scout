import argparse
import datetime as dt
import json
import math
import os
from pathlib import Path
import sqlite3
import statistics as stats
import sys
import time
import urllib.error
import urllib.parse
import urllib.request


if __name__ == '__main__':
    sys.modules['scout'] = sys.modules[__name__]
from risk import assess, assess_chart, chart_trend
import email_alerts

BASE = 'https://csfloat.com/api/v1'

class Stop(RuntimeError):
    pass

class AccessStop(Stop):
    pass

class RateLimitStop(AccessStop):
    pass

class CursorStop(Stop):
    pass

class RequestBudgetStop(Stop):
    pass

class QuotaDeferred(Stop):
    pass

class HistoryDeferred(Stop):
    pass

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None

class API:
    def __init__(self, key, interval, state_file=None):
        self.key, self.interval, self.next = key, interval, 0
        from request_policy import Policy
        self.policy=Policy(state_file,interval)
        self.request_count=0
        self.budget_end=None
        self.chart_cache = {}
        self.sales_metadata = {}
        self.opener = urllib.request.build_opener(NoRedirect())

    def call(self, path, params=None, body=None):
        if self.budget_end is not None and self.request_count>=self.budget_end:
            raise RequestBudgetStop('Paper request budget reached; work remains queued.')
        self.policy.wait(RateLimitStop)
        history=path.startswith('/history/')
        if history and self.policy.state['route_mode'] and not self.policy.history_due():
            raise HistoryDeferred('History request deferred until its scheduled slot; candidate remains queued.')
        time.sleep(max(0, self.next - time.monotonic()))
        route=('listings_page' if path=='/listings' else 'listing_detail' if path.startswith('/listings/') and body is None else
               'history_sales' if history and path.endswith('/sales') else 'history_chart' if history else 'other')
        quota_group='history' if history else route
        if body is None and self.policy.state['route_mode']:
            deadline=self.policy.quotas.deadline(quota_group)
            if not history and 0<deadline-time.time()<=60:
                while deadline>time.time():
                    if Path('STOP').exists():raise Stop('STOP file present.')
                    time.sleep(min(1,deadline-time.time()))
            if deadline>time.time():
                error_type=HistoryDeferred if history else QuotaDeferred
                raise error_type(f'{quota_group} quota pacing: next request in {math.ceil(deadline-time.time())}s; work retained.')
        from runtime_log import event
        from request_policy import retry_seconds
        def diagnostics(headers):
            result={}
            if headers is None:return result

            for key in ('X-RateLimit-Limit','X-RateLimit-Remaining','X-RateLimit-Reset'):
                value=headers.get(key)
                if isinstance(value,str) and value.isdigit():result[key.lower()]=int(value)
            delay=retry_seconds(headers.get('Retry-After'),time.time())
            if delay is not None:result['retry_after_seconds']=delay
            return result
        url = BASE + path
        if params:
            url += '?' + urllib.parse.urlencode(params)
        request = urllib.request.Request(url, headers={
            'Authorization': self.key, 'Accept': 'application/json',
            'Content-Type': 'application/json', 'User-Agent': 'CSFloatScout/1.0'},
            data=None if body is None else json.dumps(body).encode())
        if body is not None and getattr(self, "before_write", None):
            self.before_write()
        self.policy.start(self.interval)
        if history and self.policy.state['route_mode']:self.policy.start_history()
        if body is None and self.policy.state['route_mode']:
            self.policy.quotas.start(quota_group,time.time())
        self.next = time.monotonic() + self.policy.state['interval']
        self.request_count+=1
        try:
            with self.opener.open(request, timeout=25) as response:
                data = json.load(response)
                limits=diagnostics(getattr(response,'headers',None))
                if body is None:self.policy.observe_quota(route,limits)
                event('http_success',route=route,has_cursor=bool(params and params.get('cursor')),
                      request_number=self.request_count,limits=limits)
                if isinstance(data, dict) and (data.get('error') or data.get('code')):
                    raise Stop('API returned an error; inspect account/API status.')
                return data
        except urllib.error.HTTPError as error:
            from runtime_log import event
            if body is None:self.policy.observe_quota(route,diagnostics(error.headers))
            event('http_error',http_status=error.code,operation='write' if body is not None else 'read',
                  route=route,has_cursor=bool(params and params.get('cursor')),limits=diagnostics(error.headers))
            if body is None and path=='/listings' and params and params.get('cursor') and error.code in (400,404,409,410):
                raise CursorStop('Saved pagination cursor rejected; coverage gap recorded.') from None
            if error.code==429:
                self.policy.throttle(error.headers.get('Retry-After') if error.headers else None,history=history)
                error_type=RateLimitStop if body is None else AccessStop
                raise error_type('HTTP 429: cooldown saved (at least one hour, longer if Retry-After requires it). No immediate retry.') from None
            if error.code in (401,403):
                raise AccessStop(f'HTTP {error.code}: stopped. Resolve authentication/access/rate limits before restarting; no automatic retry.') from None
            raise Stop(f'HTTP {error.code} ({route}); no request retried automatically.') from None
        except (OSError, ValueError) as error:
            raise Stop(f'Network/schema failure ({type(error).__name__}); no retry.') from None

    def available_balance(self):
        return parse_balance(self.call('/me'))

    def listings(self, **params):
        return self.call('/listings', params)

    def detail(self, listing_id):
        data = self.call('/listings/' + urllib.parse.quote(str(listing_id), safe=''))
        detail=data.get('data', data) if isinstance(data, dict) else data
        observer=getattr(self,'detail_observer',None)
        if observer:
            try:observer(str(listing_id),detail)
            except sqlite3.Error:pass
        return detail

    def sales(self, name, paint):
        params = {'paint_index': paint} if paint is not None else None
        path='/history/' + urllib.parse.quote(name, safe='') + '/sales'
        data=rows(self.call(path,params))
        initial_count=len(data)
        fallback=not data and paint is not None and not self.policy.state['route_mode']
        if fallback:
            data=rows(self.call(path))
        self.sales_metadata[(name,paint)]=dict(paint_filtered_rows=initial_count,unfiltered_fallback_used=fallback,returned_rows=len(data))
        return data

    def graph(self, name, paint):
        key=(name,paint)
        cached=self.chart_cache.get(key)
        if cached and time.monotonic()-cached[0]<900:
            return cached[1]
        data=self.call('/history/'+urllib.parse.quote(name,safe='')+'/graph',
                       {'paint_index':paint} if paint is not None else None)
        if not isinstance(data,list):
            raise Stop('Chart response must be a list; refusing an unknown schema.')
        self.chart_cache[key]=(time.monotonic(),data)
        return data

    def buy(self, listing_id, price):
        return self.call('/listings/buy', body={'contract_ids': [str(listing_id)], 'total_price': price})


def parse_balance(payload):


    user = payload.get('user') if isinstance(payload, dict) else None
    value = user.get('balance') if isinstance(user, dict) else None
    if type(value) is not int or value < 0:
        raise Stop('Available balance unavailable: expected /me user.balance in integer USD cents.')
    return value


def acquisition_cost(price, config):
    return math.ceil(price*(1+config['buy_fee_rate']))+config['extra_cost_cents']


def affordable_price(balance, config):
    price = max(0, math.floor((balance-config['extra_cost_cents'])/(1+config['buy_fee_rate'])))
    while price and acquisition_cost(price,config)>balance:
        price -= 1
    if config['max_price_cents'] is not None:
        price = min(price, config['max_price_cents'])
    return price


def rows(payload):
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ('data', 'listings', 'sales'):
            if isinstance(payload.get(key), list):
                return payload[key]
    raise Stop('Unrecognized response envelope; refusing to infer data.')


def cents(value):
    return type(value) is int and value > 0


def timestamp(value):
    try:
        result = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
        if result.tzinfo is None:
            return 0
        return result.timestamp()
    except (ValueError, TypeError, AttributeError):
        return 0


def comparable(a, b, tolerance):
    x, y = a.get('item', {}), b.get('item', {})
    for key in ('market_hash_name', 'def_index', 'paint_index'):
        if x.get(key) is None or x.get(key) != y.get(key):
            return False

    fx, fy = x.get('float_value'), y.get('float_value')
    if not all(type(f) in (int, float) and math.isfinite(f) and 0 <= f <= 1 for f in (fx, fy)):
        return False
    if abs(fx - fy) > tolerance:
        return False

    return not y.get('stickers') and not y.get('keychains')


def clean_prices(values):
    logs = [math.log(v) for v in values]
    if not logs:
        return []
    median = stats.median(logs)
    mad = stats.median(abs(v - median) for v in logs)
    band = max(math.log(1.05), 3 * 1.4826 * mad)
    return [v for v in values if abs(math.log(v) - median) <= band]


def quantile(values, q):
    seq = sorted(values)
    index = (len(seq) - 1) * q
    lo, hi = math.floor(index), math.ceil(index)
    return seq[lo] * (hi-index) + seq[hi] * (index-lo) if lo != hi else seq[lo]


def evaluate(candidate, asks, sales, config, now=None, chart=None):
    now = now or time.time()
    reject = lambda why: {'eligible': False, 'reason': why}
    price, item = candidate.get('price'), candidate.get('item', {})
    name = item.get('market_hash_name', '')
    if candidate.get('state') != 'listed' or candidate.get('type') != 'buy_now':
        return reject('not an active fixed-price listing')
    if not candidate.get('id') or not cents(price) or price < config['min_price_cents'] or (config['max_price_cents'] is not None and price > config['max_price_cents']):
        return reject('invalid ID/price or outside price limits')
    if any(word.lower() in name.lower() for word in config['exclude_name_contains']):
        return reject('pattern-sensitive finish excluded')
    if item.get('stickers') or item.get('keychains'):
        return reject('decorated item requires manual valuation')
    created = timestamp(candidate.get('created_at'))
    if not 0 <= now - created <= config['max_listing_age_seconds']:
        return reject('listing timestamp missing, future, or too old')
    tolerance = config['float_tolerance']
    seller = candidate.get('seller', {}).get('steam_id')

    by_seller = {}
    for ask in asks:
        sid = ask.get('seller', {}).get('steam_id')
        if (sid and sid != seller and ask.get('id') != candidate['id'] and
                ask.get('state') == 'listed' and ask.get('type') == 'buy_now' and
                cents(ask.get('price')) and comparable(candidate, ask, tolerance)):
            by_seller[sid] = min(by_seller.get(sid, ask['price']), ask['price'])
    ask_prices = list(by_seller.values())
    if len(ask_prices) < config['min_independent_sellers']:
        return reject('insufficient comparable independent sellers')

    ask_cap = min(ask_prices)
    valid_sales, seen = [], set()
    for sale in sales:
        sid = sale.get('id')
        sold = timestamp(sale.get('sold_at'))
        if (sid and sid not in seen and cents(sale.get('price')) and
                sale.get('state') == 'sold' and
                0 <= now - sold <= config['sales_lookback_days'] * 86400 and
                comparable(candidate, sale, tolerance)):
            seen.add(sid)
            valid_sales.append(sale)
    cleaned = clean_prices([s['price'] for s in valid_sales])
    if len(cleaned) < config['min_sales']:
        return reject('insufficient recent comparable completed sales / unsupported sales schema')
    median = stats.median(cleaned)
    dispersion = (quantile(cleaned, .75) - quantile(cleaned, .25)) / median
    if dispersion > config['max_sales_iqr_ratio']:
        return reject('sales prices too dispersed')
    recent = clean_prices([s['price'] for s in valid_sales if now-timestamp(s['sold_at']) <= 3*86400])
    if len(recent) < config['min_recent_sales']:
        return reject('insufficient sales in last three days')
    recent_median = stats.median(recent)
    if recent_median < median * (1 - config['max_recent_drop']):
        return reject('recent market decline exceeds limit')
    fair = int(min(ask_cap, quantile(cleaned, .25), recent_median))
    discount = round(1 - price / fair, 12)
    reference = candidate.get('reference', {}).get('base_price')
    site_discount = round(1-price/reference, 12) if cents(reference) else None
    net = int(fair * (1-config['resale_fee_rate']) * (1-config['withdrawal_fee_rate']) *
              (1-config['resale_slippage_rate'])) - math.ceil(price*(1+config['buy_fee_rate'])) - config['extra_cost_cents']
    risk = assess_chart(chart, now, fair, price, config, timestamp) if chart is not None else assess(valid_sales, now, fair, price, config, timestamp, clean_prices)
    reasons = []
    if not risk['risk_ok']:
        reasons.append(risk['risk_reason'])
    if discount < config['min_discount']:
        reasons.append('independent discount below threshold')
    if config['require_csfloat_discount'] and (site_discount is None or site_discount < config['min_discount']):
        reasons.append('CSFloat reference discount absent or too small')
    if discount > config['max_discount']:
        reasons.append('extreme discount requires manual inspection')
    if net < config['min_net_profit_cents']:
        reasons.append('estimated net margin too small')
    return {'eligible': not reasons, 'reason': '; '.join(reasons) or 'validated',
            'price_cents': price, 'fair_cents': fair, 'discount': round(discount, 5),
            'csfloat_discount': site_discount, 'estimated_net_cents': net,
            'sales_count': len(cleaned), 'seller_count': len(by_seller),
            'reference_inflation': reference / fair - 1 if cents(reference) else None, **risk}


class Ledger:
    def __init__(self, path):
        self.db = sqlite3.connect(path, isolation_level=None)
        self.db.execute('CREATE TABLE IF NOT EXISTS purchases (id TEXT PRIMARY KEY, price INTEGER, day TEXT, status TEXT)')
        email_alerts.init_receipts(self.db)
        columns = {row[1] for row in self.db.execute('PRAGMA table_info(purchases)')}
        if 'capital_released' not in columns:
            self.db.execute('ALTER TABLE purchases ADD COLUMN capital_released INTEGER NOT NULL DEFAULT 0')
        self.db.execute('CREATE TABLE IF NOT EXISTS alerts (id TEXT, price INTEGER, PRIMARY KEY(id,price))')

    def reserve(self, listing, config):
        day = dt.datetime.now(dt.timezone.utc).date().isoformat()
        self.db.execute('BEGIN IMMEDIATE')
        try:
            if self.db.execute("SELECT 1 FROM purchases WHERE status='unknown'").fetchone():
                raise Stop('Unresolved purchase exists. Reconcile in CSFloat before another live run.')
            total, count = self.db.execute('SELECT COALESCE(SUM(price),0), COUNT(*) FROM purchases WHERE day=?', (day,)).fetchone()
            committed = math.ceil(listing['price']*(1+config['buy_fee_rate'])) + config['extra_cost_cents']
            if not self.capacity(committed, config):
                raise Stop('Open capital/position limit reached; funds are not released automatically.')
            if (config['daily_budget_cents'] is not None and total + committed > config['daily_budget_cents']) or (config['max_purchases_per_day'] is not None and count >= config['max_purchases_per_day']):
                raise Stop('Daily purchase budget/count exhausted.')
            self.db.execute('INSERT INTO purchases(id,price,day,status) VALUES (?,?,?,?)', (listing['id'], committed, day, 'unknown'))
            self.db.execute('COMMIT')
        except BaseException:
            self.db.execute('ROLLBACK')
            raise

    def capacity(self, cost, config):
        total, count = self.db.execute('SELECT COALESCE(SUM(price),0),COUNT(*) FROM purchases WHERE capital_released=0').fetchone()
        return (config['max_open_capital_cents'] is None or total+cost <= config['max_open_capital_cents']) and (config['max_open_positions'] is None or count < config['max_open_positions'])

    def record_manual(self, listing_id, cost):
        if not cents(cost):
            raise Stop('Actual total cost must be positive integer cents.')
        day = dt.datetime.now(dt.timezone.utc).date().isoformat()
        self.db.execute('INSERT INTO purchases(id,price,day,status) VALUES (?,?,?,?)', (listing_id,cost,day,'confirmed'))

    def release(self, listing_id):
        result = self.db.execute("UPDATE purchases SET capital_released=1 WHERE id=? AND status='confirmed' AND capital_released=0", (listing_id,))
        if result.rowcount != 1:
            raise Stop('No unreleased confirmed purchase found. Unknown purchases require reconciliation first.')

    def alert_once(self, listing):
        result = self.db.execute('INSERT OR IGNORE INTO alerts VALUES (?,?)', (listing['id'], listing['price']))
        return bool(result.rowcount)

    def confirm(self, listing_id, record=None, config=None):
        self.db.execute('BEGIN IMMEDIATE')
        try:
            self.db.execute("UPDATE purchases SET status='confirmed' WHERE id=?", (listing_id,))
            if record is not None:
                email_alerts.queue_purchase(self.db,record,config)
            self.db.execute('COMMIT')
        except BaseException:
            self.db.execute('ROLLBACK'); raise


def purchase(api, ledger, listing, config, record=None):
    if Path('STOP').exists():
        raise Stop('STOP file present.')
    balance = api.available_balance()
    if acquisition_cost(listing['price'],config) > balance:
        raise Stop('Listing exceeds freshly checked available CSFloat balance; no purchase submitted.')
    if Path('STOP').exists():
        raise Stop('STOP file present.')
    ledger.reserve(listing, config)

    response = api.buy(listing['id'], listing['price'])
    if not isinstance(response, dict) or response.get('message') != 'all listings purchased':
        raise Stop('Ambiguous purchase result. Reservation retained; live execution halted.')


    after = api.available_balance()
    if after > balance-listing['price']:
        raise Stop('Purchase acknowledged but balance debit not reconciled; stopped to prevent overspending.')
    if record is None:
        record = dict(created_at=listing.get('created_at'),id=listing['id'],name=listing.get('item',{}).get('market_hash_name','CSFloat item'),price_cents=listing['price'],url='https://csfloat.com/item/'+str(listing['id']),time=dt.datetime.now(dt.timezone.utc).isoformat())
    ledger.confirm(listing['id'],record,config)


def validate_config(c):
    from scanner import defaults
    defaults(c)
    for key in ('min_discount','max_discount','resale_fee_rate','withdrawal_fee_rate','resale_slippage_rate','max_recent_drop','max_sales_iqr_ratio','float_tolerance','buy_fee_rate','min_stress_drop','max_weekly_drop','max_drop_share_of_discount','min_stressed_roi'):
        if type(c[key]) not in (int,float) or not math.isfinite(c[key]) or not 0 <= c[key] < 1:
            raise Stop(f'Invalid configuration: {key}')
    for key in ('min_price_cents','min_sales','min_recent_sales','min_independent_sellers','poll_seconds','request_interval_seconds','pages_per_scan','sales_lookback_days','max_listing_age_seconds','max_validation_seconds','min_net_profit_cents','extra_cost_cents','risk_horizon_days','min_stressed_profit_cents','min_sales_per_trend_day','min_trend_days','email_retry_seconds','max_emails_per_day'):
        if type(c[key]) is not int or c[key] < 0:
            raise Stop(f'Invalid configuration: {key}')
    if not (0 < c['min_discount'] < c['max_discount'] and 0 < c['min_price_cents']):
        raise Stop('Invalid discount or price range.')
    if min(c['min_sales'],c['min_recent_sales'],c['min_independent_sellers']) < 3:
        raise Stop('At least three observations required for each evidence gate.')
    if min(c['request_interval_seconds'],c['poll_seconds'],c['pages_per_scan'],c['sales_lookback_days'],c['max_validation_seconds']) < 1:
        raise Stop('Intervals, lookback, and page limits must be positive.')
    if c['sales_lookback_days'] < 9 or not 3 <= c['min_trend_days'] <= 8 or c['min_sales_per_trend_day'] < 3 or c['risk_horizon_days'] < 7:
        raise Stop('Trend requires >=9 days lookback, 3–8 covered days, >=3 sales/day, and >=7-day risk horizon.')
    for key in ('max_price_cents','daily_budget_cents','max_open_capital_cents','max_open_positions','max_purchases_per_day'):
        if c[key] is not None and (type(c[key]) is not int or c[key] <= 0):
            raise Stop(f'{key} must be null or a positive integer.')
    if c['max_price_cents'] is not None and c['max_price_cents'] < c['min_price_cents']:
        raise Stop('Maximum price cannot be below minimum price.')
    if min(c['max_emails_per_day'],c['email_retry_seconds']) <= 0:
        raise Stop('Capital and email limits must be positive.')
    email_alerts.recipients(c)
    for key in ('enable_live_buying','email_enabled','require_csfloat_discount'):
        if type(c[key]) is not bool:
            raise Stop(f'{key} must be true or false.')
    if type(c['slow_paper_mode']) is not bool:raise Stop('slow_paper_mode must be boolean')
    for key in ('paper_listing_interval_seconds','history_request_interval_seconds','paper_history_cache_seconds'):
        if type(c[key]) is not int or c[key]<1:raise Stop(key+' must be a positive integer')
    if c['paper_listing_interval_seconds']<15:raise Stop('Paper listing interval must be at least 15 seconds')
    if c['history_request_interval_seconds']<900:raise Stop('History interval must be at least 900 seconds pending verified server limits')
    if c['paper_history_cache_seconds']>3600:raise Stop('Paper history cache may not exceed one hour')
    for key in ('paper_snapshot_seconds','paper_requests_per_cycle','paper_research_limit','newest_check_seconds','side_feed_queue_limit','paper_queue_max_age_seconds','deals_interval_seconds','focus_interval_seconds','paper_poll_seconds','discovery_pages_per_cycle','evaluations_per_cycle','discovery_overlap_seconds','recent_pages_per_cycle','deal_pages_per_cycle'):
        if type(c[key]) is not int or c[key]<1:
            raise Stop(f'{key} must be a positive integer.')
    if not 0 <= c['prefilter_discount'] <= c['paper_profile']['stable_discount']:
        raise Stop('Prefilter must not exceed the stable paper threshold.')
    r=c['paper_review']
    if type(r['watch_enabled']) is not bool:raise Stop('watch_enabled must be boolean')
    if type(r['watch_net_cents']) is not int or r['watch_net_cents']<1:raise Stop('Invalid watch_net_cents')
    if type(r['watch_discount']) not in (int,float) or not 0<r['watch_discount']<1:raise Stop('Invalid watch_discount')
    if type(r['enabled']) is not bool:raise Stop('paper_review.enabled must be boolean')
    for key in ('min_discount','high_discount','max_weekly_loss','float_tolerance','prefilter_discount','min_good_stressed_roi'):
        if type(r[key]) not in (int,float) or not math.isfinite(r[key]) or not 0<r[key]<1:raise Stop('Invalid paper_review '+key)
    for key in ('min_sales','min_recent_sales','max_listing_age_seconds','sales_window_days','recent_window_days','min_good_net_cents','min_good_stressed_cents'):
        if type(r[key]) is not int or r[key]<1:raise Stop('Invalid paper_review '+key)
    if not 1<=r['recent_window_days']<=r['sales_window_days']<=c['sales_lookback_days']:raise Stop('Invalid review sales windows')
    if r['min_recent_sales']>r['min_sales']:raise Stop('Recent sales minimum exceeds total minimum')
    if not r['prefilter_discount']<=r['min_discount']<=r['high_discount']:raise Stop('Invalid review threshold order')
    p=c['paper_profile']
    for key in ('min_discount','stable_discount','float_tolerance','min_stressed_roi','min_stress_drop','resale_slippage_rate','stable_max_change','stable_max_drawdown','stable_max_iqr','stable_min_stressed_roi'):
        if type(p[key]) not in (int,float) or not math.isfinite(p[key]) or not 0<p[key]<1:
            raise Stop(f'Invalid paper setting: {key}')
    for key in ('min_independent_sellers','min_sales','min_recent_sales','min_net_profit_cents','min_stressed_profit_cents','max_listing_age_seconds','stable_min_profit_cents'):
        if type(p[key]) is not int or p[key]<1:
            raise Stop(f'Invalid paper setting: {key}')
    if min(p['min_independent_sellers'],p['min_sales'],p['min_recent_sales'])<3:
        raise Stop('Paper evidence counts must remain at least three.')
    if not p['stable_discount']<=p['min_discount']<=c['min_discount']:
        raise Stop('Discount tiers must be ordered stable <= paper <= live.')
    if not isinstance(c['focus_watchlist'],list) or not all(isinstance(x,str) and x for x in c['focus_watchlist']):raise Stop('Invalid focus watchlist')
    if not isinstance(c['watchlist'], list) or not all(isinstance(n,str) and n for n in c['watchlist']):
        raise Stop('watchlist must be a list of exact names.')


def scan(api, ledger, c, live=False):
    from scanner import scan as staged_scan
    return staged_scan(api, ledger, c, live)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', default='config.json')
    parser.add_argument('--once', action='store_true')
    parser.add_argument('--live', action='store_true', help='spends real CSFloat balance within configured limits')
    parser.add_argument('--demo', action='store_true')
    parser.add_argument('--diagnose-name', help='read-only chart and comparable-data diagnostic for an exact item name')
    parser.add_argument('--probe-name', help='save read-only API shape diagnostics for one exact market name')
    parser.add_argument('--flush-purchase-emails', action='store_true', help='retry due saved receipts without scanning or purchasing')
    parser.add_argument('--check-balance', action='store_true', help='read available CSFloat balance; never purchases')
    parser.add_argument('--test-email', action='store_true', help='send one test email; never purchases')
    parser.add_argument('--record-manual', nargs=2, metavar=('LISTING_ID','ACTUAL_COST_CENTS'))
    parser.add_argument('--release-capital', metavar='LISTING_ID')
    parser.add_argument('--funds-credited', action='store_true', help='confirm resale/refund funds are actually available')
    parser.add_argument('--paper-report',action='store_true',help='export local simulated portfolio without API requests')
    parser.add_argument('--paper-sale',nargs=2,metavar=('LISTING_ID','GROSS_CENTS'),help='record an explicitly assumed paper exit; never sells a real item')
    args = parser.parse_args()
    c = json.loads(Path(args.config).read_text(encoding='utf-8'))
    from scanner import defaults
    defaults(c)
    validate_config(c)
    if not args.live:
        from scanner import paper_runtime_config
        c=paper_runtime_config(c)
    if args.paper_report or args.paper_sale:
        if args.live:raise Stop('Paper commands cannot be combined with --live')
        from instance_lock import InstanceLock
        from paper_portfolio import record_sale,tick
        try:paper_lock=InstanceLock('scout.lock')
        except RuntimeError as error:raise Stop(str(error)) from None
        paper_db=Ledger('scout.sqlite3').db
        try:
            if args.paper_sale:record_sale(paper_db,c,args.paper_sale[0],int(args.paper_sale[1]))
            tick(paper_db,dict(c,email_enabled=False))
        except ValueError as error:raise Stop(str(error)) from None
        print('Saved paper-portfolio.html and paper-portfolio.json. No real purchases or sales.');return
    if args.demo:
        fixture = json.loads(Path('demo.json').read_text())
        print(json.dumps(evaluate(**fixture, config=c), indent=2))
        return
    if args.flush_purchase_emails:
        email_alerts.settings()
        email_alerts.flush_purchases(Ledger('scout.sqlite3').db,c)
        return
    if args.test_email:
        for recipient in email_alerts.recipients(c):
            email_alerts.send('CSFloat Scout test', 'Email delivery test. No purchase was made.', recipient)
        print('SMTP server accepted test email; check your inbox/spam.')
        return
    if args.record_manual:
        Ledger('scout.sqlite3').record_manual(args.record_manual[0],int(args.record_manual[1]))
        print('Manual purchase recorded as committed capital.'); return
    if args.release_capital:
        if not args.funds_credited:
            raise Stop('Use --funds-credited only after verifying resale/refund funds are available.')
        Ledger('scout.sqlite3').release(args.release_capital)
        print('Capital released in local ledger.'); return
    if c['email_enabled'] and not (args.check_balance or args.probe_name or args.diagnose_name):
        email_alerts.settings()
    key = os.environ.get('CSFLOAT_API_KEY')
    if not key:
        raise Stop('Set CSFLOAT_API_KEY in your local terminal. Do not paste it into chat.')
    if args.live and not c['email_enabled']:
        raise Stop('Live mode requires email_enabled=true for purchase receipts.')
    if args.live and (not c['enable_live_buying'] or os.environ.get('CSFLOAT_LIVE_ACK') != 'I_ACCEPT_REAL_PURCHASES'):
        raise Stop('Live mode requires enable_live_buying=true and CSFLOAT_LIVE_ACK=I_ACCEPT_REAL_PURCHASES.')
    ledger = Ledger('scout.sqlite3')
    if args.live and ledger.db.execute("SELECT 1 FROM purchases WHERE status='unknown'").fetchone():
        raise Stop('Unresolved purchase; reconcile with CSFloat before live operation.')
    from instance_lock import InstanceLock
    try:process_lock=InstanceLock('scout.lock')
    except RuntimeError as error:raise Stop(str(error)) from None
    api = API(key,c['request_interval_seconds'],state_file='request-state.json')
    if not args.live:api.policy.configure_routes(c['request_interval_seconds'],c['history_request_interval_seconds'])
    if args.check_balance:
        print(f'Available CSFloat balance: ${api.available_balance()/100:.2f}')
        return
    if args.diagnose_name:
        asks=rows(api.listings(limit=50,sort_by='lowest_price',type='buy_now',market_hash_name=args.diagnose_name))
        if not asks:
            raise Stop('No listings returned for that exact name.')
        paint=asks[0].get('item',{}).get('paint_index')
        sales=api.sales(args.diagnose_name,paint)
        chart=api.graph(args.diagnose_name,paint)
        from diagnostics import report
        report=report(args.diagnose_name,asks,sales,chart,c,time.time())
        report['history_fetch']=api.sales_metadata.get((args.diagnose_name,paint),{})
        Path('diagnostic.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
        print(json.dumps(report,indent=2))
        return
    if args.probe_name:
        asks = rows(api.listings(limit=5, sort_by='lowest_price', type='buy_now', market_hash_name=args.probe_name))
        if not asks:
            raise Stop('No listings for that exact market name.')
        sales = api.sales(args.probe_name, asks[0].get('item', {}).get('paint_index'))

        def public_fields(row):
            return {k: row[k] for k in ('id','price','state','type','sold_at','created_at','item','reference') if k in row}
        Path('api-probe.json').write_text(json.dumps({'listings':[public_fields(x) for x in asks[:3]], 'sales':[public_fields(x) for x in sales[:3]]}, indent=2), encoding='utf-8')
        print('Read-only API samples saved to api-probe.json. No purchases made.')
        return
    print('LIVE BUYING — strict profile' if args.live else 'PAPER MODE — no purchases or balance required; review v5.3 — sold tracking / graveyard / paced availability', flush=True)
    if not args.live:
        print(f"Request spacing: at least {api.policy.state['interval']:g}s; cycle budget {c['paper_requests_per_cycle']}; research up to {c['paper_research_limit']} candidates; pause {c['paper_poll_seconds']}s between cycles.",flush=True)
        print(f"History/chart pacing: response quota + reserve; {api.policy.state['history_interval']:g}s fallback without usable headers. Evidence cache: {c['paper_history_cache_seconds']}s. Watch leads are manual-review alerts only.",flush=True)
    reporter=None
    if not args.live:
        from scanner import init as init_scan
        init_scan(ledger.db)
        from prospect_status import init as init_status,observe_detail
        init_status(ledger.db)
        api.detail_observer=lambda lid,raw:observe_detail(ledger.db,lid,raw)
        from prospects import Reporter
        reporter=Reporter('scout.sqlite3',c);reporter.start()
    try:
        while True:
            pause=c['paper_poll_seconds'] if not args.live and c['paper_review']['enabled'] else c['poll_seconds']
            try:
                from runtime_log import event
                if not args.live and not args.once:
                    api.policy.await_cooldown(Stop)
                event('scan_started',live=args.live)
                scan(api, ledger, c, args.live)
                event('scan_completed',live=args.live)
            except Stop as error:
                from runtime_log import event
                event('scan_error',error,live=args.live,access_stop=isinstance(error,AccessStop))
                if isinstance(error,AccessStop):
                    status_path=Path('status.json')
                    try:status=json.loads(status_path.read_text()) if status_path.exists() else {}
                    except (ValueError,OSError):status={}
                    recoverable=isinstance(error,RateLimitStop) and not args.live and not args.once and not Path('STOP').exists()
                    status.update(process_state='waiting_rate_limit' if recoverable else 'stopped_access_or_rate_limit',stopped_at=dt.datetime.now(dt.timezone.utc).isoformat(),
                                  blocked_until=api.policy.state['blocked_until'])
                    status_path.write_text(json.dumps(status,indent=2))
                    if recoverable:
                        print(str(error),flush=True)
                        continue
                if isinstance(error,AccessStop) or args.live or args.once or Path('STOP').exists():
                    raise
                print(str(error), flush=True)
                pause=max(pause,c['poll_seconds'],60)
            if args.once:
                return
            time.sleep(pause)
    finally:
        if reporter:reporter.stop()


if __name__ == '__main__':
    from runtime_log import event
    try:
        event('process_started')
        main()
        event('process_completed')
    except (Stop, KeyError, ValueError, sqlite3.Error) as error:
        event('process_stopped_error',error)
        raise SystemExit(str(error))
    except KeyboardInterrupt:
        event('user_stopped')
        print('Stopped.')
    except Exception as error:
        event('unexpected_error',error)
        raise SystemExit('Unexpected error; see runtime-events.jsonl (credentials omitted).') from None
