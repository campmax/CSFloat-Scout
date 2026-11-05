import collections
import copy
import datetime as dt
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import scanner
from scout import Ledger, timestamp
ROOT=Path(__file__).resolve().parents[1]

class ScannerTests(unittest.TestCase):
    def setUp(self):
        self.c=scanner.defaults(json.loads((ROOT/'config.json').read_text()))
        self.c['paper_review']['enabled']=False
        self.now=timestamp('2026-10-16T06:36:00Z')
        self.tmp=tempfile.TemporaryDirectory()
        self.ledger=Ledger(str(Path(self.tmp.name)/'test.sqlite3'))
        scanner.init(self.ledger.db)
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(self.ledger.db.close)
    def listing(self,i,age=60,price=24000):
        return dict(id=str(i),price=price,state='listed',type='buy_now',
            created_at=dt.datetime.fromtimestamp(self.now-age,dt.timezone.utc).isoformat(),
            item=dict(market_hash_name='Test Skin',float_value=.2),reference=dict(predicted_price=30000))
    def test_prefilter_and_duplicate_do_not_research(self):
        counts=collections.Counter()
        with patch('scanner.time.time',return_value=self.now):
            items=[self.listing(1),self.listing(2,price=29999),self.listing(3,price=500)]
            scanner.ingest(self.ledger.db,items,self.c,'paper',counts)
            scanner.ingest(self.ledger.db,items,self.c,'paper',counts)
        self.assertEqual(counts['new_unique'],3)
        self.assertEqual(counts['new_candidates'],1)
        self.assertEqual(counts['duplicate_versions'],3)
    def test_pagination_resumes_and_revisits_head(self):
        self.c['discovery_pages_per_cycle']=2
        head=dict(data=[self.listing(i) for i in range(50)],cursor='p2')
        second=dict(data=[self.listing(i) for i in range(50,100)],cursor='p3')
        last=dict(data=[self.listing(100)],cursor=None)
        api=Mock();api.listings.side_effect=[head,second,head,last]
        with patch('scanner.time.time',return_value=self.now):
            first=collections.Counter();scanner.discover(api,self.ledger.db,self.c,False,first)
            second_counts=collections.Counter();scanner.discover(api,self.ledger.db,self.c,False,second_counts)
        self.assertEqual(first['backlog_continues'],1)
        self.assertNotIn('cursor',api.listings.call_args_list[2].kwargs)
        self.assertEqual(api.listings.call_args_list[3].kwargs['cursor'],'p3')
        self.assertEqual(second_counts['new_unique'],1)
        self.assertEqual(second_counts['coverage_boundary_reached'],1)
    def test_full_page_without_cursor_reports_gap(self):
        api=Mock();api.listings.return_value={'data':[self.listing(i) for i in range(50)]}
        counts=collections.Counter()
        with patch('scanner.time.time',return_value=self.now):scanner.discover(api,self.ledger.db,self.c,False,counts)
        self.assertEqual(counts['coverage_unknown_no_cursor'],1)
    def test_cache_reuses_and_expires(self):
        fetch=Mock(return_value=[1])
        with patch('scanner.time.time',return_value=100):
            scanner.cached(self.ledger.db,'key',60,fetch)
            scanner.cached(self.ledger.db,'key',60,fetch)
        self.assertEqual(fetch.call_count,1)
        with patch('scanner.time.time',return_value=161):scanner.cached(self.ledger.db,'key',60,fetch)
        self.assertEqual(fetch.call_count,2)
    def test_stable_tier_and_live_isolation(self):
        chart=[dict(x,avg_price=30000,count=10) for x in json.loads((ROOT/'tests/chart_fixture.json').read_text())]
        original=copy.deepcopy(self.c)
        paper,tier=scanner.profile(self.c,False,chart,self.now)
        self.assertEqual(tier,'stable_10');self.assertEqual(paper['min_discount'],.10)
        live,tier=scanner.profile(self.c,True,chart,self.now)
        self.assertEqual(live['min_discount'],.20)
        self.assertEqual(live['min_stressed_profit_cents'],2500)
        self.assertEqual(self.c,original)
    def test_crashing_or_absent_chart_never_gets_stable_tier(self):
        chart=json.loads((ROOT/'tests/chart_fixture.json').read_text())
        for evidence in (None,[],chart):
            effective,tier=scanner.profile(self.c,False,evidence,self.now)
            self.assertEqual(tier,'paper_15');self.assertEqual(effective['min_discount'],.15)
    def test_expired_queue_requires_no_api_or_purchase(self):
        counts=collections.Counter()
        with patch('scanner.time.time',return_value=self.now):
            scanner.ingest(self.ledger.db,[self.listing(1)],self.c,'paper',counts)
        api=Mock()
        with patch('scanner.time.time',return_value=self.now+7200),patch('scout.purchase') as buy:
            scanner.evaluate_queue(api,self.ledger,self.c,False,counts)
            buy.assert_not_called()
        self.assertEqual(api.mock_calls,[])
        self.assertEqual(counts['queue_expired'],1)

if __name__=='__main__':unittest.main()
