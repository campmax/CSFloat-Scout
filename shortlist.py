import datetime as dt
import html
import json
from listing_time import describe as listed
from pathlib import Path


def init(db):
    db.execute('CREATE TABLE IF NOT EXISTS review_shortlist (id TEXT,price INTEGER,payload TEXT,PRIMARY KEY(id,price))')


def remember(db,record):
    init(db)
    if record.get('id') and record.get('price_cents'):
        db.execute('INSERT OR REPLACE INTO review_shortlist VALUES (?,?,?)',
                   (str(record['id']),record['price_cents'],json.dumps(record)))


def export(db):
    init(db)

    marker='shortlist-import-v48'
    if not db.execute('SELECT 1 FROM discovery_state WHERE target=?',(marker,)).fetchone():
        path=Path('paper-review.jsonl')
        if path.exists():
            with path.open(encoding='utf-8') as f:
                for line in f:
                    try:r=json.loads(line)
                    except ValueError:continue
                    if isinstance(r,dict):remember(db,r)
        db.execute('INSERT OR REPLACE INTO discovery_state VALUES (?,?)',(marker,'true'))
    researched=[json.loads(r[0]) for r in db.execute('SELECT payload FROM review_shortlist')]

    researched.sort(key=lambda r:(r.get('estimated_net_cents') is not None,
                     r.get('estimated_net_cents',-10**12),r.get('recent_sales_count',0)),reverse=True)
    researched=researched[:30]
    queued=[]
    for lid,price,raw,seen in db.execute("SELECT id,price,payload,added FROM scan_items WHERE state='queued' AND mode='paper_review_v4' ORDER BY score DESC,added DESC LIMIT 20"):
        r=json.loads(raw);ref=r.get('reference') or {};v=ref.get('predicted_price') or ref.get('base_price')
        queued.append(dict(created_at=r.get('created_at'),id=lid,name=r.get('item',{}).get('market_hash_name','Unknown'),price_cents=price,
            reference_discount=1-price/v if isinstance(v,(int,float)) and v>0 else None,
            time=dt.datetime.fromtimestamp(seen,dt.timezone.utc).isoformat(),
            reason='Unresearched: reference discount only; sales value and availability unverified'))
    data=dict(generated_at=dt.datetime.now(dt.timezone.utc).isoformat(),researched=researched,unresearched=queued)
    Path('best-available.json').write_text(json.dumps(data,indent=2),encoding='utf-8')
    esc=lambda x:html.escape(str(x))
    money=lambda x:'Unknown' if x is None else f'${x/100:,.2f}'
    def table(rows,preliminary=False):
        parts=['<table><tr><th>Item</th><th>Price</th><th>Est. net</th><th>Downside net</th><th>Sales / recent</th><th>Listed / age</th><th>Observed</th><th>Assessment</th></tr>']
        for r in rows:
            lid=str(r.get('id',''));link='https://csfloat.com/item/'+lid if lid.isdigit() else '#'
            reason=r.get('reason','')+'; '+'; '.join(r.get('warnings',[]))
            parts.append('<tr><td><a href="'+esc(link)+'">'+esc(r.get('name',lid))+'</a></td>'+''.join('<td>'+esc(x)+'</td>' for x in (
                money(r.get('price_cents')),money(r.get('estimated_net_cents')),money(r.get('stressed_net_cents')),
                str(r.get('sales_count','?'))+' / '+str(r.get('recent_sales_count','?')),listed(r),r.get('time','Unknown'),reason))+'</tr>')
        return ''.join(parts)+'</table>'
    page='''<!doctype html><meta charset="utf-8"><title>CSFloat best available</title>
<style>body{font:15px system-ui;margin:30px;background:#111827;color:#e5e7eb}a{color:#7dd3fc}table{border-collapse:collapse;width:100%}td,th{padding:12px;border-bottom:1px solid #374151;text-align:left;vertical-align:top}th{background:#1f2937}</style>
<h1>Best available — manual review</h1><p>Ranked among observed candidates, not the whole market. Historical observations may already be sold. Check timestamps and current prices. Unknown profit is not zero profit. Reload this page after a scan.</p>'''
    page+='<p>Generated '+esc(data['generated_at'])+'</p><h2>Researched observations, ranked by estimated net</h2>'+table(researched)
    page+='<h2>Awaiting research — reference-ranked only</h2>'+table(queued,True)
    Path('best-available.html').write_text(page,encoding='utf-8')
    print(f'Review page: best-available.html — {len(researched)} researched observations / {len(queued)} unresearched leads (availability must be checked).',flush=True)
