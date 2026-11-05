import unittest,tempfile,os,sqlite3,copy
from unittest.mock import Mock,patch
import personal_paper as pp
from scout import QuotaDeferred
class PersonalPaperTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:',isolation_level=None);self.tmp=tempfile.TemporaryDirectory();self.old=os.getcwd();os.chdir(self.tmp.name)
        self.p=dict(names=['Gloves (Field-Tested)'],hard_max_price_cents=50000,paper_buy_markdown=.09,email_recipient='user1@example.com')
        self.r=dict(id='1',type='buy_now',state='listed',price=27300,reference={'predicted_price':30000},item=dict(market_hash_name=self.p['names'][0],float_value=.3,def_index=1,paint_index=2),created_at='2026-01-01T00:00:00Z')
        self.api=Mock();self.api.detail.return_value=copy.deepcopy(self.r)
    def tearDown(self):self.db.close();os.chdir(self.old);self.tmp.cleanup()
    def get(self):return pp.report(self.db)['entries'][0]
    def test_threshold_and_single_paper_entry_no_buy(self):
        pp.observe(self.db,[self.r],self.p,1000);pp.verify(self.db,self.api,self.p,now=1015)
        self.assertEqual(self.get()['status'],'paper_bought');self.assertEqual(self.get()['discovery_to_check_seconds'],15)
        pp.observe(self.db,[self.r],self.p,1020);pp.verify(self.db,self.api,self.p,now=1025)
        self.assertEqual(self.api.detail.call_count,1);self.api.buy.assert_not_called()
    def test_below_threshold(self):
        self.r['price']=27400;pp.observe(self.db,[self.r],self.p,1000)
        self.assertFalse(pp.report(self.db)['entries'])
    def test_changed_or_sold_not_claimed_filled(self):
        pp.observe(self.db,[self.r],self.p,1000);self.api.detail.return_value['state']='sold'
        pp.verify(self.db,self.api,self.p,now=1015);self.assertEqual(self.get()['status'],'missed_or_changed')
    def test_deferred_retry_and_expiry(self):
        pp.observe(self.db,[self.r],self.p,1000);self.api.detail.side_effect=QuotaDeferred('wait')
        pp.verify(self.db,self.api,self.p,now=1015);self.assertEqual(self.get()['status'],'deferred')
        pp.verify(self.db,self.api,self.p,now=1700);self.assertEqual(self.get()['status'],'unverified_expired')
    def test_price_increase_and_reference_drop_disqualify(self):
        for change in ('price','reference'):
            self.db.execute('DROP TABLE IF EXISTS personal_paper');pp.observe(self.db,[self.r],self.p,1000)
            fresh=copy.deepcopy(self.r)
            if change=='price':fresh['price']+=1
            else:fresh['reference']['predicted_price']=29000
            self.api.detail.return_value=fresh;pp.verify(self.db,self.api,self.p,now=1015)
            self.assertEqual(self.get()['status'],'missed_or_changed')
    def test_email_once_and_no_email_mode(self):
        pp.observe(self.db,[self.r],self.p,1000);pp.verify(self.db,self.api,self.p,now=1015)
        with patch('email_alerts.send') as send:
            pp.flush_mail(self.db,self.p,False);send.assert_not_called()
            pp.flush_mail(self.db,self.p,True);pp.flush_mail(self.db,self.p,True)
            self.assertEqual(send.call_count,1);self.assertIn('NO REAL PURCHASE',send.call_args.args[1])
    def test_real_clock_records_request_latency(self):
        pp.observe(self.db,[self.r],self.p,1000)
        with patch('personal_paper.time.time',side_effect=[1000,1020]):pp.verify(self.db,self.api,self.p)
        self.assertEqual(self.get()['discovery_to_check_seconds'],20)
