import collections
import copy
import datetime as dt
from email.utils import format_datetime
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
import urllib.error
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from request_policy import Policy,retry_seconds
from scout import API,AccessStop,RequestBudgetStop,CursorStop,Ledger,timestamp
import scanner,scheduling
from discovery import discover
ROOT=Path(__file__).resolve().parents[1]

class OptimizationTests(unittest.TestCase):
    def test_retry_after_formats(self):
        self.assertEqual(retry_seconds('120',100),120)
        self.assertIsNone(retry_seconds('invalid',100))
        self.assertIsNone(retry_seconds('nan',100))
        self.assertEqual(retry_seconds(format_datetime(dt.datetime.fromtimestamp(200,dt.timezone.utc)),100),100)
    def test_429_persists_cooldown_and_restart_sends_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'request-state.json'
            api=API('FAKE_SECRET',30,path)
            api.opener=Mock()
            api.opener.open.side_effect=urllib.error.HTTPError('https://csfloat.com',429,'limited',{'Retry-After':'7200'},None)
            with patch('runtime_log.event'),patch('request_policy.time.time',return_value=1000):
                with self.assertRaises(AccessStop):api.call('/listings')
                second=API('FAKE_SECRET',30,path);second.opener=Mock()
                with self.assertRaises(AccessStop):second.call('/listings')
                second.opener.open.assert_not_called()
            saved=json.loads(path.read_text());self.assertEqual(saved['blocked_until'],8200)
            self.assertEqual(saved['interval'],60);self.assertNotIn('FAKE_SECRET',path.read_text())
    def test_request_budget_stops_before_network(self):
        api=API('fake',30);api.budget_end=0;api.opener=Mock()
        with self.assertRaises(RequestBudgetStop):api.call('/listings')
        api.opener.open.assert_not_called()
    def test_invalid_cursor_distinguished_from_access_error(self):
        api=API('fake',30);api.opener=Mock()
        api.opener.open.side_effect=urllib.error.HTTPError('u',400,'bad',{},None)
        with patch('runtime_log.event'):
            with self.assertRaises(CursorStop):api.call('/listings',{'cursor':'old'})
    def test_newest_prioritizes_fresh_then_aging_turn(self):
        db=Ledger(':memory:').db;self.addCleanup(db.close);scanner.init(db)
        for lid,added in [('old',1),('new',90)]:
            row=dict(id=lid,item=dict(market_hash_name=lid,paint_index=1))
            db.execute('INSERT INTO scan_items VALUES (?,?,?,?,?,?,?,?)',(lid,2000,'paper_review_v4','queued','',.1,added,json.dumps(row)))
            scheduling.tag(db,lid,2000,'paper_review_v4','newest')
        c=dict(focus_watchlist=[],evaluations_per_cycle=1)
        self.assertEqual(scheduling.select(db,c,'paper_review_v4',collections.Counter(),100)[0][0],'new')
        db.execute("INSERT OR REPLACE INTO discovery_state VALUES ('research_rotation','3')")
        self.assertEqual(scheduling.select(db,c,'paper_review_v4',collections.Counter(),100)[0][0],'old')
    def test_instance_lock_releases_without_deleting_file(self):
        from instance_lock import InstanceLock
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'scout.lock';a=InstanceLock(path)
            try:
                with self.assertRaises(RuntimeError):InstanceLock(path)
            finally:a.close()
            b=InstanceLock(path);b.close()
    def test_sales_failure_avoids_chart_and_competition(self):
        c=scanner.defaults(json.loads((ROOT/'config.json').read_text()))
        c['paper_research_limit']=1
        item=json.loads((ROOT/'demo.json').read_text())['candidate']
        now=timestamp('2026-10-16T06:36:00Z');item['created_at']='2026-10-16T06:30:00Z'
        api=Mock();api.detail.return_value=item;api.sales.return_value=[]
        cwd=os.getcwd()
        with tempfile.TemporaryDirectory() as tmp:
            try:
                os.chdir(tmp);ledger=Ledger(':memory:');scanner.init(ledger.db)
                effective,_=scanner.profile(c,False)
                with patch('scanner.time.time',return_value=now):
                    scanner.ingest(ledger.db,[item],effective,'paper_review_v4',collections.Counter(),feed='newest')
                    counts=collections.Counter();scanner.evaluate_queue(api,ledger,c,False,counts)
                api.graph.assert_not_called();api.listings.assert_not_called();api.detail.assert_not_called()
                self.assertEqual(counts['chart_requests_saved'],1)
                self.assertEqual(counts['detail_requests_saved'],1)
                ledger.db.close()
            finally:os.chdir(cwd)
    def test_six_candidates_do_not_force_six_requests(self):
                                                                               
        c=scanner.defaults(json.loads((ROOT/'config.json').read_text()));item=json.loads((ROOT/'demo.json').read_text())['candidate']
        now=timestamp('2026-10-16T06:36:00Z');item['created_at']='2026-10-16T06:30:00Z'
        cwd=os.getcwd()
        with tempfile.TemporaryDirectory() as tmp:
            try:
                os.chdir(tmp);ledger=Ledger(':memory:');scanner.init(ledger.db)
                with patch('scanner.time.time',return_value=now):
                    scanner.ingest(ledger.db,[item],scanner.profile(c,False)[0],'paper_review_v4',collections.Counter())
                    api=Mock();api.detail.side_effect=RequestBudgetStop('budget')
                    with self.assertRaises(RequestBudgetStop):scanner.evaluate_queue(api,ledger,c,False,collections.Counter())
                self.assertEqual(ledger.db.execute('SELECT state FROM scan_items').fetchone()[0],'queued');ledger.db.close()
            finally:os.chdir(cwd)
    def test_scan_enforces_real_api_budget_and_saves_status(self):
        c=scanner.defaults(json.loads((ROOT/'config.json').read_text()));c['paper_requests_per_cycle']=2
        row=json.loads((ROOT/'demo.json').read_text())['candidate']
        page=dict(data=[dict(row,id=str(i)) for i in range(50)],cursor='next')
        api=API('fake',30)
        def response(*args,**kwargs):
            context=Mock();context.__enter__=Mock(return_value=io.StringIO(json.dumps(page)))
            context.__exit__=Mock(return_value=False);return context
        api.opener=Mock();api.opener.open.side_effect=response
        cwd=os.getcwd()
        with tempfile.TemporaryDirectory() as tmp:
            try:
                os.chdir(tmp);ledger=Ledger(':memory:')
                with patch('scout.time.sleep'):
                    scanner.scan(api,ledger,c)
                self.assertEqual(api.request_count,2)
                self.assertEqual(json.loads(Path('status.json').read_text())['request_budget_reached'],1)
                self.assertIsNone(api.budget_end);ledger.db.close()
            finally:os.chdir(cwd)

    def test_409_cursor_retired_but_non_cursor_conflicts_remain_errors(self):
        from scout import Stop
        for params,error_type in [({'cursor':'old'},CursorStop),({},Stop)]:
            api=API('fake',30);api.opener=Mock()
            api.opener.open.side_effect=urllib.error.HTTPError('u',409,'conflict',{},None)
            with patch('runtime_log.event'):
                with self.assertRaises(error_type):api.call('/listings',params)
            self.assertEqual(api.opener.open.call_count,1)
        api=API('fake',30);api.opener=Mock()
        api.opener.open.side_effect=urllib.error.HTTPError('u',409,'conflict',{},None)
        with patch('runtime_log.event'):
            try:api.call('/listings/buy',body={'contract_ids':['fake'],'total_price':100})
            except Stop as e:self.assertNotIsInstance(e,CursorStop)
            else:self.fail('purchase conflict was suppressed')
        self.assertEqual(api.opener.open.call_count,1)

    def test_rejected_saved_cursor_does_not_block_newest_next_scan(self):
        c=scanner.defaults(json.loads((ROOT/'config.json').read_text()))
        ledger=Ledger(':memory:');self.addCleanup(ledger.db.close);scanner.init(ledger.db)
        row=json.loads((ROOT/'demo.json').read_text())['candidate']
        api=Mock();api.listings.side_effect=[dict(data=[dict(row,id=str(i)) for i in range(50)],cursor='old'),CursorStop('conflict')]
        result=collections.Counter();discover(api,ledger.db,c,False,result,newest_only=True)
        self.assertEqual(result['coverage_gap'],1)
        self.assertEqual(result['newest:pending_traversals'],0)
        api.reset_mock();api.listings.side_effect=[{'data':[]}]
        discover(api,ledger.db,c,False,collections.Counter(),newest_only=True)
        self.assertNotIn('cursor',api.listings.call_args.kwargs)
