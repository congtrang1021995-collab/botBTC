@echo off
rem Bot2 tu dat lenh tren MT5 dang mo (XAUUSD, H1 + M15, 0.1 lot). Dong cua so nay de dung bot.
rem Can: MT5 dang mo, da dang nhap, nut Algo Trading dang BAT.
chcp 65001 >nul
cd /d "%~dp0"
python -m trading_bot.mt5 XAUUSD --tf H1 M15 --volume 0.1 %*
pause
