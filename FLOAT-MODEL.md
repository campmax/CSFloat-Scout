> Historical v4.2 method. For current central-value/uncertainty handling, read OPTIMIZATION-V44.md.

# v4.2: nonlinear float comparisons (paper review only)

The model estimates the relative value of two floats using completed sales of
exactly the same market name, definition and paint index. This includes matching
wear category and StatTrak status. It does not assume that float premiums follow
one straight line, logarithm, or monotonic curve.

For each supported sale:

    adjusted sale = actual sale price × estimated target value / estimated source value

An uncertainty deduction is then applied before the adjusted sale enters the
existing valuation, profit and trend checks. Actual sale prices in the database
are never overwritten. Candidate asking price and CSFloat reference prices do
not train the model.

## Method and refusal rules

- Local Theil–Sen regression of log price against float, fitted independently
  around source and target. Local slopes can change with float. Log PRICE is
  used to express relative differences; this does not assume logarithmic FLOAT
  pricing. Neighborhood radius is 0.035, with no extrapolation, at least three
  distinct floats, four sales and two dates. Gaps over 0.025 are refused.
- At least 12 clean sales across three UTC dates. Uses the existing seven-day
  evidence window and at most the newest 240 clean sales to bound fitting cost.
- Whole sale dates are held out during validation. Requires at least eight
  test predictions covering 60% of training sales. Median relative error must
  be at most 5%, and 90th-percentile relative error at most 10%.
- Every adjusted sale is excluded from both endpoint fits. Source and target
  neighborhoods must share at least two sale dates to reduce time/float
  confounding. This does not eliminate all temporal or selection bias.
- Adjustments must stay within a 0.5–2.0 ratio. The log-price deduction is the
  maximum of a 2% price haircut, twice the held-out 90th-percentile log error,
  and the sum of source/target local 90th-percentile residuals. Excessive local
  dispersion refuses adjustment. This is a conservative heuristic, NOT a
  statistically calibrated confidence interval or guaranteed resale floor.
- Souvenirs and finishes in exclude_name_contains are not float-normalized:
  their tournament, sticker, seed or phase premiums remain unmodeled.
- Decorations, keychains, identity errors, old dates and duplicate sales remain
  filtered. Distant sales with unsupported adjustments are rejected. When an
  adjustment is unavailable, nearby sales retain the existing direct-comparison
  rule (±0.05); that fallback is not certified by the model.

Local fitting needs dense evidence. See NIST's discussion of the data needs and
limitations of local regression (this implementation uses robust median slopes,
not NIST's weighted least-squares LOESS algorithm):
https://www.itl.nist.gov/div898/handbook/pmd/section1/pmd144.htm

## Read the results

paper-review.jsonl and diagnostic output include float_model with status,
reason, training count and held-out errors. float_adjustments records each
source float, target float, raw price, endpoint estimates, ratio, deduction,
adjusted price and whether it survived the final outlier check. These estimates
share training data: adjusted observations are not independent confirmations.

scan-stats.jsonl includes model availability counts and float_adjusted_sales.
Emails report the number of accepted adjusted comparisons. No additional API
requests are made for normalization; fitting uses already fetched/cached sales.
No new Python packages are required.

No model provides complete certainty. Rare premiums, market changes, unreliable
sales and incomplete API history can defeat these checks. Offline synthetic
unit tests establish behavior, not real-world predictive accuracy or profit.
Paper mode remains the intended evaluation environment. Live buying logic and
its strict validation are unchanged.

## Install

1. Press Ctrl+C to stop the running scout.
2. Back up your current folder, then copy the files from this ZIP's
   CSFloat-Scout folder into it. Choose Replace for matching program files.
   The ZIP has no database or runtime logs; keep scout.sqlite3 and your logs.
   Keep your existing config.json if you customized it; no new settings are
   required. The supplied config keeps live buying disabled.
3. In the same PowerShell window, run `py -3 scout.py`.
4. Confirm the banner says `review v4.2 — nonlinear float comparisons / paper alerts`.

Existing queued listings continue normally. Previously rejected listings are
not automatically requeued. New listings/price versions use the new model.
Do not delete the database to force reprocessing; it also holds purchase and
email safeguards. Inspect a specific item with the existing --diagnose-name
command when you want a fresh read-only analysis.
