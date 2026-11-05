# Latest: Main Scout v5.3 sold tracking

Red SOLD labels, 15-minute retention in place, and a persistent graveyard sorted by price × API markdown. Restart scout.py and reload the page after installing. Keep scout.sqlite3. Read PROSPECTS-START.md for probe pacing and timing limitations.

# Latest: Dashboard v5.2.1 arrival highlights

New prospects pin first for 15 seconds: solid white for 10, then fade for 5. Other cards no longer flash when they move. A floating new-listings notice appears when scrolled down. Reload your browser once after installing the HTML update.

# Latest: Dashboard v5.2

Four columns, larger text, compact fields, live ages and fading change outlines. Restart the scanner and reload the browser once after installing. Read PROSPECTS-START.md.

# Latest: Main Scout v5.1 minute prospects and dashboard

Read **PROSPECTS-START.md** for minute emails and the live local top-20 page. Personal v2.2.1 still has the 10% / $330 / float 0.15–0.20 one-pair live rule.

# Latest: Personal v2.2.1 live option

Read **LIVE-PERSONAL-START.md** first for the new one-pair $330 / 10% / float 0.15–0.20 live mode. Plain personal.py still runs paper-only. The notes below describe earlier versions.

# Combined update: Personal v2.0, Radar v1.5, listed times in all three

Stop every scanner with Ctrl+C. Copy the contents of this ZIP's CSFloat-Scout folder into your existing CSFloat-Scout folder and replace matching program/configuration files. Keep all existing databases, logs, request-state.json and quota-state.json: none are shipped or reset by this update. Do not delete your folder. This package includes the main scanner's v5 paper portfolio and previous nonlinear comparison code.

All recipients are user1@example.com. Keep your existing SMTP/API environment settings. Only run one scanner at a time, as before.

```powershell
cd "C:\Users\USER\OneDrive\Desktop\CSFloat-Scout"
py -3 radar.py --test-email
```

Run ONE of these:

```powershell
py -3 radar.py
py -3 personal.py --hours 12 --new-session
py -3 scout.py
```

Personal and Radar are read-only. The main scanner still defaults to paper mode; this update does not enable live purchases.

## Findings from your uploaded files

Radar v1.4 did not send only once: the provided console segment contains 48 SMTP-accepted minute reports, 29 with picks, totaling 63 picks. Nineteen were empty. Its per-cycle zero-email counter counted a disabled legacy sender, not minute emails. SMTP acceptance cannot prove inbox arrival. The new console labels distinguish them.

Personal was configured for one email per hour. It now summarizes every five minutes, including an explicitly unchanged shortlist or an empty status if needed. A changed top-five ID/price/reference shortlist can notify after at least 60 seconds, on the next completed cycle. A cycle still has network/quota waits, so this does not promise instant discovery. SMTP failure retains bounded retry spacing.

Radar's 60-second candidate window expired between its 90-second pauses plus requests. It now retains unsent observations for ten minutes, marks their observation age, and continues persistent same-price deduplication. Reports remain scheduled each minute independently of API waits. Items older than five minutes carry a stale-availability label. Known missing recent sales and sparse references remain explicit screening reasons. No forced fake deal is sent in an empty period.

Personal used only lowest_price and most_recent queries. It now checks best_deal and most_recent for both MW and FT, lowest_float within FT up to 0.20, plus a rotating lowest_price query. Six discovery requests at most, with two remaining slots in the existing eight-request budget for history. History remains cached and quota-paced. Deferred history no longer overwrites prior evidence with zero sales. Saved evidence timestamps remain available.

## Listed time, observation time and availability

All three now retain API created_at, list an explicit UTC creation time, and show listing age. The main immediate/hourly emails, shortlist, paper-portfolio reports and receipts include it; so do personal email/HTML and Radar email/HTML. JSON records retain creation metadata. Missing or invalid creation time is UNKNOWN: never substituted with first_seen. Old stored records can remain unknown until observed again.

Creation time describes the current listing, not prior relistings. Observed age and history age are different facts. No listing disappearance is treated as a completed sale. Email/HTML ages describe generation time, not a live clock.

## Revised Amphibious preference

Personal ranking uses API predicted-price markdown (base reference only when predicted is absent), displaying sales-estimate discount separately. Exact website badge parity is not established. Reference markdown is a lead, not proven savings or profit. Sparse history, float model uncertainty and previous warnings stay visible.

A near-MW FT means float 0.15–0.18 by default. It can move ahead of the top markdown only when within THREE percentage points of that markdown and not dominated by a cheaper, lower-float observed FT listing. Outside that window, markdown wins. MW can receive this preference at at least 8% reference markdown, still within the same three-point window. Hard ceiling remains $500; $300 remains the target. The stricter sales-model budget/target flags are displayed separately and do not suppress the manual-review shortlist.

Reports use one latest price per listing, observed within 15 minutes. Old versions stay in the database but no longer crowd the current shortlist. Float is a wear proxy; inspect knuckles/pattern visually before buying. These Amphibious preferences should be changed before adapting the monitor to another item.

Tunable personal-config.json settings: preferred_ft_max_float, preferred_ft_search_max_float, preference_discount_window, mw_exceptional_discount, email_interval_seconds, freshness_seconds.

## Your five examples, using the uploaded snapshot

| Listing ID | In saved observations? | Finding |
|---|---|---|
| 1032151125144502576 | No | Live page lookup inaccessible; cannot establish price/float or why absent. |
| 1032419332807854130 | No | Same limitation. |
| 1032748704668454292 | Yes | $247.16, float 0.26444, reference markdown 5.77%, sales-estimate discount 0.17%. |
| 1024599660972608996 | No | Same limitation. |
| 1032081439455315920 | Yes | $245, float 0.27330, reference markdown 3.97%, sales-estimate discount 1.05%. |

These two had stronger reference markdowns than the former top recommendation ($295, 0.21491, 2.28% reference markdown), but not stronger sales-estimate discounts. Discovery and valuation are separate issues. The absent three cannot honestly be declared better based on this evidence.

Replaying the uploaded snapshot with the new preference ranks:

1. 1032654554187040308 — $381, 0.15149 FT, 4.21% API-reference markdown.
2. 1032565630647273092 — $380, 0.15364 FT, 3.00% API-reference markdown.
3. 1032748704668454292 — $247.16, 0.26444 FT, 5.77% API-reference markdown: cheaper alternative.

These are historical observations, not current availability checks or purchase recommendations. No MW observations appeared in that uploaded personal snapshot. The new best-deal discovery may improve coverage, but does not guarantee any sub-$500 MW exists.

## Verification

Offline tests mock SMTP and API calls. Main/personal suite and Radar suites pass. No real requests, emails or purchases were executed during validation. Live discovery results, website badge equivalence and inbox delivery are not verified by those tests.

## Personal v2.1 — 9% prospective paper entries

Existing shortlist ranking, five-minute summaries, low-float preferences and main/Radar behavior remain. A separate personal-paper trigger now examines every discovered acceptable Amphibious MW/FT listing under the $500 ceiling before history research. At 9% or greater API reference markdown it saves a candidate, then makes a paced detail read. At most two detail checks/cycle share the existing eight-request budget; history or later discovery may defer when the budget is used. It does not increase the request allowance or bypass cooldowns.

A simulated entry is recorded only if the detail response still shows the same item active at no higher price, still within budget, with at least 9% markdown. Float preference and sales support are NOT admission gates for this initial collection experiment. The threshold uses predicted_price when available, otherwise base_price. This is API-reference markdown, not verified equivalence to the displayed CSFloat badge.

`personal-paper.html` and `personal-paper.json` show all prospective captures, checks, reference source, listing time, float, price and discovery-to-check latency. A qualifying detail response is labeled PAPER BOUGHT / still listed at check, never guaranteed execution. The scanner submits no order and reserves no funds or item. Another buyer could win immediately afterward. Changed/sold responses are marked missed_or_changed; errors or quota waits remain unverified. Disappearance alone never proves a sale. Pending observations expire after ten minutes without reobservation. No trade-outcome or resale-profit claim is made.

Each resolved paper event gets a separate email to user1@example.com, independently of the normal summary. Delivery failures retry after at least five minutes. Confirmed paper entries persist and deduplicate per listing ID across restarts/new sessions; keeping the database avoids repeat fake purchases. No live purchases are enabled. To collect overnight:

```powershell
py -3 personal.py --hours 12 --new-session
```

The number of 9% opportunities is market-dependent; there is no promised count or cadence. Polling, limited pages, request spacing and quotas can miss short-lived deals. Share personal-paper.json plus personal-report.json after the first few captures to assess float suitability. `paper_buy_markdown` in personal-config.json controls this paper-only trigger.
