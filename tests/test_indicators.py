from __future__ import annotations

import unittest

from trading_bot.config import StrategyConfig
from trading_bot.core.indicators import (
    IndicatorState,
    delta_ratios,
    linear_regression_slope,
    update_indicators,
)
from tests.helpers import make_bar


class IndicatorTests(unittest.TestCase):
    def test_linear_regression_slope_uses_oldest_to_newest(self) -> None:
        self.assertEqual(linear_regression_slope((1.0, 2.0, 3.0, 4.0)), 1.0)
        self.assertEqual(linear_regression_slope((4.0, 3.0, 2.0, 1.0)), -1.0)

    def test_zero_delta_stays_in_ratio_denominator(self) -> None:
        positive, negative = delta_ratios((1.0, 2.0, 2.0, 1.0, 2.0))
        self.assertEqual(positive, 0.5)
        self.assertEqual(negative, 0.25)

    def test_ema_matches_pine_first_source_initialization(self) -> None:
        config = StrategyConfig(
            ema_fast_length=3,
            ema_slow_length=4,
            slope_length=2,
        )
        state = IndicatorState()
        snapshots = []
        for close in (1.0, 2.0, 3.0, 4.0):
            state, snapshot = update_indicators(state, close, config)
            snapshots.append(snapshot)

        self.assertEqual(snapshots[0].ema_fast, 1.0)
        self.assertEqual(snapshots[1].ema_fast, 1.5)
        self.assertEqual(snapshots[2].ema_fast, 2.25)
        self.assertEqual(snapshots[3].ema_fast, 3.125)
        self.assertAlmostEqual(snapshots[3].ema_slow, 2.824)
        self.assertEqual(snapshots[3].ema_slope, 0.875)

    def test_confirm_slope_uses_its_own_window(self) -> None:
        # slope cũ cần 8 giá trị, slope xác nhận Bot 2 chỉ cần 7.
        config = StrategyConfig(ema_fast_length=1, slope_length=8, confirm_slope_length=7)
        state = IndicatorState()
        snapshots = []
        for close in (1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0):
            state, snapshot = update_indicators(state, close, config)
            snapshots.append(snapshot)

        self.assertIsNone(snapshots[5].ema_confirm_slope)
        self.assertIsNone(snapshots[6].ema_slope)
        self.assertAlmostEqual(snapshots[6].ema_confirm_slope, 1.0)
        self.assertAlmostEqual(snapshots[7].ema_slope, 1.0)
        self.assertAlmostEqual(snapshots[7].ema_confirm_slope, 1.0)
        self.assertEqual(len(state.fast_ema_history), 8)

    def test_confirm_slope_window_can_exceed_slope_window(self) -> None:
        config = StrategyConfig(ema_fast_length=1, slope_length=2, confirm_slope_length=3)
        state = IndicatorState()
        snapshots = []
        for close in (1.0, 2.0, 4.0):
            state, snapshot = update_indicators(state, close, config)
            snapshots.append(snapshot)

        self.assertAlmostEqual(snapshots[1].ema_slope, 1.0)
        self.assertIsNone(snapshots[1].ema_confirm_slope)
        self.assertAlmostEqual(snapshots[2].ema_slope, 2.0)
        self.assertAlmostEqual(snapshots[2].ema_confirm_slope, 1.5)

    def test_atr_uses_true_range_and_wilder_smoothing(self) -> None:
        config = StrategyConfig(atr_length=3)
        state = IndicatorState()
        bars = (
            make_bar(0, 10.0, high=11.0, low=9.0),
            make_bar(1, 12.0, high=13.0, low=10.0),
            make_bar(2, 13.0, high=14.0, low=12.0),
            make_bar(3, 15.0, high=16.0, low=14.0),
        )
        snapshots = []
        for bar in bars:
            state, snapshot = update_indicators(state, bar, config)
            snapshots.append(snapshot)

        self.assertIsNone(snapshots[1].atr)
        self.assertAlmostEqual(snapshots[2].atr, 7.0 / 3.0)
        self.assertAlmostEqual(snapshots[3].atr, 23.0 / 9.0)



if __name__ == "__main__":
    unittest.main()
