import collections,json,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scout import Ledger
import scanner,scheduling
class SchedulingTests(unittest.TestCase):
    def setUp(self):
        self.ledger=Ledger(':memory:');self.db=self.ledger.db;scanner.init(self.db)
        self.addCleanup(self.db.close)
        self.c={'focus_watchlist':['Focus'],'evaluations_per_cycle':3}
    def add(self,lid,name,feed=None,added=1,score=.99):
        listing={'id':lid,'item':{'market_hash_name':name,'paint_index':1}}
        self.db.execute('INSERT INTO scan_items VALUES (?,?,?,?,?,?,?,?)',(lid,10000,'paper_review_v4','queued','',score,added,json.dumps(listing)))
        if feed:scheduling.tag(self.db,lid,10000,'paper_review_v4',feed)
        return listing
    def select(self,now=100):return scheduling.select(self.db,self.c,'paper_review_v4',collections.Counter(),now)
    def test_large_ranked_backlog_cannot_starve_other_feeds(self):
        for i in range(60):self.add(str(i),'Souvenir '+str(i),'deals')
        self.add('fresh','Fresh','newest',2,.06);self.add('focus','Focus','focus',2,.06)
        picked=self.select();self.assertEqual({x[3] for x in picked},{'newest','focus','deals'})
    def test_multiple_feed_tags_no_double_evaluation(self):
        self.add('one','Focus','deals');scheduling.tag(self.db,'one',10000,'paper_review_v4','newest')
        self.assertEqual(len(self.select()),1)
    def test_same_market_once_and_unused_slots_reallocated(self):
        self.add('a','Same','deals');self.add('b','Same','deals');self.add('c','Other','deals')
        self.assertEqual(len(self.select()),2)
    def test_empty_history_cooldown_expires_and_positive_evidence_resets(self):
        a=self.add('a','Same','deals');b=self.add('b','Same','deals')
        scheduling.observe(self.db,a,{'sales_count':0},100)
        scheduling.observe(self.db,b,{'sales_count':0},100)
        self.assertEqual(self.select(101),[])
        self.assertEqual(len(self.select(1901)),1)
        scheduling.observe(self.db,a,{'sales_count':1},102)
        self.assertEqual(len(self.select(103)),1)
    def test_old_queue_preserved_and_focus_inferred(self):
        self.add('a','Focus');self.add('b','Old')
        self.assertEqual({x[3] for x in self.select()},{'focus','deals'})
        self.assertEqual(self.db.execute("SELECT count(*) FROM scan_items WHERE state='queued'").fetchone()[0],2)
    def test_single_slot_rotates_across_feeds(self):
        self.c['evaluations_per_cycle']=1
        self.add('a','Focus','focus');self.add('b','Fresh','newest');self.add('c','Ranked','deals')
        self.assertEqual([self.select()[0][3] for _ in range(3)],['focus','newest','deals'])
    def test_api_error_does_not_penalize_market(self):
        a=self.add('a','Same','deals');scheduling.observe(self.db,a,{'reason':'API failed'},100)
        self.assertEqual(self.db.execute('SELECT count(*) FROM research_health').fetchone()[0],0)

    def test_observed_liquidity_prioritized_without_excluding_unknowns(self):
        now=1000000
        self.add('thin','Thin','newest',3);self.add('unknown','Unknown','newest',2)
        active=self.add('active','Active','newest',1)
        for name in ('Thin','Active'):
            key=json.dumps([name,1])
            self.db.execute('INSERT INTO evidence_cache VALUES (?,?,?)',('sales:'+key,now,'[]'))
        key=scheduling.market_key(active)
        for i in range(4):self.db.execute('INSERT INTO observed_sales VALUES (?,?,?,?)',(key,str(i),now-100,'{}'))
        self.assertEqual([x[0] for x in self.select(now)],['active','unknown','thin'])

    def test_slower_profile_migrates_old_settings_without_changing_live_config(self):
        c=scanner.defaults(json.loads((Path(__file__).resolve().parents[1]/'config.json').read_text()))
        c.update(request_interval_seconds=30,paper_requests_per_cycle=12,paper_research_limit=6)
        slow=scanner.paper_runtime_config(c)
        self.assertEqual(slow['request_interval_seconds'],15)
        self.assertEqual(slow['paper_requests_per_cycle'],8)
        self.assertEqual(slow['paper_research_limit'],3)
        self.assertEqual(c['request_interval_seconds'],30)

    def test_newest_priority_uses_post_time_not_time_old_page_was_fetched(self):
        self.c['evaluations_per_cycle']=1
        import datetime as dt
        for lid,added,posted in [('head',90,80),('old_page',99,20)]:
            item=self.add(lid,lid,'newest',added)
            item['created_at']=dt.datetime.fromtimestamp(posted,dt.timezone.utc).isoformat()
            self.db.execute('UPDATE scan_items SET payload=? WHERE id=?',(json.dumps(item),lid))
        self.assertEqual(self.select()[0][0],'head')

    def test_blocked_candidates_cannot_consume_research_slots(self):
        for i in range(10):self.add('blocked'+str(i),'Cold'+str(i),'newest',99)
        self.add('ready','Cached','deals',1)
        counts=collections.Counter()
        picked=scheduling.select(self.db,self.c,'paper_review_v4',counts,100,
                                 readiness=lambda x:3 if x['id']=='ready' else 0)
        self.assertEqual([x[0] for x in picked],['ready'])
        self.assertEqual(counts['queue:waiting_history'],10)

    def test_finish_pending_chart_before_starting_cold_market(self):
        self.c['evaluations_per_cycle']=3
        self.add('cold','Cold','focus',99);self.add('finish','Promising','newest',1)
        self.add('cached','Cached','deals',50)
        ranks={'cold':1,'finish':4,'cached':3}
        picked=scheduling.select(self.db,self.c,'paper_review_v4',collections.Counter(),100,
                                 readiness=lambda x:ranks[x['id']])
        self.assertEqual([x[0] for x in picked],['finish','cached'])

    def test_shared_cache_allows_multiple_listings_of_same_market(self):
        self.add('a','Same','newest',1);self.add('b','Same','newest',2)
        self.add('c','Other','newest',3)
        picked=scheduling.select(self.db,self.c,'paper_review_v4',collections.Counter(),100,readiness=lambda x:3)
        self.assertEqual(len(picked),3)
