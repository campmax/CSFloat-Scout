> v4.4.1 patch: HTTP 409 on a saved listing cursor is retired with a coverage gap, including ranked-feed cursors. Other 409s remain errors. Runtime logs now include safe route/cursor context. 111 offline tests pass. Startup banner: review v4.4.1 — cursor recovery / budgeted research.

# v4.4: request-efficient paper research

This release supersedes the schedules in v4.1–v4.3 and the uncertainty formula
in FLOAT-MODEL.md. It retains $20 minimum, no configured upper price ceiling,
nonlinear float comparisons, fair feed scheduling, fees/trend checks, two email
recipients, database history, and purchase/receipt safeguards. Buying stays off.

## What changed

1. **Request budget:** at most 12 actual API requests per paper scan, shared by
   discovery and research. A budget stop keeps unfinished candidates queued and
   writes scan statistics. It is not a rejection or an API failure.
2. **Pacing:** supplied interval is 30 seconds, enforced as a minimum for paper
   CLI commands even if an older config still says 15. At most about 120 requests
   per hour from one continuous process at that spacing; not a guaranteed safe
   CSFloat allowance. Other sessions/services may consume the same allowance.
3. **Durable 429 stop:** honors a longer Retry-After value (seconds or HTTP date),
   stores a minimum one-hour cooldown and doubles spacing for a later manual
   restart. A blocked restart sends no request. No rejected request or purchase
   is automatically retried. Pacing does not automatically speed up again.
   Keep request-state.json. Server access/rate limits can still stop the scout.
4. **Single requesting process per folder:** OS lock prevents a second scout
   CLI command in the same folder. The lock is released by the OS after a crash;
   an existing scout.lock file is normal. Separate copies/other apps are not
   coordinated. Stop the scanner before running balance/probe commands there.
5. **Sales-first research:** reuse a listing observed within the last 60 seconds,
   otherwise refresh details. Fetch completed sales next. Missing evidence,
   nonpositive modeled net or insufficient discount skips chart and competition
   requests. Fetch chart only for plausible deals, then competition only if the
   chart-based review qualifies. Confirm the listing again before emailing.
   Sales-only rejects explicitly say research_stage=sales_only: no chart fetched
   must not be mistaken for a demonstrated bad trend. Cached history lives ten
   minutes; chart 15 minutes; competition two minutes. These are bounded snapshots,
   not assurances of perfect current market data.
6. **Research priority:** up to six distinct markets per scan, within the request
   budget. Freshest queued candidates first on three scheduling turns; oldest
   first every fourth turn. Feed rotation and the market cooldown remain. More
   than six can still queue, and fewer than six may finish because of the budget.
7. **Avoid obsolete work:** newly observed prices supersede older queued versions.
   Unresearched candidates older than one hour in the queue expire explicitly;
   records remain in the DB. This is a freshness choice, not evidence they were
   bad deals. Prior research windows and qualification thresholds are unchanged.
8. **Discovery overhead:** full newest pass at scan start; a head-page-only check
   between research tasks when 120 seconds have elapsed since the prior check.
   Saved continuations get all spare pages, instead of only one reserved page.
   Returned cursors stay opaque. Duplicate cursors are coalesced, boundaries from
   ranked feeds cannot masquerade as newest boundaries. Existing pending cursors
   are retained. Rejected expired cursors are retired with an explicit coverage
   gap; their missing data is not counted as scanned. A backlog can still grow
   when arrival rate exceeds capacity.
9. **Side feeds:** ranked deals retain five-minute timing; focus retains ten-minute
   timing, but both defer while at least 12 candidates await research. They resume
   when the queue falls below that level. No claims of complete market coverage.
10. **Status:** actual API-request count, saved chart/detail/competition requests,
    budget stops, expired/superseded queue counts and stopped-access state are
    available in status.json/scan-stats.jsonl. Runtime logs retain stop events.

## Float value versus uncertainty

The model continues robust local regression of log price, not a single global
float curve. Identity, decorations, data-support, independent endpoint fits and
held-out-date prediction-error gates remain. It also refuses local residual
scatter over 15% to avoid smoothing through abrupt price discontinuities.

Previously, sale-price noise at both endpoints was deducted from EVERY adjusted
sale and then normal market stress was applied. The latest run showed a 12.6%
median deduction. This confounded normal transaction dispersion with uncertainty
in the relative float adjustment.

Now adjusted_price_cents is the central normalized price (actual price × fitted
ratio). uncertainty_price_cents is separate. The latter uses the larger of:

- 1% minimum deduction;
- 90th-percentile change in the fitted relative log-price ratio when each sale
  date is held out, requiring at least two supported held-out ratios;
- median held-out price prediction error, scaled by float distance up to one
  neighborhood radius.

Relative uncertainty over 8% refuses the adjustment. Central medians determine
fair_cents and independent discount. Medians of uncertainty prices determine
uncertainty_fair_cents/uncertainty_net_cents. The existing weekly/future downside
scenario is applied to that lower value ONCE. Nearby unsupported floats still
use the prior direct-comparison fallback. No premiums for stickers/seeds/phases
are invented. These are empirical heuristics, not calibrated confidence bounds,
independent confirmations, or guaranteed resale prices. Offline tests do not
establish live predictive accuracy. The 15%+ paper tier retains its existing
warning-based behavior for trend risk; it is never live purchase approval.

## Install

1. Stop any old scout with Ctrl+C. Back up the existing folder.
2. Extract this ZIP. Copy the CONTENTS of CSFloat-Scout into your existing folder.
   Replace matching program files and config.json for all new supplied defaults.
   If keeping a custom config, merge the defaults listed below; old configs get
   defaults for absent keys, but existing values such as pauses remain yours.
3. Keep scout.sqlite3, request-state.json (if present), email/receipt records and
   your logs. The ZIP contains none of your runtime data. Do not delete cooldown
   state to restart sooner. No database reset or rejected-listing replay occurs.
4. Use the same PowerShell window with your existing environment variables:
   py -3 scout.py
5. Banner: review v4.4 — budgeted research / calibrated float comparisons

New supplied settings: request_interval_seconds=30, paper_poll_seconds=30,
paper_requests_per_cycle=12, paper_research_limit=6, evaluations_per_cycle=6,
newest_check_seconds=120, side_feed_queue_limit=12,
paper_queue_max_age_seconds=3600. Price minimum remains 2000 cents. No extra
Python packages are required. Profit requirements are not lowered by this release.
Live buying retains strict valuation and purchase reconciliation; the durable
transport policy/instance lock also apply to its commands.

## Verification and limits

109 offline tests passed, including nonlinear/discontinuous float pricing,
held-out-date errors, no API call during a restarted cooldown, Retry-After date
parsing, request-budget preservation, sales-first request savings, fresh/aging
queue turns, process lock release and prior purchase/receipt guards. No live
account requests, trades or emails were made while testing. Rate limiting,
market losses, missing listings and server changes remain possible.

Primary protocol references:
https://www.rfc-editor.org/rfc/rfc6585.html#section-4
https://www.rfc-editor.org/rfc/rfc9110.html#name-retry-after
Official API reference (opaque listing cursor, max listing page size):
https://docs.csfloat.com/
