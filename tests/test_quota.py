import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from quota import Quotas
from request_policy import Policy
from scout import API, HistoryDeferred


def headers(limit=500, remaining=433, reset=87400):
    return {'x-ratelimit-limit':limit,'x-ratelimit-remaining':remaining,'x-ratelimit-reset':reset}


class QuotaTests(unittest.TestCase):
    def test_reported_daily_budget_replaces_arbitrary_fifteen_minutes(self):
        p=Policy(None,15);p.configure_routes(15,900)
        with patch('request_policy.time.time',return_value=1000):
            p.start_history();p.observe_quota('history_sales',headers())
            self.assertAlmostEqual(p.state['history_next']-1000,86400/383*1.15)
            self.assertFalse(p.history_due())

    def test_missing_headers_and_restart_preserve_consumption(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'quota.json'
            q=Quotas(path);q.observe('history',headers(),1000)
            due=q.deadline('history');q.start('history',due)
            self.assertFalse(q.observe('history',{},due))
            restored=Quotas(path)
            self.assertEqual(restored.buckets['history']['remaining'],432)
            self.assertGreater(restored.deadline('history'),due)

    def test_quota_drop_slows_pacing_and_refill_does_not_restore_units(self):
        q=Quotas();q.observe('history',headers(remaining=498),1000)
        before=q.interval('history',1000)
        q.observe('history',headers(remaining=433,reset=88000),1100)
        self.assertGreater(q.interval('history',1100),before)
        q.observe('history',headers(remaining=499,reset=89000),1200)
        self.assertEqual(q.buckets['history']['remaining'],433)

    def test_reserve_reset_and_probe_do_not_invent_a_balance(self):
        q=Quotas();q.observe('history',headers(remaining=50,reset=2000),1000)
        self.assertEqual(q.deadline('history'),2005)
        q.start('history',2005)
        self.assertEqual(q.deadline('history'),2905)
        self.assertEqual(q.buckets['history']['remaining'],49)
        q.observe('history',headers(remaining=499,reset=88405),2005)
        self.assertEqual(q.buckets['history']['remaining'],499)

    def test_invalid_headers_never_enable_fast_history(self):
        for invalid in ({},headers(reset=3600),headers(remaining=501),headers(reset=10**15)):
            p=Policy(None,15);p.configure_routes(15,900)
            with patch('request_policy.time.time',return_value=10000):
                p.start_history();p.observe_quota('history_sales',invalid)
                self.assertEqual(p.state['history_next'],10900)

    def test_429_backoff_wins_over_usable_headers(self):
        p=Policy(None,15);p.configure_routes(15,900)
        with patch('request_policy.time.time',return_value=1000):
            p.throttle('7200',history=True)
            p.observe_quota('history_sales',headers())
            self.assertEqual(p.state['history_next'],8200)
        with patch('request_policy.time.time',return_value=8200):
            p.observe_quota('history_sales',headers())
            self.assertEqual(p.state['history_next'],10000)

    def test_listing_hourly_quota_is_paced_and_separate_from_history(self):
        q=Quotas();q.observe('reads',headers(200,199,4600),1000)
        self.assertAlmostEqual(q.interval('reads',1000),3600/179*1.15)
        self.assertEqual(q.deadline('history'),0)

    def test_actual_api_headers_govern_sales_and_chart_together(self):
        old=os.getcwd()
        with tempfile.TemporaryDirectory() as tmp:
            os.chdir(tmp)
            try:
                api=API('test',15,'request-state.json');api.policy.configure_routes(15,900)
                response=io.StringIO('[]')
                response.headers={k.title():str(v) for k,v in headers().items()}

                response.headers={k.replace('Ratelimit','RateLimit'):v for k,v in response.headers.items()}
                api.opener=Mock();api.opener.open.return_value=response
                with patch('request_policy.time.time',return_value=1000),patch('scout.time.sleep'):
                    api.sales('Name',1)
                    self.assertLess(api.policy.state['history_next'],1900)
                    api.policy.state['next_allowed']=0
                    with self.assertRaises(HistoryDeferred):api.graph('Name',1)
                    self.assertEqual(api.opener.open.call_count,1)
            finally:os.chdir(old)
