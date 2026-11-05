@echo off
cd /d "%~dp0"
if exist paper-portfolio.html (
  start "" "paper-portfolio.html"
) else (
  echo No portfolio report yet. Run scout.py first, or use py -3 scout.py --paper-report.
  pause
)
