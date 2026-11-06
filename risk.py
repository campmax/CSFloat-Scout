pass                                                                             
import datetime as dt
import math
import statistics


def assess(sales, now, fair, price, c, parse_time, clean_prices):
    today = dt.datetime.fromtimestamp(now, dt.timezone.utc).date()
    days = {}
    for sale in sales:
        day = dt.datetime.fromtimestamp(parse_time(sale['sold_at']), dt.timezone.utc).date()
        age = (today-day).days
        if 0 <= age <= 8:
            days.setdefault(age, []).append(sale['price'])
    medians = {age: statistics.median(clean_prices(values)) for age, values in days.items()
               if len(values) >= c['min_sales_per_trend_day']}
                                                                               
    start = [v for age, v in medians.items() if 6 <= age <= 8]
    end = [v for age, v in medians.items() if 0 <= age <= 1]
    if not start or not end or len([a for a in medians if a <= 7]) < c['min_trend_days']:
        return {'risk_ok': False, 'risk_reason': 'insufficient dated sales coverage for seven-day trend'}
    baseline, current = statistics.median(start), statistics.median(end)
    weekly_change = current/baseline-1
    decline = max(0, -weekly_change)
                                                                              
    recent_peak = max(v for a,v in medians.items() if a <= 7)
    drawdown = max(0, 1-current/recent_peak)
    return stress(weekly_change,drawdown,fair,price,c,len(medians),'matched_sales')


def stress(weekly_change, drawdown, fair, price, c, trend_days, source):
    decline = max(0,-weekly_change)
    observed_drop = max(decline, drawdown)
    stressed_drop = max(c['min_stress_drop'],
                        1-(1-observed_drop)**(c['risk_horizon_days']/7))
    stressed_value = math.floor(fair*(1-stressed_drop))
    acquisition = math.ceil(price*(1+c['buy_fee_rate'])) + c['extra_cost_cents']
    proceeds = math.floor(stressed_value*(1-c['resale_fee_rate'])*
                          (1-c['withdrawal_fee_rate'])*(1-c['resale_slippage_rate']))
    net = proceeds-acquisition
    roi = net/acquisition
    discount = 1-price/fair
    reasons = []
    if observed_drop >= c['max_weekly_drop']:
        reasons.append('seven-day decline/drawdown exceeds crash limit')
    if observed_drop >= discount*c['max_drop_share_of_discount']:
        reasons.append('recent drop consumes too much of discount')
    if net < c['min_stressed_profit_cents'] or roi < c['min_stressed_roi']:
        reasons.append('insufficient profit after another downside scenario')
    return {'risk_ok': not reasons, 'risk_reason': '; '.join(reasons),
            'weekly_change': round(weekly_change,5), 'weekly_drawdown': round(drawdown,5),
            'stress_drop': round(stressed_drop,5), 'stressed_net_cents': net,
            'stressed_roi': round(roi,5), 'trend_days': trend_days,
            'risk_horizon_days': c['risk_horizon_days'], 'trend_source': source}


def chart_trend(chart, now, c, parse_time):
    pass                                                                           
    reject=lambda why: {'risk_ok':False,'risk_reason':why,'trend_source':'daily_average_chart'}
    if not isinstance(chart,list):
        return reject('chart response is not a list')
    today=dt.datetime.fromtimestamp(now,dt.timezone.utc).date()
    points={}
    for row in chart:
        if not isinstance(row,dict):
            return reject('invalid chart row')
        ts=parse_time(row.get('day'))
        count,avg=row.get('count'),row.get('avg_price')
        if not ts or type(count) is not int or count<0 or type(avg) not in (int,float) or not math.isfinite(avg) or avg<=0:
            return reject('invalid chart date/count/price')
        age=(today-dt.datetime.fromtimestamp(ts,dt.timezone.utc).date()).days
        if age<0:
            return reject('future chart date')
        if age==0 or age>8:
            continue
        if age in points:
            return reject('duplicate chart day')
        points[age]=(avg,count)
    usable={age:avg for age,(avg,count) in points.items() if count>=c['min_sales_per_trend_day']}
                                                                                    
    if 1 not in usable or 8 not in usable or sum(a<=7 for a in usable)<c['min_trend_days']:
        return reject('insufficient chart coverage: need yesterday, seven days earlier, and enough populated days')
    current,baseline=usable[1],usable[8]
    peak=max(usable.values())
    return {'risk_ok':True,'risk_reason':'','weekly_change':current/baseline-1,
            'weekly_drawdown':max(0,1-current/peak),'trend_days':len(usable),
            'trend_source':'daily_average_chart','baseline_day':(today-dt.timedelta(days=8)).isoformat(),
            'latest_complete_day':(today-dt.timedelta(days=1)).isoformat(),
            'baseline_average_cents':baseline,'latest_average_cents':current,
            'chart_sale_count':sum(count for age,(avg,count) in points.items() if age in usable)}


def assess_chart(chart, now, fair, price, c, parse_time):
    trend=chart_trend(chart,now,c,parse_time)
    if not trend['risk_ok']:
        return trend
    result=stress(trend['weekly_change'],trend['weekly_drawdown'],fair,price,c,trend['trend_days'],trend['trend_source'])
    return {**trend,**result}
