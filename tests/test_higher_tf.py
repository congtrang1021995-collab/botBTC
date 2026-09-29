from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

from trading_bot.backtest.csv_loader import load_bars_csv
from trading_bot.backtest.runner import run_backtest_report
from trading_bot.config import StrategyConfig
from trading_bot.core.higher_tf import HigherTrendFeed, infer_minutes
from trading_bot.core.models import (
    EmaReference,
    PendingEntry,
    PositionSide,
    SetupType,
    TrendState,
)
from trading_bot.strategy.entry import EntryDecision, filter_by_higher_trend
from tests.helpers import make_bar, make_context

DATA = Path(__file__).resolve().parents[1] / "data" / "mt5"


def _signal(side: PositionSide, index: int = 5) -> EntryDecision:
    setup = SetupType.VALUE_ZONE_LONG if side == PositionSide.LONG else SetupType.VALUE_ZONE_SHORT
    return EntryDecision(
        side=side,
        source_setup=setup,
        signal_bar_index=index,
        pending_entry=PendingEntry(side=side, source_setup=setup, signal_bar_index=index),
        value_zone_entry_side=side,
        value_zone_entry_ema=EmaReference.FAST,
        reason="VALUE_ZONE_CONFIRMED",
    )


class HigherTrendFilterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.context = make_context(close=100.0, index=5)
        self.lenient = StrategyConfig()
        self.strict = StrategyConfig(higher_tf_filter="strict")

    def test_default_is_lenient(self) -> None:
        self.assertEqual(StrategyConfig().higher_tf_filter, "lenient")
        with self.assertRaises(ValueError):
            StrategyConfig(higher_tf_filter="loose")

    def test_lenient_blocks_only_opposite_higher_trend(self) -> None:
        long_signal = _signal(PositionSide.LONG)
        blocked = filter_by_higher_trend(long_signal, self.context, TrendState.DOWNTREND, self.lenient)
        self.assertIsNone(blocked.pending_entry)
        self.assertEqual(blocked.reason, "HIGHER_TF_TREND_FILTER")
        for trend in (TrendState.UPTREND, TrendState.SIDEWAY):
            self.assertIs(filter_by_higher_trend(long_signal, self.context, trend, self.lenient), long_signal)

        short_signal = _signal(PositionSide.SHORT)
        self.assertIsNone(
            filter_by_higher_trend(short_signal, self.context, TrendState.UPTREND, self.lenient).pending_entry
        )
        self.assertIs(
            filter_by_higher_trend(short_signal, self.context, TrendState.SIDEWAY, self.lenient), short_signal
        )

    def test_strict_needs_same_direction(self) -> None:
        long_signal = _signal(PositionSide.LONG)
        for trend in (TrendState.SIDEWAY, TrendState.DOWNTREND):
            self.assertIsNone(filter_by_higher_trend(long_signal, self.context, trend, self.strict).pending_entry)
        self.assertIs(filter_by_higher_trend(long_signal, self.context, TrendState.UPTREND, self.strict), long_signal)

    def test_blocked_signal_clears_value_zone_waiting_state(self) -> None:
        blocked = filter_by_higher_trend(
            _signal(PositionSide.LONG), self.context, TrendState.DOWNTREND, self.lenient
        )
        self.assertIsNone(blocked.value_zone_entry_side)
        self.assertIsNone(blocked.value_zone_entry_ema)
        self.assertIsNone(blocked.side)

    def test_no_filter_without_higher_trend_or_when_off(self) -> None:
        long_signal = _signal(PositionSide.LONG)
        self.assertIs(filter_by_higher_trend(long_signal, self.context, None, self.lenient), long_signal)
        off = StrategyConfig(higher_tf_filter="off")
        self.assertIs(filter_by_higher_trend(long_signal, self.context, TrendState.DOWNTREND, off), long_signal)

    def test_only_new_signals_are_filtered(self) -> None:
        old_pending = _signal(PositionSide.LONG, index=4)
        self.assertIs(
            filter_by_higher_trend(old_pending, self.context, TrendState.DOWNTREND, self.lenient), old_pending
        )


class HigherTrendFeedTests(unittest.TestCase):
    def test_trend_available_only_after_higher_bar_closes(self) -> None:
        feed = HigherTrendFeed(60)
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        for i in range(3):
            self.assertTrue(feed.add(start + timedelta(hours=i), 100.0, 101.0, 99.0, 100.0))
        self.assertIsNone(feed.trend_at(start + timedelta(minutes=59)))
        self.assertEqual(feed.trend_at(start + timedelta(hours=1)), TrendState.SIDEWAY)
        self.assertEqual(len(feed), 3)

    def test_old_or_duplicate_bars_are_ignored(self) -> None:
        feed = HigherTrendFeed(60)
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        feed.add(start, 1.0, 2.0, 0.5, 1.5)
        self.assertFalse(feed.add(start, 1.0, 2.0, 0.5, 1.5))
        self.assertFalse(feed.add(start - timedelta(hours=1), 1.0, 2.0, 0.5, 1.5))
        self.assertEqual(len(feed), 1)

    def test_infer_minutes_uses_smallest_gap(self) -> None:
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        bars = [replace(make_bar(i, 1.0), timestamp=start + timedelta(minutes=15 * i + (60 if i > 2 else 0)))
                for i in range(6)]
        self.assertEqual(infer_minutes(bars), 15)


@unittest.skipUnless((DATA / "MetaQuotes-Demo_XAUUSD_M15.csv").exists(), "thiếu dữ liệu MT5")
class HigherTrendBacktestTests(unittest.TestCase):
    def test_m15_trades_never_open_against_closed_h1_trend(self) -> None:
        m15 = load_bars_csv(DATA / "MetaQuotes-Demo_XAUUSD_M15.csv")[:6000]
        h1 = load_bars_csv(DATA / "MetaQuotes-Demo_XAUUSD_H1.csv")[:1600]
        report = run_backtest_report(m15, higher_bars=h1)
        plain = run_backtest_report(m15)
        feed = HigherTrendFeed(60)
        for bar in h1:
            feed.add(bar.timestamp, bar.open, bar.high, bar.low, bar.close)
        opposite = {PositionSide.LONG: TrendState.DOWNTREND, PositionSide.SHORT: TrendState.UPTREND}
        self.assertTrue(report.trades)
        for trade in report.trades:
            signal_close = m15[trade.entry_bar_index - 1].timestamp + timedelta(minutes=15)
            self.assertNotEqual(feed.trend_at(signal_close), opposite[trade.side])
        self.assertLess(len(report.trades), len(plain.trades))


if __name__ == "__main__":
    unittest.main()
