@echo off
cd /d "%~dp0"
if exist personal-report.html (
  start "" "personal-report.html"
) else (
  echo Run the personal monitor through its first cycle first.
  pause
)
