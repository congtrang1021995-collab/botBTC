"""Bot 2 (2026-09-29): trend khung lớn dùng để lọc lệnh khung nhỏ.

Mỗi khung giao dịch lọc theo khung ngay trên nó (M15 <- H1, H1 <- H4). Trend khung lớn
tính bằng chính ``TradingEngine`` trên nến khung lớn (cùng rule, cùng config) và chỉ
dùng nến khung lớn **đã đóng** tại thời điểm nến khung nhỏ đóng — không nhìn trước.
"""

from __future__ import annotations

import bisect
from datetime import datetime, timedelta

from trading_bot.config import StrategyConfig
from trading_bot.core.engine import TradingEngine
from trading_bot.core.models import Bar, TrendState

# Khung giao dịch -> khung lọc (tên kiểu MT5 và kiểu Binance).
HIGHER_TIMEFRAME = {"M15": "H1", "H1": "H4", "15m": "1h", "1h": "4h"}
TIMEFRAME_MINUTES = {"M1": 1, "M5": 5, "M15": 15, "M30": 30, "H1": 60, "H4": 240, "D1": 1440,
                     "1m": 1, "5m": 5, "15m": 15, "30m": 30, "1h": 60, "4h": 240, "1d": 1440}


def infer_minutes(bars: list[Bar]) -> int:
    """Độ dài nến (phút) = khoảng cách nhỏ nhất giữa các nến đầu chuỗi."""
    stamps = [b.timestamp for b in bars[:500] if b.timestamp is not None]
    gaps = [(b - a).total_seconds() / 60 for a, b in zip(stamps, stamps[1:]) if b > a]
    if not gaps:
        raise ValueError("cần ít nhất hai nến có thời gian để suy ra khung")
    return int(min(gaps))


class HigherTrendFeed:
    """Nhận nến khung lớn đã đóng theo thứ tự, trả trend tại một thời điểm bất kỳ."""

    def __init__(self, minutes: int, config: StrategyConfig | None = None) -> None:
        self.step = timedelta(minutes=minutes)
        self.engine = TradingEngine(config)
        self.closes: list[datetime] = []
        self.trends: list[TrendState] = []
        self.last_open: datetime | None = None

    def __len__(self) -> int:
        return len(self.closes)

    def add(self, timestamp: datetime, open_: float, high: float, low: float, close: float) -> bool:
        """Thêm một nến đã đóng (theo giờ mở nến). Nến cũ/trùng bị bỏ qua, trả False."""
        if self.last_open is not None and timestamp <= self.last_open:
            return False
        bar = Bar(index=len(self.closes), open=open_, high=high, low=low, close=close,
                  timestamp=timestamp)
        result = self.engine.process_bar(bar)
        self.closes.append(timestamp + self.step)
        self.trends.append(result.state.trend)
        self.last_open = timestamp
        return True

    def trend_at(self, moment: datetime) -> TrendState | None:
        """Trend của nến khung lớn mới nhất đã đóng tại ``moment``; None nếu chưa có nến nào."""
        i = bisect.bisect_right(self.closes, moment) - 1
        return self.trends[i] if i >= 0 else None
