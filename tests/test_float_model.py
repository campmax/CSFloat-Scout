import copy
import math
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from float_model import FloatModel
from scout import timestamp


def sample(curve=lambda f: 30000*math.exp(-3*f+4*f*f)):
    return [dict(id=f'{day}-{i}',state='sold',price=round(curve(f)),
                 sold_at=f'2026-10-{day:02d}T12:00:00Z',
                 item=dict(float_value=f,market_hash_name='AK-47 | Redline (Field-Tested)',def_index=7,paint_index=282))
            for day in (14,15,16) for i in range(21) for f in [.16+i*.01]]


class FloatModelTests(unittest.TestCase):
    def test_nonlinear_relative_prices_and_independent_adjustment(self):
        rows=sample();model=FloatModel(rows,.20,timestamp)
        self.assertEqual(model.info['status'],'available')
        row=rows[12]
        result,reason=model.adjust(row)
        self.assertIsNone(reason)
        expected=math.exp((-3*.20+4*.20**2)-(-3*.28+4*.28**2))
        self.assertAlmostEqual(result['ratio'],expected,delta=.015)
        self.assertLessEqual(abs(result['adjusted_price_cents']-row['price']*result['ratio']),1)
        self.assertLess(result['uncertainty_price_cents'],result['adjusted_price_cents'])

        changed=dict(row,price=row['price']*3)
        altered,_=model.adjust(changed)
        self.assertEqual(result['ratio'],altered['ratio'])

    def test_nonmonotonic_curve_allowed(self):
        model=FloatModel(sample(lambda f:30000*math.exp(8*(f-.25)**2)),.25,timestamp)
        self.assertEqual(model.info['status'],'available')
        result,_=model.adjust(sample()[2])
        self.assertLess(result['ratio'],1)

    def test_logarithmic_float_curve(self):
        rows=sample(lambda f:30000*(1-.4*math.log(f/.16)))
        model=FloatModel(rows,.20,timestamp)
        self.assertEqual(model.info['status'],'available')
        result,_=model.adjust(rows[12])
        expected=(1-.4*math.log(.20/.16))/(1-.4*math.log(.28/.16))
        self.assertAlmostEqual(result['ratio'],expected,delta=.02)

    def test_steep_discontinuity_not_silently_smoothed(self):
        rows=sample(lambda f:30000 if f<.25 else 60000)
        model=FloatModel(rows,.245,timestamp)
        adjusted,_=model.adjust(rows[12])
        self.assertIsNone(adjusted)

    def test_sparse_extrapolation_and_pattern_refusal(self):
        rows=sample()
        for model in (FloatModel(rows[:8],.20,timestamp),FloatModel(rows,.5,timestamp),
                      FloatModel(rows,.20,timestamp,blocked=True)):
            self.assertEqual(model.info['status'],'unavailable')
            self.assertIsNone(model.adjust(rows[0])[0])

    def test_confounded_time_float_refused(self):
        rows=sample()
        for r in rows:
            day=int(r['sold_at'][8:10]);f=r['item']['float_value']
            r['item']['float_value']=f+(day-14)*.3
        model=FloatModel(rows,.20,timestamp)
        self.assertEqual(model.info['status'],'unavailable')

    def test_large_time_shift_fails_held_out_dates(self):
        rows=sample()
        for r in rows:
            if r['sold_at'][8:10]=='16':r['price']*=2
        model=FloatModel(rows,.20,timestamp)
        self.assertEqual(model.info['status'],'unavailable')

    def test_noisy_market_refused(self):
        rows=sample()
        for i,r in enumerate(rows):r['price']=int(r['price']*(1.7 if i%2 else .6))
        self.assertEqual(FloatModel(rows,.20,timestamp).info['status'],'unavailable')

    def test_collect_preserves_input_and_recovers_distant_sales(self):
        from review import collect_sales
        from scanner import defaults
        import json
        c=defaults(json.loads((Path(__file__).resolve().parents[1]/'config.json').read_text()))
        rows=sample();before=copy.deepcopy(rows)
        candidate=dict(item=dict(rows[0]['item'],float_value=.20))
        kept,_,evidence=collect_sales(candidate,rows,c,timestamp('2026-10-17T12:00:00Z'))
        self.assertEqual(rows,before)
        self.assertGreater(len(kept),sum(abs(r['item']['float_value']-.20)<=.05 for r in rows))
        self.assertTrue(any(abs(a['source_float']-.20)>.05 for a in evidence['float_adjustments']))
        self.assertTrue(all(a['uncertainty_haircut']>=.0099 for a in evidence['float_adjustments']))

    def test_identity_decorations_duplicates_and_dates_still_filtered(self):
        from review import collect_sales
        from scanner import defaults
        import json
        c=defaults(json.loads((Path(__file__).resolve().parents[1]/'config.json').read_text()))
        rows=sample();candidate=dict(item=dict(rows[0]['item'],float_value=.20))
        rows[0]['item']['paint_index']=999
        rows[1]['item']['stickers']=[{'name':'premium'}]
        rows[2]['sold_at']='2026-01-01T12:00:00Z'
        rows.append(copy.deepcopy(rows[3]))
        _,_,evidence=collect_sales(candidate,rows,c,timestamp('2026-10-17T12:00:00Z'))
        for key in ('identity_mismatch','decorated_non_souvenir','outside_sales_window','duplicate_id'):
            self.assertEqual(evidence['sales_filter_counts'][key],1)

if __name__=='__main__':unittest.main()
