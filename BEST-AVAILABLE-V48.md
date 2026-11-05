# v4.8 — best available for manual review

Stop with Ctrl+C, replace program files in the existing folder, and keep your
database, logs and request/quota-state files. Run `py -3 scout.py`.
Check for v4.8 in the banner. The normal command remains paper-only.

After a cycle, open `best-available.html` in this folder. It lists up to 30
researched observations ranked by estimated net, and up to 20 queued leads.
Reload the page after scans. Rejected candidates remain visible. Unknown
profit stays unknown. Historical entries are dated and may already be sold.
The ranking covers observed candidates, not every item on CSFloat.

`historical-review.html` is included immediately, generated from the 639
decisions you supplied. It is an archive for comparison, not live offers.
The live review page also imports your existing paper-review.jsonl once.

## Diagnosis

In the uploaded scans after 03:00 UTC on October 20, 218 of 219 cycles made
zero API requests. Only one completed research. The latest output still used
the old misleading budget message. This is a stall, not evidence of no deals.

Across all 639 decisions, 448 failed comparable-sale minimums, 98 were already
sold/withdrawn/repriced, 78 failed recent-sale/break-even checks, and 15 failed
discount/trend requirements. Most decisions came from older configurations.

The v4.7 read quota aggregation could merge the remaining count from one
endpoint with another endpoint's reset and limit, producing an excessively
long wait. v4.8 separates listing pages, listing details, and other read
endpoints. The obsolete aggregate remains on disk but no longer governs these
routes. Each route learns from its next response at normal request spacing.
Global server cooldowns and Retry-After are preserved. The exact server quota
scope is still not proven, so no zero-rate-limit guarantee is possible.

## Paper criteria now

- Two valid comparable completed sales in seven days, with at least one in
  the last three days. A second distinct sale date is no longer required.
- Best-available leads require at least 2% sales-based discount, positive
  estimated net after configured fees and 1% resale slippage, and at least
  one recent comparable sale above fee-adjusted break-even.
- Missing weekly charts, falling trends and negative downside scenarios are
  warnings for these manual-review leads, not automatic exclusion. Cached
  charts are used when available; new chart calls do not delay paper alerts.
- Valid identity, float comparisons, actual completed-sale status and final
  listing confirmation remain required for passed leads. The nonlinear float
  model is retained; missing evidence is not manufactured.
- Research prefilter lowered to 2%. The $20 minimum remains.
- Eligible paper leads use the existing email notification mechanism. Rejected
  or unresearched page entries are not emailed as profitable deals.

This profile applies in paper_runtime_config even with your existing config.
Set paper_review.best_available to false to opt back into the legacy review
profile. Live purchase rules are unchanged; paper leads never authorize buys.

The summary retains total searched / new / candidates / researched / passed.
The new report exists even with zero passes, provided there are observations.
148 offline tests passed. No real API calls, emails or purchases were made.
