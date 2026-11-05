# v4.5: slower requests, better candidate selection

## Install

Stop the scanner with Ctrl+C. Extract this ZIP and copy the files inside its CSFloat-Scout folder into your existing folder, replacing program files. Keep your database, logs, request-state.json and customized config.json. The slower paper profile applies to older configs automatically. Restart in the same configured PowerShell:

```powershell
cd "C:\Users\USER\OneDrive\Desktop\CSFloat-Scout"
py -3 scout.py
```

Look for v4.5. Existing rate-limit cooldowns remain in force. The supplied configuration remains paper-only.

## Changes

- Paper mode has a minimum 60-second interval between requests, retaining any longer interval already saved after a rate limit. It waits at least 60 seconds between cycles, allows at most eight API requests per cycle, and researches up to three candidates per cycle. These are local limits, not confirmed CSFloat quotas.
- Newest discovery retains up to three pages per pass and checks the newest page between research tasks when five minutes have elapsed. It follows returned cursors only; pages retain the existing 50-item request size.
- Ranked deals run no more often than every 15 minutes, focus searches every 30 minutes, with at most one page per side feed. A feed returning no new or repriced listing versions doubles its interval, up to eight times its normal interval. New versions reset that backoff. Secondary searches still defer when the queue is busy.
- Newest candidates use their posting time for priority. Previously, older pages discovered later could incorrectly jump ahead of newer postings.
- Within each feed, observed recent sales activity improves research priority. Unknown markets remain eligible for exploration; every fourth scheduling turn still considers older candidates. This uses existing evidence, adds no API requests, and does not substitute for float/price validation.
- Paper research can reuse a listing snapshot up to three minutes old. Any qualified alert still requires a final detail request and re-evaluation. Live-mode freshness rules are unchanged.
- Historical pagination chains older than 30 minutes, or beyond eight retained chains at the start of a discovery pass, are retired with an explicit coverage-gap count. Their cursor records are archived in the database (latest 128). This deliberately trades exhaustive old-inventory traversal for fresh discovery; it does not claim full coverage.
- Each completed scan prints research rejection reasons, average new IDs per discovery request, unchanged versions skipped, request usage and saved requests.

The profile is enabled by default through slow_paper_mode=true. It only changes paper runtime settings, leaving the live configuration untouched. Existing custom settings slower or smaller than these bounds are retained. paper_snapshot_seconds defaults to 180. The $20 minimum, nonlinear float model, fees, weekly risk checks, purchase safeguards, paper qualification thresholds and email recipients are unchanged.

## What the supplied logs show

The latest 220 recorded evaluations in paper-review(8).jsonl contain:

| Outcome | Count |
|---|---:|
| Insufficient comparable sales | 105 |
| Sold, withdrawn or repriced before evaluation | 74 |
| Insufficient completed sales above fee-adjusted break-even | 36 |
| Final discount/trend requirement not met | 5 |

Of the 105 insufficient-evidence outcomes, 60 had zero accepted comparable sales and 80 had zero accepted recent sales. Several history samples span months or years despite returning 40 rows. The historical API sample is not a complete market-sales record, so missing evidence cannot establish that no trades happened.

Across all 631 supplied decisions, 443 failed evidence requirements (including an older stricter rule). These records span different program versions and are not a controlled test. Lowering the final discount alone cannot repair missing evidence or stale candidates. The change therefore targets freshness and the use of limited research requests rather than labeling unsupported listings as profitable.

## Validation and limits

122 offline tests pass, including actual CLI request budgeting and cooldown recovery, posting-time ordering, liquidity prioritization, old-config migration, unchanged-feed backoff, repricing detection, cursor retirement with coverage reporting, and existing valuation/purchase protections. No live API calls, emails or purchases were made during validation.

Slower scanning can miss short-lived deals. There is no guarantee of finding deals, resale profit, uninterrupted access, or account safety. A completed scan is the point at which its latest statistics appear; rate-limited scans can end before those statistics are written. Keep runtime-events.jsonl, request-state.json, scan-stats.jsonl and paper-review.jsonl for the next diagnosis, without sharing API keys or email passwords.
