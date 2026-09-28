"""Chart mẫu: nến + EMA34/89 + vùng TP/SL ban đầu + trailing stop cho từng lệnh backtest.

Chạy lại backtest bằng code hiện tại rồi nhúng dữ liệu vào `template.html`
thành một trang HTML độc lập.

    python data/chart_template/build_chart.py "Dữ liệu/XAU" --symbol XAU/USD --tf H1
    python data/chart_template/build_chart.py outputs/xau_combined_2025-01_to_2026-09.csv --symbol XAU/USD
    python data/chart_template/build_chart.py "Dữ liệu/BTC" --symbol BTC/USD --out outputs/btc-trade-explorer.html

Đầu vào là một hoặc nhiều file CSV, hoặc thư mục (lấy mọi *.csv, xếp theo tên).
Cột đầu tiên phải là thời gian ISO-8601 nếu không có cột `timestamp/time/date`.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
WORKSPACE = HERE.parents[1]
sys.path.insert(0, str(WORKSPACE))

from trading_bot.backtest.csv_loader import load_bars_csv  # noqa: E402
from trading_bot.backtest.runner import run_backtest_report  # noqa: E402
from trading_bot.core.models import Bar, PositionSide  # noqa: E402

TEMPLATE = HERE / "template.html"


def csv_files(inputs: list[Path]) -> list[Path]:
    files: list[Path] = []
    for item in inputs:
        files.extend(sorted(item.glob("*.csv")) if item.is_dir() else [item])
    if not files:
        raise SystemExit("Không tìm thấy file CSV nào trong đầu vào.")
    return files


def load_bars(files: list[Path]) -> list[Bar]:
    """Nối các file theo thứ tự, bỏ nến trùng thời gian, đánh lại index từ 0."""
    bars: list[Bar] = []
    last: datetime | None = None
    for path in files:
        loaded = load_bars_csv(path)
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            first = reader.fieldnames[0]
            stamps = [row[first] for row in reader if any((v or "").strip() for v in row.values())]
        for source, text in zip(loaded, stamps, strict=True):
            stamp = source.timestamp or datetime.fromisoformat(text)
            if last is not None and stamp <= last:
                continue
            bars.append(Bar(index=len(bars), open=source.open, high=source.high,
                            low=source.low, close=source.close, timestamp=stamp))
            last = stamp
    return bars


def r2(value: float | None) -> float | None:
    return None if value is None else round(value, 2)


def build_payload(bars: list[Bar]) -> dict:
    report = run_backtest_report(bars)
    results = report.results

    def active_stops(side: PositionSide, entry: int, exit_: int, initial: float) -> list[float]:
        # Stop chốt ở Close nến trước, có hiệu lực từ nến kế tiếp. Có thể nhiều lệnh mở
        # song song, nên tìm đúng lệnh theo chiều + nến vào lệnh.
        stops = [initial]
        for bar_index in range(entry + 1, exit_ + 1):
            stop = next((p.hard_stop_price for p in results[bar_index - 1].state.open_positions
                         if p.side == side and p.entry_bar_index == entry), None)
            stops.append(r2(stop) if stop else stops[-1])
        return stops

    trades = []
    for number, trade in enumerate(report.trades, start=1):
        direction = 1.0 if trade.side == PositionSide.LONG else -1.0
        initial_stop = r2(trade.entry_price - direction * trade.initial_risk / trade.quantity)
        trades.append({
            "id": number, "ei": trade.entry_bar_index, "xi": trade.exit_bar_index,
            "side": trade.side.value,
            "setup": trade.source_setup.name if trade.source_setup else "",
            "entry": r2(trade.entry_price), "exit": r2(trade.exit_price),
            "sl": initial_stop, "tp": r2(trade.take_profit_price),
            "reason": trade.exit_reason, "pnl": r2(trade.pnl), "r": round(trade.r_multiple, 3),
            "stops": active_stops(trade.side, trade.entry_bar_index, trade.exit_bar_index,
                                  initial_stop),
        })

    open_positions = results[-1].state.open_positions if results else ()
    for last in open_positions:
        if last.size <= 0 or last.entry_bar_index is None:
            continue
        initial_stop = r2(last.initial_hard_stop_price)
        trades.append({
            "id": len(trades) + 1, "ei": last.entry_bar_index, "xi": len(bars) - 1,
            "side": last.side.value,
            "setup": last.source_setup.name if last.source_setup else "",
            "entry": r2(last.entry_price), "exit": None, "sl": initial_stop,
            "tp": r2(last.take_profit_price), "reason": "OPEN", "pnl": None, "r": None,
            "stops": active_stops(last.side, last.entry_bar_index, len(bars) - 1, initial_stop),
            "open": True,
        })

    # Engine trả lệnh theo thứ tự đóng; xếp lại theo nến vào lệnh để duyệt theo thời gian.
    trades.sort(key=lambda x: (x["ei"], x["xi"]))
    for number, trade in enumerate(trades, start=1):
        trade["id"] = number

    return {
        "t": [int(b.timestamp.timestamp()) for b in bars],
        "o": [round(b.open, 3) for b in bars],
        "h": [round(b.high, 3) for b in bars],
        "l": [round(b.low, 3) for b in bars],
        "c": [round(b.close, 3) for b in bars],
        "e34": [r2(r.context.indicators.ema_fast) for r in results],
        "e89": [r2(r.context.indicators.ema_slow) for r in results],
        "trades": trades,
        "m": {k: (round(v, 4) if isinstance(v, float) else v)
              for k, v in asdict(report.trade_metrics).items()},
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Dựng chart lệnh backtest từ CSV OHLC.")
    parser.add_argument("inputs", nargs="+", type=Path, help="File CSV hoặc thư mục chứa CSV.")
    parser.add_argument("--symbol", required=True, help="Tên mã hiển thị, ví dụ XAU/USD.")
    parser.add_argument("--tf", default="H1", help="Khung thời gian hiển thị (mặc định H1).")
    parser.add_argument("--out", type=Path, help="File HTML đầu ra.")
    parser.add_argument("--source", default="giá BID", help="Nhãn nguồn giá hiển thị, ví dụ \"Binance Futures\".")
    args = parser.parse_args()

    bars = load_bars(csv_files(args.inputs))
    if not bars or bars[0].timestamp is None:
        raise SystemExit("Dữ liệu cần có cột thời gian.")
    slug = args.symbol.split("/")[0].lower()
    out = args.out or WORKSPACE / "outputs" / f"{slug}-{args.tf.lower()}-trade-explorer.html"

    payload = build_payload(bars)
    payload["src"] = args.source
    html = (TEMPLATE.read_text(encoding="utf-8")
            .replace("__TITLE__", f"{args.symbol.split('/')[0]} {args.tf} Bot2 Trade Explorer")
            .replace("__SYMBOL__", args.symbol)
            .replace("__TF__", args.tf)
            .replace("__DATA_JSON__", json.dumps(payload, ensure_ascii=True, separators=(",", ":"))))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    print(json.dumps({"path": str(out), "bytes": out.stat().st_size, "bars": len(bars),
                      "trades": len(payload["trades"])}, ensure_ascii=False))


if __name__ == "__main__":
    main()
