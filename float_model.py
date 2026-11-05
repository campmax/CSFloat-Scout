"""Local robust log-price regression for PAPER review, not purchase approval.

No global linear/logarithmic float curve is assumed. Local slopes may change
sign. Entire sale dates are held out for error checks; errors are empirical,
not confidence guarantees. Input is already identity/date/decoration filtered.
"""
import math
import statistics as st

VERSION = 'local-log-v2-ratio-uncertainty'
RADIUS = .035
MIN_ROWS = 12


def percentile(values, fraction):
    ordered = sorted(values)
    return ordered[min(len(ordered)-1, math.ceil(fraction*len(ordered))-1)]


def local(points, value):
    near = [p for p in points if abs(p[0]-value) <= RADIUS]
    if len(near) < 4 or len({p[2] for p in near}) < 2:
        return None
    xs = sorted({p[0] for p in near})
    if len(xs) < 3 or not xs[0] <= value <= xs[-1]:
        return None
    if any(b-a > .025 for a,b in zip(xs,xs[1:])):
        return None
    # Theil-Sen local slope resists isolated expensive sales. Median intercept
    # evaluates the curve at this exact float without a global shape assumption.
    slopes = [(b[1]-a[1])/(b[0]-a[0]) for i,a in enumerate(near)
              for b in near[i+1:] if abs(b[0]-a[0]) >= .002]
    if not slopes:
        return None
    slope = st.median(slopes)
    prediction = st.median(p[1]+slope*(value-p[0]) for p in near)
    scatter = percentile([abs(p[1]+slope*(value-p[0])-prediction) for p in near], .9)
    return prediction, scatter, {p[2] for p in near}, len(near)


class FloatModel:
    def __init__(self, rows, target, timestamp, blocked=False):
        available_rows = len(rows)
        rows = sorted(rows, key=lambda r: (timestamp(r['sold_at']), str(r['id'])), reverse=True)[:240]
        self.points = [(r['item']['float_value'], math.log(r['price']),
                        int(timestamp(r['sold_at'])//86400), str(r['id'])) for r in rows]
        self.target = target
        self.error = None
        self.info = dict(version=VERSION, status='unavailable', training_sales=len(rows), available_clean_sales=available_rows,
                         target_float=target, neighborhood_radius=RADIUS,
                         uncertainty_note='Empirical validation only; no guarantee of resale value.')
        if blocked:
            self.info['reason'] = 'pattern or souvenir premiums are not normalized'
            return
        if len(rows) < MIN_ROWS or len({p[2] for p in self.points}) < 3:
            self.info['reason'] = 'needs 12 clean sales across at least three dates'
            return
        if local(self.points, target) is None:
            self.info['reason'] = 'target float lacks local bracketing support'
            return
        errors = []
        for point in self.points:
            pred = local([p for p in self.points if p[2] != point[2]], point[0])
            if pred is not None:
                errors.append(abs(pred[0]-point[1]))
        self.info['held_out_predictions'] = len(errors)
        if len(errors) < 8 or len(errors)/len(rows) < .6:
            self.info['reason'] = 'insufficient held-out-date coverage'
            return
        error = percentile(errors, .9)
        self.info.update(held_out_p90_relative_error=math.expm1(error),
                         held_out_median_relative_error=math.expm1(st.median(errors)))
        if math.expm1(error) > .10 or math.expm1(st.median(errors)) > .05:
            self.info['reason'] = 'held-out prediction error too large'
            return
        self.error = error
        self.info.update(status='available', reason='local support and held-out checks passed')

    def adjust(self, row):
        if self.error is None:
            return None, self.info['reason']
        # A sale must never train its own source or target estimate.
        points = [p for p in self.points if p[3] != str(row['id'])]
        source = local(points, row['item']['float_value'])
        target = local(points, self.target)
        if source is None or target is None:
            return None, 'source or target lacks independent local support'
        if len(source[2] & target[2]) < 2:
            return None, 'source and target lack overlapping sale dates'
        if max(source[1],target[1])>math.log(1.15):
            return None,'local discontinuity or dispersion exceeds 15%'
        ratio = math.exp(target[0]-source[0])
        if not .5 <= ratio <= 2:
            return None, 'adjustment exceeds supported ratio limit'
        # Estimate uncertainty of the RELATIVE float adjustment, rather than
        # subtracting both endpoints' raw sale-price dispersion from every sale.
        # Leave whole dates out: common price noise at both floats can cancel.
        ratios=[]
        for day in sorted(source[2] | target[2]):
            subset=[p for p in points if p[2]!=day]
            a=local(subset,row['item']['float_value']);b=local(subset,self.target)
            if a is not None and b is not None:ratios.append(b[0]-a[0])
        if len(ratios)<2:return None,'insufficient date-held-out relative-price support'
        spread=percentile([abs(v-math.log(ratio)) for v in ratios],.9)
        distance=abs(row['item']['float_value']-self.target)
        penalty=max(-math.log(.99),spread,
                    math.log1p(self.info['held_out_median_relative_error'])*min(1,distance/RADIUS))
        if math.expm1(penalty)>.08:return None,'relative-price uncertainty exceeds 8%'
        adjusted=math.floor(row['price']*ratio)
        return dict(id=str(row['id']), source_float=row['item']['float_value'],
                    target_float=self.target, raw_price_cents=row['price'],
                    source_estimate_cents=round(math.exp(source[0])),
                    target_estimate_cents=round(math.exp(target[0])),
                    ratio=ratio, uncertainty_haircut=1-math.exp(-penalty),
                    adjusted_price_cents=adjusted, uncertainty_price_cents=math.floor(adjusted*math.exp(-penalty)),
                    held_out_ratio_predictions=len(ratios),source_support=source[3],
                    target_support=target[3]), None
