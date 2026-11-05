# CSFloat Scout v5.0 — prospective paper purchases

This is a simulation, with no real purchases or sales. Keep running without `--live`.
The personal Amphibious monitor is unchanged. Run only one main/personal process at a time.

## Install and run

1. Stop the old scanner with Ctrl+C. Back up your existing folder.
2. Extract the ZIP and copy all files from its inner `CSFloat-Scout` folder into your existing folder, replacing program files. Include `paper_portfolio.py` and `tests`. Keep `scout.sqlite3`, JSONL logs, request/quota state, and personal reports. Do not delete them.
3. The new settings also default correctly with your existing config. If you have customized `config.json` or `personal-config.json`, retain those copies; otherwise use the supplied config. Default virtual starting cash is **$1,000**. To change it before your first v5 scan, set `paper_portfolio.initial_cash_cents` (100000 means $1,000). No real balance is queried.
4. In the existing PowerShell window with API/SMTP environment variables:

```powershell
cd "C:\Users\USER\OneDrive\Desktop\CSFloat-Scout"
py -3 scout.py --test-email
py -3 scout.py
```

The banner must say **v5.0 — paper portfolio / immediate opportunities**.
Keep the PC awake and PowerShell open. Ctrl+C stops cleanly. Restarting preserves virtual cash and positions. Changing initial cash in config after initialization deliberately does not reset the wallet. This release installs no automatic startup task.

## What gets emailed

- Every newly validated eligible opportunity still gets an immediate alert, with persistent duplicate suppression; there is no hourly alert quota. Lower listing prices may generate new opportunity alerts.
- A new **PAPER BUY** email records an actual prospective simulated cash commitment. It includes the entry cost, competitive net estimate, downside estimate, and local-sales counts.
- Hourly good-option reviews continue, now including virtual cash and open-position counts.
- Only **user3@example.com** receives these emails. SMTP acceptance does not prove inbox delivery. Paper-buy receipts retry at five-minute intervals, up to six attempts, without buying again. A lost SMTP acknowledgement can still cause a duplicate receipt; the ledger never duplicates the purchase.

## Paper buy decision

Broad alerts remain permissive. A separate paper-purchase assessment requires:

- At least **3% estimated net ROI and $2 estimated net profit**, after configured fees and 1% estimated resale slippage.
- At least three comparable sales in seven days, including two direct local-float sales and one direct sale in three days. At least one recent direct sale must exceed fee-adjusted break-even.
- Supported active competing asks. The competitive estimate is capped by the lower sales-based scenario and the lowest comparable ask minus one cent. This is still an asking-price estimate, not a bid or guaranteed execution.
- Nonnegative estimated net after an additional decline of at least 3%, increased when normalized weekly sales show a larger decline.
- A freshly confirmed active listing at the same price and identity/float, no more than 30 seconds before the simulated decision. Sales evidence must be no older than one hour; competing asks no older than two minutes, including validation time.
- Enough available virtual cash. There is no arbitrary per-item maximum beyond the wallet.

Factory New is not banned. Direct float tolerances shrink near wear boundaries and ultra-low floats; broad alerts retain their earlier comparison rules. Adjusted sales never count as direct local liquidity. Nonlinear adjustment uses the existing local, date-held-out model, and compares source/target support independently. Competing asks use this sales-trained model when they are not direct comparisons. Uncertain source/target ranges are refused. No fitted model offers certainty.

Pattern-sensitive, decorated, thin, unsupported-competition, low-margin, and downside-negative cases remain visible as **watches**, with explicit reasons. They do not debit virtual cash. These exploratory thresholds are not proven optimal and do not force a daily purchase quota.

When at least five sale dates span six days within the seven-day window, the report estimates weekly change from daily normalized medians. Otherwise it explicitly labels weekly history unknown and uses an assumed downside scenario. This adds no chart requests and does not guarantee protection from a future crash.

## Reports and capital

Double-click `open-paper-portfolio.bat` or open `paper-portfolio.html` for:

- Prospective paper buys, entry estimates, cash, held positions and settlement.
- The best observed options over the latest 24 hours, ranked retrospectively. This list is **not** a claim that the scanner bought the day's eventual best item.
- Watch/rejection reasons and any later comparable-sales evidence available in the shared cache.

`paper-portfolio.json` provides the full machine-readable report. Durable decisions, positions and pending emails live in `scout.sqlite3`; `paper-review.jsonl` also includes each new assessment. Old historical observations are not backfilled as purchases.

The simulation assumes a seven-day acquisition hold starting at the paper fill. It does not instantly release cash after that hold. Waiting for a buyer can take longer. A disappeared/delisted listing never proves an exit or profit.

A paper exit must be explicitly entered after the hold, with an assumed gross sale price in cents. Stop the scanner first:

```powershell
py -3 scout.py --paper-sale LISTING_ID GROSS_CENTS
```

Replace both placeholders. For example, a hypothetical $120 gross sale uses `12000`. This command never sells anything on CSFloat. It labels the fill as a **user-assumed simulation**, deducts configured selling/withdrawal fees, and locks proceeds for another eight simulated days before crediting cash. The hold and settlement defaults are modeling assumptions; actual transfer, listing, buyer and settlement timing can differ. Do not interpret simulated realized profit as real realized profit.

To regenerate the report offline while the scanner is stopped:

```powershell
py -3 scout.py --paper-report
```

No API key or SMTP connection is needed for these offline commands. Shared history can supply post-unlock comparable sales, but there is no extra polling just for held positions and no automatic simulated resale. Marks can be absent or stale and are labeled with their cache timestamp.

## Research and rate limits

The listing/request pace, shared quotas, reserve and saved cooldown protections are preserved. Valuation, ranking, reports and portfolio tracking reuse fetched evidence; they add **zero market requests**. Normal scanner validation still makes its existing requests.

Research now favors recent direct sales near the candidate's float. Repeated thin local evidence cools that market temporarily; the scheduler retains exploration and cached reuse. This improves allocation, not total API quota. It cannot guarantee full market coverage, a fixed number of purchases, no 429 responses, or a ban-free account.

For the next review, upload `paper-portfolio.json`, `paper-review.jsonl`, `scan-stats.jsonl`, `runtime-events.jsonl`, `hourly-archive.jsonl`, and `config.json`. Do not include credentials. Preserve the database locally for restart continuity.

## Validation

191 offline tests pass, including fee/competition valuation, nonlinear ask normalization, local liquidity, sold/changed final confirmations, wallet rollback, restart deduplication, email retries, capital settlement and shared-cache exit evidence. The offline report CLI was also checked. Tests make no real API calls, sends or purchases.
