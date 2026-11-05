# Release verification

Public source copies were checked for personal identifiers and credentials. Email defaults are disabled in CSFloat Scout and Markdown Live.

ExecutionLab passed 62 Python tests and JavaScript calculator checks. Markdown Live passed 36 Python tests. QuantLab passed 20 compiled tests. PairLab passed 42 compiled tests. KalshiLens passed 81 compiled tests after renaming a Windows-conflicting test helper.

CSFloat Scout ran 228 tests with 3 failures and 14 errors in Windows. Outstanding issues include cooldown/session expectations, SQLite cleanup while handles remain open and a restricted local socket. Its offline demo succeeds. Live API and SMTP behavior was not validated.
