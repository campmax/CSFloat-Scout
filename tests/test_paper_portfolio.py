import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch,Mock
from collections import Counter
from scout import Ledger,timestamp
from scanner import defaults,init,profile,ingest,queue_mode,evaluate_queue
import paper_portfolio as pp

ROOT=Path(__file__).resolve().parents[1]

class PaperPortfolioTests(unittest.TestCase):
    def setUp(self):
        self.old=os.getcwd();self.tmp=tempfile.TemporaryDirectory();os.chdir(self.tmp.name)
        self.c=defaults(json.loads((ROOT/'config.json').read_text()));self.c['email_enabled']=False
        self.now=timestamp('2026-10-20T12:00:00Z');self.db=Ledger(':memory:').db;init(self.db)
        self.item=dict(market_hash_name='AK-47 | Redline (Field-Tested)',def_index=7,paint_index=282,float_value=.20)
        self.candidate=dict(id='target',price=10000,state='listed',type='buy_now',item=self.item,created_at='2026-10-20T11:59:00Z',reference={'base_price':13000})
        self.sales=[dict(id=str(i),state='sold',price=12000,item=dict(self.item,float_value=.20+i*.0005),sold_at=f'2026-10-{19-i%3:02}T12:00:00Z') for i in range(6)]
        self.asks=[dict(self.candidate,id='competitor',price=12000)]
    def tearDown(self):
        self.db.close();os.chdir(self.old);self.tmp.cleanup()
    def assessment(self):return pp.assess(self.candidate,self.asks,self.sales,self.c,self.now)
    def record(self,lid='target'):
        return dict(id=lid,name=self.item['market_hash_name'],price_cents=10000,eligible=True,url='https://csfloat.com/item/'+lid,time='2026-10-20T12:00:00Z',paper_item=self.item,paper_purchase=self.assessment(),paper_history_age_seconds=10,paper_competition_age_seconds=10)
    def test_supported_buy_nets_fees_and_stress(self):
        r=self.assessment();self.assertEqual(r['status'],'paper_buy_candidate');self.assertEqual(r['direct_sales'],6)
        self.assertEqual(r['adjusted_sales'],0);self.assertEqual(r['competitive_resale_cents'],11999)
        self.assertEqual(r['estimated_net_cents'],int(11999*.98*.99)-10000)
        self.assertGreater(r['stressed_net_cents'],0);self.assertFalse(r['weekly_trend_verified'])
    def test_cheap_ask_caps_exit_even_when_median_profitable(self):
        self.asks[0]['price']=10100;r=self.assessment();self.assertEqual(r['status'],'watch');self.assertLess(r['estimated_net_cents'],0)
        self.assertGreater(r['patient_net_cents'],0)
    def test_missing_competition_never_certifies_buy(self):
        self.asks=[];self.assertEqual(self.assessment()['status'],'watch')
    def test_near_fn_boundary_cannot_use_whole_fn_range(self):
        item=dict(self.item,market_hash_name='Gloves (Factory New)',float_value=.0699)
        self.candidate['item']=item
        for s in self.sales:s['item']=dict(item,float_value=.02)
        self.assertLess(pp.direct_tolerance(item),.001)
        self.assertEqual(self.assessment()['direct_sales'],0);self.assertEqual(self.assessment()['status'],'watch')
    def test_ultralow_float_is_separate_from_ordinary_fn(self):
        item=dict(self.item,market_hash_name='Rifle (Factory New)',float_value=.0002)
        self.assertLess(pp.direct_tolerance(item),.001)
    def test_exact_local_thin_sample_not_disguised_as_liquid(self):
        self.sales=self.sales[:1];r=self.assessment();self.assertEqual(r['status'],'watch');self.assertEqual(r['direct_sales'],1)
    def test_pattern_sensitive_is_watch_even_if_profitable(self):
        self.c['exclude_name_contains']=['Redline'];self.assertEqual(self.assessment()['status'],'watch')
    def test_duplicate_and_old_sales_do_not_inflate_liquidity(self):
        self.sales=self.sales[:1]*5+[dict(self.sales[1],sold_at='2026-09-20T12:00:00Z')]
        self.assertEqual(self.assessment()['direct_sales'],1)
    def test_wallet_debits_once_across_reopen_and_price_changes(self):
        r=self.record();out=pp.consider(self.db,r,self.c,self.now,self.now)
        self.assertEqual(out['status'],'paper_bought');self.assertIsNone(pp.consider(self.db,r,self.c,self.now,self.now))
        r['price_cents']=9000;self.assertEqual(pp.consider(self.db,r,self.c,self.now,self.now)['status'],'already_owned')
        pp.init(self.db,dict(self.c,paper_portfolio=dict(initial_cash_cents=999999)))
        self.assertEqual(self.db.execute('SELECT cash FROM paper_wallet').fetchone()[0],90000)
    def test_cash_limit_no_overdraft(self):
        self.c['paper_portfolio']['initial_cash_cents']=5000
        self.assertEqual(pp.consider(self.db,self.record(),self.c,self.now,self.now)['status'],'insufficient_virtual_cash')
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM paper_positions').fetchone()[0],0)
    def test_stale_or_missing_confirmation_is_missed_fill(self):
        for lid,confirm in [('a',None),('b',self.now-31)]:
            self.assertEqual(pp.consider(self.db,self.record(lid),self.c,confirm,self.now)['status'],'missed_fill')
    def test_changed_listing_never_buys(self):
        r=self.record();r['eligible']=False
        self.assertEqual(pp.consider(self.db,r,self.c,self.now,self.now)['status'],'missed_fill')
    def test_old_or_missing_evidence_cannot_buy(self):
        for i,(key,value) in enumerate([('paper_history_age_seconds',4000),('paper_competition_age_seconds',121),('paper_history_age_seconds',None)]):
            r=self.record(str(i));r[key]=value
            self.assertEqual(pp.consider(self.db,r,self.c,self.now,self.now)['status'],'watch')
    def test_unlock_does_not_release_cash_and_sale_waits_settlement(self):
        pp.consider(self.db,self.record(),self.c,self.now,self.now)
        with self.assertRaises(ValueError):pp.record_sale(self.db,self.c,'target',12000,self.now+1)
        unlocked=self.now+7*86400
        pp.tick(self.db,self.c,unlocked)
        self.assertEqual(self.db.execute('SELECT cash FROM paper_wallet').fetchone()[0],90000)
        pp.record_sale(self.db,self.c,'target',12000,unlocked)
        pp.tick(self.db,self.c,unlocked+8*86400-1)
        self.assertEqual(self.db.execute('SELECT cash FROM paper_wallet').fetchone()[0],90000)
        data=pp.tick(self.db,self.c,unlocked+8*86400)
        self.assertEqual(data['available_cash_cents'],101760);self.assertEqual(data['realized_simulated_net_cents'],1760)
        pp.tick(self.db,self.c,unlocked+9*86400)
        self.assertEqual(self.db.execute('SELECT cash FROM paper_wallet').fetchone()[0],101760)
        with self.assertRaises(ValueError):pp.record_sale(self.db,self.c,'target',12000,unlocked+9*86400)
    def test_buy_receipt_retries_and_deduplicates_without_another_buy(self):
        pp.consider(self.db,self.record(),self.c,self.now,self.now);self.c['email_enabled']=True
        with patch('email_alerts.send',side_effect=OSError()):pp.tick(self.db,self.c,self.now)
        with patch('email_alerts.send') as send:
            pp.tick(self.db,self.c,self.now+1);self.assertEqual(send.call_count,0)
            pp.tick(self.db,self.c,self.now+301);pp.tick(self.db,self.c,self.now+700)
            self.assertEqual(send.call_count,1);self.assertEqual(send.call_args.args[2],'user1@example.com')
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM paper_positions').fetchone()[0],1)
    def test_atomic_rollback_no_cash_loss_on_insert_error(self):
        pp.init(self.db,self.c)
        self.db.execute("CREATE TRIGGER fail_position BEFORE INSERT ON paper_positions BEGIN SELECT RAISE(ABORT,'test'); END")
        with self.assertRaises(Exception):pp.consider(self.db,self.record(),self.c,self.now,self.now)
        self.assertEqual(self.db.execute('SELECT cash FROM paper_wallet').fetchone()[0],100000)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM paper_decisions').fetchone()[0],0)
    def test_weekly_decline_stresses_estimate_when_coverage_exists(self):
        self.sales=[]
        for i in range(7):
            self.sales.append(dict(id=str(i),state='sold',price=12000+i*500,item=self.item,sold_at=f'2026-10-{19-i:02}T12:00:00Z'))
        r=self.assessment();self.assertTrue(r['weekly_trend_verified']);self.assertLess(r['weekly_change_estimate'],0)
        self.assertGreater(r['stress_drop'],.03)
    def test_report_distinguishes_ranking_from_prospective_positions(self):
        pp.consider(self.db,self.record(),self.c,self.now,self.now)
        data=pp.tick(self.db,self.c,self.now)
        self.assertEqual(len(data['positions']),1)
        self.assertEqual(len(data['retrospective_best_observed_24h']),1)
        self.assertIn('NOT historical buys',Path('paper-portfolio.html').read_text())
    def test_scanner_integration_no_purchase_or_balance_calls(self):
        ledger=Mock(db=self.db);api=Mock();api.detail.return_value=self.candidate
        api.sales.return_value=self.sales;api.listings.return_value={'data':self.asks};api.graph.return_value=[]
        effective,_=profile(self.c,False);counts=Counter()
        with patch('scanner.time.time',return_value=self.now),patch('scout.purchase') as buy:
            ingest(self.db,[self.candidate],effective,queue_mode(self.c,False),counts)
            evaluate_queue(api,ledger,self.c,False,counts)
            buy.assert_not_called();api.available_balance.assert_not_called()
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM paper_positions').fetchone()[0],1)
        self.assertEqual(counts['paper_purchase:paper_bought'],1)

    def test_nonlinear_ask_normalization_uses_sales_model(self):
        from test_float_model import sample
        self.sales=sample()
        self.now=timestamp('2026-10-17T12:00:00Z')
        self.asks=[dict(self.candidate,id='other-float',price=20000,item=dict(self.item,float_value=.24))]
        r=self.assessment()
        self.assertGreater(r['adjusted_sales'],0)
        self.assertEqual(r['comparable_asks'][0]['method'],'float_adjusted_lower_scenario')
        self.assertNotEqual(r['comparable_asks'][0]['equivalent_price_cents'],20000)
        self.assertGreater(r['direct_sales'],0)
    def test_final_sold_response_records_missed_fill(self):
        ledger=Mock(db=self.db);api=Mock();api.detail.side_effect=[self.candidate,dict(self.candidate,state='sold')]
        api.sales.return_value=self.sales;api.listings.return_value={'data':self.asks};api.graph.return_value=[]
        effective,_=profile(self.c,False);counts=Counter()
        with patch('scanner.time.time',return_value=self.now):
            ingest(self.db,[self.candidate],effective,queue_mode(self.c,False),counts)
            evaluate_queue(api,ledger,self.c,False,counts)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM paper_positions').fetchone()[0],0)
        self.assertEqual(counts['paper_purchase:missed_fill'],1)
    def test_final_float_change_records_missed_fill(self):
        ledger=Mock(db=self.db);api=Mock()
        api.detail.side_effect=[self.candidate,dict(self.candidate,item=dict(self.item,float_value=.32))]
        api.sales.return_value=self.sales;api.listings.return_value={'data':self.asks};api.graph.return_value=[]
        effective,_=profile(self.c,False);counts=Counter()
        with patch('scanner.time.time',return_value=self.now):
            ingest(self.db,[self.candidate],effective,queue_mode(self.c,False),counts)
            evaluate_queue(api,ledger,self.c,False,counts)
        self.assertEqual(counts['paper_purchase:missed_fill'],1)
    def test_real_database_reopen_preserves_cash_and_dedup(self):
        db=Ledger('restart.sqlite3').db
        pp.consider(db,self.record(),self.c,self.now,self.now);db.close()
        db=Ledger('restart.sqlite3').db
        try:
            self.assertIsNone(pp.consider(db,self.record(),self.c,self.now,self.now+10))
            self.assertEqual(db.execute('SELECT cash FROM paper_wallet').fetchone()[0],90000)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM paper_mail').fetchone()[0],1)
        finally:db.close()
    def test_thin_local_market_cools_down_without_globally_blocking(self):
        import scheduling
        r={'sales_count':50,'paper_purchase':{'direct_sales':0,'direct_recent_sales':0}}
        scheduling.observe(self.db,self.candidate,r,self.now)
        scheduling.observe(self.db,dict(self.candidate,id='second'),r,self.now)
        self.assertGreater(self.db.execute('SELECT cooldown_until FROM research_health').fetchone()[0],self.now)
        scheduling.observe(self.db,self.candidate,{'sales_count':3,'paper_purchase':{'direct_sales':3,'direct_recent_sales':1}},self.now+1)
        self.assertEqual(self.db.execute('SELECT cooldown_until FROM research_health').fetchone()[0],0)
    def test_exit_evidence_never_automatically_realizes_profit(self):
        pp.consider(self.db,self.record(),self.c,self.now,self.now)
        future=self.now+8*86400
        rows=[dict(s,sold_at='2026-10-28T11:00:00Z') for s in self.sales]
        key='sales:'+json.dumps([self.item['market_hash_name'],self.item['paint_index']])
        self.db.execute('INSERT INTO evidence_cache VALUES (?,?,?)',(key,future,json.dumps(rows)))
        data=pp.tick(self.db,self.c,future)
        self.assertEqual(data['positions'][0]['mark']['post_unlock_comparable_sales'],6)
        self.assertEqual(data['positions'][0]['status'],'held')
        self.assertEqual(data['available_cash_cents'],90000)
        self.assertEqual(data['realized_simulated_net_cents'],0)

    def test_watch_can_be_promoted_by_new_fresh_evidence(self):
        r=self.record();r['paper_purchase']['status']='watch';r['paper_purchase']['reasons']=['thin earlier']
        self.assertEqual(pp.consider(self.db,r,self.c,self.now,self.now)['status'],'watch')
        self.assertEqual(pp.consider(self.db,self.record(),self.c,self.now+60,self.now+60)['status'],'paper_bought')
        self.assertEqual(self.db.execute('SELECT cash FROM paper_wallet').fetchone()[0],90000)

if __name__=='__main__':unittest.main()
