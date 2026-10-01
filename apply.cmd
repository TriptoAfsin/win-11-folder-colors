@echo off
REM Usage: apply.cmd [blue^|green^|purple^|black^|gray^|teal^|red^|orange^|pink^|yellow]
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0apply.ps1" %*
pause
