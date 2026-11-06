def report(name,asks,sales,chart,config,now):
    from scout import timestamp,comparable,evaluate
    from scanner import profile
    from review import collect_sales,evaluate_review,paper_risk_config
    from risk import chart_trend
    effective,tier=profile(config,False,chart,now)
    review=config['paper_review']['enabled']
    dates=[timestamp(x.get('sold_at')) for x in sales if isinstance(x,dict) and timestamp(x.get('sold_at'))]
    result=dict(mode='READ ONLY — no purchases or emails',diagnostic_version=2,market_hash_name=name,
        profile=tier,listing_count=len(asks),sales_count=len(sales),
        sales_span_hours=round((max(dates)-min(dates))/3600,2) if dates else 0,
        oldest_sale= min(dates) if dates else None,newest_sale=max(dates) if dates else None,
        settings=config['paper_review'] if review else dict(float_tolerance=effective['float_tolerance']),
        chart=chart_trend(chart,now,paper_risk_config(effective) if review else effective,timestamp),
        history_scope='Current API response only; scanner may additionally have previously observed cached sales.',
        exclusion_counts='First failing sales rule; accepted_sales plus exclusion counts equals raw_rows. matched_before_outliers is an intermediate count.',
        comparables=[])
    for candidate in asks[:3]:
        if review:
            _,_,evidence=collect_sales(candidate,sales,effective,now)
            decision=evaluate_review(candidate,asks,sales,effective,now,chart)
        else:
            evidence={'matching_sales':sum(comparable(candidate,x,effective['float_tolerance']) for x in sales)}
            decision=evaluate(candidate,asks,sales,effective,now,chart)
        result['comparables'].append(dict(id=candidate.get('id'),price_cents=candidate.get('price'),
            float=(candidate.get('item') or {}).get('float_value'),**evidence,decision=decision))
    return result
