"""Permissive paper-review evidence. NEVER used to authorize purchases."""
import math
import statistics
import time


def paper_risk_config(config):
    return dict(config,min_sales_per_trend_day=1,min_trend_days=3,min_stress_drop=.03,resale_slippage_rate=.01)


def match_reason(candidate, row, tolerance):
    a=candidate.get('item') or {};b=row.get('item') or {}
    for key in ('market_hash_name','def_index','paint_index'):
        if a.get(key) is None or b.get(key) is None:return 'missing_identity'
        if a[key]!=b[key]:return 'identity_mismatch'
    floats=[a.get('float_value'),b.get('float_value')]
    if not all(type(f) in (int,float) and math.isfinite(f) and 0<=f<=1 for f in floats):return 'invalid_float'
    if abs(floats[0]-floats[1])>tolerance:return 'float_mismatch'
    return None


def collect_sales(candidate,sales,config,now):
    from collections import Counter
    from scout import cents,timestamp,clean_prices
    p=config['paper_review'];counts=Counter();kept=[];seen=set()
    souvenir=(candidate.get('item') or {}).get('market_hash_name','').startswith('Souvenir ')
    for sale in sales:
        counts['raw_rows']+=1
        if not isinstance(sale,dict):counts['malformed_row']+=1;continue
        lid=sale.get('id');sold=timestamp(sale.get('sold_at'))
        reason=None
        if not lid:reason='missing_id'
        elif lid in seen:reason='duplicate_id'
        elif sale.get('state')!='sold':reason='not_sold'
        elif not cents(sale.get('price')):reason='invalid_price'
        elif not sold or sold>now:reason='invalid_sold_date'
        elif now-sold>p['sales_window_days']*86400:reason='outside_sales_window'
        else:reason=match_reason(candidate,sale,1.0)
        if not reason:
            item=sale.get('item') or {}
            if item.get('keychains'):reason='keychain'
            elif item.get('stickers') and not souvenir:reason='decorated_non_souvenir'
        if reason:counts[reason]+=1;continue
        seen.add(lid);kept.append(sale)
    from float_model import FloatModel
    name=(candidate.get('item') or {}).get('market_hash_name','')
    blocked=souvenir or any(word.lower() in name.lower() for word in config['exclude_name_contains'])
    model=FloatModel(kept,candidate['item']['float_value'],timestamp,blocked=blocked)
    normalized=[];audit=[];refusals=Counter()
    for sale in kept:
        if p.get('prefer_direct') and match_reason(candidate,sale,p['float_tolerance']) is None:
            normalized.append(sale);counts['direct_float_comparisons']+=1
            continue
        adjusted,reason=model.adjust(sale)
        if adjusted is not None:
            normalized.append(dict(sale,price=adjusted['adjusted_price_cents'],
                                   uncertainty_price_cents=adjusted['uncertainty_price_cents']))
            audit.append(adjusted)
        elif match_reason(candidate,sale,p['float_tolerance']) is None:
            normalized.append(sale)
            counts['direct_float_comparisons']+=1
        else:
            counts['float_mismatch']+=1
            refusals[reason]+=1
    kept=normalized
    counts['float_adjusted_comparisons']=len(audit)
    counts['matched_before_outliers']=len(kept)
    cleaned=clean_prices([x['price'] for x in kept])
    filtered=[x for x in kept if x['price'] in cleaned]
    counts['price_outlier']=len(kept)-len(filtered)
    counts['accepted_sales']=len(filtered)
    accepted_ids={str(x['id']) for x in filtered}
    for adjustment in audit:
        adjustment['accepted_after_outlier_check']=adjustment['id'] in accepted_ids
    recent=[x for x in filtered if now-timestamp(x['sold_at'])<=p['recent_window_days']*86400]
    days=len({int(timestamp(x['sold_at'])//86400) for x in filtered})
    recent_days=len({int(timestamp(x['sold_at'])//86400) for x in recent})
    return filtered,recent,dict(sales_count=len(filtered),recent_sales_count=len(recent),
        sale_days=days,recent_sale_days=recent_days,sales_filter_counts=dict(counts),
        sales_window_days=p['sales_window_days'],recent_window_days=p['recent_window_days'],
        min_sales_required=p['min_sales'],min_recent_sales_required=p['min_recent_sales'],
        float_tolerance=p['float_tolerance'],float_model=dict(model.info,refused_adjustments=dict(refusals)),
        float_adjustments=audit)


def evaluate_review(candidate, asks, sales, config, now=None, chart=None):
    from scout import cents, timestamp, clean_prices, quantile
    from risk import chart_trend, stress
    now=time.time() if now is None else now
    p=config['paper_review'];item=candidate.get('item') or {};price=candidate.get('price')
    warnings=[]
    def reject(reason,**extra):
        return dict(eligible=False,reason=reason,review_only=True,warnings=warnings,**extra)
    if candidate.get('state')!='listed' or candidate.get('type')!='buy_now':return reject('not active buy-now')
    if not cents(price) or price<config['min_price_cents']:return reject('invalid price or below minimum')
    if config['max_price_cents'] is not None and price>config['max_price_cents']:return reject('above configured maximum')
    if not 0<=now-timestamp(candidate.get('created_at'))<=p['max_listing_age_seconds']:return reject('listing age outside review window')
    value=item.get('float_value')
    if type(value) not in (int,float) or not math.isfinite(value) or not 0<=value<=1:return reject('unsupported item / invalid float')
    if any(item.get(k) is None for k in ('market_hash_name','def_index','paint_index')):return reject('missing item identity')
    if item.get('stickers') or item.get('keychains'):warnings.append('Decorations ignored in valuation; inspect manually.')
    if any(w.lower() in item['market_hash_name'].lower() for w in config['exclude_name_contains']):warnings.append('Pattern-sensitive finish: seed/phase premium is NOT validated.')
    if item['market_hash_name'].startswith('Souvenir '):
        warnings.append('Souvenir sticker-bearing sales included; tournament/player/sticker premiums are not normalized.')
    def matches(row):
        return match_reason(candidate,row,p['float_tolerance']) is None
    kept,recent,evidence=collect_sales(candidate,sales,config,now)
    evidence['price_cents']=price
    if evidence['float_adjustments']:
        warnings.append('Float-adjusted central values and an empirical lower scenario are reported separately; neither is guaranteed.')
    if len(kept)<p['min_sales'] or len(recent)<p['min_recent_sales'] or evidence['sale_days']<(1 if p.get('best_available') else 2):
        dates='one or more dates' if p.get('best_available') else 'two dates'
        return reject(f"review needs {p['min_sales']} comparable sales in {p['sales_window_days']} days across {dates}, including {p['min_recent_sales']} in {p['recent_window_days']} days",**evidence)
    cleaned=[x['price'] for x in kept]
    if len(recent)<4:warnings.append('Thin recent sample: fewer than four matching sales in the recent window.')
    fair=math.floor(min(statistics.median(cleaned),statistics.median([s['price'] for s in recent])))
    conservative_fair=math.floor(min(statistics.median([s.get('uncertainty_price_cents',s['price']) for s in kept]),
                                     statistics.median([s.get('uncertainty_price_cents',s['price']) for s in recent])))
    discount=round(1-price/fair,12)
    dispersion=(quantile(cleaned,.75)-quantile(cleaned,.25))/statistics.median(cleaned)
    if dispersion>.25:warnings.append('Comparable sales vary widely; median may not represent this item.')
    ask_prices=[a['price'] for a in asks if a.get('id')!=candidate.get('id') and a.get('state')=='listed' and a.get('type')=='buy_now' and cents(a.get('price')) and matches(a)]
    lowest=min(ask_prices) if ask_prices else None
    if lowest is None:warnings.append('No matching active competition found.')
    elif lowest<fair:warnings.append('A competing ask is below the sales median; resale at the median is uncertain.')
    c=paper_risk_config(config)
    trend=chart_trend(chart,now,c,timestamp)
    if trend['risk_ok']:
        risk=stress(trend['weekly_change'],trend['weekly_drawdown'],conservative_fair,price,c,trend['trend_days'],'daily_average_chart')
        if not risk['risk_ok']:warnings.append('Strict risk check: '+risk['risk_reason'])
        if trend['weekly_drawdown']>.06:warnings.append('Drawdown from a recent peak exceeds 6%.')
    else:
        warnings.append('Weekly trend UNVERIFIED: '+trend['risk_reason'])
        risk=stress(0,0,conservative_fair,price,c,0,'assumed_scenario_only')
        risk.update(weekly_change=None,weekly_drawdown=None,risk_ok=False,risk_reason=trend['risk_reason'])
    acquisition=math.ceil(price*(1+config['buy_fee_rate']))+config['extra_cost_cents']
    net=math.floor(fair*(1-config['resale_fee_rate'])*(1-config['withdrawal_fee_rate'])*.99)-acquisition
    profitable_sales=sum(s['price']*(1-config['resale_fee_rate'])*(1-config['withdrawal_fee_rate'])*.99>acquisition for s in recent)
    ref=candidate.get('reference') or {}
    base=ref.get('base_price');predicted=ref.get('predicted_price')
    evidence.update(fair_cents=fair,uncertainty_fair_cents=conservative_fair,discount=discount,estimated_net_cents=net,
        uncertainty_net_cents=math.floor(conservative_fair*(1-config['resale_fee_rate'])*(1-config['withdrawal_fee_rate'])*.99)-acquisition,
        csfloat_base_discount=1-price/base if cents(base) else None,
        csfloat_predicted_discount=1-price/predicted if cents(predicted) else None,
        reference_note='API base and float-adjusted references; exact website badge parity is not verified.',
        comparable_asks=len(ask_prices),lowest_ask_cents=lowest,sales_iqr_ratio=dispersion,
        recent_sales_above_break_even=profitable_sales,csfloat_discount=1-price/base if cents(base) else None,**risk)
    if net<=0 or profitable_sales<p['min_recent_sales']:return reject('insufficient completed sales above fee-adjusted break-even',**evidence)
    def watch_or_reject(reason):
        if (p.get('best_available') and discount>=p.get('watch_discount',.02) and
            net>=p.get('watch_net_cents',1)):
            warnings.append('MANUAL REVIEW: small estimated margin or thin evidence; not purchase approval.')
            if risk['stressed_net_cents']<=0:warnings.append('DOWNSIDE LOSS: modeled downside loses money.')
            if trend['risk_ok'] and trend['weekly_change'] < -p['max_weekly_loss']:
                warnings.append('FALLING MARKET: weekly loss exceeds the normal limit.')
            return dict(eligible=True,reason='best-available paper lead — manual review only',review_only=True,
                        review_tier='paper_watch',warnings=warnings,**evidence)
        if (p.get('watch_enabled',False) and discount>=p.get('watch_discount',.04) and
            net>=p.get('watch_net_cents',100) and trend['risk_ok'] and
            trend['weekly_change']>=-p['max_weekly_loss']-1e-9):
            warnings.append('PAPER WATCH ONLY: a smaller estimated margin; this does not satisfy the stronger deal criteria.')
            if risk['stressed_net_cents']<=0:
                warnings.append('DOWNSIDE LOSS: the modeled downside scenario loses money. This is not a validated profitable resale.')
            return dict(eligible=True,reason='paper watch lead — manual review only',review_only=True,
                        review_tier='paper_watch',warnings=warnings,**evidence)
        return reject(reason,**evidence)
    if discount>=p['high_discount']:
        tier='review_15_plus'
    elif discount>=p['min_discount'] and trend['risk_ok'] and trend['weekly_change']>=-p['max_weekly_loss']-1e-9:
        if net<p['min_good_net_cents'] or risk['stressed_net_cents']<p['min_good_stressed_cents'] or risk['stressed_roi']<p['min_good_stressed_roi']:
            return watch_or_reject('modest deal has insufficient margin after fees and downside scenario')
        tier='review_good_6_plus'
    else:return watch_or_reject('needs high discount or configured modest discount with verified acceptable weekly loss')
    return dict(eligible=True,reason='paper review candidate — not purchase approval',review_only=True,
                review_tier=tier,warnings=warnings,**evidence)
