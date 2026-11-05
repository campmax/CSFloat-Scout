# v4.9.1 — immediate opportunity emails and hourly recaps

Every newly validated eligible paper opportunity is now emailed immediately to
user3@example.com. No first-hour warm-up, previous-hour cutoff, two-alert
ceiling or ten-email daily ceiling applies to these opportunity alerts.
The hourly recap continues. Provisional/rejected entries are recap observations,
not instant validated-opportunity alerts. Personal monitor files are unchanged.

The supplied archive had one supported observation (Duct Tape, estimated net
$0.60) and four provisional observations. Later logs showed a passed Asiimov
with estimated net $4.97. These are modeled values, not confirmed profits.
No new 429 appears in the recent run; request pacing is preserved.

Deduplication persists by listing and price. An equal or higher price does not
repeat a successfully accepted email. A lower price may alert again if it passes
a fresh evaluation. SMTP acceptance is logged as opportunity_email_accepted;
delivery into your inbox cannot be guaranteed by SMTP acceptance alone.

Failures are logged without credentials. Up to three total attempts within
15 minutes are allowed, at least five minutes apart, and each retry requires
a fresh eligible evaluation. A crash during delivery can leave acceptance
uncertain, so an occasional duplicate is possible. No purchase is retried.
Expired/sold/changed listings cannot be sent from a stale email queue.

New decision records include discovery_to_decision_seconds for measuring
research latency. No additional polling, credential rotation, or rate-limit
override was added. Server cooldowns and quota reserves remain enforced.

## Overnight run

1. Ctrl+C to stop the running scanner.
2. Replace program files with this update; retain databases, logs, request-state
   and quota-state files. Keep your existing PowerShell environment settings.
3. Run `py -3 scout.py --test-email`, then `py -3 scout.py`.
4. Confirm the v4.9.1 banner. Keep Windows awake and PowerShell open.

The main scanner runs until stopped. It uses CSFloat request quota and SMTP,
not OpenAI API tokens. No remaining AI-token balance is needed overnight.
It cannot guarantee a listing will remain available until an email is read.

165 offline tests passed, including uncapped first-hour alerts, persistent
deduplication, lower-price alerts, failed-send limits and hourly recap retention.
No live API requests, purchases or emails were used for validation.
