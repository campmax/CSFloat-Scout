import json
from pathlib import Path
import tempfile
import unittest
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scout import parse_balance, affordable_price, purchase, Ledger, Stop, validate_config

ROOT=Path(__file__).resolve().parents[1]
class BalanceTests(unittest.TestCase):
    def setUp(self):
        self.c=json.loads((ROOT/'config.json').read_text())
    def test_pending_not_added(self):
        self.assertEqual(parse_balance({'user':{'balance':12345,'pending_balance':999999}}),12345)
    def test_missing_or_invalid_fails_closed(self):
        for value in ({}, {'balance':123}, {'user':{'balance':12.5}}, {'user':{'balance':True}}, {'user':{'balance':-1}}):
            with self.assertRaises(Stop):parse_balance(value)
    def test_no_fixed_ceiling_and_costs_included(self):
        self.c.update(buy_fee_rate=.02,extra_cost_cents=100)
        self.assertEqual(affordable_price(103000,self.c),100882)
        validate_config(self.c)
    def test_insufficient_balance_never_buys(self):
        class Fake:
            def available_balance(self):return 100
            def buy(self,*args):raise AssertionError('must not buy')
        with tempfile.TemporaryDirectory() as d:
            ledger=Ledger(str(Path(d)/'db'))
            with self.assertRaises(Stop):purchase(Fake(),ledger,{'id':'x','price':10000},self.c)
            self.assertEqual(ledger.db.execute('SELECT COUNT(*) FROM purchases').fetchone()[0],0)
    def test_unreconciled_debit_blocks_next_purchase(self):
        class Fake:
            def available_balance(self):return 100000
            def buy(self,*args):return {'message':'all listings purchased'}
        with tempfile.TemporaryDirectory() as d:
            ledger=Ledger(str(Path(d)/'db'))
            with self.assertRaises(Stop):purchase(Fake(),ledger,{'id':'x','price':10000},self.c)
            self.assertEqual(ledger.db.execute('SELECT status FROM purchases').fetchone()[0],'unknown')
    def test_existing_positions_do_not_double_subtract_balance(self):
        with tempfile.TemporaryDirectory() as d:
            ledger=Ledger(str(Path(d)/'db'))
            ledger.record_manual('old',200000)
            self.assertTrue(ledger.capacity(100000,self.c))

if __name__=='__main__':unittest.main()
