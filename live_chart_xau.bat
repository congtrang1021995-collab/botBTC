@echo off
rem Chart Bot2 live - gia XAUUSDT Futures H1 tu Binance (cong 8767). Dong cua so nay de dung.
chcp 65001 >nul
cd /d "%~dp0"
python data\chart_template\live_server.py XAUUSDT --market futures --start 2025-12-01 --port 8767 %*
pause
