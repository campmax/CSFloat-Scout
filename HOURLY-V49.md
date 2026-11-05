# Main scanner v4.9: hourly ranking

The personal Amphibious monitor (personal.py and its configuration) is unchanged.
Stop the main scanner, replace program files, keep database/log/state files, and
run `py -3 scout.py`. Existing configuration automatically enables hourly paper
ranking unless paper_review.hourly_ranking is explicitly false.

Each completed scan updates hourly-best.html, hourly-best.txt and
hourly-best.json. These rank observations from the current monitoring hour.
The first hourly email arrives after approximately 60 minutes of running plus
any ongoing scan time. Windows are relative to start, not clock-hour boundaries.
State survives restarts; old observations outside the latest hour are excluded.

The hourly email includes up to five supported candidates ranked by estimated
net ROI after fees. Support requires positive estimated net, at least 2%
sales-based discount, two comparable sales, one recent sale and one recent sale
above break-even. A sold/withdrawn/changed listing cannot be a supported option.
These are manual-review estimates; weekly risk warnings remain visible.

The previous completed hour's fifth-best supported ROI becomes the next hour's
early-alert cutoff. With fewer than five, use the weakest supported ROI. With
none, do not invent a cutoff. Up to two newly evaluated eligible listings that
beat that cutoff can trigger early emails per hour. Repeats of the same listing
are suppressed within the hour. The hourly summary may include early-alert items.

Target: five summary options plus up to two early alerts, not a guarantee of
3–7 unique deals. If there are too few supported observations, rejected or
incomplete observations and unresearched leads are separated and labeled. If
no fresh data was collected, the hourly email says so. No negative or unknown
margin is relabeled as a good deal to meet a quota.

All hourly emails go only to user3@example.com. This replaces individual
paper-candidate emails in the main scanner; live purchase receipt logic and
buy authorization are unchanged. Hourly emails have their own one-summary / 
two-early-alert pacing instead of the old ten-individual-emails-per-day cap.
SMTP failures retain local reports; hourly summaries retry after five minutes.

Test email from your existing PowerShell session:

```
py -3 scout.py --test-email
```

Keep the PowerShell session containing your API and SMTP environment settings.
The test sends no purchase request. 163 offline tests passed; no real API or
email calls were used for validation.
