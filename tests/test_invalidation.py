from __future__ import annotations

import unittest

from trading_bot.config import StrategyConfig, config_for_timeframe
from trading_bot.core.models import (
    PendingEntry,
    PositionSide,
    PositionState,
    PositionStatus,
    SetupType,
    StrategyState,
    TrendState,
)
from trading_bot.strategy.invalidation import (
    apply_minimum_risk,
    evaluate_invalidation,
    minimum_initial_risk,
)
from tests.helpers import make_context


class InvalidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = StrategyConfig(
            stop_atr_multiplier=0.30,
            minimum_tick=0.01,
        )

    def test_default_stop_parameters(self) -> None:
        config = StrategyConfig()
        self.assertEqual(config.atr_length, 13)
        self.assertEqual(config.stop_atr_multiplier, 0.30)

    def test_default_minimum_initial_risk_is_ten_price_units(self) -> None:
        self.assertEqual(StrategyConfig().min_initial_risk, 10.0)
        with self.assertRaises(ValueError):
            StrategyConfig(min_initial_risk=-1.0)

    def test_minimum_initial_risk_is_max_of_price_floor_and_atr_multiple(self) -> None:
        self.assertEqual(StrategyConfig().min_initial_risk_atr_multiplier, 0.0)
        config = config_for_timeframe(None, 15)
        self.assertEqual(config.min_initial_risk_atr_multiplier, 4.0)
        self.assertEqual(config_for_timeframe(None, 60).min_initial_risk_atr_multiplier, 0.0)
        custom = StrategyConfig(min_initial_risk_atr_multiplier=2.0)
        self.assertEqual(config_for_timeframe(custom, 15).min_initial_risk_atr_multiplier, 2.0)
        self.assertAlmostEqual(minimum_initial_risk(config, 2.0), 10.0)
        self.assertAlmostEqual(minimum_initial_risk(config, 9.6), 38.4)
        self.assertAlmostEqual(minimum_initial_risk(config, None), 10.0)
        off = StrategyConfig(min_initial_risk_atr_multiplier=0.0)
        self.assertAlmostEqual(minimum_initial_risk(off, 9.6), 10.0)
        with self.assertRaises(ValueError):
            StrategyConfig(min_initial_risk_atr_multiplier=-1.0)

    def test_minimum_risk_widens_only_tight_stops(self) -> None:
        long_, short = PositionSide.LONG, PositionSide.SHORT
        self.assertAlmostEqual(apply_minimum_risk(long_, 100.0, 97.0, 10.0), 90.0)
        self.assertAlmostEqual(apply_minimum_risk(short, 100.0, 103.0, 10.0), 110.0)
        # 1R đã đủ mốc: giữ nguyên.
        self.assertAlmostEqual(apply_minimum_risk(long_, 100.0, 85.0, 10.0), 85.0)
        self.assertAlmostEqual(apply_minimum_risk(short, 100.0, 110.0, 10.0), 110.0)
        # Giá khớp đã vượt qua stop (gap): giữ nguyên để lệnh bị hủy như cũ.
        self.assertAlmostEqual(apply_minimum_risk(long_, 100.0, 101.0, 10.0), 101.0)
        self.assertAlmostEqual(apply_minimum_risk(short, 100.0, 99.0, 10.0), 99.0)
        # Mốc 0 = tắt.
        self.assertAlmostEqual(apply_minimum_risk(long_, 100.0, 97.0, 0.0), 97.0)

    def test_long_stop_uses_frozen_protected_low_and_atr_buffer(self) -> None:
        pending = PendingEntry(
            side=PositionSide.LONG,
            source_setup=SetupType.VALUE_ZONE_LONG,
            signal_bar_index=5,
        )
        result = evaluate_invalidation(
            make_context(close=105.0, atr=4.0),
            StrategyState(
                protected_swing_low=100.0,
                pending_entry=pending,
            ),
            self.config,
        )
        self.assertAlmostEqual(result.stop_buffer, 1.2)
        self.assertAlmostEqual(result.trade_invalidation_price, 100.0)
        self.assertAlmostEqual(result.hard_stop_price, 98.8)
        self.assertEqual(result.pending_entry.hard_stop_price, 98.8)

    def test_short_stop_is_symmetric(self) -> None:
        pending = PendingEntry(
            side=PositionSide.SHORT,
            source_setup=SetupType.BREAKOUT_SHORT,
            signal_bar_index=5,
        )
        result = evaluate_invalidation(
            make_context(close=105.0, atr=4.0),
            StrategyState(
                protected_swing_high=110.0,
                pending_entry=pending,
            ),
            self.config,
        )
        self.assertAlmostEqual(result.hard_stop_price, 111.2)

    def test_minimum_three_tick_buffer_is_used_before_atr_exists(self) -> None:
        pending = PendingEntry(
            side=PositionSide.LONG,
            source_setup=SetupType.BREAKOUT_LONG,
            signal_bar_index=5,
        )
        result = evaluate_invalidation(
            make_context(close=105.0, atr=None),
            StrategyState(
                protected_swing_low=100.0,
                pending_entry=pending,
            ),
            self.config,
        )
        self.assertAlmostEqual(result.stop_buffer, 0.03)
        self.assertAlmostEqual(result.hard_stop_price, 99.97)

    def test_gap_through_stop_exits_at_open(self) -> None:
        position = PositionState(
            status=PositionStatus.OPEN,
            side=PositionSide.LONG,
            entry_price=110.0,
            trade_invalidation_price=100.0,
            hard_stop_price=99.6,
            stop_buffer=0.4,
            size=1.0,
        )
        result = evaluate_invalidation(
            make_context(open_=98.0, close=99.0),
            StrategyState(trend=TrendState.UPTREND, position=position),
            self.config,
        )
        self.assertTrue(result.hard_stop_triggered)
        self.assertEqual(result.exit_price, 98.0)
        self.assertEqual(result.reason, "HARD_STOP_GAP_EXIT")

    def test_intrabar_stop_exits_at_hard_stop(self) -> None:
        position = PositionState(
            status=PositionStatus.OPEN,
            side=PositionSide.SHORT,
            entry_price=100.0,
            trade_invalidation_price=110.0,
            hard_stop_price=110.4,
            stop_buffer=0.4,
            size=1.0,
        )
        result = evaluate_invalidation(
            make_context(open_=105.0, close=106.0),
            StrategyState(position=position),
            self.config,
        )
        # Default high is max(Open, Close) + 1, so explicitly cross the stop.
        crossing_context = make_context(open_=105.0, close=110.0)
        result = evaluate_invalidation(
            crossing_context,
            StrategyState(position=position),
            self.config,
        )
        self.assertTrue(result.hard_stop_triggered)
        self.assertEqual(result.exit_price, 110.4)
        self.assertEqual(result.reason, "HARD_STOP_INTRABAR_EXIT")

    def test_close_through_protected_swing_does_not_exit_by_itself(self) -> None:
        position = PositionState(
            status=PositionStatus.OPEN,
            side=PositionSide.LONG,
            entry_price=110.0,
            trade_invalidation_price=100.0,
            hard_stop_price=99.6,
            stop_buffer=0.4,
            size=1.0,
        )
        result = evaluate_invalidation(
            make_context(open_=101.0, close=99.8, low=99.7),
            StrategyState(trend=TrendState.UPTREND, position=position),
            self.config,
        )
        self.assertFalse(result.trade_invalidated)
        self.assertFalse(result.hard_stop_triggered)
        self.assertIsNone(result.exit_price)
        self.assertEqual(result.reason, "POSITION_VALID")

    def test_long_trailing_stop_uses_initial_risk_and_strict_thresholds(self) -> None:
        position = PositionState(
            status=PositionStatus.OPEN,
            side=PositionSide.LONG,
            entry_price=100.0,
            initial_hard_stop_price=90.0,
            hard_stop_price=90.0,
            size=1.0,
        )

        at_one_r = evaluate_invalidation(
            make_context(close=109.0, open_=100.0, high=110.0, low=99.0),
            StrategyState(trend=TrendState.UPTREND, position=position),
            self.config,
        )
        self.assertFalse(at_one_r.stop_updated)
        self.assertEqual(at_one_r.hard_stop_price, 90.0)

        beyond_one_r = evaluate_invalidation(
            make_context(close=110.0, open_=100.0, high=110.01, low=99.0),
            StrategyState(trend=TrendState.UPTREND, position=position),
            self.config,
        )
        self.assertTrue(beyond_one_r.stop_updated)
        self.assertEqual(beyond_one_r.hard_stop_price, 100.0)

        at_two_r = evaluate_invalidation(
            make_context(close=119.0, open_=100.0, high=120.0, low=99.0),
            StrategyState(trend=TrendState.UPTREND, position=position),
            self.config,
        )
        self.assertTrue(at_two_r.stop_updated)
        self.assertEqual(at_two_r.hard_stop_price, 100.0)

        beyond_two_r = evaluate_invalidation(
            make_context(close=120.0, open_=100.0, high=120.01, low=99.0),
            StrategyState(trend=TrendState.UPTREND, position=position),
            self.config,
        )
        self.assertEqual(beyond_two_r.hard_stop_price, 110.0)

        at_three_r = evaluate_invalidation(
            make_context(close=129.0, open_=100.0, high=130.0, low=99.0),
            StrategyState(trend=TrendState.UPTREND, position=position),
            self.config,
        )
        self.assertEqual(at_three_r.hard_stop_price, 110.0)

        beyond_three_r = evaluate_invalidation(
            make_context(close=130.0, open_=100.0, high=130.01, low=99.0),
            StrategyState(trend=TrendState.UPTREND, position=position),
            self.config,
        )
        self.assertEqual(beyond_three_r.hard_stop_price, 120.0)

        at_four_r = evaluate_invalidation(
            make_context(close=139.0, open_=100.0, high=140.0, low=99.0),
            StrategyState(trend=TrendState.UPTREND, position=position),
            self.config,
        )
        self.assertEqual(at_four_r.hard_stop_price, 120.0)

        beyond_four_r = evaluate_invalidation(
            make_context(close=140.0, open_=100.0, high=140.01, low=99.0),
            StrategyState(trend=TrendState.UPTREND, position=position),
            self.config,
        )
        self.assertEqual(beyond_four_r.hard_stop_price, 130.0)

        # Bot 2 (2026-09-28): vượt 5R..9R -> stop lên +4R..+8R.
        for trigger_r in range(5, 10):
            at_level = evaluate_invalidation(
                make_context(
                    close=100.0 + trigger_r * 10.0 - 1.0,
                    open_=100.0,
                    high=100.0 + trigger_r * 10.0,
                    low=99.0,
                ),
                StrategyState(trend=TrendState.UPTREND, position=position),
                self.config,
            )
            self.assertEqual(at_level.hard_stop_price, 100.0 + (trigger_r - 2) * 10.0)
            beyond_level = evaluate_invalidation(
                make_context(
                    close=100.0 + trigger_r * 10.0,
                    open_=100.0,
                    high=100.0 + trigger_r * 10.0 + 0.01,
                    low=99.0,
                ),
                StrategyState(trend=TrendState.UPTREND, position=position),
                self.config,
            )
            self.assertEqual(beyond_level.hard_stop_price, 100.0 + (trigger_r - 1) * 10.0)

        beyond_nine_r_caps_at_eight_r = evaluate_invalidation(
            make_context(close=195.0, open_=100.0, high=199.0, low=99.0),
            StrategyState(trend=TrendState.UPTREND, position=position),
            self.config,
        )
        self.assertEqual(beyond_nine_r_caps_at_eight_r.hard_stop_price, 180.0)

    def test_short_trailing_stop_is_symmetric(self) -> None:
        position = PositionState(
            status=PositionStatus.OPEN,
            side=PositionSide.SHORT,
            entry_price=100.0,
            initial_hard_stop_price=110.0,
            hard_stop_price=110.0,
            size=1.0,
        )
        result = evaluate_invalidation(
            make_context(close=90.0, open_=99.0, high=99.5, low=89.99),
            StrategyState(trend=TrendState.DOWNTREND, position=position),
            self.config,
        )
        self.assertTrue(result.stop_updated)
        self.assertEqual(result.hard_stop_price, 100.0)

    def test_trailing_stop_never_moves_backward(self) -> None:
        position = PositionState(
            status=PositionStatus.OPEN,
            side=PositionSide.SHORT,
            entry_price=100.0,
            initial_hard_stop_price=110.0,
            hard_stop_price=90.0,
            size=1.0,
        )
        result = evaluate_invalidation(
            make_context(close=80.0, open_=96.0, high=99.0, low=79.99),
            StrategyState(trend=TrendState.DOWNTREND, position=position),
            self.config,
        )
        self.assertFalse(result.stop_updated)
        self.assertEqual(result.hard_stop_price, 90.0)


if __name__ == "__main__":
    unittest.main()
