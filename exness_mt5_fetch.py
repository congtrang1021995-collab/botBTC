"""Tải nến từ MT5 đang mở (đã đăng nhập) ra CSV, chỉ lấy nến đã đóng.

    python exness_mt5_fetch.py                       # XAUUSD* đầu tiên, H1, từ 2025-01-01
    python exness_mt5_fetch.py XAUUSDm --tf M15 --start 2024-01-01
"""
import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import MetaTrader5 as mt5
import pandas as pd

TIMEFRAMES = {"M1": mt5.TIMEFRAME_M1, "M5": mt5.TIMEFRAME_M5, "M15": mt5.TIMEFRAME_M15,
              "M30": mt5.TIMEFRAME_M30, "H1": mt5.TIMEFRAME_H1, "H4": mt5.TIMEFRAME_H4,
              "D1": mt5.TIMEFRAME_D1}

parser = argparse.ArgumentParser()
parser.add_argument("symbol", nargs="?")
parser.add_argument("--tf", default="H1", choices=TIMEFRAMES)
parser.add_argument("--start", default="2025-01-01")
parser.add_argument("--out-dir", type=Path, default=Path(__file__).parent / "data" / "mt5")
args = parser.parse_args()

if not mt5.initialize():
    sys.exit(f"Không kết nối được MT5: {mt5.last_error()}")

acc = mt5.account_info()
print("Tài khoản:", acc.login, acc.server)

symbol = args.symbol or [s.name for s in mt5.symbols_get("XAUUSD*")][0]
mt5.symbol_select(symbol, True)

start = datetime.fromisoformat(args.start).replace(tzinfo=timezone.utc)
rates = mt5.copy_rates_range(symbol, TIMEFRAMES[args.tf], start,
                             datetime.now(timezone.utc) + timedelta(days=1))  # MT5 hiểu mốc là giờ server
if rates is None or len(rates) < 2:
    mt5.shutdown()
    sys.exit(f"Không lấy được nến {symbol}: {mt5.last_error()}")

df = pd.DataFrame(rates).iloc[:-1]  # nến cuối đang chạy
# MT5 trả giờ server dưới dạng epoch. Exness là UTC+0; MetaQuotes-Demo và đa số broker
# khác dùng giờ New York + 7 (UTC+2 mùa đông, UTC+3 mùa hè) -> đổi về UTC.
server_time = pd.to_datetime(df["time"], unit="s")
tick = mt5.symbol_info_tick(symbol)
offset_now = round((tick.time - datetime.now(timezone.utc).timestamp()) / 3600)
if offset_now == 0:
    utc = server_time.dt.tz_localize("UTC")
else:
    utc = (server_time - pd.Timedelta(hours=7)).dt.tz_localize(
        "America/New_York", ambiguous="NaT", nonexistent="NaT").dt.tz_convert("UTC")
    df = df[utc.notna()]
    utc = utc.dropna()
    print(f"Giờ server lệch UTC {offset_now:+d}h -> đã đổi về UTC (giờ New York + 7)")
df["time"] = utc.dt.strftime("%Y-%m-%dT%H:%M:%S+00:00")
df = df[["time", "open", "high", "low", "close", "tick_volume", "spread"]]

server = acc.server.replace(" ", "_")
args.out_dir.mkdir(parents=True, exist_ok=True)
out = args.out_dir / f"{server}_{symbol}_{args.tf}.csv"
df.to_csv(out, index=False)
print(f"{len(df)} nến {symbol} {args.tf}: {df['time'].iloc[0]} -> {df['time'].iloc[-1]}")
print("Lưu:", out)

mt5.shutdown()
