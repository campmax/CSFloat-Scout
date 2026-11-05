import copy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scout import timestamp,validate_config
from scanner import defaults,profile,screen,queue_mode
from review import evaluate_review
ROOT=Path(__file__).resolve().parents[1]
class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.c=defaults(json.loads((ROOT/'config.json').read_text()))
        self.f=json.loads((ROOT/'demo.json').read_text())
        self.now=timestamp('2026-10-16T06:36:00Z')
        self.item=self.f['candidate'];self.item['created_at']='2026-10-16T06:30:00Z'
        self.sales=self.f['sales'][:8]
        for i,s in enumerate(self.sales):s.update(price=30000,sold_at=f'2026-10-{15-i%2}T05:00:00Z')
        self.chart=[dict(x,avg_price=30000,count=2) for x in json.loads((ROOT/'tests/chart_fixture.json').read_text())]
    def run_review(self,chart=True):
        return evaluate_review(self.item,[],self.sales,self.c,now=self.now,chart=self.chart if chart else [])
    def test_high_discount_missing_chart_flags_unverified(self):
        r=self.run_review(False);self.assertTrue(r['eligible']);self.assertIsNone(r['weekly_change']);self.assertFalse(r['risk_ok'])
    def test_ten_percent_with_six_percent_weekly_loss(self):
        self.item['price']=27000
        self.chart=[dict(x,avg_price=28200 if x['day'].startswith('2026-10-15') else 30000) for x in self.chart]
        self.assertTrue(self.run_review()['eligible'])
        self.chart=[dict(x,avg_price=28100 if x['day'].startswith('2026-10-15') else 30000) for x in self.chart]
        self.assertFalse(self.run_review()['eligible'])
    def test_ten_percent_missing_chart_rejected(self):
        self.item['price']=27000;self.assertFalse(self.run_review(False)['eligible'])
    def test_reference_never_sets_sales_value(self):
        self.item['reference']={'base_price':9999999};r=self.run_review();self.assertEqual(r['fair_cents'],30000)
    def test_no_sales_no_flag(self):
        self.sales=[];self.assertFalse(self.run_review()['eligible'])
    def test_one_day_burst_not_sustained_sales(self):
        for s in self.sales:s['sold_at']='2026-10-15T05:00:00Z'
        self.assertFalse(self.run_review()['eligible'])
    def test_decoration_warning_and_live_unchanged(self):
        self.item['item']['stickers']=[{'name':'test'}]
        self.assertTrue(self.run_review()['eligible'])
        live,_=profile(self.c,True);self.assertNotIn('_paper_review',live);self.assertEqual(live['min_discount'],.20)
        paper,_=profile(self.c,False)
        self.item['reference']={'base_price':30000,'predicted_price':24000}
        self.assertIsNone(screen(self.item,paper,self.now)[0])
        self.assertIsNotNone(screen(self.item,live,self.now)[0])
    def test_cheap_screen_rejects_stickers_before_research(self):
        paper,_=profile(self.c,False);self.item['item'].pop('float_value')
        self.assertIn('unsupported',screen(self.item,paper,self.now)[0])
    def test_paper_queue_emails_review_without_buy_or_balance(self):
        import collections,os,tempfile
        from unittest.mock import Mock
        import scanner
        from scout import Ledger
        previous=os.getcwd()
        with tempfile.TemporaryDirectory() as tmp:
            os.chdir(tmp)
            ledger=Ledger('test.sqlite3');scanner.init(ledger.db)
            try:
                counts=collections.Counter();api=Mock()
                api.detail.return_value=self.item;api.listings.return_value={'data':[]}
                api.sales.return_value=self.sales;api.graph.return_value=[]
                effective,_=profile(self.c,False)
                with patch('scanner.time.time',return_value=self.now),patch('scout.purchase') as buy,patch('email_alerts.notify') as notify:
                    scanner.ingest(ledger.db,[self.item],effective,queue_mode(self.c,False),counts)
                    scanner.evaluate_queue(api,ledger,self.c,False,counts)
                    buy.assert_not_called();api.available_balance.assert_not_called()
                    self.assertEqual(notify.call_count,1)
                    record=notify.call_args.args[1]
                    self.assertTrue(record['review_only']);self.assertIsNone(record['weekly_change'])
                    self.assertTrue(Path('paper-review.jsonl').exists())
            finally:
                ledger.db.close();os.chdir(previous)

    def test_four_weekly_two_recent_qualify(self):
        self.sales=self.sales[:4]
        for i,sale in enumerate(self.sales):sale['sold_at']=f"2026-10-{15 if i<2 else 11}T05:00:00Z"
        r=self.run_review();self.assertTrue(r['eligible']);self.assertEqual(r['recent_sales_count'],2)
        self.sales[1]['sold_at']='2026-10-11T05:00:00Z'
        self.assertFalse(self.run_review()['eligible'])
    def test_souvenir_stickers_allowed_only_with_same_identity(self):
        name='Souvenir AK-47 | Redline (Field-Tested)'
        self.item['item']['market_hash_name']=name
        for sale in self.sales:
            sale['item']=dict(sale['item'],market_hash_name=name,stickers=[{'name':'test'}])
        self.assertTrue(self.run_review()['eligible'])
        self.item['item']['market_hash_name']='AK-47 | Redline (Field-Tested)'
        r=self.run_review();self.assertFalse(r['eligible']);self.assertEqual(r['sales_filter_counts']['identity_mismatch'],8)
    def test_diagnostic_matches_paper_judgment_and_chart_settings(self):
        from diagnostics import report
        d=report('test',[self.item],self.sales,self.chart,self.c,self.now)
        self.assertEqual(d['comparables'][0]['decision'],self.run_review())
        self.assertEqual(d['settings']['float_tolerance'],.05)
        self.assertTrue(d['chart']['risk_ok'])
    def test_diagnostic_explains_missing_float_decoration_and_age(self):
        from review import collect_sales
        samples=copy.deepcopy(self.sales[:4])
        samples[0]['item'].pop('float_value')
        samples[1]['item']['stickers']=[{'name':'test'}]
        samples[2]['sold_at']='2026-10-01T05:00:00Z'
        samples[3]['item']['float_value']=.9
        _,_,r=collect_sales(self.item,samples,self.c,self.now)
        counts=r['sales_filter_counts']
        for reason in ('invalid_float','decorated_non_souvenir','outside_sales_window','float_mismatch'):self.assertEqual(counts[reason],1)
        self.assertEqual(counts['accepted_sales'],0)

    def test_modest_eight_percent_qualifies_when_stable(self):
        self.item['price']=27600
        r=self.run_review();self.assertTrue(r['eligible']);self.assertEqual(r['review_tier'],'review_good_6_plus')
        self.assertGreaterEqual(r['stressed_roi'],.01)
    def test_modest_eight_percent_rejects_another_six_percent_drop(self):
        self.c['paper_review']['watch_enabled']=False
        self.item['price']=27600
        self.chart=[dict(x,avg_price=28200 if x['day'].startswith('2026-10-15') else 30000) for x in self.chart]
        self.assertFalse(self.run_review()['eligible'])
    def test_watch_lead_labels_negative_downside_and_requires_recent_sales(self):
        self.item['price']=28700
        r=self.run_review()
        self.assertTrue(r['eligible']);self.assertEqual(r['review_tier'],'paper_watch')
        self.assertLess(r['stressed_net_cents'],0)
        self.assertTrue(any('DOWNSIDE LOSS' in w for w in r['warnings']))
        self.assertFalse(self.run_review(False)['eligible'])
        self.sales=self.sales[:1]
        self.assertFalse(self.run_review()['eligible'])
    def test_three_sales_across_dates_with_two_recent_pass_broader_profile(self):
        from scanner import paper_runtime_config
        self.c['paper_review']['best_available']=False  # legacy profile remains selectable
        self.c=paper_runtime_config(self.c);self.sales=self.sales[:3]
        self.assertTrue(self.run_review()['eligible'])
        self.sales[1]['sold_at']='2026-10-01T05:00:00Z'
        self.assertFalse(self.run_review()['eligible'])
    def test_modest_missing_chart_does_not_claim_stability(self):
        self.item['price']=27600;self.assertFalse(self.run_review(False)['eligible'])
    def test_reference_discounts_separately_reported(self):
        self.item['reference']={'base_price':32000,'predicted_price':30000}
        r=self.run_review();self.assertEqual(r['csfloat_base_discount'],.25)
        self.assertAlmostEqual(r['csfloat_predicted_discount'],.2)

    def test_new_queue_namespace_and_config_valid(self):
        validate_config(self.c);self.assertEqual(queue_mode(self.c,False),'paper_review_v4')

if __name__=='__main__':unittest.main()
