@echo off
cd /d C:\Users\zane_\btc-signal-bot
if not exist "%LOCALAPPDATA%\btc-orderbook" mkdir "%LOCALAPPDATA%\btc-orderbook"
echo [%date% %time%] tick start >> "%LOCALAPPDATA%\btc-orderbook\tick.log"
railway run --service btc-signal-bot python scripts/orderbook_logger.py --once >> "%LOCALAPPDATA%\btc-orderbook\tick.log" 2>&1
echo [%date% %time%] tick exit %errorlevel% >> "%LOCALAPPDATA%\btc-orderbook\tick.log"
