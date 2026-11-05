# Markdown Radar v1.4 — fresh, diverse markdown discovery

Stop all scanners with Ctrl+C. Copy ALL files from this folder beside your existing scout.py, replacing Radar files. Keep your databases and quota/request state. This is an add-on; it preserves main/personal scanner code.

```powershell
cd "C:\Users\USER\OneDrive\Desktop\CSFloat-Scout"
py -3 switch-email.py
py -3 radar.py --test-email
py -3 radar.py
```

All Radar emails go to user1@example.com. The address updater changes installed scanner recipient literals with backups. SMTP environment settings stay unchanged.

## What changed

- Every cycle checks newest listings and a rotating best_deal feed: full range, then $20–50, $50–100, $100–200, $200–400, $400–700 and $700–1,000, clipped to configured bounds.
- Every other cycle can target an exact market with recent completed sales in the local history cache. It rotates among the ten most active cached markets. This is NOT a verified global most-sold list.
- Each one-minute report selects up to three highest positive API-reference markdowns actually observed within the last 60 seconds, with at most one item per exact market name.
- A listing already emailed is suppressed persistently unless its price falls. Re-fetching it cannot reset that suppression. Last-report IDs from v1.3 seed the suppression during upgrade.
- Known zero-recent-sale listings are excluded when fetched history is current. Unknown-history listings need reference quantity at least three. Quantity is not represented as a verified sales count. Any positive markdown can appear; there is no 5% admission floor for scheduled reports.
- Recent market activity allows long shots even without direct float support. An unprofitable comparable remains visible as negative evidence, not a claim of profitability.
- Empty minutes produce status emails with skip counts; old AWP listings are no longer recycled to fill them. Approximately one SMTP attempt/minute does NOT guarantee a new deal/minute.

## Discount limitation

The screenshot shows a question-mark badge. Its exact meaning and the website's percentage-display eligibility are not verified. The API references available here do not establish that a number is visibly displayed on the site. Emails explicitly say reference markdown: the smaller available base/predicted discount, calculated as 1 - listing_price/reference_price. It is not ROI and is not claimed to reproduce the visible badge. Missing references and non-positive discounts are excluded. Sparse-reference filtering reduces the observed problem but cannot guarantee badge parity.

## Runtime and reports

Price range remains $20–$1,000. Existing 15-second minimum request spacing, four-request cycle budget, history quota, cooldowns and 90-second cycle pause remain. Discovery uses at most three listing requests/cycle, leaving room for at most one permitted history request. No quota bypass and no purchases. Some reporting minutes will have no API observations because discovery is slower than email cadence.

radar-minute.json is the latest attempted report and includes skip counts. radar-minute.jsonl records SMTP-accepted reports, not proof of inbox delivery. radar-best.json/html remain the separate stricter eligibility view. Keep radar.sqlite3 for observations, history, dedup and email timing.

```powershell
py -3 radar.py --no-email
py -3 radar-tests.py -q
py -3 radar-minute-tests.py -q
```

41 offline tests cover reporting, dedup across repeat observations, lower-price re-alerts, sparse/zero-sale exclusion, rotating discovery and prior behaviors. Tests use mocked SMTP/API calls. Live badge parity has not been tested.
