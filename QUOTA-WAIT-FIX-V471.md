# v4.7.1

Listing quota waits now have their own exception and console message. They no
longer report that the eight-request cycle budget was reached, and discovery
pauses no longer end the cycle before available research is considered.

If a fresh listing detail is blocked, an available history slot may populate
shared sales/chart evidence. The candidate stays queued and cannot pass until
required listing confirmation is available. Prefetches are shown separately
from completed research. Existing quota pacing and server cooldowns remain.

Each cycle prints:

`Scan: 100 total searched / 23 NEW unique / 1 candidates / 1 researched / 0 passed / 67 queued. Total unique seen: 26199.`

Total searched counts listings returned in that cycle, including repeats.
NEW unique counts previously unseen listing IDs. Total unique seen is cumulative.
Passed means eligible under the active paper review profile, not guaranteed
profit or purchase approval.

Installation: Ctrl+C to stop; replace the program files in your existing folder
with the contents of this ZIP. Keep your database, logs, request-state.json and
quota-state.json. Run `py -3 scout.py` and check the banner says v4.7.1.

Validation: all 144 offline tests passed, including blocked discovery continuing
to research, real cycle-budget enforcement, zero-request quota waits and history
prefetch during blocked listing confirmation. No live API calls or purchases
were made during testing.
