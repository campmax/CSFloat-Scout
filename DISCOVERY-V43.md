> Historical v4.3 schedule. Current pacing, queue and pagination changes are in OPTIMIZATION-V44.md.

# v4.3: newest-first discovery and $20 minimum

This update retains v4.2's nonlinear float comparisons, fair research scheduling,
paper-review qualification rules, fee/trend checks, email configuration, and
purchase safeguards. It changes paper discovery and lowers the supplied price
minimum from $100 to $20. There is still no configured upper price limit.

## Schedule

- Fetch newest listings first, then evaluate queued candidates before side feeds.
- Fetch newest listings again between research tasks. Newly found candidates join
  the durable queue; the current batch remains bounded and fair.
- Ranked deals: every 300 seconds, alternating best_deal/highest_discount.
- Amphibious focus: every 600 seconds. Configured focus lists still rotate.
- Paper pause: 15 seconds after a cycle, instead of the old 60 seconds.
- Request spacing remains configured at 15 seconds minimum. Actual newest-check
  latency includes pagination, network time, research and occasional side feeds;
  this is not a promise of a new scan every 15 seconds.
- Transient outer-loop errors retain at least a 60-second pause; access/rate-limit
  stops remain stops. No extra worker or parallel API requester is introduced.

## Coverage

Newest listings are followed until a completely known page overlaps a prior
newest traversal or results end, subject to the per-call page budget. Boundaries
are tracked for the exact name/price query: ranked-feed sightings cannot alone
stop a newest traversal. The initial run must establish these boundaries.

At the page budget, returned cursors are saved in scout.sqlite3. Later checks
fetch the fresh head first and reserve a page for the oldest continuation,
then spend remaining pages following the fresh head. Both continuations survive
if neither finishes. A backlog gets at least one resume page even when the
configured newest budget is one (that check can therefore use two pages).

A missing or repeated cursor is reported as unknown coverage/a gap. No cursor
is invented. Saved cursors depend on the server remaining willing to accept
them; expired-cursor errors require inspecting runtime logs, not pretending the
market was covered. Moving listings and sales between polls can still be missed.
This is improved partial coverage, not a full-market guarantee.

The newest page budget applies to each discovery pass, including passes between
research tasks. Busy periods can grow a backlog. scan-stats.jsonl records
newest:pending_traversals, newest:resumed_pages and the feed timer skips.
Repeated listings are skipped before background research. Price changes remain
new listing versions eligible for screening. Unique count is listing IDs,
not the number of distinct skin names. Older listings can still be checked for
price reductions through the timed ranked and focus searches.

## Price and profit

The supplied config.json now uses min_price_cents=2000. The existing modest-deal
minimums remain $2 estimated net, $1 stressed net and 1% stressed ROI. This means
many $20 items still will not qualify on small discounts. The 15%+ review tier
continues its previous warning-based policy; no profit or risk threshold was
loosened in this release. All amounts are modeled estimates, not guaranteed gains.

## Install without losing previous work

1. Stop with Ctrl+C. Back up the current folder.
2. Extract the ZIP and copy the CONTENTS of its CSFloat-Scout folder into your
   existing folder. Replace matching program files and config.json to use the
   supplied $20 setup. If you customized config.json, keep it and change only
   min_price_cents to 2000; the new timers default automatically when absent.
3. Keep scout.sqlite3, all logs and existing receipt/email records. This ZIP
   contains no runtime database or logs and does not reset them.
4. In the same PowerShell window run: py -3 scout.py
5. Confirm: review v4.3 — newest-first scanning / nonlinear float comparisons

New default keys: deals_interval_seconds=300, focus_interval_seconds=600,
paper_poll_seconds=15. Old poll_seconds still applies outside the new paper
review loop. The minimum price setting is shared with live mode; live buying
remains disabled in the supplied configuration. Do not use live mode to test
this update. Previously rejected listing versions are not automatically requeued.
