import copy
import json
from pathlib import Path
import tempfile
import unittest
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scout import evaluate, Ledger, purchase, Stop, validate_config, rows

ROOT = Path(__file__).resolve().parents[1]
class ScoutTests(unittest.TestCase):
    def setUp(self):
        self.c = json.loads((ROOT/'config.json').read_text())
        self.f = json.loads((ROOT/'demo.json').read_text())
        self.c.update(min_price_cents=5000,min_net_profit_cents=1000,min_stressed_profit_cents=500,max_purchases_per_day=1)
        for row in [self.f['candidate']]+self.f['asks']+self.f['sales']: row['price'] //= 3
        self.f['candidate']['reference']['base_price'] //= 3
    def result(self):
        return evaluate(**self.f, config=self.c)
    def test_real_discount(self):
        self.assertTrue(self.result()['eligible'])
    def test_inflated_reference_cannot_make_deal(self):
        self.f['candidate']['reference']['base_price'] = 1000000
        self.f['candidate']['price'] = 9900
        self.assertFalse(self.result()['eligible'])
    def test_expensive_sale_outlier(self):
        self.f['sales'][-1]['price'] = 1000000
        self.assertLess(self.result()['fair_cents'], 11000)
    def test_cheap_competitor_is_not_deleted(self):
        self.f['asks'][0]['price'] = 7000
        self.assertFalse(self.result()['eligible'])
    def test_duplicate_sales_not_volume(self):
        self.f['sales'] = [self.f['sales'][0]]*20
        self.assertFalse(self.result()['eligible'])
    def test_single_seller_not_depth(self):
        for a in self.f['asks']: a['seller']['steam_id'] = 'one'
        self.assertFalse(self.result()['eligible'])
    def test_stale_sales_rejected(self):
        for a in self.f['sales']: a['sold_at'] = '2020-01-01T00:00:00Z'
        self.assertFalse(self.result()['eligible'])
    def test_missing_metadata_rejected(self):
        for a in self.f['sales']: a.pop('item')
        self.assertFalse(self.result()['eligible'])
    def test_wrong_finish_rejected(self):
        for a in self.f['sales']: a['item']['paint_index'] = 999
        self.assertFalse(self.result()['eligible'])
    def test_extreme_discount_rejected(self):
        self.f['candidate']['price'] = 5000
        self.assertFalse(self.result()['eligible'])
    def test_recent_crash_rejected(self):
        for a in self.f['sales'][:3]: a['price'] = 6500
        self.assertFalse(self.result()['eligible'])
    def test_invalid_config(self):
        self.c['min_discount'] = float('nan')
        with self.assertRaises(Stop): validate_config(self.c)
    def test_unknown_response_rejected(self):
        with self.assertRaises(Stop): rows({'something': []})
    def test_budget_persists(self):
        with tempfile.TemporaryDirectory() as d:
            path = str(Path(d)/'ledger.db')
            ledger = Ledger(path)
            ledger.reserve(self.f['candidate'], self.c)
            ledger.confirm(self.f['candidate']['id'])
            other = copy.deepcopy(self.f['candidate']); other['id']='other'
            with self.assertRaises(Stop): Ledger(path).reserve(other,self.c)
    def test_timeout_never_retried_and_blocks_next_buy(self):
        class Fake:
            calls=0
            def available_balance(self): return 100000
            def buy(self,*args):
                self.calls+=1
                raise Stop('timeout')
        with tempfile.TemporaryDirectory() as d:
            ledger=Ledger(str(Path(d)/'ledger.db')); api=Fake()
            with self.assertRaises(Stop): purchase(api,ledger,self.f['candidate'],self.c)
            with self.assertRaises(Stop): purchase(api,ledger,self.f['candidate'],self.c)
            self.assertEqual(api.calls,1)
    def test_acknowledged_purchase(self):
        class Fake:
            balances=iter([100000,92000])
            def available_balance(self): return next(self.balances)
            def buy(self,*args): return {'message':'all listings purchased'}
        with tempfile.TemporaryDirectory() as d:
            ledger=Ledger(str(Path(d)/'ledger.db'))
            purchase(Fake(),ledger,self.f['candidate'],self.c)
            self.assertEqual(ledger.db.execute('SELECT status FROM purchases').fetchone()[0],'confirmed')

if __name__=='__main__': unittest.main()
