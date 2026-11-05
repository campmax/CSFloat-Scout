> Historical setup reference. See START-HERE.md for current scan behavior, paper thresholds and update instructions.

# Purchase receipts and platform restrictions — v4

## Your two recipients

`config.json` now contains:

```json
"email_enabled": true,
"email_recipients": ["user3@example.com", "user1@example.com"]
```

These are the exact addresses you supplied. Each receives a separate message. Sender SMTP credentials are still required locally; destination addresses alone do not enable delivery. `SCOUT_EMAIL_TO` is no longer used: edit `email_recipients` if you want to change destinations. Do not publish this personalized config without removing your email addresses.

Follow the SMTP setup in `SETUP-V2.md`, then run:

```powershell
py -3 scout.py --test-email
```

That command sends real test emails when you run it with working credentials. No email was sent during development. The demo still works without SMTP credentials. Ordinary scans now require email configuration because email_enabled defaults true. You can set it false for paper-only terminal output; live mode requires it true.

## Automatic purchase workflow

1. All deal, risk and account-balance checks pass.
2. Bot submits ONE purchase request.
3. CSFloat returns the recognized success acknowledgement, and the account debit is visible.
4. Purchase confirmation and a receipt for each address are committed together to SQLite.
5. Bot sends separate emails to both destinations.
6. You wait for the seller's Steam offer, verify the item, and accept manually.

Subject: **CSFloat purchased: [item name]**

The email contains the listing, paid listing price, timestamp, link, and explicit instructions not to buy the item again. A receipt confirms acknowledgement and observed debit only; it does not confirm delivery or profit. There is no incoming-Steam-offer detector. You still need to monitor Steam/CSFloat for the actual offer.

A failure delivering to one address does not prevent attempting the other. Each successful recipient is marked sent. Failed or interrupted deliveries are retried after at least five minutes at the next scan entry or after a subsequent purchase. Receipt retries have no attempt cap and are not suppressed by opportunity-email limits. They survive a restart if you keep `scout.sqlite3`.

To retry due saved receipts without accessing the market or buying:

```powershell
py -3 scout.py --flush-purchase-emails
```

The process must be running for retries; this is not a hosted email service. SMTP acceptance does not guarantee inbox placement, speed, or delivery. A timeout after the mail server accepted a message can cause a duplicate email on retry. It never causes a duplicate purchase.

If the purchase response or debit is uncertain, the bot stops with an unknown reservation and does not send a success receipt. Check CSFloat purchase history before taking any manual action. An interruption between a server-side purchase and local acknowledgement also requires reconciliation; never assume no receipt means no purchase.

## Ban/flag risk: no guarantee

No bot implementation can guarantee that CSFloat or Steam will never flag, restrict or ban an account. Automated-buying permission for this specific workflow has not been established. Live account integration remains unverified. Do not interpret passing unit tests, use of an API key, or a fixed delay as approval from CSFloat.

Official developer support states rate limits are per endpoint and observable through response headers. This program has a fixed minimum delay, not a fully verified endpoint-specific quota scheduler. It now halts on HTTP 401 (authentication), 403 (access denied) and 429 (rate limiting) in both modes, with no automatic retry. Do not repeatedly restart to get around these responses.

The bot uses API requests, never browser clicking, CAPTCHA solving, rotating accounts/proxies, or concealment. It does not automate Steam login, trade acceptance or confirmations. These choices reduce avoidable account/security risks but cannot remove platform-policy risk or market losses.

Before enabling real purchases, obtain confirmation from CSFloat support that your developer key is permitted to poll these endpoints and submit automatic purchases, and what endpoint-specific request limits apply. This has NOT been done by this project, and we have not contacted support on your behalf. If avoiding all possibility of account restriction is a hard requirement, this bot cannot satisfy it. Manual purchases with automated scanning can also involve API-use restrictions.

References checked October 16, 2026 UTC:
- https://csfloat.com/support/wizard/4 — developer API and per-endpoint rate limits
- https://csfloat.com/terms-of-service — current terms, API usage and automated-access restrictions; full page was not accessible to the research tool, so no blanket permission is asserted

## Deals and verification

Amphibious listings shown sold at 10% off are useful leads, but they do not establish the frequency of deals passing an independent 20% discount plus weekly-risk checks. Defaults remain unchanged. Changing min_discount to 0.10 alone would still leave the $25/8% stressed-profit and crash requirements in force.

36 offline tests pass. New tests verify separate receipt delivery, persistence across restart, retrying only the failed recipient, explicit delivery disclaimers, and stopping on 401/403/429. All SMTP tests are mocked. No actual email, purchase, or account login was performed during development.
