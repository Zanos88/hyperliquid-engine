@echo off
rem Trend forward-test tick — run by Windows Task Scheduler (daily x2 + logon).
rem Idempotent: overlapping/missed runs are harmless (UNIQUE marks, self-healing).
cd /d C:\Users\zane_\btc-signal-bot
if not exist "%LOCALAPPDATA%\btc-trend-forward" mkdir "%LOCALAPPDATA%\btc-trend-forward"
set LOG=%LOCALAPPDATA%\btc-trend-forward\tick.log
echo [%date% %time%] tick start >> "%LOG%"
railway run --service btc-signal-bot python forward_test.py --once >> "%LOG%" 2>&1
echo [%date% %time%] tick exit %errorlevel% >> "%LOG%"
