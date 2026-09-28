from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path

from trading_bot.core.models import Bar


REQUIRED_COLUMNS = frozenset({"open", "high", "low", "close"})
# Tên cột thời gian thường gặp khi xuất từ TradingView, Amibroker, MetaTrader...
TIMESTAMP_ALIASES = ("timestamp", "time", "date", "datetime", "<date>")


def load_bars_csv(path: str | Path) -> list[Bar]:
    """Load chronological OHLC rows from CSV; timestamp and volume are optional."""
    source = Path(path)
    bars: list[Bar] = []
    previous_timestamp: datetime | None = None

    with source.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ValueError("CSV must contain a header row")

        columns = {name.strip().lower(): name for name in reader.fieldnames}
        missing = REQUIRED_COLUMNS - columns.keys()
        if missing:
            names = ", ".join(sorted(missing))
            raise ValueError(f"CSV is missing required columns: {names}")

        timestamp_column = next(
            (columns[name] for name in TIMESTAMP_ALIASES if name in columns),
            None,
        )
        for row_number, row in enumerate(reader, start=2):
            if not any((value or "").strip() for value in row.values()):
                continue
            try:
                timestamp = (
                    _parse_timestamp(row[timestamp_column])
                    if timestamp_column and (row[timestamp_column] or "").strip()
                    else None
                )
                bar = Bar(
                    index=len(bars),
                    open=float(row[columns["open"]]),
                    high=float(row[columns["high"]]),
                    low=float(row[columns["low"]]),
                    close=float(row[columns["close"]]),
                    timestamp=timestamp,
                )
            except (TypeError, ValueError) as exc:
                raise ValueError(f"invalid CSV row {row_number}: {exc}") from exc

            if (
                timestamp is not None
                and previous_timestamp is not None
                and timestamp <= previous_timestamp
            ):
                raise ValueError(
                    f"timestamps must increase strictly; row {row_number} is out of order"
                )
            if timestamp is not None:
                previous_timestamp = timestamp
            bars.append(bar)

    if not bars:
        raise ValueError("CSV contains no OHLC data rows")
    return bars


def _parse_timestamp(value: str) -> datetime:
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = f"{normalized[:-1]}+00:00"
    # Unix epoch (giây hoặc mili giây) — TradingView và nhiều API dùng dạng này.
    if normalized.lstrip("-").isdigit():
        epoch = int(normalized)
        if abs(epoch) > 10_000_000_000:
            epoch //= 1000
        return datetime.fromtimestamp(epoch, tz=timezone.utc)
    # Dạng ngày thuần của một số nguồn: 20240102 đã rơi vào nhánh trên, nên ở đây
    # chỉ còn các dạng có dấu phân cách.
    normalized = normalized.replace("/", "-")
    if " " in normalized and "T" not in normalized:
        normalized = normalized.replace(" ", "T", 1)
    return datetime.fromisoformat(normalized)
