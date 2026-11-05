import copy
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from scout import Ledger, Stop
import personal_live as live

class FakeAPI:
    def __init__(self, raw):
        self.raw=raw;self.budget_end=8;self.request_count=1;self.buys=[];self.before_write=None
        self.balances=iter([50000,20000]);self.reply={'message':'all listings purchased'}
    def available_balance(self): self.request_count+=1;return next(self.balances)
    def detail(self,lid): self.request_count+=1;return copy.deepcopy(self.raw)
    def buy(self,lid,price):
        if self.before_write:self.before_write()
        self.request_count+=1;self.buys.append((lid,price))
        if isinstance(self.reply,Exception):raise self.reply
        return self.reply

class LiveTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.old=os.getcwd();os.chdir(self.tmp.name)
        self.ledger=Ledger('personal.sqlite3');self.db=self.ledger.db
        self.raw=dict(id='123',price=30000,type='buy_now',state='listed',reference={'predicted_price':35000},item=dict(market_hash_name=live.NAME,float_value=.18,def_index=5030,paint_index=10045,asset_id='a'))
        self.api=FakeAPI(self.raw);self.c=dict(buy_fee_rate=0,extra_cost_cents=0)
        self.p=dict(_live=True,email_recipient='user1@example.com')
        self.mail=patch('email_alerts.send').start()
    def tearDown(self):
        patch.stopall();self.db.close();os.chdir(self.old);self.tmp.cleanup()
    def attempt(self):live.attempt(self.db,self.api,[self.raw],self.c,self.p,float('inf'))
    def test_success_locks_across_restart(self):
        self.attempt();self.assertEqual(live.status(self.db)['status'],'confirmed')
        self.assertEqual(len(self.api.buys),1);self.assertEqual(self.mail.call_count,1)
        self.db.close();self.ledger=Ledger('personal.sqlite3');self.db=self.ledger.db
        self.attempt();self.assertEqual(len(self.api.buys),1)
    def test_bounds_and_fee_cap(self):
        for f,price,ref,ok in [(.15,33000,40000,True),(.20,33000,40000,True),(.200001,30000,40000,False),(.1499,30000,40000,False),(.18,33001,40000,False),(.18,30000,33000,False),(.18,27000,30000,True),(.18,27001,30000,False)]:
            r=copy.deepcopy(self.raw);r['item']['float_value']=f;r['price']=price;r['reference']['predicted_price']=ref
            self.assertEqual(live.eligible(r,self.c),ok)
        r=copy.deepcopy(self.raw);r['price']=33000;self.assertFalse(live.eligible(r,dict(buy_fee_rate=.02,extra_cost_cents=0)))
    def test_unknown_never_retried(self):
        self.api.reply=Stop('timeout')
        with self.assertRaises(Stop):self.attempt()
        self.assertEqual(live.status(self.db)['status'],'unknown');self.attempt();self.assertEqual(len(self.api.buys),1)
    def test_acknowledged_debit_failure_locks(self):
        self.api.balances=iter([50000,50000])
        with self.assertRaises(Stop):self.attempt()
        self.assertEqual(live.status(self.db)['status'],'acknowledged');self.attempt();self.assertEqual(len(self.api.buys),1)
    def test_paper_no_write_and_insufficient_balance(self):
        self.p['_live']=False;self.attempt();self.assertFalse(self.api.buys)
        self.p['_live']=True;self.api.balances=iter([100]);self.attempt();self.assertFalse(self.api.buys);self.assertIsNone(live.status(self.db))
    def test_changed_item_price_or_sold(self):
        for kind in ('item','price','state'):
            self.api.raw=copy.deepcopy(self.raw)
            if kind=='item':self.api.raw['item']['asset_id']='other'
            if kind=='price':self.api.raw['price']+=1
            if kind=='state':self.api.raw['state']='sold'
            self.api.balances=iter([50000]);self.attempt();self.assertFalse(self.api.buys)
    def test_stop_and_expired_detail_before_write(self):
        Path('STOP').touch()
        with self.assertRaises(Stop):self.attempt()
        self.assertFalse(self.api.buys);self.assertIsNone(live.status(self.db));Path('STOP').unlink()
        self.api.balances=iter([50000])
        with patch('personal_live.time.time',side_effect=[100,161,161,161]):
            with self.assertRaises(Stop):self.attempt()
        self.assertFalse(self.api.buys);self.assertIsNone(live.status(self.db))
    def test_receipt_failure_saved(self):
        self.mail.side_effect=RuntimeError('smtp unavailable');self.attempt()
        self.assertEqual(live.status(self.db)['status'],'confirmed')
        self.assertEqual(self.db.execute('SELECT mailed FROM personal_live_order').fetchone()[0],0)
        self.db.execute('UPDATE personal_live_order SET mail_at=0');self.mail.side_effect=None
        live.flush_mail(self.db,self.p);self.assertEqual(self.db.execute('SELECT mailed FROM personal_live_order').fetchone()[0],1)
    def test_budget_respected(self):
        self.api.budget_end=4;self.attempt();self.assertFalse(self.api.buys)
