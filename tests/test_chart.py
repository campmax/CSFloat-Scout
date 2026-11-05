import json
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scout import timestamp,evaluate,API
from risk import chart_trend,assess_chart
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
class ChartTests(unittest.TestCase):
    def setUp(self):
        self.chart=json.loads((ROOT/'tests/chart_fixture.json').read_text())
        self.c=json.loads((ROOT/'config.json').read_text())
        self.now=timestamp('2026-10-16T06:36:00Z')
    def test_uploaded_chart_weekly_decline(self):
        r=chart_trend(self.chart,self.now,self.c,timestamp)
        self.assertTrue(r['risk_ok'])
        self.assertAlmostEqual(r['weekly_change'],27720.344827586207/30996.16-1)
        self.assertEqual(r['latest_complete_day'],'2026-10-15')
    def test_partial_today_cannot_hide_crash(self):
        self.chart[0].update(avg_price=999999,count=10000)
        r=assess_chart(self.chart,self.now,30000,24000,self.c,timestamp)
        self.assertFalse(r['risk_ok'])
        self.assertIn('crash',r['risk_reason'])
    def test_missing_yesterday_rejected(self):
        self.chart=[x for x in self.chart if not x['day'].startswith('2026-10-15')]
        self.assertFalse(chart_trend(self.chart,self.now,self.c,timestamp)['risk_ok'])
    def test_bad_values_rejected(self):
        for bad in (float('nan'),-1,True):
            self.chart[1]['avg_price']=bad
            self.assertFalse(chart_trend(self.chart,self.now,self.c,timestamp)['risk_ok'])
    def test_duplicate_day_rejected(self):
        self.chart.append(self.chart[1])
        self.assertFalse(chart_trend(self.chart,self.now,self.c,timestamp)['risk_ok'])
    def test_insufficient_sales_on_baseline_rejected(self):
        self.chart[8]['count']=1
        self.assertFalse(chart_trend(self.chart,self.now,self.c,timestamp)['risk_ok'])
    def test_cache_separates_paint(self):
        api=API('fake',15)
        with patch.object(api,'call',return_value=self.chart) as call:
            api.graph('name',1);api.graph('name',1);api.graph('name',2)
            self.assertEqual(call.call_count,2)
    def test_chart_cannot_inflate_fair_value(self):
        f=json.loads((ROOT/'demo.json').read_text())
        # Full stable chart but inflated levels must never enter fair-value model.
        self.chart=[dict(x,avg_price=999999) for x in self.chart]
        f['now']=self.now
        f['candidate']['created_at']='2026-10-16T06:30:00Z'
        f['sales']=[dict(x,sold_at='2026-10-16T05:00:00Z') for x in f['sales'][:12]]
        r=evaluate(**f,config=self.c,chart=self.chart)
        self.assertTrue(r['eligible'])
        self.assertEqual(r['fair_cents'],30000)
    def test_chart_not_substitute_for_missing_comparable_sales(self):
        f=json.loads((ROOT/'demo.json').read_text());f['sales']=[]
        self.assertFalse(evaluate(**f,config=self.c,chart=self.chart)['eligible'])

if __name__=='__main__':unittest.main()
