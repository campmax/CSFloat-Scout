# Main Scout v5.2 — minute prospects and local dashboard

Stop the current scanner with Ctrl+C. Extract the updated ZIP and copy its CSFloat-Scout folder contents into your existing folder, replacing code/config files. Keep all your runtime databases, quota files and logs.

Run the MAIN scanner in the existing PowerShell window that has your API key and SMTP settings:

```powershell
cd "C:\Users\USER\OneDrive\Desktop\CSFloat-Scout"
py -3 scout.py
```

Open http://127.0.0.1:8765/ in a browser on the same PC. The startup banner also prints the link. The page works only while the main scanner is running. You can open it with open-prospects.bat. Only localhost is bound, and the server exposes the dashboard and its sanitized report JSON; no configs, databases, credentials, or purchase endpoints are served.

The main scanner stays paper-only with this command. Its existing hourly reports, opportunity emails and paper portfolio remain. Personal live buying still requires its separate personal.py --live command. The shared process lock permits only one scanner at a time: stop the personal monitor before starting the main scanner. This update does not reset a saved personal purchase lock or change its 10%, $330, float 0.15–0.20 rules.

## Minute emails

Every 60 seconds, an independent local reporter sends up to 10 current positive API-reference markdowns to user1@example.com. It reads existing discovery snapshots, so it does not wait for candidate research or use more CSFloat API requests. It includes unresearched prospects even when normal research eligibility is not met. These are leads to investigate, not purchase approvals.

The subject remains constant; Message-ID, In-Reply-To and References headers request a single conversation across restarts. Your email app controls final grouping. Each email shows the current list, so repeated unchanged listings are intentional. Empty reports state that no fresh positive markdowns are available; it will not fabricate ten results. Rate limits or discovery pauses may leave a minute with no new observations.

## Dashboard

Top 20 observed positive markdowns are ranked by API predicted reference when valid, otherwise base reference. These percentages may differ from the website badge and do not represent ROI. The dashboard can filter by skin name or researched status, and sort the displayed top 20 by ROI, recency or price. It is not a market-wide search.

The browser checks local report data every five seconds without refreshing the whole page. Updates pause when your mouse is over the cards, a card link has keyboard focus, or text is selected. Pause updates freezes the cards; Refresh now applies the latest cached report manually. Scroll position is retained, and links open CSFloat in another tab. Local refresh does not trigger a CSFloat request.

Each card/email contains price, reference markdown, float/pattern if supplied, original listing time and age if supplied, last observed time, and existing same-price research: modeled net/ROI, downside estimate, sales counts, evidence timestamp, assessment and warnings. Unknown values remain unknown. Cached sales figures describe the model's comparable evidence, not total market volume. ROI uses the existing modeled net divided by its acquisition cost; no new model or research calls are added.

Only snapshots observed within 15 minutes are eligible. Latest observed price per listing wins; earlier price versions and known sold/inactive assessments are excluded. Discovery is sampled and incomplete; a listing can sell before the next report. A bounded pool of up to 2,000 recent snapshot rows is considered, with one row per listing in output. Repeated sightings update last-seen time. Listing time always comes from created_at, never from first discovery.

prospects-latest.json stores the latest cached list. prospects-state.sqlite3 stores email threading and pacing. Existing hourly output still works. If port 8765 is occupied, the scanner prints a warning and keeps emailing; close the conflicting local server and restart if you want the dashboard.

## Validation

220 offline tests passed, including purchase safeguards and new prospect filtering, recency, same-price evidence, email threading/pacing, failures and dashboard route restrictions. JavaScript syntax checked. API calls and SMTP sends were mocked in tests; no real order or email was sent during development.

## Dashboard v5.2

Four columns on screens at least 1200 CSS pixels wide, two on medium screens and one on phones. Cards use larger text and five decimal places for float; missing ROI, net, downside, sales and pattern/float fields are hidden. Listing date is local month/day with a live age. Seen age ticks each second and turns amber after five minutes; expired sightings are marked if the view is paused. The report age and newest sighting age are shown separately.

New, moved and materially changed cards get a white outline that fades over nine seconds. Routine timestamp updates do not trigger it. Card nodes are kept stable across refreshes. Reduced-motion settings suppress animation. The assessment accordion is removed; researched ROI retains a short estimate caveat with any detailed warnings available on hover.

After installing, restart scout.py and reload the browser once to load the new interface. Future report updates are automatic.

## Dashboard v5.2.1 arrivals

Only newly seen dashboard listing IDs get a white outline. The first loaded list is the baseline; reordering, changing metrics, and rediscovering an already seen ID do not flash the cards. New visible prospects are temporarily placed ahead of the selected ordering: white outline for 10 seconds, fade for 5 seconds, then return to the selected sort. Several simultaneous arrivals use the selected order within their pinned group. The timer starts when the card is first displayed, so paused updates do not consume it. Reordering waits if updates are paused or you are interacting with the cards.

A floating newly seen listings button appears when scrolled down. Click to apply pending updates and return to the top. Scroll anchoring tries to keep the card you were reading in the same viewport position. New means new to this open dashboard session, not necessarily newly posted on CSFloat. Seen age describes the last API sighting, not competitiveness or confirmed availability.

## Main v5.3: availability probes and sold graveyard

Restart scout.py after installing this version, then reload the browser once. Keep scout.sqlite3: it now also holds the durable prospect-status and sold archive tables. The personal live-buy rules remain unchanged.

A newly displayed prospect becomes eligible for an availability check after 60 seconds. Checks run sequentially through the existing authenticated API client, at most one per main scan cycle and at least 60 seconds apart. They consume a slot within the existing cycle request budget, after newest discovery and before research; they may reduce research throughput by one request per cycle. The normal spacing, quota waits and rate-limit cooldown apply. With 20 cards, not every item can be checked in the first minute. A still-listed item becomes eligible again five minutes after its check. Availability check pending means no completed probe yet. Retrying a failed read waits five minutes; HTTP 429 or access failures use the existing scanner stop/cooldown handling.

Existing listing-detail responses used for research also update tracked status at no extra request cost. There are no API calls from the web page and no purchase behavior in these checks.

Only a matching listing ID with API state sold is labeled SOLD. Missing listings, HTTP failures, and other states do not establish a sale. Those retain an unknown/unavailable explanation. Confirmed sold cards get red SOLD text beside the title without reducing other text. They stay in their current grid slots even as new cards arrive; sold-card slots override sorting and arrival placement until retirement. When filters hide cards or the grid has fewer items, positions may necessarily change. No exact viewport/card size is promised across screen sizes.

Sold cards are retained for 15 minutes from the first confirmed observation, then become VOID and leave the main grid at the next applied update. If the view is paused or held while you interact, retirement waits for updates to resume. The highest remaining observed options fill the available slots. VOID means removed from the active grid, not a cancelled transaction. Reloading the page restores the backend default positions; per-browser sort/positions are session-local.

The separate graveyard retains all confirmed sold links and observed prices in scout.sqlite3, including after they become VOID. Sort by highest markdown value (default), latest confirmation, or highest percentage. Markdown value is exactly observed listing price × observed API markdown, rounded to cents. It ignores fees as requested; it is not profit and not the reference-price-minus-ask calculation. The observed price is not independently verified as the final transaction price. Download archive exports the current graveyard JSON.

Timing shows first tracked → sale confirmation and last seen listed → sale confirmation. Those are observational intervals, not exact time to sell. A valid API sold_at is shown separately when supplied. The 15-minute display timer uses confirmation time so delayed discovery does not make the card instantly disappear.

228 offline tests passed including new availability timing, quota/budget handling, uncertain responses, exact-ID matching, sold retention and persistent graveyard checks. Browser ordering logic tested for sold-slot preservation during new arrivals and sorting. No real API requests, purchases, or emails were made during development.
