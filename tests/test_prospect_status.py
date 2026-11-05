import copy,json,os,tempfile,unittest,collections
from unittest.mock import Mock
from scout import Ledger,Stop,QuotaDeferred,RateLimitStop
import prospect_status as ps

class StatusTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.old=os.getcwd();os.chdir(self.tmp.name);self.ledger=Ledger('scout.sqlite3');self.db=self.ledger.db
  self.row=dict(id='1',name='Knife',price_cents=10000,markdown=.12,url='https://csfloat.com/item/1',float=.01,last_seen=ps.stamp(1000))
  self.data=dict(picks=[self.row],observed_candidates=1);ps.enrich(self.db,copy.deepcopy(self.data),1000)
 def tearDown(self):self.db.close();os.chdir(self.old);self.tmp.cleanup()
 def details(self,state='sold',**kwargs):return dict(id='1',state=state,**kwargs)
 def test_first_probe_due_after_minute(self):
  api=Mock(request_count=0,budget_end=8);api.detail.return_value=self.details('listed')
  counts=collections.Counter();ps.probe(api,self.db,counts,1059);api.detail.assert_not_called()
  ps.probe(api,self.db,counts,1060);api.detail.assert_called_once_with('1');self.assertEqual(counts['availability_probes'],1)
 def test_confirmed_sale_held_and_archived_at_15_minutes(self):
  ps.observe_detail(self.db,'1',self.details(),1100)
  candidate=dict(self.row,id='2',markdown=.2)
  data=ps.enrich(self.db,dict(picks=[candidate],observed_candidates=1),1999)
  self.assertEqual(data['picks'][0]['id'],'1');self.assertEqual(data['picks'][0]['availability_status'],'sold')
  self.assertFalse(data['graveyard'][0]['void']);self.assertEqual(data['graveyard'][0]['markdown_value_cents'],1200)
  data=ps.enrich(self.db,dict(picks=[candidate],observed_candidates=1),2000)
  self.assertEqual([r['id'] for r in data['picks']],['2']);self.assertTrue(data['graveyard'][0]['void'])
 def test_disappearance_is_not_a_sale(self):
  ps.observe_detail(self.db,'1',self.details('cancelled'),1100)
  data=ps.enrich(self.db,copy.deepcopy(self.data),1101)
  self.assertEqual(data['picks'][0]['availability_status'],'unavailable');self.assertFalse(data['graveyard'])
 def test_error_not_sold_and_retry_not_immediate(self):
  api=Mock(request_count=0,budget_end=8);api.detail.side_effect=Stop('404')
  ps.probe(api,self.db,collections.Counter(),1060);ps.probe(api,self.db,collections.Counter(),1120)
  self.assertEqual(api.detail.call_count,1);self.assertIsNone(self.db.execute('SELECT sold_detected FROM prospect_status').fetchone()[0])
 def test_budget_quota_and_rate_limit(self):
  api=Mock(request_count=8,budget_end=8);ps.probe(api,self.db,collections.Counter(),1060);api.detail.assert_not_called()
  api.request_count=0;api.detail.side_effect=QuotaDeferred('wait');ps.probe(api,self.db,collections.Counter(),1060)
  self.assertEqual(self.db.execute('SELECT last_probe FROM prospect_status').fetchone()[0],0)
  api.detail.side_effect=RateLimitStop('429')
  with self.assertRaises(RateLimitStop):ps.probe(api,self.db,collections.Counter(),1070)
 def test_bad_sold_timestamp_not_exact_sale_time(self):
  ps.observe_detail(self.db,'1',self.details(sold_at=ps.stamp(900)),1100)
  row=ps.enrich(self.db,dict(picks=[],observed_candidates=0),1101)['graveyard'][0]
  self.assertIsNone(row['sold_at']);self.assertEqual(row['sale_window_seconds'],100)
 def test_wrong_listing_response_rejected(self):
  ps.observe_detail(self.db,'1',dict(id='2',state='sold'),1100)
  self.assertFalse(ps.enrich(self.db,copy.deepcopy(self.data),1101)['graveyard'])
 def test_archive_survives_restart(self):
  ps.observe_detail(self.db,'1',self.details(),1100);self.db.close();self.ledger=Ledger('scout.sqlite3');self.db=self.ledger.db
  data=ps.enrich(self.db,dict(picks=[],observed_candidates=0),5000)
  self.assertEqual(data['graveyard'][0]['url'],self.row['url']);self.assertFalse(data['picks'])
