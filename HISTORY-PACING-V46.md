# v4.6: separate history pacing and broader paper leads

## Install

Stop the scanner with Ctrl+C. Copy the contents of this ZIP's CSFloat-Scout folder into the existing CSFloat-Scout folder, replacing program files. Keep the database, logs and request-state.json. Keeping an older customized config.json is supported; new settings receive defaults and the new paper profile applies automatically.

```powershell
cd "C:\Users\USER\OneDrive\Desktop\CSFloat-Scout"
py -3 scout.py
```

The banner should say v4.6. The first startup migrates old globally increased pacing into the new policy: listing spacing becomes the configured paper minimum, while all outstanding cooldown and next-request deadlines remain intact. Do not delete request-state.json. Subsequent restarts do not reset new backoffs.

## Request behavior

- paper_listing_interval_seconds defaults to 15. This is a minimum between all requests, not a confirmed CSFloat allowance. The eight-request cycle cap, newest-first discovery, posting-time priority, adaptive side-feed timing and 60-second cycle pause remain.
- history_request_interval_seconds defaults to 900. All sales-history and chart requests share this slot across all market names. It allows at most roughly four history/chart requests per hour initially. This is a deliberately conservative local setting, not a known server quota.
- A candidate needing a history slot stays queued while other discovery and cached-evidence work proceeds. Repeated detail requests are suppressed for candidates already waiting on history. A first-time candidate requiring both sales and a chart may need two slots; short-lived listings can sell before validation.
- Sales and chart evidence is reused for up to paper_history_cache_seconds=3600. Sales cache age and fetch time appear in decision metadata. Cached evidence is never treated as complete transaction history. Live research retains its shorter scanner cache windows.
- Empty sales results no longer trigger an immediate second, unfiltered history request in paper mode. Genuine access errors are never treated as empty evidence.
- A history 429 increases history spacing without doubling the ordinary listing interval. A non-history 429 still backs off ordinary requests. Every 429 continues to pause ALL API requests for at least an hour, or longer when Retry-After requires it. We do not yet know whether the server's restriction is global, so the program does not continue discovery during that cooldown.
- HTTP logs now distinguish history_sales from history_chart and record successful request categories as well as errors. Only numeric allowlisted rate-limit headers and parsed Retry-After durations are logged. Cookies, authentication headers and response bodies are omitted. Recorded reset headers are diagnostic only because their units/scope are not confirmed.

No request frequency can be guaranteed free of rate limits. The supplied logs identified the failing category, not CSFloat's exact quota or the reason it was imposed. Testing used mocked responses and made no CSFloat calls.

## Paper evaluation

The runtime paper profile lowers the weekly minimum from four to three accepted comparable sales, still across at least two dates, including at least two within the last three days. User settings already below three remain as configured. The normal modest discount starts at 5%, retaining the configured fee and downside-margin checks. The cheap reference prefilter becomes 3%; this only selects research candidates and never establishes resale value.

A separate paper_watch tier shows leads with at least:

- 4% estimated discount against comparable completed sales;
- $1 estimated net profit after configured fees and paper slippage;
- the required comparable-sale sample, including two recent sales above fee-adjusted break-even;
- a verified weekly chart change no worse than -6% under the supplied settings.

Watch leads can fail the stronger downside-margin checks. Their output explicitly says PAPER WATCH ONLY, and a negative downside scenario adds DOWNSIDE LOSS. They count among qualified paper alerts but are also counted separately as paper_watch. Emails use that tier in the subject. They require final listing confirmation, cannot authorize purchases, and must not be presented as guaranteed profitable opportunities. Pattern/phase warnings and float-model uncertainty remain visible.

The earlier high-discount paper tier and strict live-buying rules remain; live buying is disabled in the supplied config. The $20 minimum and recipients are retained. Float tolerances, identity matching, decoration filtering and nonlinear model validation were not weakened.

## Historical evidence and limitations

Based only on recorded metrics, seven historical evaluations meet the new watch discount/net/recent-profitable-sales/weekly-change tests. They are repeated evaluations of three item names, not seven confirmed currently available deals. Full historical replay is impossible from the summarized decisions alone.

- Karambit Gamma Doppler: recorded estimated discounts about 6.6–8.9%; some positive downside scenarios, others negative; phase/pattern premium remains unvalidated.
- Bowie Knife Gamma Doppler: about 5.4% discount, $4.09 estimated net, -$0.75 downside scenario.
- Amphibious Field-Tested: about 4.4% discount, $3.84 estimated net, -$5.85 downside scenario, eight recent comparable sales above fee-adjusted break-even.

The Galil record showing a 14.8% discount also showed a roughly 14.4% weekly decline and a negative downside scenario. The modest/watch tiers continue to reject that weekly decline.

129 offline tests pass, including durable migration, cooldown preservation, shared history pacing across restarts, history backoff without discovery doubling, cache age preservation, waiting candidates without repeated detail requests, broader evidence thresholds, downside labels, and prior discovery/valuation/purchase safeguards.
