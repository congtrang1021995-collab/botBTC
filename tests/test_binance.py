from __future__ import annotations

import tempfile
import unittest
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

from trading_bot.backtest.csv_loader import load_bars_csv
from trading_bot.data.binance import fetch_klines, klines_to_bars, write_klines_csv
from trading_bot.live.monitor import LiveMonitor

HOUR = 3_600_000
T0 = int(datetime(2026, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)


class FakeBinance:
    """Giả lập /klines: `count` nến H1 từ T0, nến cuối chưa đóng tại `now`."""

    def __init__(self, count: int, page: int = 1000) -> None:
        self.count = count
        self.page = page
        self.calls = 0

    @property
    def now(self) -> int:
        return T0 + (self.count - 1) * HOUR + HOUR // 2

    def row(self, i: int) -> list[object]:
        price = 100.0 + i
        return [T0 + i * HOUR, str(price), str(price + 2), str(price - 2), str(price + 1),
                "10", T0 + (i + 1) * HOUR - 1]

    def __call__(self, url: str) -> object:
        self.calls += 1
        q = {k: v[0] for k, v in urllib.parse.parse_qs(urllib.parse.urlparse(url).query).items()}
        limit = min(int(q.get("limit", 500)), self.page)
        idx = range(self.count)
        if "startTime" in q:
            idx = [i for i in idx if T0 + i * HOUR >= int(q["startTime"])]
            return [self.row(i) for i in idx[:limit]]
        if "endTime" in q:
            idx = [i for i in idx if T0 + i * HOUR <= int(q["endTime"])]
        return [self.row(i) for i in list(idx)[-limit:]]


class FetchKlinesTest(unittest.TestCase):
    def test_latest_drops_unclosed_bar(self) -> None:
        api = FakeBinance(50)
        klines = fetch_klines(limit=10, fetch_json=api, now_ms=api.now)
        self.assertEqual(len(klines), 10)
        self.assertEqual(klines[-1].open_time.timestamp() * 1000, T0 + 48 * HOUR)

    def test_latest_pages_backwards(self) -> None:
        api = FakeBinance(2500)
        klines = fetch_klines(limit=2200, fetch_json=api, now_ms=api.now)
        self.assertEqual(len(klines), 2200)
        times = [k.open_time for k in klines]
        self.assertEqual(times, sorted(set(times)))
        self.assertGreater(api.calls, 1)

    def test_range_pages_forwards(self) -> None:
        api = FakeBinance(2500)
        start = datetime.fromtimestamp(T0 / 1000, tz=timezone.utc)
        klines = fetch_klines(start=start, fetch_json=api, now_ms=api.now)
        self.assertEqual(len(klines), 2499)
        self.assertEqual(len({k.open_time for k in klines}), 2499)

    def test_csv_roundtrip_with_loader(self) -> None:
        api = FakeBinance(20)
        klines = fetch_klines(limit=15, fetch_json=api, now_ms=api.now)
        with tempfile.TemporaryDirectory() as tmp:
            path = write_klines_csv(klines, Path(tmp) / "btc.csv")
            bars = load_bars_csv(path)
        self.assertEqual(bars, klines_to_bars(klines))


class LiveMonitorTest(unittest.TestCase):
    def test_poll_processes_only_new_closed_bars(self) -> None:
        api = FakeBinance(300)
        monitor = LiveMonitor(warmup_bars=200, fetch_json=api)
        # now_ms mặc định là giờ thật (sau 2026-01-01) nên nến giả đều coi là đã đóng;
        # giới hạn bằng cách tăng dần số nến của API.
        api.count = 200
        self.assertEqual(len(monitor.warm_up()), 200)
        self.assertEqual(len(monitor.poll()), 0)
        api.count = 203
        results = monitor.poll()
        self.assertEqual([r.context.bar.index for r in results], [200, 201, 202])
        self.assertEqual(monitor.engine.state.market.last_bar_index, 202)

    def test_seconds_until_next_close(self) -> None:
        monitor = LiveMonitor(fetch_json=FakeBinance(1))
        now = datetime(2026, 1, 1, 10, 59, 0, tzinfo=timezone.utc)
        self.assertAlmostEqual(monitor.seconds_until_next_close(now, delay=3), 63)


if __name__ == "__main__":
    unittest.main()
