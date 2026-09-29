"""Chart mẫu: nến + EMA34/89 + vùng TP/SL ban đầu + trailing stop cho từng lệnh backtest.

Chạy lại backtest bằng code hiện tại rồi nhúng dữ liệu vào `template.html`
thành một trang HTML độc lập.

    python data/chart_template/build_chart.py "Dữ liệu/XAU" --symbol XAU/USD --tf H1
    python data/chart_template/build_chart.py outputs/xau_combined_2025-01_to_2026-09.csv --symbol XAU/USD
    python data/chart_template/build_chart.py "Dữ liệu/BTC" --symbol BTC/USD --out outputs/btc-trade-explorer.html
    python data/chart_template/build_chart.py data/mt5/MetaQuotes-Demo_XAUUSD_M15.csv --symbol XAU/USD --tf M15         --higher data/mt5/MetaQuotes-Demo_XAUUSD_H1.csv      # lọc lệnh theo trend khung lớn (Bot 2)

Đầu vào là một hoặc nhiều file CSV, hoặc thư mục (lấy mọi *.csv, xếp theo tên).
Cột đầu tiên phải là thời gian ISO-8601 nếu không có cột `timestamp/time/date`.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
WORKSPACE = HERE.parents[1]
sys.path.insert(0, str(WORKSPACE))

from trading_bot.backtest.csv_loader import load_bars_csv  # noqa: E402
from trading_bot.core.higher_tf import infer_minutes  # noqa: E402
from trading_bot.core.models import Bar  # noqa: E402

sys.path.insert(0, str(HERE))
from incremental import IncrementalChart  # noqa: E402

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


def build_payload(bars: list[Bar], higher: list[Bar] | None = None) -> dict:
    """Chạy Bot2 trên toàn bộ nến và trả dữ liệu chart (xem incremental.IncrementalChart).

    ``higher``: nến khung lớn để lọc lệnh theo trend (Bot 2), đưa vào trước mỗi nến khung nhỏ
    những nến khung lớn đã đóng tới lúc nến đó đóng.
    """
    if not higher:
        chart = IncrementalChart()
        for bar in bars:
            chart.add(bar)
        return chart.payload()
    minutes, higher_minutes = infer_minutes(bars), infer_minutes(higher)
    chart = IncrementalChart(minutes=minutes, higher_minutes=higher_minutes)
    step, higher_step = timedelta(minutes=minutes), timedelta(minutes=higher_minutes)
    h = 0
    for bar in bars:
        while h < len(higher) and higher[h].timestamp + higher_step <= bar.timestamp + step:
            hb = higher[h]
            chart.add_higher(hb.timestamp, hb.open, hb.high, hb.low, hb.close)
            h += 1
        chart.add(bar)
    return chart.payload()


def main() -> None:
    parser = argparse.ArgumentParser(description="Dựng chart lệnh backtest từ CSV OHLC.")
    parser.add_argument("inputs", nargs="+", type=Path, help="File CSV hoặc thư mục chứa CSV.")
    parser.add_argument("--symbol", required=True, help="Tên mã hiển thị, ví dụ XAU/USD.")
    parser.add_argument("--tf", default="H1", help="Khung thời gian hiển thị (mặc định H1).")
    parser.add_argument("--out", type=Path, help="File HTML đầu ra.")
    parser.add_argument("--higher", nargs="+", type=Path,
                        help="CSV/thư mục nến khung lớn để lọc lệnh theo trend (M15 <- H1, H1 <- H4).")
    parser.add_argument("--source", default="giá BID", help="Nhãn nguồn giá hiển thị, ví dụ \"Binance Futures\".")
    args = parser.parse_args()

    bars = load_bars(csv_files(args.inputs))
    if not bars or bars[0].timestamp is None:
        raise SystemExit("Dữ liệu cần có cột thời gian.")
    slug = args.symbol.split("/")[0].lower()
    out = args.out or WORKSPACE / "outputs" / f"{slug}-{args.tf.lower()}-trade-explorer.html"

    higher = load_bars(csv_files(args.higher)) if args.higher else None
    payload = build_payload(bars, higher)
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
