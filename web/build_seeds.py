"""Tính sẵn Bot2 cho trang live (chạy trên GitHub Actions, gọi từ build_site.py --seeds).

Tải nến lịch sử từ kho công khai data.binance.vision (file tháng + file ngày), chạy Bot2 bằng
CPython rồi ghi cho mỗi khung:
  seed/<key>.json  dữ liệu chart (hiện ngay khi mở trang)
  seed/<key>.pkl   trạng thái Bot2 (IncrementalChart) để trình duyệt tính tiếp nến mới
  seed/index.json  danh sách seed + mã phiên bản code
Pickle phải cùng phiên bản Python với Pyodide (0.28 = Python 3.13).
Lỗi tải một khung chỉ bỏ seed khung đó; trang vẫn chạy được, chỉ chậm hơn lần đầu.
"""

from __future__ import annotations

import csv
import io
import json
import pickle
import sys
import time
import urllib.error
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "data" / "chart_template"))

from incremental import IncrementalChart  # noqa: E402
from trading_bot.core.models import Bar  # noqa: E402

ARCHIVE = "https://data.binance.vision/data/futures/um"
SYMBOL = "BTCUSDT"
ARCHIVE_START = date(2020, 1, 1)   # kho futures có file tháng từ 01/2020
# Lịch sử seed mỗi khung: "days" = số ngày gần nhất, "start" = từ ngày cố định.
SEEDS = {
    "5m": {"days": 270},
    "15m": {"days": 1000},
    "1h": {"start": date(2020, 1, 1)},
    "4h": {"start": date(2020, 1, 1)},
    "1d": {"start": date(2020, 1, 1)},
}


def _get(url: str) -> bytes | None:
    for attempt in range(3):
        try:
            with urllib.request.urlopen(url, timeout=60) as response:
                return response.read()
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None
            time.sleep(2 * (attempt + 1))
        except (urllib.error.URLError, TimeoutError):
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"không tải được {url}")


def _rows(blob: bytes | None) -> list[list]:
    if not blob:
        return []
    with zipfile.ZipFile(io.BytesIO(blob)) as archive:
        text = archive.read(archive.namelist()[0]).decode()
    out = []
    for row in csv.reader(io.StringIO(text)):
        if not row or not row[0].isdigit():   # file mới có dòng tiêu đề, file cũ thì không
            continue
        out.append([int(row[0]), float(row[1]), float(row[2]), float(row[3]), float(row[4]), int(row[6])])
    return out


def download(interval: str, start: date, pool: ThreadPoolExecutor) -> list[list]:
    """Tháng đã có file tháng thì dùng file tháng; tháng hiện tại/tháng chưa có thì ghép file ngày."""
    today = datetime.now(timezone.utc).date()
    base = f"{ARCHIVE}/monthly/klines/{SYMBOL}/{interval}/{SYMBOL}-{interval}"
    months, cursor = [], date(start.year, start.month, 1)
    while cursor <= today:
        months.append(cursor)
        cursor = date(cursor.year + cursor.month // 12, cursor.month % 12 + 1, 1)
    monthly = list(pool.map(lambda m: _get(f"{base}-{m:%Y-%m}.zip"), months))
    urls = []
    for month, blob in zip(months, monthly):
        if blob is None:
            day = month
            while day.month == month.month and day < today:
                urls.append(f"{ARCHIVE}/daily/klines/{SYMBOL}/{interval}/{SYMBOL}-{interval}-{day:%Y-%m-%d}.zip")
                day += timedelta(days=1)
    daily = list(pool.map(_get, urls))
    rows = [r for blob in monthly + daily for r in _rows(blob)]
    start_ms = int(datetime(start.year, start.month, start.day, tzinfo=timezone.utc).timestamp() * 1000)
    now_ms = int(time.time() * 1000)
    seen, clean = set(), []
    for r in sorted(rows):
        if r[0] >= start_ms and r[5] < now_ms and r[0] not in seen:
            seen.add(r[0])
            clean.append(r[:5])
    return clean


def build(out: Path, version: str) -> None:
    out.mkdir(parents=True, exist_ok=True)
    index = {"version": version, "symbol": SYMBOL, "market": "futures", "seeds": {}}
    today = datetime.now(timezone.utc).date()
    with ThreadPoolExecutor(max_workers=12) as pool:
        for interval, spec in SEEDS.items():
            began = time.perf_counter()
            start = spec.get("start") or today - timedelta(days=spec["days"])
            start = max(start, ARCHIVE_START)
            try:
                rows = download(interval, start, pool)
                if not rows:
                    raise RuntimeError("không có nến")
                chart = IncrementalChart()
                for i, r in enumerate(rows):
                    chart.add(Bar(index=i, open=r[1], high=r[2], low=r[3], close=r[4],
                                  timestamp=datetime.fromtimestamp(r[0] / 1000, tz=timezone.utc)))
                payload = chart.payload()
                payload["src"] = "Binance Futures (live)"
                key = f"{SYMBOL}-futures-{interval}"
                (out / f"{key}.json").write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
                (out / f"{key}.pkl").write_bytes(pickle.dumps(chart, protocol=5))
                index["seeds"][interval] = {"start": start.isoformat(), "last": rows[-1][0], "bars": len(rows),
                                            "json": f"seed/{key}.json", "pkl": f"seed/{key}.pkl"}
                print(f"seed {interval}: {len(rows)} nến từ {start} · {len(payload['trades'])} lệnh · "
                      f"{time.perf_counter() - began:.1f}s", flush=True)
            except Exception as exc:  # thiếu seed không làm hỏng trang
                print(f"seed {interval}: BỎ QUA ({exc})", flush=True)
    (out / "index.json").write_text(json.dumps(index, indent=1), encoding="utf-8")


if __name__ == "__main__":
    build(ROOT / "_site" / "seed", sys.argv[1] if len(sys.argv) > 1 else "dev")
