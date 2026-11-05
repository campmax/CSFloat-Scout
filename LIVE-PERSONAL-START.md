# Personal v2.2.1 — one real Amphibious purchase

Stop the running scanner with Ctrl+C. Extract the updated ZIP, then copy the contents of its CSFloat-Scout folder into your existing folder and replace code/config files. Keep personal.sqlite3 and all other databases, logs, and quota/request-state files. Run only one scanner.

Start a new 24-hour LIVE session in the PowerShell window with your API key and SMTP environment already set:

```powershell
cd "C:\Users\USER\OneDrive\Desktop\CSFloat-Scout"
py -3 personal.py --new-session --hours 24 --live
```

This authorizes ONE real purchase of Sport Gloves | Amphibious (Field-Tested), with all of:

- API-reference markdown at least 10%, using predicted_price when valid, otherwise base_price. This is not necessarily the percentage displayed on the website, and not a profit estimate.
- Float from 0.15 through 0.20 inclusive.
- Price and estimated total cost, including configured buying fees, no more than $330; sufficient available CSFloat balance.
- Fresh listing-detail check showing the same item still listed, no price increase, still within all limits.

The first matching verified candidate can be bought immediately; this does not wait until the end of the day. Broader MW/FT reports up to $500 continue, but those reporting settings cannot expand live buying limits. Recent-sales support and weekly trends are informational for this personal-use purchase, not additional live gates.

Exactly one order attempt is durably reserved in personal.sqlite3 before sending it. After success OR an uncertain result, buying remains locked even after --new-session or restarting. Reports keep running. Do not delete the database or manually clear the lock; first reconcile any unknown outcome in CSFloat. There is no automatic purchase retry, no automatic second pair, and no Steam trade acceptance automation.

Successful acknowledgment plus observed balance debit prints PERSONAL LIVE PURCHASE: confirmed and emails user1@example.com. An uncertain outcome also generates an email with instructions to check your account. Receipt failures are saved for later retry. Read personal-live.json for the saved order status. An acknowledged/confirmed order does not confirm Steam delivery: check the actual item in the seller's trade and accept manually.

Ctrl+C stops the program. A file named STOP in the scanner folder also stops it, including a check immediately before order submission. Neither can cancel an order already sent. The existing rate limits, quotas, spacing, and cooldowns remain active; they can delay discovery or prevent capture.

Without --live, the program remains paper-only. Paper entries now use 10%, float 0.15–0.20, and a $330 listing-price ceiling; the live path also includes configured costs. Historical paper entries stay in their existing reports.

Test email (does not purchase):

```powershell
py -3 scout.py --test-email
```

Implementation was verified with mocked API/SMTP tests, including bounds, price/item changes, insufficient funds, failures, restart lock, and receipt retry. No real-money transaction was used as a test. The existing purchase endpoint/response contract is reused; a changed API or ambiguous response leaves buying locked for manual reconciliation. Public official API documentation did not establish the purchase endpoint contract during this update.
