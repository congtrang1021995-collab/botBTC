"""Tải nến Binance ra CSV để backtest / dựng chart.

    python -m trading_bot.data BTCUSDT --interval 1h --days 365
    python -m trading_bot.data BTCUSDT --interval 1h --start 2025-01-01 --out data/btc.csv
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from pathlib import Path

from trading_bot.data.binance import INTERVAL_MS, fetch_klines, write_klines_csv


def main() -> None:
    parser = argparse.ArgumentParser(description="Tải nến đã đóng từ Binance ra CSV.")
    parser.add_argument("symbol", nargs="?", default="BTCUSDT")
    parser.add_argument("--interval", default="1h", choices=sorted(INTERVAL_MS))
    parser.add_argument("--market", default="spot", choices=["spot", "futures"])
    parser.add_argument("--days", type=float, default=365.0, help="Số ngày gần nhất (bỏ qua nếu có --start).")
    parser.add_argument("--start", type=_parse_date, help="Ngày bắt đầu UTC, vd 2025-01-01.")
    parser.add_argument("--end", type=_parse_date, help="Ngày kết thúc UTC (mặc định: hiện tại).")
    parser.add_argument("--out", type=Path, help="Mặc định data/binance/<symbol>_<interval>_<market>.csv")
    args = parser.parse_args()

    start = args.start or datetime.now(timezone.utc) - timedelta(days=args.days)
    klines = fetch_klines(args.symbol, args.interval, market=args.market, start=start, end=args.end)
    if not klines:
        raise SystemExit("Binance không trả về nến nào trong khoảng đã chọn.")
    out = args.out or Path("data/binance") / f"{args.symbol.lower()}_{args.interval}_{args.market}.csv"
    write_klines_csv(klines, out)
    print(f"Đã lưu {len(klines)} nến {args.symbol} {args.interval} ({args.market}) "
          f"{klines[0].open_time:%Y-%m-%d %H:%M} → {klines[-1].open_time:%Y-%m-%d %H:%M} UTC vào {out}")


def _parse_date(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


if __name__ == "__main__":
    main()
