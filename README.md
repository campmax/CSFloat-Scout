# CSFloat Scout

Python market scanner with comparable-sales valuation, persistent research queues, request pacing, alerts and paper portfolio tracking.

# Current release: v5.0 — paper portfolio

Read **PAPER-PORTFOLIO-V5.md** first. It supersedes the historical release notes below. This version adds prospective paper buys with $1,000 virtual starting cash, competitive resale estimates, narrow direct-float liquidity checks, cash/hold/settlement tracking, and paper-buy emails. Immediate opportunity emails and hourly reviews continue. The personal monitor is unchanged. No additional market requests are introduced.

# Current patch: v4.6.1

Read QUEUE-FIX-V461.md. Selects runnable candidates before applying the research limit, gives pending chart completion priority over new history work, and lets listings share cached evidence in the same batch. Request spacing and cooldowns remain intact. 132 offline tests pass.

# Previous release: v4.6

Read HISTORY-PACING-V46.md. Paper discovery returns to a 15-second minimum, while history and charts share a separate 15-minute request slot and an hour-long evidence cache. Existing cooldowns are preserved. Broader paper-watch alerts require recent sale evidence and label downside losses. This supersedes older timing/threshold instructions below. 129 offline tests pass.

# Previous release: v4.5

Read SLOWER-SCANNING-V45.md. Adds a slower paper profile that also applies with existing configuration, prioritizes newest posting times and observed market liquidity, backs off unchanged side feeds, and reports discovery yield and rejection reasons. Retains the $20 minimum, valuation model, alerts, request budget and durable cooldown. 122 offline tests pass.

# Previous patch: v4.4.2

Fixes script-entry-point class identity so the paper API request budget is actually enforced when launched with `py -3 scout.py`. Prints actual API requests per cycle. Continuous paper mode waits through a saved HTTP 429 cooldown, with a minute-by-minute status message, then resumes scanning. Read RECOVERY-V442.md before installing. Retains configuration and earlier valuation/discovery features.

# Previous patch: v4.4.1

Adds recovery for rejected saved pagination cursors (HTTP 409) and request-category error logs. Retains all v4.4 settings and features. Keep your existing configuration when installing this patch.

# Current release: v4.4

Read OPTIMIZATION-V44.md first. It supersedes older scheduling and float uncertainty instructions below. Starts in paper mode at a $20 minimum; retains earlier features.

# Update: v4.3 newest-first scanning

Read DISCOVERY-V43.md for installation and schedule changes. The supplied config starts at $20. All v4.2 float-model features are retained.

# Update: v4.2 float comparisons

See FLOAT-MODEL.md for the model, limits and installation instructions. No additional dependencies or API calls.

# CSFloat Scout

Start with START-HERE.md for the current Windows update instructions, paper thresholds and coverage limits.

A staged API scanner: discover recent listings, cheaply screen possible discounts, research comparable evidence, and log decisions. Default mode is paper-only. Live buying requires explicit enablement and remains unverified end-to-end. Never run multiple instances against the same account.

## Files

- scout.py: API adapter, valuation, purchase guards and CLI.
- scanner.py: paginated discovery, persisted queue/cache and paper profiles.
- scheduling.py: balanced paper research and temporary empty-evidence cooldowns.
- discovery.py: bounded newest, ranked-deal and focus feeds.
- runtime_log.py: persistent lifecycle/error metadata without exception bodies.
- diagnostics.py: read-only reports using the active paper evidence rules.
- review.py: permissive paper-only leads with explicit risk warnings.
- risk.py: weekly chart checks and stress calculations.
- email_alerts.py: opportunity alerts and durable confirmed-purchase receipts.
- config.json: strict live settings plus separate paper settings.
- tests/: 81 offline unit tests.

Run `python -m unittest discover -s tests -q` from this folder to verify locally.

SETUP-V2.md contains SMTP setup details. PURCHASE-EMAILS.md describes receipt handling. Where older documents differ on scanning, balance checks or thresholds, START-HERE.md is authoritative.

Pricing, fees, available API routes and platform rules can change. Configured fees are assumptions to verify before any live use. Do not bypass platform restrictions or raise request frequency to evade rate limits. Neither profitability nor absence of account restrictions is guaranteed.
