import importlib.util,sys,unittest,json
from pathlib import Path
from unittest.mock import patch
spec=importlib.util.spec_from_file_location('base_tests',Path(__file__).with_name('radar-tests.py'))
base=importlib.util.module_from_spec(spec);spec.loader.exec_module(base)
import radar,radar_minute
class MinuteTests(unittest.TestCase):
    setUp=base.RadarTests.setUp
    tearDown=base.RadarTests.tearDown
    row=base.RadarTests.row
    date=base.RadarTests.date
    history=base.RadarTests.history
    def update(self,offset=0,**kw):return radar_minute.send_update(self.db,self.c,self.now+offset,**kw)
    def test_empty_status_and_cooldown(self):
        with patch('radar_minute.email_alerts.send') as send:
            self.assertTrue(self.update(blocked_until=self.now+3600))
        self.assertIn('NO NEW REPORTABLE',send.call_args.args[1]);self.assertIn('API cooldown',send.call_args.args[1])
    def test_below_floor_and_negative_evidence_still_sent(self):
        self.history(price=1000);radar.ingest(self.db,[self.row(base=10001)],self.c,self.now)
        with patch('radar_minute.email_alerts.send') as send:self.update()
        self.assertIn('/1',send.call_args.args[1]);self.assertIn('break-even',send.call_args.args[1])
    def test_repeats_and_persisted_spacing(self):
        radar.ingest(self.db,[self.row()],self.c,self.now)
        with patch('radar_minute.email_alerts.send') as send:
            self.assertTrue(self.update());self.assertFalse(self.update(59));self.assertTrue(self.update(60))
        self.assertEqual(send.call_count,2);self.assertNotIn('/1',send.call_args.args[1])
    def test_stale_label(self):
        radar.ingest(self.db,[self.row()],self.c,self.now-601)
        with patch('radar_minute.email_alerts.send') as send:self.update()
        self.assertNotIn('/1',send.call_args.args[1])
    def test_unknown_reference_not_fabricated(self):
        row=self.row();row['reference']={};radar.ingest(self.db,[row],self.c,self.now)
        with patch('radar_minute.email_alerts.send') as send:self.update()
        self.assertNotIn('/1',send.call_args.args[1])
    def test_range_applied_before_limit(self):
        radar.ingest(self.db,[self.row(str(i),price=90000,base=900000) for i in range(3)]+[self.row('valid')],self.c,self.now)
        self.c['max_price_cents']=20000
        with patch('radar_minute.email_alerts.send') as send:self.update()
        self.assertIn('/valid',send.call_args.args[1]);self.assertNotIn('$900.00',send.call_args.args[1])
    def test_failure_bounded(self):
        with patch('radar_minute.email_alerts.send',side_effect=OSError()) as send:
            self.assertFalse(self.update());self.assertFalse(self.update(1));self.assertFalse(self.update(60))
        self.assertEqual(send.call_count,2)
    def test_no_email(self):
        self.c['email_enabled']=False
        with patch('radar_minute.email_alerts.send') as send:self.update()
        send.assert_not_called()
    def test_legacy_sender_disabled_in_minute_mode(self):
        self.c['minute_updates']=True;radar.ingest(self.db,[self.row()],self.c,self.now)
        with patch('radar.email_alerts.send') as send:radar.alerts(self.db,self.c,self.now)
        send.assert_not_called()
    def test_worker_reports_without_scanner(self):
        import threading
        db=radar.connect('worker.sqlite3');db.close();called=threading.Event()
        worker=radar_minute.MinuteReporter('worker.sqlite3',self.c,lambda:self.now+3600)
        with patch('radar_minute.email_alerts.send',side_effect=lambda *a:called.set()):
            worker.start()
            try:self.assertTrue(called.wait(3))
            finally:worker.stop()
        self.assertFalse(worker.thread.is_alive())
    def test_reobserved_id_stays_suppressed_and_drop_returns(self):
        radar.ingest(self.db,[self.row()],self.c,self.now)
        with patch('radar_minute.email_alerts.send') as send:
            self.update()
            radar.ingest(self.db,[self.row()],self.c,self.now+60);self.update(60)
            self.assertNotIn('/1',send.call_args.args[1])
            radar.ingest(self.db,[self.row()],self.c,self.now+120);self.update(120)
            self.assertNotIn('/1',send.call_args.args[1])
            radar.ingest(self.db,[self.row(price=9900)],self.c,self.now+180);self.update(180)
            self.assertIn('/1',send.call_args.args[1])
    def test_known_zero_recent_sales_excluded(self):
        self.history(age=90*86400);radar.ingest(self.db,[self.row()],self.c,self.now)
        with patch('radar_minute.email_alerts.send') as send:self.update()
        self.assertNotIn('/1',send.call_args.args[1])
    def test_sparse_unknown_excluded(self):
        row=self.row();row['reference']['quantity']=1;radar.ingest(self.db,[row],self.c,self.now)
        with patch('radar_minute.email_alerts.send') as send:self.update()
        self.assertNotIn('/1',send.call_args.args[1])
    def test_discovery_rotates_and_targets_cached_sales(self):
        from radar_discovery import queries
        self.history()
        first=list(queries(self.db,self.c,0,self.now));second=list(queries(self.db,self.c,1,self.now))
        self.assertEqual(first[0]['sort_by'],'most_recent')
        self.assertEqual(first[2]['market_hash_name'],self.row()['item']['market_hash_name'])
        self.assertNotEqual(first[1]['max_price'],second[1]['max_price'])
        self.assertLessEqual(len(first),3)
    def test_candidate_survives_gap_between_scans(self):
        radar.ingest(self.db,[self.row()],self.c,self.now-180)
        with patch('radar_minute.email_alerts.send') as send:self.update()
        self.assertIn('/1',send.call_args.args[1])
        self.assertIn('Listed:',send.call_args.args[1])
if __name__=='__main__':unittest.main()
