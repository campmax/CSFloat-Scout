# v4.7: use observed quota to pace research

Stop the running scanner with Ctrl+C. Extract this ZIP and replace the program
files inside your existing CSFloat-Scout folder. Keep scout.sqlite3,
request-state.json, quota-state.json (if present), and your logs. Start from that
folder with `py -3 scout.py`. This remains paper mode unless explicitly invoked
with --live. Do not delete state files to clear a cooldown.

## What the supplied log established

The successful listing responses reported a 200-unit quota, with a reset one
hour after the first logged response. History responses reported a 500-unit
quota with a reset approximately one day away. These are observed headers, not
a verified universal API contract or proof of separate account/IP quotas.

History remaining values were 499, 498 and 433. There were only three successful
history calls in that excerpt. The final drop and changed reset are unexplained:
other consumption, charging rules or server behavior cannot be distinguished
from this log. The scanner must react to actual remaining values.

## Behavior

- History sales and chart calls conservatively share a budget. Other reads
  conservatively share the observed listing budget. No new credentials or
  accounts are used.
- Reserve 10% of advertised capacity and add 15% spacing headroom. With the
  last logged balance (433 of 500) and roughly 23.4 hours until reset, estimated
  spacing is about 253 seconds: approximately 14 history requests/hour.
  This is not 14 fully validated candidates/hour: sales and charts can each
  consume a request. Reused evidence can validate multiple candidates without
  another history call.
- Headers can lengthen or shorten the fallback 900-second interval after the
  next successful history response. The existing pending slot is preserved on
  upgrade. No usable headers means the conservative fallback remains.
- Persist quota consumption and next request deadlines in quota-state.json.
  Missing headers still consume local budget. At reset, allow a probe, not an
  invented fresh balance. Unexpected quota increases cannot replenish an
  unexpired local bucket; decreases take effect immediately.
- Server cooldowns, Retry-After, and history backoff after a 429 take precedence.
  A previously increased history backoff is preserved; this release does not
  clear old restrictions just to make the displayed rate faster.
- Keep shared cached evidence, runnable-first scheduling, float normalization,
  weekly risk checks, and purchase safeguards. Deal thresholds are unchanged.

The console now reports remaining history quota and estimated request spacing.
Keep runtime-events.jsonl and scan-stats.jsonl for the next review. The estimate
does not guarantee zero 429s: response headers may omit other server limits or
consumption by other clients. Do not run multiple scanner instances.

Validation: 140 offline tests passed, including actual API-wrapper propagation
of mocked response headers, shared sales/chart pacing, quota drops, missing
headers, persistence, reset probes, invalid headers and cooldown precedence.
No live API requests, purchases or emails were made during testing.
