pass                                                                         
import math
import time

def decorate(r,p):
    r=dict(r);f=r.get('float',1);d=r.get('reference_discount')
    valid=type(d) in (int,float) and math.isfinite(d)
    r['ranking_discount']=d if valid else None
    r['preference']='near-MW Field-Tested' if .15<=f<=p.get('preferred_ft_max_float',.18) else 'Minimal Wear' if .07<=f<.15 else 'other Field-Tested'
    r['ranking_basis']='API float-adjusted reference markdown; website badge parity unverified' if valid else 'reference unavailable'
    r['sales_discount']=r.get('discount')
    r['preference_window_points']=p.get('preference_discount_window',.03)*100
    return r

def rank(data,p,now=None):
    now=time.time() if now is None else now
    latest={}
    for original in data:
        r=decorate(original,p)
        if r.get('last_seen',0)<now-p.get('freshness_seconds',900):continue
        old=latest.get(r['id'])
        if not old or (r['last_seen']>old['last_seen'] or (r['last_seen']==old['last_seen'] and r['price_cents']<old['price_cents'])):latest[r['id']]=r
    data=list(latest.values())
                                                                                     
    for r in data:
        r['dominated_by']=[s['id'] for s in data if s['id']!=r['id'] and s['name']==r['name'] and
            s['total_cost_cents']<=r['total_cost_cents'] and s['float']<=r['float'] and
            (s['total_cost_cents']<r['total_cost_cents'] or s['float']<r['float'])][:3]
    def score(r):return r['ranking_discount'] if r['ranking_discount'] is not None else -10
    data.sort(key=lambda r:(score(r),-r['total_cost_cents']),reverse=True)
    if not data:return data
    best=score(data[0]);window=p.get('preference_discount_window',.03)
    near=[r for r in data if score(r)>0 and score(r)>=best-window and not r['dominated_by'] and
          (r['preference']=='near-MW Field-Tested' or (r['preference']=='Minimal Wear' and score(r)>=p.get('mw_exceptional_discount',.08)))]
    near.sort(key=lambda r:(score(r),-r['float']),reverse=True)
    ids={r['id'] for r in near}
    return near+[r for r in data if r['id'] not in ids]

def queries(p,turn):
    common=dict(limit=50,type='buy_now',max_price=p['hard_max_price_cents'])
    names=sorted(p['names'],key=lambda n: not n.endswith('(Field-Tested)')) if p.get('_live') else p['names']
    for name in names:
        for order in ('best_deal','most_recent'):
            yield dict(common,market_hash_name=name,sort_by=order)
    ft=next((n for n in p['names'] if n.endswith('(Field-Tested)')),None)
    if ft:yield dict(common,market_hash_name=ft,sort_by='lowest_float',max_float=p.get('preferred_ft_search_max_float',.20))
    yield dict(common,market_hash_name=p['names'][turn%len(p['names'])],sort_by='lowest_price')
