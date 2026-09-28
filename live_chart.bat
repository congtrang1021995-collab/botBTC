@echo off
rem Chart Bot2 live - gia BTCUSDT Futures H1 tu Binance. Dong cua so nay de dung.
chcp 65001 >nul
cd /d "%~dp0"
python data\chart_template\live_server.py %*
pause
