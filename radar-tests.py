import json,os,sys,tempfile,time,unittest,datetime
from pathlib import Path
from unittest.mock import patch,Mock
sys.path.insert(0,str(Path(__file__).resolve().parent))
fallback=Path(__file__).resolve().parent.parent/'CSFloat-Scout'
if fallback.exists():sys.path.append(str(fallback))
import radar

class RadarTests(unittest.TestCase):
    def setUp(self):
        self.old=os.getcwd();self.tmp=tempfile.TemporaryDirectory();os.chdir(self.tmp.name)
        self.db=radar.connect(':memory:');self.c=dict(radar.DEFAULTS,minute_updates=False);self.now=time.time()
    def tearDown(self):self.db.close();os.chdir(self.old);self.tmp.cleanup()
    def date(self,age=0):return datetime.datetime.fromtimestamp(self.now-age,datetime.timezone.utc).isoformat()
    def row(self,i='1',price=10000,base=15000,age=60):
        return dict(id=i,state='listed',type='buy_now',price=price,created_at=self.date(age),reference={'base_price':base,'quantity':5},item=dict(market_hash_name='AK-47 | Redline (Field-Tested)',def_index=7,paint_index=282,float_value=.2))
    def history(self,age=60,price=12000):
        sale=dict(self.row('sale',price=price),state='sold',sold_at=self.date(age))
        r=radar.lead(self.row(),self.c)
        self.db.execute('INSERT OR REPLACE INTO radar_history VALUES (?,?,?)',(radar.market(r),self.now,json.dumps([sale])))
    def alerts(self,offset=0):
        with patch('radar.time.time',return_value=self.now+offset):return radar.alerts(self.db,self.c,self.now+offset)
    def test_price_bounds(self):
        for price in (2000,100000):self.assertIsNotNone(radar.lead(self.row(price=price,base=200000),self.c))
        for price in (1999,100001):self.assertIsNone(radar.lead(self.row(price=price,base=200000),self.c))
    def test_uses_smaller_reference_discount(self):
        row=self.row();row['reference']['predicted_price']=20000
        r=radar.lead(row,self.c);self.assertAlmostEqual(r['discount'],1-10000/15000);self.assertEqual(r['discount_source'],'base_price')
        row['reference']['predicted_price']=11000;self.assertAlmostEqual(radar.lead(row,self.c)['discount'],1-10000/11000)
    def test_sparse_reference_is_warning_missing_base_is_skipped(self):
        for qty in (None,0,1,2):
            row=self.row();row['reference']['quantity']=qty;self.assertTrue(radar.lead(row,self.c)['reference_warning'])
        row=self.row();row['reference']={'predicted_price':20000,'quantity':20};self.assertIsNotNone(radar.lead(row,self.c))
    def test_unknown_new_listing_gets_labeled_longshot(self):
        radar.ingest(self.db,[self.row()],self.c,self.now)
        with patch('radar.email_alerts.send') as send:self.alerts()
        self.assertEqual(send.call_count,1);self.assertIn('[LONGSHOT]',send.call_args.args[0]);d=json.loads(Path('radar-best.json').read_text());self.assertEqual(len(d['leads']),1)
    def test_one_profitable_weekly_sale_is_enough(self):
        self.history(age=6*86400);radar.ingest(self.db,[self.row()],self.c,self.now)
        with patch('radar.email_alerts.send') as send:self.alerts()
        self.assertEqual(send.call_count,1);self.assertEqual(send.call_args.args[2],'user1@example.com')
    def test_three_month_old_sale_fails(self):
        self.history(age=90*86400);radar.ingest(self.db,[self.row()],self.c,self.now)
        with patch('radar.email_alerts.send') as send:self.alerts()
        send.assert_not_called()
    def test_recent_but_unprofitable_sale_fails(self):
        self.history(price=9000);radar.ingest(self.db,[self.row()],self.c,self.now)
        with patch('radar.email_alerts.send') as send:self.alerts()
        send.assert_not_called()
    def test_new_has_priority_over_larger_old_markdown(self):
        self.history(price=20000)
        radar.ingest(self.db,[self.row('old',base=30000,age=8000),self.row('new')],self.c,self.now)
        with patch('radar.email_alerts.send') as send:self.alerts()
        self.assertEqual(send.call_count,1);self.assertIn('/new',send.call_args.args[1])
    def test_spacing_and_hourly_cap_persist(self):
        self.history()
        with patch('radar.email_alerts.send') as send:
            for i in range(8):
                offset=i*301;radar.ingest(self.db,[self.row(str(i))],self.c,self.now+offset);self.alerts(offset)
            self.assertEqual(send.call_count,8)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM radar_delivery').fetchone()[0],8)
    def test_older_cap_two_per_hour(self):
        self.history()
        with patch('radar.email_alerts.send') as send:
            for i in range(4):
                radar.ingest(self.db,[self.row(str(i),age=100000)],self.c,self.now+i*301);self.alerts(i*301)
            self.assertEqual(send.call_count,2)
    def test_recent_reprice_of_old_listing_gets_new_priority(self):
        self.history();radar.ingest(self.db,[self.row('old',price=11000,age=90000)],self.c,self.now)
        radar.ingest(self.db,[self.row('old',price=10000,age=90000)],self.c,self.now+1)
        with patch('radar.email_alerts.send') as send:self.alerts(1)
        self.assertIn('NEW / RECENT PRICE DROP',send.call_args.args[1])
    def test_same_listing_deduplicated_after_spacing(self):
        self.history()
        with patch('radar.email_alerts.send') as send:
            for offset in (0,301):
                radar.ingest(self.db,[self.row()],self.c,self.now+offset);self.alerts(offset)
        self.assertEqual(send.call_count,1)
    def test_stale_observation_not_emailed(self):
        self.history();radar.ingest(self.db,[self.row()],self.c,self.now-301)
        with patch('radar.email_alerts.send') as send:self.alerts()
        send.assert_not_called()
    def test_sold_observation_removed(self):
        radar.ingest(self.db,[self.row()],self.c,self.now);radar.ingest(self.db,[dict(self.row(),state='sold')],self.c,self.now)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM radar_items').fetchone()[0],0)
    def test_read_only_enforced(self):
        api=radar.ReadOnlyAPI('test',15)
        for path,body in [('/listings/buy',{}),('/me',None),('/listings',{})]:
            with self.assertRaises(radar.Stop):api.call(path,body=body)
    def test_longshot_email_precedes_optional_history(self):
        api=Mock();api.request_count=0;api.policy.history_due.return_value=True
        api.listings.return_value={'data':[self.row()]};order=[]
        api.sales.side_effect=lambda *a:(order.append('history') or [dict(self.row('sale',price=12000),state='sold',sold_at=self.date())])
        with patch('radar.email_alerts.send',side_effect=lambda *a:order.append('email')):radar.cycle(api,self.db,self.c)
        self.assertEqual(order,['email','history']);self.assertEqual(api.listings.call_args_list[0].kwargs['sort_by'],'most_recent')
        api.buy.assert_not_called()
    def test_side_feed_throttled(self):
        api=Mock();api.request_count=0;api.policy.history_due.return_value=False;api.listings.return_value={'data':[]}
        self.db.execute("INSERT INTO radar_state VALUES ('last_ranked',?)",(int(self.now),))
        radar.cycle(api,self.db,self.c);self.assertEqual(api.listings.call_count,2)
    def test_failure_retries_without_claiming_delivery(self):
        self.history();radar.ingest(self.db,[self.row()],self.c,self.now)
        with patch('radar.email_alerts.send',side_effect=OSError()):self.alerts()
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM radar_delivery').fetchone()[0],0)
        radar.ingest(self.db,[self.row()],self.c,self.now+301)
        with patch('radar.email_alerts.send') as send:self.alerts(301)
        self.assertEqual(send.call_count,1)
    def test_config_migrates_original_burst_limit(self):
        Path('old.json').write_text(json.dumps(dict(emails_per_cycle=12)))
        c=radar.config('old.json');self.assertEqual(c['emails_per_cycle'],2);self.assertEqual(c['emails_per_hour'],8)

    def test_upgrade_preserves_sent_history_and_counts_recent_mail(self):
        db=radar.connect('old.sqlite3')
        db.execute("DELETE FROM radar_state WHERE key='policy_version'")
        db.execute("INSERT INTO radar_mail VALUES ('prior',10000,'sent',1,?)",(self.now,))
        db.close();db=radar.connect('old.sqlite3')
        try:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM radar_delivery').fetchone()[0],1)
            self.assertTrue(radar.already_sent(db,{'id':'prior','price_cents':10000}))
        finally:db.close()
        db=radar.connect('old.sqlite3')
        self.assertEqual(db.execute('SELECT COUNT(*) FROM radar_delivery').fetchone()[0],1);db.close()

    def test_only_four_longshots_per_hour(self):
        with patch('radar.email_alerts.send') as send:
            for i in range(7):
                offset=i*150;radar.ingest(self.db,[self.row(str(i))],self.c,self.now+offset);self.alerts(offset)
        self.assertEqual(send.call_count,4)
    def test_unknown_older_inventory_is_not_flooded(self):
        radar.ingest(self.db,[self.row(age=86400)],self.c,self.now)
        with patch('radar.email_alerts.send') as send:self.alerts()
        send.assert_not_called()
    def test_unknown_souvenir_is_report_only(self):
        row=self.row();row['item']['market_hash_name']='Souvenir AK-47 | Redline (Field-Tested)'
        radar.ingest(self.db,[row],self.c,self.now)
        with patch('radar.email_alerts.send') as send:self.alerts()
        send.assert_not_called()
    def test_recent_other_float_is_activity_not_local_support(self):
        self.history();raw=self.db.execute('SELECT payload FROM radar_history').fetchone()[0]
        sales=json.loads(raw);sales[0]['item']['float_value']=.32
        self.db.execute('UPDATE radar_history SET payload=?',(json.dumps(sales),))
        radar.ingest(self.db,[self.row()],self.c,self.now)
        with patch('radar.email_alerts.send') as send:leads,_,_=self.alerts()
        self.assertEqual(send.call_count,1);self.assertEqual(leads[0]['alert_tier'],'longshot')
        self.assertEqual(leads[0]['support']['sales'],0);self.assertEqual(leads[0]['support']['market_recent_sales'],1)
    def test_known_stale_finding_not_erased_by_cache_expiry(self):
        self.history(age=90*86400);radar.ingest(self.db,[self.row()],self.c,self.now)
        with patch('radar.email_alerts.send') as send:
            self.alerts();radar.ingest(self.db,[self.row()],self.c,self.now+3700);self.alerts(3700)
        send.assert_not_called()
    def test_adaptive_cutoff_cannot_be_dominated_by_outliers(self):
        radar.ingest(self.db,[self.row(base=50000)],self.c,self.now)
        self.assertEqual(radar.cutoff(self.db,self.c,self.now),.10)
    def test_spacing_reason_is_visible(self):
        self.history();radar.ingest(self.db,[self.row()],self.c,self.now)
        with patch('radar.email_alerts.send'):
            self.alerts();radar.ingest(self.db,[self.row('second')],self.c,self.now+1);self.alerts(1)
        d=json.loads(Path('radar-best.json').read_text())
        self.assertIn('email spacing',[r.get('delivery_status') for r in d['leads']])

if __name__=='__main__':unittest.main()
