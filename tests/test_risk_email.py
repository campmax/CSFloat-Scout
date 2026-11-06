import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scout import evaluate, Ledger, timestamp, clean_prices, Stop
from risk import assess
import email_alerts
ROOT = Path(__file__).resolve().parents[1]

class RiskTests(unittest.TestCase):
    def setUp(self):
        self.c=json.loads((ROOT/'config.json').read_text())
        self.c['email_recipients']=['user5@example.com']
        self.f=json.loads((ROOT/'demo.json').read_text())
    def test_twenty_percent_boundary_passes(self):
        self.assertTrue(evaluate(**self.f,config=self.c)['eligible'])
    def test_cheap_skin_rejected(self):
        self.f['candidate']['price']=self.c['min_price_cents']-1
        self.assertIn('price limits',evaluate(**self.f,config=self.c)['reason'])
    def test_10_percent_fall_14_percent_deal(self):
        for sale in self.f['sales']:
            age=(self.f['now']-timestamp(sale['sold_at']))/86400
            sale['price']=30000 if age>=6 else 27000
        r=assess(self.f['sales'],self.f['now'],27000,23220,self.c,timestamp,clean_prices)
        self.assertFalse(r['risk_ok'])
        self.assertAlmostEqual(r['weekly_change'],-.10)
        self.assertIn('crash',r['risk_reason'])
    def test_no_week_old_data_no_trade(self):
        self.f['sales']=self.f['sales'][:8]
        r=assess(self.f['sales'],self.f['now'],30000,24000,self.c,timestamp,clean_prices)
        self.assertFalse(r['risk_ok'])
    def test_recent_peak_crash(self):
        for sale in self.f['sales']:
            age=(self.f['now']-timestamp(sale['sold_at']))/86400
            if 2<=age<=4: sale['price']=40000
        r=assess(self.f['sales'],self.f['now'],30000,24000,self.c,timestamp,clean_prices)
        self.assertFalse(r['risk_ok']);self.assertGreater(r['weekly_drawdown'],.20)
    def test_buy_fee_reduces_profit(self):
        a=evaluate(**self.f,config=self.c)
        self.c['buy_fee_rate']=.03
        b=evaluate(**self.f,config=self.c)
        self.assertLess(b['stressed_net_cents'],a['stressed_net_cents'])
    def test_capital_never_resets_with_date(self):
        self.c['max_open_capital_cents']=50000
        with tempfile.TemporaryDirectory() as d:
            ledger=Ledger(str(Path(d)/'db'))
            ledger.record_manual('old',50000)
            ledger.db.execute("UPDATE purchases SET day='2020-01-01'")
            self.assertFalse(ledger.capacity(10000,self.c))
            ledger.release('old')
            self.assertTrue(ledger.capacity(10000,self.c))
    def test_unknown_cannot_release(self):
        with tempfile.TemporaryDirectory() as d:
            ledger=Ledger(str(Path(d)/'db'))
            ledger.reserve(self.f['candidate'],self.c)
            with self.assertRaises(Stop): ledger.release(self.f['candidate']['id'])
    def test_email_deduplication(self):
        self.c['email_enabled']=True
        r=dict(id='one',name='Example',url='https://csfloat.com/item/one',time='now',**evaluate(**self.f,config=self.c))
        with tempfile.TemporaryDirectory() as d,patch('email_alerts.send') as send:
            ledger=Ledger(str(Path(d)/'db'))
            email_alerts.notify(ledger.db,r,self.c);email_alerts.notify(ledger.db,r,self.c)
            self.assertEqual(send.call_count,1)
    def test_email_failure_retry_after_cooldown(self):
        self.c['email_enabled']=True
        r=dict(id='one',name='Example',url='https://csfloat.com/item/one',time='now',**evaluate(**self.f,config=self.c))
        with tempfile.TemporaryDirectory() as d,patch('email_alerts.send',side_effect=OSError) as send:
            ledger=Ledger(str(Path(d)/'db'))
            email_alerts.notify(ledger.db,r,self.c);email_alerts.notify(ledger.db,r,self.c)
            self.assertEqual(send.call_count,1)
            ledger.db.execute('UPDATE emails SET last_attempt=0')
            email_alerts.notify(ledger.db,r,self.c)
            self.assertEqual(send.call_count,2)

if __name__=='__main__':unittest.main()
