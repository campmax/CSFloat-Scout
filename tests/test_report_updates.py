import unittest,time,copy,json
from unittest.mock import patch
from listing_time import fields,describe
from personal_strategy import rank,queries
class ReportUpdates(unittest.TestCase):
    def row(self,i,f,d,price=30000,seen=None):
        return dict(id=i,name='Gloves (Field-Tested)',float=f,reference_discount=d,discount=.01,price_cents=price,total_cost_cents=price,last_seen=time.time() if seen is None else seen)
    def test_dates_and_unknown(self):
        self.assertEqual(fields('2026-01-01T01:00:00+01:00',1767229200)['listing_age_seconds'],3600)
        self.assertIn('1h',describe({'created_at':'2026-01-01T00:00:00Z'},1767229200))
        for v in (None,'bad','2026-01-01',True):self.assertIsNone(fields(v)['listing_age_seconds'])
    def test_near_boundary_preference_within_three_points(self):
        rows=[self.row('cheap',.27,.058,24700),self.row('near',.1515,.042,38100)]
        self.assertEqual(rank(rows,{})[0]['id'],'near')
        rows[0]['reference_discount']=.12
        self.assertEqual(rank(rows,{})[0]['id'],'cheap')
    def test_stale_and_old_price_versions_excluded(self):
        now=time.time();rows=[self.row('same',.2,.05,30000,now-10),self.row('same',.2,.04,31000,now),self.row('stale',.15,.5,20000,now-901)]
        got=rank(rows,{},now);self.assertEqual(len(got),1);self.assertEqual(got[0]['price_cents'],31000)
    def test_six_discovery_requests_cover_deals_newest_boundary(self):
        p=dict(names=['Gloves (Minimal Wear)','Gloves (Field-Tested)'],hard_max_price_cents=50000)
        got=list(queries(p,0));self.assertEqual(len(got),6)
        self.assertEqual(sum(x['sort_by']=='best_deal' for x in got),2)
        self.assertEqual(got[4]['max_float'],.2)
    def test_float_dominance_is_reported(self):
        got=rank([self.row('a',.16,.06,30000),self.row('b',.17,.05,31000)],{})
        self.assertEqual(next(r for r in got if r['id']=='b')['dominated_by'],['a'])

class PersonalCadence(unittest.TestCase):
    def test_change_alert_and_unchanged_five_minute_summary(self):
        import personal
        from unittest.mock import Mock
        state=dict(last_email=0,final_email=False,end=9999999999)
        config=dict(email_interval_seconds=300,email_recipient='user1@example.com')
        with patch('personal.ranked',return_value=[]),patch('personal.save'),patch('personal.email_alerts.send') as mail:
            with patch('personal.time.time',return_value=1000):personal.email_summary(Mock(),state,config,True)
            with patch('personal.time.time',return_value=1100):personal.email_summary(Mock(),state,config,True)
            self.assertEqual(mail.call_count,1)
            with patch('personal.time.time',return_value=1300):personal.email_summary(Mock(),state,config,True)
            self.assertEqual(mail.call_count,2)
