@echo off
rem Cau noi nen MT5 (XAUUSD) cho trang Bot2 Live tren GitHub Pages, cong 8770. Dong cua so nay de dung.
rem Can: MT5 dang mo va da dang nhap.
chcp 65001 >nul
cd /d "%~dp0"
python mt5_feed.py XAUUSD --port 8770 %*
pause
