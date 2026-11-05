# v4.4.2: request budget and paper cooldown recovery

Running scout.py as a script previously created a second copy of its API and exception classes when scanner modules imported scout. As a result, the paper request-budget type check could fail and exception handling could miss pagination/budget exceptions. The CLI now registers one shared module before those imports. A subprocess regression test exercises the actual script entry point.

Completed paper scans now print `API requests: N/12 cycle budget; minimum spacing 30s.` Numbers reflect your configuration and saved pacing. All API calls during a scan, including failed calls and research, consume this budget. This is a local work limit, not a claim about CSFloat's permitted quota.

## Install

1. Stop an existing scanner with Ctrl+C.
2. Extract this ZIP and copy the files inside its CSFloat-Scout folder into your existing CSFloat-Scout folder. Replace program files, including scout.py, scanner.py, request_policy.py, and tests. Keep your existing config.json if you customized it.
3. Keep scout.sqlite3, request-state.json, logs, and other runtime data. In particular, do not delete the saved rate-limit cooldown.
4. In the same configured PowerShell window, run:

```powershell
cd "C:\Users\USER\OneDrive\Desktop\CSFloat-Scout"
py -3 scout.py
```

The banner should say v4.4.2. A saved cooldown may produce a waiting message immediately; that is expected.

## Recovery behavior

- Continuous paper mode pauses after a read receives HTTP 429. No API requests are sent during the saved cooldown. It waits at least an hour, or longer if the server's Retry-After requires it, and keeps the slower saved request spacing.
- It reports remaining time once per minute and writes waiting_rate_limit to status.json. Ctrl+C or a STOP file can end the wait. After the cooldown it begins a new scan, retaining the queue and discovery state.
- A restart respects the same saved cooldown. Restarting repeatedly does not shorten it.
- Another 429 causes another full cooldown and increases request spacing under the existing pacing policy. Do not run another scanner against the account while waiting.
- Authentication/access failures (401/403), live mode failures, purchase requests, and --once do not automatically resume. Live buying remains disabled in the supplied config.

The $20 minimum, newest-first discovery, cached evidence, nonlinear float comparisons, fee/trend checks, paper alerts and email settings are retained. No eligibility thresholds were changed in this patch. API rate limits depend on the service; this fix cannot guarantee uninterrupted scanning or absence of account restrictions.

Validated with 117 offline tests, including CLI budget enforcement, saved cooldown on restart, Retry-After waiting, authentication failures and interruptible waiting. No live CSFloat requests or purchases were made during testing.
