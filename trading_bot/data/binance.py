"""Nguồn dữ liệu nến Binance (API public, không cần API key).

Chỉ dùng standard library. Mọi hàm trả về nến ĐÃ ĐÓNG — nến đang chạy bị bỏ qua để
engine không xử lý dữ liệu chưa chốt (engine thiết kế cho nến đã đóng).
"""

from __future__ import annotations

import csv
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from trading_bot.core.models import Bar


BASE_URLS = {
    "spot": "https://api.binance.com/api/v3/klines",
    "futures": "https://fapi.binance.com/fapi/v1/klines",
}
# Số nến tối đa mỗi request theo tài liệu Binance.
MAX_LIMIT = {"spot": 1000, "futures": 1500}
INTERVAL_MS = {
    "1m": 60_000,
    "3m": 180_000,
    "5m": 300_000,
    "15m": 900_000,
    "30m": 1_800_000,
    "1h": 3_600_000,
    "2h": 7_200_000,
    "4h": 14_400_000,
    "6h": 21_600_000,
    "8h": 28_800_000,
    "12h": 43_200_000,
    "1d": 86_400_000,
}

# fetch_json(url) -> dữ liệu JSON; tách ra để test không cần mạng.
JsonFetcher = Callable[[str], object]


@dataclass(frozen=True, slots=True)
class Kline:
    open_time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    close_time_ms: int


def http_get_json(url: str, *, timeout: float = 15.0, retries: int = 3) -> object:
    request = urllib.request.Request(url, headers={"User-Agent": "investment-system-bot-2"})
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError) as exc:
            # 4xx là lỗi tham số (sai symbol/interval) -> báo ngay, không thử lại.
            if isinstance(exc, urllib.error.HTTPError) and 400 <= exc.code < 500:
                body = exc.read().decode("utf-8", "replace")
                raise ValueError(f"Binance từ chối request ({exc.code}): {body}") from exc
            if attempt == retries - 1:
                raise
            time.sleep(2**attempt)
    raise RuntimeError("unreachable")


def fetch_klines(
    symbol: str = "BTCUSDT",
    interval: str = "1h",
    *,
    market: str = "spot",
    start: datetime | None = None,
    end: datetime | None = None,
    limit: int | None = None,
    fetch_json: JsonFetcher = http_get_json,
    now_ms: int | None = None,
) -> list[Kline]:
    """Tải nến đã đóng theo thứ tự thời gian.

    - Có ``start``: tải từ ``start`` tới ``end`` (hoặc hiện tại), tự phân trang.
    - Không có ``start``: lấy ``limit`` nến đã đóng gần nhất (mặc định 1000).
    """
    if market not in BASE_URLS:
        raise ValueError("market must be 'spot' or 'futures'")
    if interval not in INTERVAL_MS:
        raise ValueError(f"interval không hỗ trợ: {interval}")
    now_ms = int(time.time() * 1000) if now_ms is None else now_ms
    page = MAX_LIMIT[market]
    end_ms = _to_ms(end) if end is not None else None

    if start is None:
        wanted = limit or page
        # +1 vì nến cuối cùng trả về thường là nến đang chạy.
        cursor_end = end_ms
        collected: list[Kline] = []
        while len(collected) < wanted:
            params = {"symbol": symbol, "interval": interval,
                      "limit": min(page, wanted - len(collected) + 1)}
            if cursor_end is not None:
                params["endTime"] = cursor_end
            rows = _request(market, params, fetch_json)
            batch = [k for k in rows if k.close_time_ms < now_ms]
            if collected:
                first_ms = _to_ms(collected[0].open_time)
                batch = [k for k in batch if _to_ms(k.open_time) < first_ms]
            if not batch:
                break
            collected = batch + collected
            cursor_end = _to_ms(batch[0].open_time) - 1
            if len(rows) < params["limit"]:
                break
        return collected[-wanted:]

    cursor = _to_ms(start)
    collected = []
    while True:
        params = {"symbol": symbol, "interval": interval, "startTime": cursor, "limit": page}
        if end_ms is not None:
            params["endTime"] = end_ms
        rows = _request(market, params, fetch_json)
        batch = [k for k in rows if k.close_time_ms < now_ms]
        collected.extend(batch)
        if len(rows) < page or not batch or (limit and len(collected) >= limit):
            break
        cursor = _to_ms(batch[-1].open_time) + INTERVAL_MS[interval]
    return collected[:limit] if limit else collected


def klines_to_bars(klines: Iterable[Kline], start_index: int = 0) -> list[Bar]:
    return [
        Bar(
            index=start_index + offset,
            open=k.open,
            high=k.high,
            low=k.low,
            close=k.close,
            timestamp=k.open_time,
        )
        for offset, k in enumerate(klines)
    ]


def write_klines_csv(klines: Iterable[Kline], path: str | Path) -> Path:
    """Ghi CSV đúng định dạng ``load_bars_csv`` / ``build_chart.py`` đọc được."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["timestamp", "open", "high", "low", "close", "volume"])
        for k in klines:
            writer.writerow([k.open_time.isoformat(), k.open, k.high, k.low, k.close, k.volume])
    return target


def _request(market: str, params: dict[str, object], fetch_json: JsonFetcher) -> list[Kline]:
    url = f"{BASE_URLS[market]}?{urllib.parse.urlencode(params)}"
    payload = fetch_json(url)
    if not isinstance(payload, list):
        raise ValueError(f"Binance trả về dữ liệu không hợp lệ: {payload!r}")
    return [_parse_row(row) for row in payload]


def _parse_row(row: list[object]) -> Kline:
    return Kline(
        open_time=datetime.fromtimestamp(int(row[0]) / 1000, tz=timezone.utc),
        open=float(row[1]),
        high=float(row[2]),
        low=float(row[3]),
        close=float(row[4]),
        volume=float(row[5]),
        close_time_ms=int(row[6]),
    )


def _to_ms(value: datetime) -> int:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return int(value.timestamp() * 1000)
