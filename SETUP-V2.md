> Historical setup reference. See START-HERE.md for current scan behavior, paper thresholds and update instructions.

# Scout — manual alerts and selective deals

**v3 update:** See `START-HERE.md`. Fixed dollar, position-count and daily-count ceilings now default to `null` (disabled). The API available balance determines affordability. Historical capital-ledger controls below are optional only if you re-enable their caps; confirmed old purchases are not subtracted again from the already-debited available balance.

## What automatic purchasing does and does not do

`--live` can submit an automatic marketplace purchase request. The purchase integration is still unverified on a live account. It does not complete Steam trade acceptance, delivery verification, resale, or settlement. Use the default paper/manual-alert mode until the API contract and account permissions are verified. Do not automatically try a manual purchase after an uncertain live result: the first purchase may have succeeded.

Email mode independently finds qualified deals and emails the item URL for manual purchase. It never submits a buy. No emails were sent during development; SMTP behavior was tested with mocks. Without your local SMTP credentials and recipient address, email is not active.

## New defaults

| Control | Default |
|---|---|
| Minimum item price | $100 |
| Maximum item price | Available account balance, less modeled buying costs |
| Independent discount | At least 20% |
| Normal modeled profit | At least $25 |
| Modeled profit after downside stress | At least $25 AND 8% of total acquisition cost |
| Minimum hypothetical further price drop | 5% |
| Hard recent crash cutoff | 8% decline or drawdown |
| Maximum observed drop relative to discount | Less than half the discount |
| Sale fee | 2% |
| Withdrawal fee | 0%, assuming you keep proceeds on CSFloat |
| Buy fee | 0% configurable assumption; enter any applicable fee |
| Resale slippage | 3% additional haircut |
| Open capital cap | Disabled; current available account balance controls affordability |
| Open positions | No fixed count cap |
| Purchases per UTC day | No fixed count cap |

These are editable conservative choices, not empirically optimized thresholds. Buying fewer items reduces transaction volume; it does not establish immunity from platform restrictions. Nothing bypasses rate limits or bot controls.

## Seven-day chart check

The code calculates a trend from dated, comparable completed-sales records already fetched for valuation. It does not visually read the website chart or assume its plotted reference exactly matches these sales. This adds no separate chart request. A precise live graph API adapter has not been verified.

- Builds daily medians, requiring at least three sales per usable day.
- Requires five usable days in the last seven days (including today), plus an observation near the beginning and end of the period.
- Compares the median of daily medians 6–8 calendar days ago with those today/yesterday. This is an approximate seven-day comparison, not an exactly seven-day price tick.
- Also measures the decline from the highest daily median in the recent week. This catches a rise followed by a crash even if the start-to-end price barely changed.
- Rejects an observed decline/drawdown of 8% or greater, or one consuming half or more of the independent discount.
- Stress-tests another drop equal to the larger of 5% or the observed decline/drawdown. `risk_horizon_days` defaults to 7; larger values compound that observed weekly decline over the chosen horizon.
- Subtracts modeled sale/withdrawal/buy fees, 3% slippage and extra fixed costs. Requires at least $25 and 8% ROI after that scenario.

This is a stress scenario, not a forecast or guarantee. A future crash can exceed it. Old completed sales are required: if the API only returns a few recent sales and cannot establish week-long coverage, the deal is rejected. Missing chart evidence is never treated as a flat market. Because the history adapter is provisional, a schema change or limited history can produce zero qualified deals. Run the read-only probe first.

### Your 14%-off / 10%-decline example

If current fair value is $100 and the price is $86, another 10% fall gives a resale value of $90. After a 2% sale fee, that is $88.20, or $2.20 profit before other costs. After the additional configured 3% slippage, proceeds are $85.55 after cent rounding: a small loss. With the default settings this is rejected for the discount, recent crash, and stressed-margin criteria.

Percentages have different bases; subtracting the displayed percentages directly does not calculate actual dollar profit. The agent computes the dollar cashflows.

## Email setup in PowerShell

Use your mail provider's SMTP settings and a dedicated app password where supported. Some providers require OAuth or prohibit password SMTP; this implementation supports SMTP password authentication over TLS only. Do not send secrets in chat.

```powershell
$env:SCOUT_SMTP_HOST = "YOUR_PROVIDER_SMTP_HOST"
$env:SCOUT_SMTP_PORT = "465"
$env:SCOUT_SMTP_MODE = "ssl"
$env:SCOUT_SMTP_USER = "YOUR_EMAIL_ADDRESS"
$env:SCOUT_SMTP_PASSWORD = "YOUR_SMTP_APP_PASSWORD"
$env:SCOUT_EMAIL_FROM = "YOUR_EMAIL_ADDRESS"
# Recipients are already set in config.json; SCOUT_EMAIL_TO is not used.
py -3 scout.py --test-email
```

For a provider requiring STARTTLS, use port `587` and mode `starttls`. Plaintext SMTP is not supported. The test sends one clearly labeled test email and never purchases. Check your inbox/spam. SMTP acceptance cannot guarantee inbox delivery or speed.

Then keep `"email_enabled": true` in `config.json` and run:

```powershell
$env:CSFLOAT_API_KEY = "YOUR_CSFLOAT_KEY"
py -3 scout.py
```

Use this command without `--live` for manual-purchase emails. Eligible alerts include price, independent discount, weekly change/drawdown, stress loss, projected profit and the CSFloat link. One successful email per listing ID is recorded durably; price changes do not trigger repeat emails. Failed sends may retry only after 5 minutes and a NEW eligible evaluation, up to three attempts per listing. The daily limit is 10 distinct emailed/attempted listings, not ten total retry attempts. SMTP timeout delivery is uncertain and a retry may duplicate a message. There is no guaranteed delivery queue; deals that disappear or become ineligible are not retried.

Opportunity alerts are sent in manual/paper mode. Purchase receipts are sent in live mode after acknowledgement and balance reconciliation. Live purchase errors stop execution and retain uncertain reservations; they do not email an invitation to purchase a potentially already-bought item. Successful reconciled purchases now queue receipts to both configured recipients; see PURCHASE-EMAILS.md.

## Capital stays committed until funds are actually available

Steam's documentation says received CS2 items are protected from transfer for seven days. CSFloat's homepage says proceeds after a sale can take around eight days after delivery to be credited. Buying, waiting, reselling and reusing proceeds can therefore take more than two weeks, plus delivery and time to find a buyer. The seven-day stress horizon concerns holding the unsold item's price risk; the capital lock also covers settlement after resale. Adjust the horizon if you expect a longer unsold holding period.

The ledger counts all confirmed and uncertain purchases as committed capital regardless of their age. Nothing unlocks on day seven, day fifteen, or at midnight. An open-capital cap is not an actual live balance query. Purchases made outside this agent are invisible unless you record them.

After buying manually, record the CSFloat listing ID and ACTUAL total amount paid, including any buy costs:

```powershell
py -3 scout.py --record-manual LISTING_ID 24000
```

This records $240 already spent; it does not purchase anything. Since it records a historical fact, the command can exceed the cap, which will block further opportunities. Keep the ledger current before relying on exposure checks. The daily purchase budget also counts manually recorded purchases.

Only after resale or refund funds are available for use again:

```powershell
py -3 scout.py --release-capital LISTING_ID --funds-credited
```

This releases that original acquisition cost in the local ledger, not funds on CSFloat. It does not assume profit can increase your configured budget; adjust the cap manually if appropriate. An uncertain purchase cannot be released by this command: reconcile the account first. Never delete the SQLite ledger or run multiple copied project folders to bypass limits. Existing v1 ledgers migrate automatically; historical purchases are conservatively treated as still committed until you release them.

## Verification and limits

36 offline tests pass, including seven-day crashes, recent-peak crashes, insufficient history, minimum item value, stressed margins, email retry/deduplication, persistent capital and prevention of releasing uncertain purchases. All fixtures are synthetic; email tests send no actual mail. Live CSFloat purchasing, history response compatibility and delivery remain unverified.

Sources checked October 16, 2026 UTC:

- Steam Trade Protected Items: https://help.steampowered.com/en/faqs/view/365F-4BEE-2AE2-7BDD
- CSFloat current homepage, 2% sale fee and approximately 8-day proceeds delay: https://csfloat.com/
- CSFloat explanation that reusing balance does not incur a withdrawal fee: https://blog.csfloat.com/changes-to-fees-on-csgofloat-market/
