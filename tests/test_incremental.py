from __future__ import annotations

import pickle
import random
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "data" / "chart_template"))

from incremental import IncrementalChart  # noqa: E402
from trading_bot.backtest.metrics import extract_closed_trades  # noqa: E402
from trading_bot.backtest.runner import run_backtest  # noqa: E402
from trading_bot.core.models import Bar  # noqa: E402


def wave_bars(count: int, seed: int = 3) -> list[Bar]:
    """Random walk cố định (seed) với xu hướng lên/xuống xen kẽ mỗi 400 nến để Bot2 có lệnh."""
    rng = random.Random(seed)
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    bars, previous = [], 100.0
    for i in range(count):
        drift = 0.25 if (i // 400) % 2 == 0 else -0.25
        close = max(5.0, previous + drift + rng.gauss(0, 1.2))
        high = max(previous, close) + abs(rng.gauss(0, 0.6))
        low = min(previous, close) - abs(rng.gauss(0, 0.6))
        bars.append(Bar(index=i, open=previous, high=high, low=low, close=close,
                        timestamp=start + timedelta(hours=i)))
        previous = close
    return bars


class IncrementalChartTest(unittest.TestCase):
    def test_resume_from_pickle_matches_single_run(self) -> None:
        bars = wave_bars(3000)
        single = IncrementalChart()
        for bar in bars:
            single.add(bar)
        expected = single.payload()
        self.assertGreater(len(expected["trades"]), 5)

        resumed = IncrementalChart()
        for cut in (0, 1000, 2200, 3000):
            resumed = pickle.loads(pickle.dumps(resumed))
            for bar in bars[len(resumed):cut]:
                resumed.add(bar)
        self.assertEqual(resumed.payload(), expected)

    def test_ledger_matches_backtest_runner(self) -> None:
        bars = wave_bars(2000)
        chart = IncrementalChart()
        for bar in bars:
            chart.add(bar)
        self.assertEqual(chart.closed, extract_closed_trades(run_backtest(bars)))

    def test_higher_timeframe_filter_matches_backtest_and_survives_pickle(self) -> None:
        bars = wave_bars(2400)
        higher = [Bar(index=i // 4, open=bars[i].open, high=max(b.high for b in bars[i:i + 4]),
                      low=min(b.low for b in bars[i:i + 4]), close=bars[i + 3].close,
                      timestamp=bars[i].timestamp) for i in range(0, 2400, 4)]
        expected = extract_closed_trades(run_backtest(bars, higher_bars=higher))
        chart = IncrementalChart(minutes=60, higher_minutes=240)
        for i, bar in enumerate(bars):
            if i == 1200:
                chart = pickle.loads(pickle.dumps(chart))
            for hb in higher:
                if hb.timestamp + timedelta(hours=4) <= bar.timestamp + timedelta(hours=1):
                    chart.add_higher(hb.timestamp, hb.open, hb.high, hb.low, hb.close)
            chart.add(bar)
        self.assertEqual(chart.closed, expected)
        self.assertNotEqual(expected, extract_closed_trades(run_backtest(bars)))

    def test_rejects_out_of_order_bar(self) -> None:
        chart = IncrementalChart()
        bars = wave_bars(3)
        chart.add(bars[0])
        with self.assertRaises(ValueError):
            chart.add(bars[2])


if __name__ == "__main__":
    unittest.main()
