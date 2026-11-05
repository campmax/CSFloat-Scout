# v4.6.1: runnable queue and shared evidence

The prior scheduler selected up to three candidates before checking history availability. All three could be blocked while candidates with reusable cached evidence remained elsewhere in the queue. The one-market-per-batch rule also restricted reuse of the same cached history for different listings.

This patch checks readiness before assigning research slots:

- Candidates requiring unavailable history stay queued without consuming a research slot or causing a detail request.
- When a history slot opens, a candidate with cached sales waiting for a chart is prioritized over starting research for a new market.
- Cached candidates can fill other available research slots, across feeds and even within the same market. The actual valuation still compares each listing's float and price independently.
- A chart cached by work on another listing can unblock a waiting candidate immediately; an old wait marker no longer unnecessarily holds it back.
- At most one explicitly uncached history task is scheduled per batch. The API's existing shared history gate, request budget, final listing checks, fees and trend checks still apply.
- Output shows seconds until the next history slot. The history-deferred count now includes blocked candidates found throughout the queue, so it may be larger than three. It does not count API requests or newly discovered candidates.

Discovery remains at a 15-second minimum between API requests, sales/chart history uses its existing shared 15-minute slot (or longer saved backoff), and evidence expires after one hour. No cooldown is shortened or reset. No increase in request budgets or concurrency is introduced.

This improves use of existing evidence. It cannot manufacture history for uncached markets, guarantee a qualifying alert, or guarantee no server rate limits. If every queued market lacks usable evidence, completed research remains constrained by history access. The queue can still outgrow research capacity; short-lived listings may sell before evaluation.

## Install

Stop with Ctrl+C. Copy this ZIP's CSFloat-Scout folder contents into the existing project folder and replace program files. Keep config.json, scout.sqlite3, request-state.json and logs. In the same configured PowerShell run:

```powershell
py -3 scout.py
```

Look for v4.6.1. No new credentials or configuration edits are needed. Broader paper-watch alerts and strict live protections from v4.6 remain.

132 offline tests pass. Regression cases cover blocked candidates not consuming research slots, pending charts receiving priority over new markets, multiple listings using a shared cache, saved cooldowns and request pacing, and existing valuation/purchase protections. No live requests or purchases were made during testing.
