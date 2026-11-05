import json,sys,collections,tempfile
from pathlib import Path
from unittest.mock import Mock,patch
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scout import Ledger,API,Stop
import scanner
ROOT=Path(__file__).resolve().parents[1]
class RankedTests(unittest.TestCase):
    def setUp(self):
        self.c=scanner.defaults(json.loads((ROOT/'config.json').read_text()))
        self.ledger=Ledger(':memory:');scanner.init(self.ledger.db);self.addCleanup(self.ledger.db.close)
    def test_ranked_and_focus_queries_and_missing_cursor_bounded(self):
        self.c['side_feed_queue_limit']=1000;self.c['recent_pages_per_cycle']=1;self.c['deal_pages_per_cycle']=1
        row=json.loads((ROOT/'demo.json').read_text())['candidate']
        page={'data':[dict(row,id=str(i)) for i in range(50)]}
        api=Mock();api.listings.return_value=page
        counts=collections.Counter();scanner.discover(api,self.ledger.db,self.c,False,counts)
        self.assertEqual(api.listings.call_count,3)
        self.assertEqual([x.kwargs['sort_by'] for x in api.listings.call_args_list],['most_recent','best_deal','best_deal'])
        self.assertEqual(api.listings.call_args_list[-1].kwargs['market_hash_name'],self.c['focus_watchlist'][0])
        self.assertGreater(counts['coverage_unknown_no_cursor'],0)
        scanner.discover(api,self.ledger.db,self.c,False,collections.Counter())
        self.assertEqual(api.listings.call_count,4)
        self.assertEqual(api.listings.call_args_list[-1].kwargs['sort_by'],'most_recent')
        with patch('discovery.time.time',return_value=__import__('time').time()+1201):
            scanner.discover(api,self.ledger.db,self.c,False,collections.Counter())
        self.assertEqual(api.listings.call_args_list[-2].kwargs['sort_by'],'highest_discount')
        self.assertTrue(all('cursor' not in x.kwargs for x in api.listings.call_args_list))
    def test_repeated_cursor_does_not_loop(self):
        self.c['side_feed_queue_limit']=1000;self.c['recent_pages_per_cycle']=3;self.c['deal_pages_per_cycle']=1;self.c['focus_watchlist']=[]
        row=json.loads((ROOT/'demo.json').read_text())['candidate']
        pages=[{'data':[dict(row,id=str(i+offset)) for i in range(50)],'cursor':'same'} for offset in (0,50,100)]
        api=Mock();api.listings.side_effect=pages
        counts=collections.Counter();scanner.discover(api,self.ledger.db,self.c,False,counts)
        self.assertEqual(counts['newest:repeated_cursor'],1)
        self.assertEqual(api.listings.call_count,3)
    def test_empty_filtered_sales_fallback_and_error_not_suppressed(self):
        api=API('fake',15)
        with patch.object(api,'call',side_effect=[[],[{'id':'sale'}]]) as call:
            self.assertEqual(api.sales('name',42),[{'id':'sale'}]);self.assertEqual(call.call_count,2)
            self.assertTrue(api.sales_metadata[('name',42)]['unfiltered_fallback_used'])
        with patch.object(api,'call',side_effect=Stop('failed')) as call:
            with self.assertRaises(Stop):api.sales('name',42)
            self.assertEqual(call.call_count,1)
    def test_error_log_omits_exception_secret(self):
        import os
        from runtime_log import event
        cwd=os.getcwd()
        with tempfile.TemporaryDirectory() as tmp:
            try:
                os.chdir(tmp)
                try:raise ValueError('SECRET_TEST_TOKEN')
                except ValueError as error:event('failure',error)
                text=Path('runtime-events.jsonl').read_text()
                self.assertNotIn('SECRET_TEST_TOKEN',text);self.assertIn('ValueError',text)
            finally:os.chdir(cwd)
