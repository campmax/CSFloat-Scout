import copy,json,os,sqlite3,tempfile,time,unittest,urllib.request,urllib.error
from unittest.mock import patch
from scout import Ledger
from scanner import init
from shortlist import remember
import prospects

class ProspectTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.old=os.getcwd();os.chdir(self.tmp.name)
  self.ledger=Ledger('scout.sqlite3');self.db=self.ledger.db;init(self.db)
  self.c=dict(min_price_cents=2000,max_price_cents=None,buy_fee_rate=0,extra_cost_cents=0,email_enabled=True)
  self.raw=dict(id='123',state='listed',type='buy_now',price=10000,created_at='1970-01-01T00:01:00Z',reference={'predicted_price':12000},item={'market_hash_name':'Skin <script>','float_value':.16,'paint_seed':1})
 def tearDown(self):self.db.close();os.chdir(self.old);self.tmp.cleanup()
 def snap(self,r=None,when=1000):
  r=r or self.raw;self.db.execute('INSERT OR REPLACE INTO listing_snapshots VALUES(?,?,?,?)',(r['id'],r['price'],when,json.dumps(r)))
 def test_unresearched_visible_no_roi(self):
  self.snap();d=prospects.collect(self.db,self.c,1010);r=d['picks'][0]
  self.assertEqual(r['research'],'Awaiting research');self.assertIsNone(r['roi']);self.assertIn('1970',r['listed'])
 def test_expiry_and_latest_version_no_old_research(self):
  self.snap();remember(self.db,dict(id='123',price_cents=10000,estimated_net_cents=1000,time='2026-10-21T00:00:00Z'))
  self.assertAlmostEqual(prospects.collect(self.db,self.c,1010)['picks'][0]['roi'],.1)
  newer=copy.deepcopy(self.raw);newer['price']=11000;self.snap(newer,1020)
  rows=prospects.collect(self.db,self.c,1030)['picks'];self.assertEqual(len(rows),1);self.assertIsNone(rows[0]['roi'])
  self.assertFalse(prospects.collect(self.db,self.c,2000)['picks'])
 def test_sold_and_invalid_reference_excluded(self):
  self.raw['state']='sold';self.snap();self.assertFalse(prospects.collect(self.db,self.c,1010)['picks'])
  self.raw['state']='listed';self.raw['reference']={};self.snap();self.assertFalse(prospects.collect(self.db,self.c,1010)['picks'])
 def test_top20_and_email10(self):
  for i in range(25):
   r=copy.deepcopy(self.raw);r['id']=str(i);r['price']=10000+i;self.snap(r)
  data=prospects.collect(self.db,self.c,1010);self.assertEqual(len(data['picks']),20)
  self.assertEqual(prospects.email_text(data).count('https://csfloat.com/item/'),10)
 def test_thread_persisted_and_minute_throttle(self):
  self.snap();data=prospects.collect(self.db,self.c,1010)
  with patch('email_alerts.send') as send:
   self.assertTrue(prospects.send_digest(self.db,self.c,data,1010))
   self.assertFalse(prospects.send_digest(self.db,self.c,data,1030))
   self.assertTrue(prospects.send_digest(self.db,self.c,data,1070))
   first=send.call_args_list[0].kwargs['thread_headers'];second=send.call_args_list[1].kwargs['thread_headers']
   self.assertEqual(second['In-Reply-To'],first['Message-ID']);self.assertEqual(second['References'],first['Message-ID'])
 def test_email_failure_retries_once_next_minute(self):
  with patch('email_alerts.send',side_effect=RuntimeError('offline')) as send:
   data=prospects.collect(self.db,self.c,1000)
   prospects.send_digest(self.db,self.c,data,1000);prospects.send_digest(self.db,self.c,data,1005)
   self.assertEqual(send.call_count,1)
 def test_server_whitelist_and_no_purchase_endpoint(self):
  reporter=prospects.Reporter('scout.sqlite3',dict(self.c,email_enabled=False,prospects_port=0));reporter.start()
  try:
   url='http://127.0.0.1:'+str(reporter.server.server_port)
   self.assertIn(b'Current prospects',urllib.request.urlopen(url).read())
   self.assertIn('picks',json.load(urllib.request.urlopen(url+'/data.json')))
   for path in ('/config.json','/scout.sqlite3','/buy'):
    with self.assertRaises(urllib.error.HTTPError):urllib.request.urlopen(url+path)
  finally:reporter.stop()
