# Current release: v5.0 — paper portfolio

Read **PAPER-PORTFOLIO-V5.md** first. It supersedes the historical release notes below. This version adds prospective paper buys with $1,000 virtual starting cash, competitive resale estimates, narrow direct-float liquidity checks, cash/hold/settlement tracking, and paper-buy emails. Immediate opportunity emails and hourly reviews continue. The personal monitor is unchanged. No additional market requests are introduced.

# Current patch: v4.4.1

Adds recovery for rejected saved pagination cursors (HTTP 409) and request-category error logs. Retains all v4.4 settings and features. Keep your existing configuration when installing this patch.

# Current release: v4.4

Read OPTIMIZATION-V44.md first. It supersedes older scheduling and float uncertainty instructions below. Starts in paper mode at a $20 minimum; retains earlier features.

# Update: v4.3 newest-first scanning

Read DISCOVERY-V43.md for installation and schedule changes. The supplied config starts at $20. All v4.2 float-model features are retained.

# Update: v4.2 float comparisons

See FLOAT-MODEL.md for the model, limits and installation instructions. No additional dependencies or API calls.

# Scout v4.1 — ranked discovery and good-deal PAPER alerts

Stop the bot with Ctrl+C. Extract the ZIP, then copy ALL files from its inner CSFloat-Scout folder into your existing folder and choose Replace. Include config.json and the discovery.py, runtime_log.py and new scheduling.py modules. Keep scout.sqlite3 and existing logs; do not overwrite them with older copies. Back up any personal config changes first. Run one instance.

In your existing PowerShell window with API/SMTP variables configured:

```powershell
cd "C:\Users\USER\OneDrive\Desktop\CSFloat-Scout"
py -3 scout.py
```

Startup must say: PAPER MODE — no purchases or balance required; review v4.1 — balanced research / good-deal alerts

Closing PowerShell, sleeping or rebooting stops scanning. Ctrl+C stops cleanly. No automatic relaunch is installed. New terminals need credentials set again; see SETUP-V2.md for SMTP environment-variable names. Do not share passwords or API keys.

## Finding listings

The official API documents most_recent, best_deal and highest_discount sorting: https://docs.csfloat.com/

Each paper cycle checks up to three pages of newest listings, two pages ranked by best_deal or highest_discount (alternating by cycle), and one best_deal page for a rotating focus item. Amphibious Field-Tested is the supplied focus item. Empty watchlist means whole-market searches above the $100 minimum; focus_watchlist supplements that search. No upper price limit is imposed by default.

Newest paging stops when a fully known listing/price page is reached. Deal-ranked results have no chronological coverage guarantee. No cursor is invented. Missing/repeated cursors and exhausted budgets are counted. Each cycle starts with fresh rankings instead of persisting a stale ranked cursor. This intentionally replaces the repeated historical sweep; it does NOT promise near-complete coverage. The old live-mode missing-cursor loop also now advances its observation boundary while explicitly recording a gap.

At most six discovery requests and three candidate evaluations occur in a normal full-budget cycle with one focus item. Requests remain spaced at least 15 seconds apart, plus the 60-second pause between cycles. Several minutes may pass between summaries. Quickly purchased deals can still be missed; no speed or ban-free claim is made. 401/403/429 stop the run.

Paper creation-age allowance is now 30 days so active ranked deals and repriced older listings can be considered. Every researched candidate is checked for current availability; age allowance is not permission to buy a stale quote. The cheap prefilter needs at least 4% against either valid API reference; missing-reference candidates enter at lower priority. Unsupported non-float items are skipped. A new queue version reconsiders current listings without deleting purchases or email records.

## What qualifies for review

The site/API reference and actual completed-sale comparisons are different evidence. Logs and email show API base-reference discount, API float-adjusted-reference discount and independent sales discount separately. Exact equality with the website badge is NOT verified. Never assume that a reference discount guarantees a profitable resale.

- Modest tier: at least 6% below the sales-based reference, verified weekly loss no greater than 6%, at least $2 modeled net before the downside scenario, and at least $1 AND 1% ROI after the downside scenario.
- High-discount tier: at least 15% below the sales reference and positive base modeled net. Prior permissive behavior remains: failed chart/stress checks become explicit warnings. This tier is not automatically safer than the modest tier.
- Both require four matching, outlier-filtered sales within seven days across at least two UTC dates, including two within three days. At least two recent sales must exceed fee-adjusted break-even.
- Valuation uses the lower of the seven-day and three-day sales medians. Exact item identity and float within 0.05 are required. The minimum discount is measured against this value, not inflated site references.
- Modeled costs include configured buy/sell/withdrawal fees, fixed costs and 1% resale slippage. Configured defaults are assumptions to verify before live use. The downside scenario assumes another decline equal to the greater of 3%, observed weekly loss or recent drawdown, over the configured holding horizon.
- Competing cheaper asks, sparse samples, pattern/phase uncertainty and unknown chart history are displayed as warnings. Sales medians are not executable bids. No profit or sale-time guarantee is made.
- Exact Souvenir items may use sticker-bearing Souvenir sales; tournament/player/sticker premiums are not normalized and are warned about. Non-Souvenir decorated sales and all keychain-bearing sales are excluded. Pattern-sensitive candidates are review-only.

The modest tier's net-profit requirements can make its effective minimum discount higher than 6%. For example, an 8% discount can qualify in a stable market, but may fail if another 6% decline would eliminate its margin after costs. Missing history is never interpreted as stability.

Live buying remains disabled. Its strict valuation and purchase safeguards are separate from review.py. No live checkout was performed for this update.

## Evidence and runtime diagnostics

Sales retrieval makes one name-only fallback request if the paint-filtered history response is empty. Exact paint/item matching is still enforced locally. Errors are not converted to empty history. Undocumented history pagination is not invented. The returned history may still be incomplete; locally observed sales continue accumulating.

- paper-review.jsonl and decisions.jsonl: decisions, warnings, discounts, sales exclusion counts and history-source counts.
- scan-stats.jsonl and status.json: completed scans, per-feed discoveries, duplicates and coverage limits.
- runtime-events.jsonl: process/scan starts and completions, handled errors, HTTP status, unexpected error types and code locations. Error bodies/credentials are omitted. A power loss cannot log its own cause; an unmatched start only establishes interruption.

Upload paper-review.jsonl, scan-stats.jsonl and runtime-events.jsonl after testing. History-source counts may describe cached API responses and repeat across decisions; they are not unique market-wide sales totals.

Optional read-only diagnosis (stop scanner first):

```powershell
py -3 scout.py --diagnose-name "★ Sport Gloves | Amphibious (Field-Tested)"
```

Upload diagnostic.json. It uses the active paper matching/chart settings and sends no emails or purchase requests. It uses current API history; the running scanner can have additional cached observations.

Qualified paper leads use the existing email setup, with up to 10 opportunity alerts per recipient per day. All decisions remain logged. Failed opportunity emails are logged rather than durably retried. Confirmed purchase receipts retain their separate durable retry mechanism. SMTP acceptance is not a delivery guarantee.

81 offline tests pass: ranked and focus queries, missing/repeated cursor bounds, sales fallback, reference separation, stable 8% qualification and downside rejection, diagnostics consistency, live isolation, and credential-free error records. Real API coverage and new live alert frequency remain unverified.

## Balanced research (v4.1)

Three available research slots are distributed across focus, newest and ranked candidates, one per nonempty eligible feed before assigning extra slots. Starting feed rotates each cycle so smaller custom budgets are fair too. Empty or cooling-down feeds relinquish their slots. Within a feed, older queued candidates go first rather than the largest reference discounts. Each exact market name/paint combination receives at most one research slot per cycle. Souvenirs are not banned; they no longer monopolize the queue simply by having huge reference discounts.

After two different listings of an exact market name/paint combination return zero usable matching sales, pending listings of that type pause for 30 minutes. They remain queued and become eligible for research afterward; positive matching-sales evidence clears the penalty. This is an efficiency choice, not proof the market has no sales. Cooldowns can delay a newly viable deal. API errors and sold listings do not create this penalty.

The existing v4 queue and all purchase/email records are preserved. The mode identifier remains paper_review_v4 for compatibility. Older queued entries have no source tags: focus names are recognized from configuration; other unknown-source entries use the ranked queue until rediscovery supplies source tags. Already rejected entries are not automatically requeued.

Console Research distribution and scan statistics show researched:focus, researched:newest, researched:deals, and queue:cooldown. Decisions include research_feed. Counters describe scheduling, not a guarantee of evenly distributed market opportunities. Discount, sales evidence, fees, request spacing and purchase settings are unchanged.
