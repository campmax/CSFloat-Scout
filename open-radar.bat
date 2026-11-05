@echo off
cd /d "%~dp0"
if exist radar-best.html (start "" "radar-best.html") else (echo Run Markdown Radar first. & pause)
