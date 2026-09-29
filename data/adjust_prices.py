"""Điều chỉnh giá lùi (back-adjust) theo sự kiện quyền: cổ tức tiền, cổ phiếu thưởng/cổ tức cổ phiếu.

    python data/adjust_prices.py outputs/dgw_daily.csv "Dữ liệu/DGW_corporate_actions.csv" --out outputs/dgw_daily_adj.csv

File sự kiện có các cột `ex_date,cash,stock_ratio,note`:
- `ex_date`: ngày giao dịch không hưởng quyền (YYYY-MM-DD).
- `cash`: cổ tức tiền mặt trên mỗi cổ phiếu cũ (đồng).
- `stock_ratio`: tỷ lệ cổ phiếu nhận thêm trên mỗi cổ phiếu cũ (30% -> 0.3).

Giá tham chiếu ngày GDKHQ = (Close phiên trước - cash) / (1 + stock_ratio), như cách HOSE tính.
Mọi nến trước ngày GDKHQ nhân với hệ số = giá tham chiếu / Close phiên trước; các hệ số dồn lại
theo thời gian, nên nến gần nhất giữ nguyên giá thật.
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

PRICE_COLUMNS = ("open", "high", "low", "close")


def main() -> None:
    parser = argparse.ArgumentParser(description="Điều chỉnh giá OHLC theo cổ tức / chia tách.")
    parser.add_argument("prices", type=Path, help="CSV giá, cột đầu là thời gian, xếp tăng dần.")
    parser.add_argument("actions", type=Path, help="CSV sự kiện quyền: ex_date,cash,stock_ratio.")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")

    with args.prices.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fields = reader.fieldnames
        rows = list(reader)
    stamp = fields[0]
    with args.actions.open(encoding="utf-8-sig", newline="") as handle:
        actions = sorted(csv.DictReader(handle), key=lambda a: a["ex_date"])

    factors = [1.0] * len(rows)
    for action in actions:
        ex = next((i for i, r in enumerate(rows) if r[stamp][:10] >= action["ex_date"]), None)
        if ex is None or ex == 0:
            print(f"Bỏ qua {action['ex_date']}: nằm ngoài dữ liệu.")
            continue
        prev_close = float(rows[ex - 1]["close"])
        reference = (prev_close - float(action["cash"] or 0)) / (1 + float(action["stock_ratio"] or 0))
        factor = reference / prev_close
        for i in range(ex):
            factors[i] *= factor
        print(f"{action['ex_date']}: close trước {prev_close:,.0f} -> tham chiếu {reference:,.1f}, "
              f"hệ số {factor:.6f}, mở cửa {float(rows[ex]['open']):,.0f}")

    for row, factor in zip(rows, factors):
        for column in PRICE_COLUMNS:
            row[column] = f"{float(row[column]) * factor:.4f}".rstrip("0").rstrip(".")

    with args.out.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    print(f"Đã ghi {len(rows)} nến vào {args.out}")


if __name__ == "__main__":
    main()
