import collections
import copy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import scanner
from discovery import discover,load
from scout import Ledger,Stop,validate_config
ROOT=Path(__file__).resolve().parents[1]

class FreshTests(unittest.TestCase):
    def setUp(self):
        self.c=scanner.defaults(json.loads((ROOT/'config.json').read_text()))
        self.c['recent_pages_per_cycle']=2
        self.db=Ledger(':memory:').db;scanner.init(self.db);self.addCleanup(self.db.close)
        self.row=json.loads((ROOT/'demo.json').read_text())['candidate']
        self.api=Mock()
    def page(self,start,cursor=None,n=50):
        result={'data':[dict(self.row,id=str(i)) for i in range(start,start+n)]}
        if cursor:result['cursor']=cursor
        return result
    def run_fresh(self):
        counts=collections.Counter();discover(self.api,self.db,self.c,False,counts,newest_only=True);return counts
    def test_head_then_saved_backlog_with_restart(self):
        self.api.listings.side_effect=[self.page(0,'a'),self.page(50,'b')]
        first=self.run_fresh();self.assertEqual(first['backlog_continues'],1)
        self.api.reset_mock();self.api.listings.side_effect=[self.page(0,'a'),self.page(100,n=3)]
        second=self.run_fresh()
        self.assertNotIn('cursor',self.api.listings.call_args_list[0].kwargs)
        self.assertEqual(self.api.listings.call_args_list[1].kwargs['cursor'],'b')
        self.assertEqual(second['newest:pending_traversals'],0)
    def test_failed_continuation_remains_saved(self):
        self.api.listings.side_effect=[self.page(0,'a'),Stop('temporary')]
        with self.assertRaises(Stop):self.run_fresh()
        saved=json.loads(self.db.execute("SELECT payload FROM discovery_state WHERE target LIKE 'fresh_backlog:%'").fetchone()[0])
        self.assertEqual(saved[0]['cursor'],'a')
        self.api.reset_mock();self.api.listings.side_effect=[self.page(0,'a'),self.page(50,n=1)]
        self.run_fresh();self.assertEqual(self.api.listings.call_args_list[1].kwargs['cursor'],'a')
    def test_secondary_feeds_do_not_define_newest_boundary(self):
        self.api.listings.return_value=self.page(0,'a')
        counts=collections.Counter();discover(self.api,self.db,self.c,False,counts,secondary_only=True)
        self.api.reset_mock();self.api.listings.side_effect=[self.page(0,'a'),self.page(50,n=1)]
        result=self.run_fresh()
        self.assertEqual(self.api.listings.call_count,2)
        self.assertEqual(result['newest:known_page_reached'],0)
    def test_query_scope_changes_when_minimum_changes(self):
        self.api.listings.side_effect=[self.page(0,'a'),self.page(50,n=1)]
        self.run_fresh();self.c['min_price_cents']=5000
        self.api.reset_mock();self.api.listings.side_effect=[self.page(0,'a'),self.page(50,n=1)]
        self.run_fresh();self.assertEqual(self.api.listings.call_count,2)
    def test_low_price_configuration_and_validation(self):
        self.assertEqual(self.c['min_price_cents'],2000);validate_config(self.c)
        self.c['paper_poll_seconds']=0
        with self.assertRaises(Stop):validate_config(self.c)
    def test_repeat_cursor_stops_and_reports_gap(self):
        self.api.listings.side_effect=[self.page(0,'a'),self.page(50,'a')]
        r=self.run_fresh();self.assertEqual(r['coverage_gap'],1)
        self.assertEqual(r['newest:pending_traversals'],0)
    def test_due_feeds_have_separate_timers(self):
        self.api.listings.return_value=self.page(0,n=0)
        with patch('discovery.time.time',return_value=1000):
            discover(self.api,self.db,self.c,False,collections.Counter(),secondary_only=True)
        self.api.reset_mock()
        with patch('discovery.time.time',return_value=1601):
            r=collections.Counter();discover(self.api,self.db,self.c,False,r,secondary_only=True)
        self.assertEqual(self.api.listings.call_count,1)
        self.assertEqual(r['focus:skipped_not_due'],1)
    def test_scan_prioritizes_research_before_secondary(self):
        ledger=Mock();ledger.db=self.db
        calls=[]
        def discovery(*args,**kwargs):calls.append('newest' if kwargs.get('newest_only') else 'secondary')

        import os,tempfile
        cwd=os.getcwd()
        with tempfile.TemporaryDirectory() as tmp:
            try:
                os.chdir(tmp)
                with patch('discovery.discover',side_effect=discovery),patch('scanner.evaluate_queue',side_effect=lambda *a:calls.append('research')),patch('email_alerts.flush_purchases'):
                    scanner.scan(self.api,ledger,self.c)
            finally:os.chdir(cwd)
        self.assertEqual(calls,['newest','research','secondary'])

    def test_newest_check_between_two_research_tasks(self):
        self.c['newest_check_seconds']=0
        import os,tempfile
        ledger=Mock();ledger.db=self.db
        rows=[(str(i),self.row['price'],json.dumps(dict(self.row,id=str(i))),'newest') for i in range(2)]
        sequence=[]
        def detail(lid):
            sequence.append('detail:'+lid)
            return dict(self.row,id=lid,price=self.row['price']+1)
        self.api.detail.side_effect=detail
        cwd=os.getcwd()
        with tempfile.TemporaryDirectory() as tmp:
            try:
                os.chdir(tmp)
                with patch('scheduling.select',return_value=rows),patch('discovery.discover',side_effect=lambda *a,**kw:sequence.append('newest')):
                    scanner.evaluate_queue(self.api,ledger,self.c,False,collections.Counter())
            finally:os.chdir(cwd)
        self.assertEqual(sequence,['detail:0','newest','detail:1'])

    def test_old_traversals_are_archived_and_gap_reported(self):
        from discovery import save
        scope=json.dumps([None,self.c['min_price_cents'],None,'paper_review_v4'])
        save(self.db,'fresh_backlog:'+scope,[dict(cursor='stale',visited=[],started=1)])
        self.api.listings.return_value=self.page(0,n=0)
        with patch('discovery.time.time',return_value=2000):result=self.run_fresh()
        self.assertEqual(self.api.listings.call_count,1)
        self.assertEqual(result['coverage_gap'],1)
        self.assertEqual(load(self.db,'retired:'+scope,[])[0]['cursor'],'stale')

    def test_unchanged_side_feed_backs_off_but_repricing_resets(self):
        self.c['focus_watchlist']=[];self.c['side_feed_queue_limit']=1000
        self.api.listings.return_value=self.page(0,n=1)
        def side(now):
            with patch('discovery.time.time',return_value=now):
                discover(self.api,self.db,self.c,False,collections.Counter(),secondary_only=True)
        side(1000);side(1301)
        self.api.reset_mock();side(1602)
        self.api.listings.assert_not_called()
        page=self.page(0,n=1);page['data'][0]['price']-=1;self.api.listings.return_value=page
        side(1902);self.assertEqual(self.api.listings.call_count,1)
        self.api.reset_mock();side(2203)
        self.assertEqual(self.api.listings.call_count,1)
