# Public source release

Python 3.11 or newer. Uses the Python standard library.

Email is disabled in the included configuration. Set your own CSFLOAT_API_KEY in the process environment for live API access. SMTP settings use SCOUT_SMTP_HOST, SCOUT_SMTP_USER, SCOUT_SMTP_PASSWORD and SCOUT_EMAIL_FROM. Keep credentials outside version control.

Offline demo command: python scout.py --demo
Offline tests: python -m unittest discover -s tests

Local observations, portfolios, databases, reports, backups and caches are excluded. Historical release documentation is included.

Set SCOUT_EMAIL_TO for the dashboard and optional summary alert recipient. The personal monitor uses email_recipient in personal-config.json. Enable email deliberately after configuring your own SMTP account.
