import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from scanner import defaults,paper_runtime_config,init
from scout import Ledger,timestamp
from review import evaluate_review
from quota import Quotas
from shortlist import remember,export


class BestAvailableTests(unittest.TestCase):
    def setUp(self):
        root=Path(__file__).resolve().parents[1]
        self.c=paper_runtime_config(defaults(json.loads((root/'config.json').read_text())))
        f=json.loads((root/'demo.json').read_text());self.item=f['candidate'];self.sales=f['sales'][:2]
        self.now=timestamp('2026-10-16T06:36:00Z');self.item['created_at']='2026-10-16T06:30:00Z'
        self.item['price']=28800
        for s in self.sales:s.update(price=30000,sold_at='2026-10-15T05:00:00Z')
    def test_small_positive_margin_two_sales_same_day_missing_chart_is_manual_lead(self):
        r=evaluate_review(self.item,[],self.sales,self.c,now=self.now,chart=[])
        self.assertTrue(r['eligible']);self.assertEqual(r['review_tier'],'paper_watch')
        self.assertIsNone(r['weekly_change']);self.assertFalse(r['risk_ok']);self.assertTrue(r['review_only'])
    def test_negative_margin_and_no_sales_are_not_passed(self):
        self.item['price']=31000
        for sales in (self.sales,[]):
            self.assertFalse(evaluate_review(self.item,[],sales,self.c,now=self.now)['eligible'])
    def test_different_read_endpoints_do_not_merge_remaining_or_reset(self):
        q=Quotas()
        q.observe('listings_page',{'x-ratelimit-limit':200,'x-ratelimit-remaining':190,'x-ratelimit-reset':4600},1000)
        q.observe('listing_detail',{'x-ratelimit-limit':20,'x-ratelimit-remaining':1,'x-ratelimit-reset':87400},1000)
        self.assertLess(q.deadline('listings_page'),1030)
        self.assertEqual(q.deadline('listing_detail'),87405)
    def test_report_displays_rejected_and_incomplete_records_without_inventing_profit(self):
        old=os.getcwd()
        with tempfile.TemporaryDirectory() as tmp:
            os.chdir(tmp)
            try:
                ledger=Ledger(':memory:');init(ledger.db)
                remember(ledger.db,dict(id='123',name='<script>bad</script>',price_cents=2000,eligible=False,reason='insufficient sales',time='2026-10-20'))
                with contextlib.redirect_stdout(io.StringIO()):export(ledger.db)
                page=Path('best-available.html').read_text()
                self.assertIn('Unknown',page);self.assertIn('insufficient sales',page);self.assertNotIn('<script>',page)
                self.assertFalse(json.loads(Path('best-available.json').read_text())['researched'][0]['eligible'])
                ledger.db.close()
            finally:os.chdir(old)
