import json,os,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from scout import Ledger
from scanner import init
import hourly

class HourlyTests(unittest.TestCase):
    def setUp(self):
        self.old=os.getcwd();self.tmp=tempfile.TemporaryDirectory();os.chdir(self.tmp.name)
        self.db=Ledger(':memory:').db;init(self.db)
        self.c={'email_enabled':True}
    def tearDown(self):self.db.close();os.chdir(self.old);self.tmp.cleanup()
    def row(self,i,net=500):return dict(id=str(i),price_cents=10000,estimated_net_cents=net,sales_count=3,recent_sales_count=2,recent_sales_above_break_even=2,discount=.1,eligible=True,name='Item',reason='manual review',url='https://csfloat.com/item/'+str(i))
    def test_top_five_and_baseline_persist(self):
        with patch('hourly.email_alerts.send') as send:
            hourly.tick(self.db,self.c,1000)
            for i in range(8):hourly.remember(self.db,self.row(i,100+i*100),{'email_enabled':False},1100)
            hourly.tick(self.db,self.c,4600)
        self.assertEqual(send.call_count,1)
        data=json.loads(Path('hourly-best.json').read_text());self.assertEqual(len(data['supported']),5)
        self.assertEqual(data['supported'][0]['id'],'7')
        self.assertEqual(hourly.state(self.db,4600)['cutoff'],4)
    def test_all_eligible_alert_immediately_without_baseline_or_cap(self):
        hourly.save(self.db,hourly.state(self.db,1000))
        s=hourly.state(self.db,1000);s['cutoff']=None;hourly.save(self.db,s)
        with patch('hourly.email_alerts.send') as send:
            for i in range(6):hourly.remember(self.db,self.row(i),self.c,1100)
        self.assertEqual(send.call_count,6)
        self.assertTrue(all(x.args[2]=='user1@example.com' for x in send.call_args_list))
    def test_missing_evidence_is_provisional_not_supported(self):
        r=self.row(1);r['sales_count']=0
        with patch('hourly.email_alerts.send'):
            hourly.remember(self.db,r,self.c,1000);hourly.tick(self.db,self.c,1001)
        data=json.loads(Path('hourly-best.json').read_text())
        self.assertEqual(data['supported'],[]);self.assertEqual(len(data['provisional']),1)
    def test_empty_hour_emails_status_without_inventing_results(self):
        with patch('hourly.email_alerts.send') as send:
            hourly.tick(self.db,self.c,1000);hourly.tick(self.db,self.c,4600)
        self.assertEqual(send.call_count,1);self.assertIn('No fresh observations',send.call_args.args[1])
    def test_smtp_failure_retries_without_changing_baseline(self):
        with patch('hourly.email_alerts.send',side_effect=OSError()) as send:
            hourly.tick(self.db,self.c,1000);hourly.tick(self.db,self.c,4600);hourly.tick(self.db,self.c,4700)
        self.assertEqual(send.call_count,1);self.assertEqual(hourly.state(self.db,4700)['start'],1000)
    def test_duplicate_and_higher_price_suppressed_lower_price_alerts(self):
        with patch('hourly.email_alerts.send') as send:
            r=self.row(1);hourly.remember(self.db,r,self.c,1000)
            hourly.remember(self.db,r,self.c,5000)
            r['price_cents']=11000;hourly.remember(self.db,r,self.c,5100)
            r['price_cents']=9900;hourly.remember(self.db,r,self.c,5200)
        self.assertEqual(send.call_count,2)
    def test_retry_requires_eligible_fresh_record_and_is_bounded(self):
        with patch('hourly.email_alerts.send',side_effect=OSError()) as send:
            r=self.row(1)
            hourly.remember(self.db,r,self.c,1000)
            hourly.remember(self.db,r,self.c,1050)
            r['eligible']=False;hourly.remember(self.db,r,self.c,1300)
            r['eligible']=True
            for now in (1301,1602,1903):hourly.remember(self.db,r,self.c,now)
        self.assertEqual(send.call_count,3)
