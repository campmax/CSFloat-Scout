import io,json,os,sys,tempfile,unittest,urllib.error
from pathlib import Path
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scout import API,HistoryDeferred,RateLimitStop
from request_policy import Policy

class HistoryPacingTests(unittest.TestCase):
    def setUp(self):
        self.old=os.getcwd();self.tmp=tempfile.TemporaryDirectory();os.chdir(self.tmp.name)
        self.addCleanup(self.cleanup)
    def cleanup(self):os.chdir(self.old);self.tmp.cleanup()
    def api(self):
        api=API('SECRET',15,'request-state.json');api.policy.configure_routes(15,900)
        response=Mock();response.__enter__=Mock(side_effect=lambda:io.StringIO('[]'))
        response.__exit__=Mock(return_value=False)
        api.opener=Mock();api.opener.open.return_value=response
        return api
    def test_migration_preserves_existing_deadlines_and_is_one_time(self):
        Path('state.json').write_text(json.dumps(dict(interval=240,blocked_until=9000,next_allowed=9000)))
        p=Policy('state.json',15);p.configure_routes(15,900)
        self.assertEqual(p.state['interval'],15)
        self.assertEqual(p.state['blocked_until'],9000)
        self.assertEqual(p.state['next_allowed'],9000)
        with patch('request_policy.time.time',return_value=1000):p.throttle(None)
        second=Policy('state.json',15);second.configure_routes(15,900)
        self.assertEqual(second.state['interval'],30)
    def test_history_shared_slot_and_restart_do_not_burst(self):
        with patch('request_policy.time.time',return_value=1000),patch('scout.time.sleep'):
            api=self.api();api.sales('Name',1)
            self.assertEqual(api.opener.open.call_count,1)
            api.policy.state['next_allowed']=0
            with self.assertRaises(HistoryDeferred):api.graph('Other',2)
            second=API('SECRET',15,'request-state.json');second.opener=Mock()
            second.policy.state['next_allowed']=0
            with self.assertRaises(HistoryDeferred):second.sales('Third',3)
            second.opener.open.assert_not_called()
    def test_history_429_preserves_global_cooldown_without_doubling_discovery(self):
        with patch('request_policy.time.time',return_value=1000),patch('scout.time.sleep'):
            api=self.api()
            api.opener.open.side_effect=urllib.error.HTTPError('url',429,'limited',{'Retry-After':'7200','Set-Cookie':'SECRET'},None)
            with self.assertRaises(RateLimitStop):api.sales('Name',1)
            self.assertEqual(api.policy.state['interval'],15)
            self.assertEqual(api.policy.state['history_interval'],1800)
            self.assertEqual(api.policy.state['blocked_until'],8200)
            with self.assertRaises(RateLimitStop):api.listings()
            self.assertEqual(api.opener.open.call_count,1)
            log=Path('runtime-events.jsonl').read_text()
            self.assertNotIn('SECRET',log)
            event=json.loads(log.splitlines()[0]);self.assertEqual(event['route'],'history_sales')
            self.assertEqual(event['limits']['retry_after_seconds'],7200)
    def test_cached_sales_reused_without_refreshing_their_age(self):
        from scout import Ledger
        from scanner import init,sales_evidence
        ledger=Ledger(':memory:');self.addCleanup(ledger.db.close);init(ledger.db)
        api=Mock();api.sales.return_value=[]
        with patch('scanner.time.time',return_value=1000):sales_evidence(api,ledger.db,'Name',1,14,3600)
        with patch('scanner.time.time',return_value=2000):sales_evidence(api,ledger.db,'Name',1,14,3600)
        self.assertEqual(api.sales.call_count,1)
        source=json.loads(ledger.db.execute("SELECT payload FROM evidence_cache WHERE key LIKE 'sales_source:%'").fetchone()[0])
        self.assertEqual(source['cache_age_seconds'],1000)
    def test_waiting_chart_candidate_stays_queued_without_repeated_detail_calls(self):
        import collections
        from scout import Ledger,timestamp
        from scanner import init,defaults,evaluate_queue,ingest,profile
        root=Path(__file__).resolve().parents[1]
        c=defaults(json.loads((root/'config.json').read_text()))
        candidate=json.loads((root/'demo.json').read_text())['candidate']
        candidate['created_at']='2026-10-16T06:30:00Z';now=timestamp('2026-10-16T06:36:00Z')
        ledger=Ledger(':memory:');self.addCleanup(ledger.db.close);init(ledger.db)
        with patch('scanner.time.time',return_value=now):
            ingest(ledger.db,[candidate],profile(c,False)[0],'paper_review_v4',collections.Counter(),feed='newest')
            api=self.api();api.policy.state['history_next']=now+900
            ledger.db.execute('INSERT INTO discovery_state VALUES (?,?)',
                ('history_wait:'+json.dumps([candidate['id'],candidate['price']]),json.dumps(now+900)))
            counts=collections.Counter();evaluate_queue(api,ledger,c,False,counts)
            api.opener.open.assert_not_called()
            self.assertEqual(counts['history_deferred'],1)
            self.assertEqual(ledger.db.execute('SELECT state FROM scan_items').fetchone()[0],'queued')
