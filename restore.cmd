@echo off
REM Puts the stock yellow Windows folders back from backup\r
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0apply.ps1" yellow
pause
