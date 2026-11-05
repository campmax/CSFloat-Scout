import contextlib
import copy
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock,patch
import personal
from scout import Ledger,HistoryDeferred,QuotaDeferred
from scanner import defaults,init


class PersonalTests(unittest.TestCase):
    def setUp(self):
        root=Path(__file__).resolve().parents[1]
        self.c=defaults(json.loads((root/'config.json').read_text()))
        self.p=json.loads((root/'personal-config.json').read_text())
        fixture=json.loads((root/'demo.json').read_text())
        self.r=fixture['candidate'];self.r['item']['market_hash_name']=self.p['names'][1]
        self.r['item']['float_value']=.2;self.r['price']=28000
        self.now=1792470000
        self.sales=fixture['sales'][:4]
        for i,s in enumerate(self.sales):
            s['item']=copy.deepcopy(self.r['item']);s['price']=30000
            s['state']='sold';s['sold_at']=personal.stamp(self.now-3600*(i+1))
        self.old=os.getcwd();self.tmp=tempfile.TemporaryDirectory();os.chdir(self.tmp.name)
        self.addCleanup(self.cleanup)
        self.ledger=Ledger(':memory:');self.addCleanup(self.ledger.db.close);init(self.ledger.db)
    def cleanup(self):os.chdir(self.old);self.tmp.cleanup()
    def assess(self):return personal.assess(self.r,self.sales,self.c,self.p,self.now)
    def test_matching_wear_and_hard_ceiling(self):
        self.assertTrue(personal.acceptable(self.r,self.p))
        self.r['price']=50001;self.assertFalse(personal.acceptable(self.r,self.p))
        self.r['price']=30000;self.r['item']['float_value']=.38
        self.assertFalse(personal.acceptable(self.r,self.p))
        self.r['item']['market_hash_name']=self.p['names'][0];self.r['item']['float_value']=.07
        self.assertTrue(personal.acceptable(self.r,self.p))
    def test_missing_sales_does_not_invent_deal(self):
        r=personal.assess(self.r,[],self.c,self.p,self.now)
        self.assertFalse(r['target_match']);self.assertIsNone(r['fair_cents']);self.assertFalse(r['supported'])
    def test_personal_savings_do_not_subtract_resale_fees(self):
        r=self.assess();self.assertEqual(r['savings_cents'],2000);self.assertTrue(r['target_match'])
    def test_flexible_budget_requires_growing_discount(self):
        self.r['price']=40000
        for s in self.sales:s['price']=45000
        self.assertFalse(self.assess()['budget_fit'])
        for s in self.sales:s['price']=50000
        self.assertTrue(self.assess()['target_match'])
        self.r['price']=50000
        self.assertAlmostEqual(self.assess()['required_discount'],.20)
    def test_float_bonus_cannot_overrule_one_percent_better_discount(self):
        a=self.assess();self.r['price']-=300;self.r['item']['float_value']=.3
        for s in self.sales:s['item']['float_value']=.3
        b=self.assess();self.assertGreater(b['deal_score'],a['deal_score'])
        self.assertLessEqual(a['float_bonus'],.1)
    def test_session_resume_and_new_session(self):
        state=personal.setup(self.ledger.db,12)
        restored=personal.setup(self.ledger.db,24)
        self.assertEqual(state['end'],restored['end']);self.assertEqual(state['id'],restored['id'])
        self.assertNotEqual(state['id'],personal.setup(self.ledger.db,24,True)['id'])
    def test_report_and_repricing_history(self):
        state=personal.setup(self.ledger.db,12);r=self.assess();personal.record(self.ledger.db,state,r)
        self.r['price']=27000;personal.record(self.ledger.db,state,self.assess())
        with patch('personal_strategy.time.time',return_value=self.now):data=personal.report(self.ledger.db,state)
        self.assertEqual(len(data),1);self.assertEqual(data[0]['price_cents'],27000)
        self.assertIn('No purchases',Path('personal-report.html').read_text())
    def test_cycle_records_even_when_history_is_deferred_and_never_buys(self):
        state=personal.setup(self.ledger.db,12);api=Mock();api.request_count=0
        api.listings.return_value=[self.r]
        with patch('personal.sales_evidence',side_effect=HistoryDeferred('wait')),contextlib.redirect_stdout(io.StringIO()):
            personal.cycle(api,self.ledger,state,self.c,self.p)
        self.assertEqual(len(personal.ranked(self.ledger.db,state)),1)
        api.buy.assert_not_called()
    def test_summary_only_one_recipient_and_final_once(self):
        state=personal.setup(self.ledger.db,12);personal.record(self.ledger.db,state,self.assess())
        with patch('personal.email_alerts.send') as send:
            personal.email_summary(self.ledger.db,state,self.p,True,final=True)
            personal.email_summary(self.ledger.db,state,self.p,True,final=True)
        self.assertEqual(send.call_count,1);self.assertEqual(send.call_args.args[2],'user1@example.com')
    def test_removed_backup_receipt_is_cancelled_without_sending(self):
        import email_alerts
        c=dict(self.c,email_enabled=True,email_recipients=['user3@example.com'])
        email_alerts.init_receipts(self.ledger.db)
        self.ledger.db.execute('INSERT INTO purchase_emails VALUES (?,?,?,?,?,?)',('123','user1@example.com','{}','pending',0,0))
        with patch('email_alerts.send') as send:email_alerts.flush_purchases(self.ledger.db,c)
        send.assert_not_called()
        self.assertEqual(self.ledger.db.execute('SELECT status FROM purchase_emails').fetchone()[0],'cancelled')
