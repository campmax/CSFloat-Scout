import collections
import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from scout import API,Ledger,QuotaDeferred,RequestBudgetStop,timestamp
from scanner import scan,init,defaults,ingest,profile,evaluate_queue


class IndependentQuotaTests(unittest.TestCase):
    def setUp(self):
        self.old=os.getcwd();self.tmp=tempfile.TemporaryDirectory();os.chdir(self.tmp.name)
        self.addCleanup(self.cleanup)
        root=Path(__file__).resolve().parents[1]
        self.config=defaults(json.loads((root/'config.json').read_text()))
        self.candidate=json.loads((root/'demo.json').read_text())['candidate']
        self.ledger=Ledger(':memory:');self.addCleanup(self.ledger.db.close)
        init(self.ledger.db)
        self.api=API('test',15,None);self.api.policy.configure_routes(15,900)
        self.api.opener=Mock()
    def cleanup(self):os.chdir(self.old);self.tmp.cleanup()

    def test_zero_request_quota_wait_still_runs_research_and_reports_correctly(self):
        output=io.StringIO()
        with patch('discovery.discover',side_effect=QuotaDeferred('wait')),patch('scanner.evaluate_queue') as research,contextlib.redirect_stdout(output):
            scan(self.api,self.ledger,self.config)
        research.assert_called_once()
        self.assertIn('0 total searched / 0 NEW unique / 0 candidates / 0 researched / 0 passed',output.getvalue())
        self.assertNotIn('Request budget reached;',output.getvalue())
        self.assertIn('Listing/read quota waiting:',output.getvalue())

    def test_real_cycle_budget_still_stops(self):
        with patch('discovery.discover',side_effect=RequestBudgetStop('budget')),patch('scanner.evaluate_queue') as research,contextlib.redirect_stdout(io.StringIO()):
            scan(self.api,self.ledger,self.config)
        research.assert_not_called()
        self.assertEqual(json.loads(Path('status.json').read_text())['request_budget_reached'],1)

    def test_api_quota_wait_is_not_cycle_budget_and_sends_no_request(self):
        with patch('scout.time.time',return_value=1000):
            self.api.policy.quotas.observe('listings_page',{'x-ratelimit-limit':200,'x-ratelimit-remaining':20,'x-ratelimit-reset':4600},1000)
            with self.assertRaises(QuotaDeferred):self.api.listings()
        self.api.opener.open.assert_not_called()
        self.assertEqual(self.api.request_count,0)

    def test_blocked_detail_prefetches_history_but_never_passes_candidate(self):
        self.candidate['created_at']='2026-10-16T06:30:00Z'
        now=timestamp('2026-10-16T06:36:00Z')
        with patch('scanner.time.time',return_value=now):
            ingest(self.ledger.db,[self.candidate],profile(self.config,False)[0],'paper_review_v4',collections.Counter(),feed='newest')
            self.ledger.db.execute('DELETE FROM listing_snapshots')
            self.api.detail=Mock(side_effect=QuotaDeferred('read quota'))
            def sales(*args):
                self.api.request_count+=1
                self.api.policy.start_history()
                return []
            self.api.sales=Mock(side_effect=sales)
            counts=collections.Counter()
            evaluate_queue(self.api,self.ledger,self.config,False,counts)
        self.api.sales.assert_called_once()
        self.assertEqual(counts['history_prefetched'],1)
        self.assertEqual(counts['qualified'],0)
        self.assertEqual(counts['evaluated'],0)
        self.assertEqual(self.ledger.db.execute('SELECT state FROM scan_items').fetchone()[0],'queued')
        self.assertEqual(self.ledger.db.execute("SELECT COUNT(*) FROM evidence_cache WHERE key LIKE 'sales:%'").fetchone()[0],1)
