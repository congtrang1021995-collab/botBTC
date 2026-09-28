"""Theo dõi tín hiệu Bot 2 trên giá Binance realtime (không đặt lệnh thật).

    python -m trading_bot.live                       # BTCUSDT H1 spot, chạy liên tục
    python -m trading_bot.live --once                # làm nóng rồi in trạng thái hiện tại
    python -m trading_bot.live ETHUSDT --interval 15m --market futures --log outputs/live.jsonl
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import timedelta, timezone, datetime
from pathlib import Path

from trading_bot.core.engine import ProcessResult
from trading_bot.data.binance import INTERVAL_MS
from trading_bot.live.monitor import LiveMonitor, run_forever

LOCAL_TZ = timezone(timedelta(hours=7))


def main() -> None:
    parser = argparse.ArgumentParser(description="Chạy Bot 2 trên nến Binance thực tế (paper).")
    parser.add_argument("symbol", nargs="?", default="BTCUSDT")
    parser.add_argument("--interval", default="1h", choices=sorted(INTERVAL_MS))
    parser.add_argument("--market", default="spot", choices=["spot", "futures"])
    parser.add_argument("--warmup", type=int, default=1000, help="Số nến lịch sử để làm nóng engine.")
    parser.add_argument("--once", action="store_true", help="Chỉ làm nóng và in trạng thái, không chạy vòng lặp.")
    parser.add_argument("--log", type=Path, help="Ghi mọi sự kiện realtime ra file JSONL.")
    args = parser.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    monitor = LiveMonitor(args.symbol, args.interval, args.market, args.warmup)

    def report(results: list[ProcessResult], warmup: bool) -> None:
        if not results:
            return
        if warmup:
            first, last = results[0].context.bar, results[-1].context.bar
            print(f"Đã làm nóng {len(results)} nến {args.symbol} {args.interval} ({args.market}) "
                  f"{_fmt(first.timestamp)} → {_fmt(last.timestamp)} (UTC+7)")
            print(_status_line(results[-1]))
            for position in results[-1].state.open_positions:
                setup = position.source_setup.name if position.source_setup else "-"
                print(f"  lệnh đang mở (theo lịch sử): {position.side.value} {setup} "
                      f"entry={_px(position.entry_price)} stop={_px(position.hard_stop_price)} "
                      f"TP={_px(position.take_profit_price)}")
            if not args.once:
                print("Đang chờ nến tiếp theo đóng... (Ctrl+C để dừng)")
            return
        for result in results:
            print(_status_line(result))
            for event in result.events:
                print(f"  >> {event.name} {json.dumps(event.payload, ensure_ascii=False, default=str)}")
            if args.log:
                _append_log(args.log, args.symbol, args.interval, result)

    try:
        run_forever(monitor, report, once=args.once)
    except KeyboardInterrupt:
        print("Đã dừng.")


def _status_line(result: ProcessResult) -> str:
    bar, ind = result.context.bar, result.context.indicators
    ema = (f"EMA34={ind.ema_fast:.2f} EMA89={ind.ema_slow:.2f}"
           if ind.ema_fast is not None and ind.ema_slow is not None else "EMA chưa đủ dữ liệu")
    slope = f" slope13={ind.ema_confirm_slope:+.2f}" if ind.ema_confirm_slope is not None else ""
    setups = ",".join(s.name for s in sorted(result.state.active_setups, key=int)) or "-"
    return (f"[{_fmt(bar.timestamp)}] close={bar.close:.2f} {ema}{slope} "
            f"trend={result.state.trend.name} setup={setups} "
            f"lệnh mở={len(result.state.open_positions)}")


def _px(value: float | None) -> str:
    return f"{value:.2f}" if value is not None else "-"


def _fmt(value: datetime | None) -> str:
    return value.astimezone(LOCAL_TZ).strftime("%Y-%m-%d %H:%M") if value else "?"


def _append_log(path: Path, symbol: str, interval: str, result: ProcessResult) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    bar = result.context.bar
    row = {
        "symbol": symbol,
        "interval": interval,
        "time": bar.timestamp.isoformat() if bar.timestamp else None,
        "open": bar.open, "high": bar.high, "low": bar.low, "close": bar.close,
        "trend": result.state.trend.name,
        "open_positions": len(result.state.open_positions),
        "events": [{"name": e.name, **e.payload} for e in result.events],
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")


if __name__ == "__main__":
    main()
