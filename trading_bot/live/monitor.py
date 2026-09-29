"""Chạy Bot 2 trên nến Binance thực tế — chế độ theo dõi tín hiệu (paper).

Không đặt lệnh thật. Engine được làm nóng bằng lịch sử, sau đó mỗi khi một nến mới
đóng thì nến đó được đưa vào ``TradingEngine.process_bar`` giống hệt backtest.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from trading_bot.config import StrategyConfig, config_for_timeframe
from trading_bot.core.engine import ProcessResult, TradingEngine
from trading_bot.data.binance import (
    INTERVAL_MS,
    JsonFetcher,
    fetch_klines,
    http_get_json,
    klines_to_bars,
)


@dataclass(slots=True)
class LiveMonitor:
    symbol: str = "BTCUSDT"
    interval: str = "1h"
    market: str = "spot"
    warmup_bars: int = 1000
    config: StrategyConfig | None = None
    fetch_json: JsonFetcher = http_get_json
    engine: TradingEngine = field(init=False)
    last_open_time: datetime | None = field(init=False, default=None)
    next_index: int = field(init=False, default=0)

    def __post_init__(self) -> None:
        if self.interval not in INTERVAL_MS:
            raise ValueError(f"interval không hỗ trợ: {self.interval}")
        self.engine = TradingEngine(
            config_for_timeframe(self.config, INTERVAL_MS[self.interval] // 60_000)
        )

    def warm_up(self) -> list[ProcessResult]:
        """Nạp ``warmup_bars`` nến đã đóng gần nhất để EMA/pivot/trend ổn định."""
        klines = fetch_klines(
            self.symbol, self.interval, market=self.market,
            limit=self.warmup_bars, fetch_json=self.fetch_json,
        )
        if not klines:
            raise RuntimeError("Binance không trả về nến nào để làm nóng engine.")
        return self._feed(klines)

    def poll(self) -> list[ProcessResult]:
        """Xử lý mọi nến đã đóng kể từ lần trước (tự bù nếu bỏ lỡ nhiều nến)."""
        if self.last_open_time is None:
            return self.warm_up()
        start = self.last_open_time + timedelta(milliseconds=INTERVAL_MS[self.interval])
        klines = fetch_klines(
            self.symbol, self.interval, market=self.market,
            start=start, fetch_json=self.fetch_json,
        )
        return self._feed(k for k in klines if k.open_time > self.last_open_time)

    def seconds_until_next_close(self, now: datetime | None = None, delay: float = 3.0) -> float:
        now = now or datetime.now(timezone.utc)
        step = INTERVAL_MS[self.interval] / 1000
        elapsed = now.timestamp() % step
        return step - elapsed + delay

    def _feed(self, klines) -> list[ProcessResult]:
        klines = list(klines)
        bars = klines_to_bars(klines, start_index=self.next_index)
        results = [self.engine.process_bar(bar) for bar in bars]
        if klines:
            self.last_open_time = klines[-1].open_time
            self.next_index += len(klines)
        return results


def run_forever(
    monitor: LiveMonitor,
    report: Callable[[list[ProcessResult], bool], None],
    *,
    once: bool = False,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    report(monitor.warm_up(), True)
    while not once:
        sleep(monitor.seconds_until_next_close())
        try:
            results = monitor.poll()
        except Exception as exc:  # mạng chập chờn: báo lỗi, chờ nến sau rồi thử lại
            print(f"[{datetime.now(timezone.utc):%Y-%m-%d %H:%M:%S} UTC] Lỗi lấy dữ liệu: {exc}")
            continue
        report(results, False)
