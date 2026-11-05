# Amphibious personal paper monitor

Stop the main scanner with Ctrl+C. Copy this update into the same folder,
including config.json (now only user3@example.com), personal.py and
personal-config.json. Keep your databases, logs and quota/request-state files.
Both programs share the same lock and API pacing files; run only one at a time.

In PowerShell in the CSFloat-Scout folder:

```
py -3 personal.py --hours 24
```

For a fresh 12-hour session:

```
py -3 personal.py --hours 12 --new-session
```

Or double-click run-personal.bat for the default 24-hour session. Existing
sessions resume at their original end time, including time the PC was off.
After a completed session, use --new-session to start another. Ctrl+C saves
results and stops. The program must remain running and your PC awake to scan.

Open personal-report.html after the first cycle (or use open-personal-report.bat).
Refresh to see updates. The report ranks the best observed listing-price
versions, including offers that may since have sold or changed price. Every
entry has its last-seen time. personal-report.json provides the same data;
personal.sqlite3 retains session observations and evidence. No purchase occurs.

## Target and ranking

- Amphibious gloves, Minimal Wear (0.07–under 0.15) or Field-Tested
  (0.15–under 0.38). No other wear grades or gloves are accepted.
- $300 target, $500 hard ceiling for target matches, including configured
  acquisition costs. More expensive comparisons never authorize spending.
- At/below $300, a target match needs a 3% estimated sales-based discount.
  Above $300, the requirement starts at 10% and rises linearly to 20% at $500.
  These are initial adjustable rules, not proven bargain thresholds.
- Evidence-backed, budget-fitting offers rank first, then sales discount.
  Lower float within the wear grade adds at most 0.1 percentage point to the
  score. For example, 0.151 FT gets a slight preference over 0.30 FT, but a
  materially bigger discount wins. Lower float means less wear.
- Sales evidence uses the existing nonlinear float comparison and identity
  checks. At least two comparable sales in seven days, including one in
  three days, are needed for an evidence-backed target match. Missing evidence
  stays visible as unknown; the site's reference discount is not treated as
  independently verified value.
- This is a personal-purchase comparison. Savings compare acquisition cost
  with recent sale values; they are not resale profits. No seven-day resale
  holding-profit requirement or weekly chart request is made.

Every cycle requests up to 50 cheapest and 50 newest listings for each wear
grade, below the listing-price ceiling. It does not claim full-market coverage
or that the eventual best offer is still available. Requests obey shared
cooldowns and quota pacing; history is cached for an hour. Normal cycles pause
180 seconds after processing, so their total duration is longer than 180s.

## Email

Only user3@example.com receives new main-scanner alerts and personal
summaries when using the updated config. Pending receipts to removed recipients
are cancelled. The personal monitor sends a first summary when there are
observations, then at most hourly, plus a final report at the session end.
These are summaries of observed offers, not instant new-best alerts.

Use your existing CSFLOAT_API_KEY and SCOUT_SMTP_* environment variables in
the same PowerShell session. --no-email runs with local reports only. Failed
email sends leave the local report intact. Restarting a completed session can
retry a failed final email. All emails say no purchase was made.

Edit personal-config.json for budget/pacing preferences, or ask for a target
change. This initial version intentionally validates only Amphibious MW/FT.
It has no --live option and never calls the buy endpoint.

158 offline tests cover wear/price boundaries, ranking, flexible budgets,
unknown evidence, persisted sessions, reports, no-buy behavior and recipients.
