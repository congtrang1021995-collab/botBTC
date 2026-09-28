from __future__ import annotations

import unittest
from dataclasses import replace

from trading_bot.config import StrategyConfig
from trading_bot.core.models import (
    PivotConfirmation,
    PivotKind,
    StrategyState,
    TrendState,
)
from trading_bot.strategy.setup import evaluate_setup
from trading_bot.strategy.trend import evaluate_trend
from tests.helpers import make_context


class TrendTests(unittest.TestCase):
    def setUp(self) -> None:
        # Ngưỡng độ dốc = 0: các test rule cũ chỉ cần dấu của slope, không cần ATR.
        self.config = StrategyConfig(min_confirm_slope=0.0)

    def test_uptrend_requires_ema_filter_and_hh_hl(self) -> None:
        context = make_context(close=105.0)
        decision = evaluate_trend(context, StrategyState(), self.config)

        self.assertEqual(decision.trend, TrendState.UPTREND)
        self.assertTrue(decision.higher_high)
        self.assertTrue(decision.higher_low)
        self.assertEqual(decision.protected_swing_low, 95.0)

    def test_missing_higher_low_keeps_sideway(self) -> None:
        context = make_context(close=105.0, previous_low=95.0, last_low=90.0)
        decision = evaluate_trend(context, StrategyState(), self.config)
        self.assertEqual(decision.trend, TrendState.SIDEWAY)

    def test_confirmed_uptrend_survives_ema_pullback(self) -> None:
        # Close hồi xuống dưới cả EMA34 lẫn EMA89: uptrend vẫn được giữ vì
        # EMA34 > EMA89, và Value Zone Long phải kích hoạt.
        previous = StrategyState(
            trend=TrendState.UPTREND,
            protected_swing_low=95.0,
        )
        context = make_context(
            close=98.0,
            ema_fast=100.0,
            ema_slow=99.0,
            slope=-1.0,
            confirm_slope=0.5,
            positive_ratio=0.0,
            negative_ratio=1.0,
        )
        trend = evaluate_trend(context, previous, self.config)
        self.assertEqual(trend.trend, TrendState.UPTREND)

        state_after_trend = StrategyState(
            trend=trend.trend,
            protected_swing_low=trend.protected_swing_low,
        )
        setup = evaluate_setup(context, state_after_trend, self.config)
        self.assertEqual(setup.direction, 1)
        self.assertEqual(setup.mask, 1)

    def test_close_below_protected_low_does_not_break_uptrend(self) -> None:
        previous = StrategyState(
            trend=TrendState.UPTREND,
            protected_swing_low=95.0,
        )
        context = make_context(close=94.0)
        decision = evaluate_trend(context, previous, self.config)

        self.assertTrue(decision.broke_protected_low)
        self.assertEqual(decision.trend, TrendState.UPTREND)
        self.assertEqual(decision.protected_swing_low, 95.0)

    def test_close_above_protected_high_does_not_break_downtrend(self) -> None:
        previous = StrategyState(
            trend=TrendState.DOWNTREND,
            protected_swing_high=105.0,
        )
        context = make_context(
            close=106.0,
            ema_fast=100.0,
            ema_slow=101.0,
            slope=-1.0,
        )
        decision = evaluate_trend(context, previous, self.config)

        self.assertTrue(decision.broke_protected_high)
        self.assertEqual(decision.trend, TrendState.DOWNTREND)
        self.assertEqual(decision.protected_swing_high, 105.0)

    def test_uptrend_protection_uses_latest_confirmed_swing_low(self) -> None:
        previous = StrategyState(
            trend=TrendState.UPTREND,
            protected_swing_low=95.0,
        )
        context = make_context(close=100.0, last_low=90.0)
        context = replace(
            context,
            swings=replace(
                context.swings,
                confirmed_low=PivotConfirmation(
                    kind=PivotKind.LOW,
                    price=90.0,
                    pivot_bar_index=7,
                    confirmation_bar_index=10,
                ),
            ),
        )

        decision = evaluate_trend(context, previous, self.config)

        self.assertEqual(decision.trend, TrendState.UPTREND)
        self.assertEqual(decision.protected_swing_low, 90.0)

    def test_downtrend_protection_uses_latest_confirmed_swing_high(self) -> None:
        previous = StrategyState(
            trend=TrendState.DOWNTREND,
            protected_swing_high=105.0,
        )
        context = make_context(
            close=100.0,
            ema_fast=99.0,
            ema_slow=101.0,
            slope=-1.0,
            last_high=110.0,
        )
        context = replace(
            context,
            swings=replace(
                context.swings,
                confirmed_high=PivotConfirmation(
                    kind=PivotKind.HIGH,
                    price=110.0,
                    pivot_bar_index=7,
                    confirmation_bar_index=10,
                ),
            ),
        )

        decision = evaluate_trend(context, previous, self.config)

        self.assertEqual(decision.trend, TrendState.DOWNTREND)
        self.assertEqual(decision.protected_swing_high, 110.0)

    def test_downtrend_logic_is_symmetric(self) -> None:
        context = make_context(
            close=95.0,
            ema_fast=100.0,
            ema_slow=101.0,
            slope=-1.0,
            positive_ratio=0.25,
            negative_ratio=0.75,
            previous_high=110.0,
            last_high=105.0,
            previous_low=100.0,
            last_low=90.0,
        )
        decision = evaluate_trend(context, StrategyState(), self.config)

        self.assertEqual(decision.trend, TrendState.DOWNTREND)
        self.assertEqual(decision.protected_swing_high, 105.0)

    def test_uptrend_lost_when_ema_fast_crosses_below_ema_slow(self) -> None:
        previous = StrategyState(
            trend=TrendState.UPTREND,
            protected_swing_low=95.0,
        )
        context = make_context(close=105.0, ema_fast=99.0, ema_slow=100.0)
        decision = evaluate_trend(context, previous, self.config)

        self.assertFalse(decision.broke_protected_low)
        self.assertFalse(decision.ema_up_maintain)
        self.assertEqual(decision.trend, TrendState.SIDEWAY)
        self.assertIsNone(decision.protected_swing_low)

    def test_equal_emas_do_not_break_uptrend(self) -> None:
        previous = StrategyState(
            trend=TrendState.UPTREND,
            protected_swing_low=95.0,
        )
        context = make_context(close=105.0, ema_fast=100.0, ema_slow=100.0)
        decision = evaluate_trend(context, previous, self.config)

        self.assertTrue(decision.ema_up_maintain)
        self.assertEqual(decision.trend, TrendState.UPTREND)

    def test_equal_emas_do_not_break_downtrend(self) -> None:
        previous = StrategyState(
            trend=TrendState.DOWNTREND,
            protected_swing_high=105.0,
        )
        context = make_context(close=95.0, ema_fast=100.0, ema_slow=100.0, slope=-1.0)
        decision = evaluate_trend(context, previous, self.config)

        self.assertTrue(decision.ema_down_maintain)
        self.assertEqual(decision.trend, TrendState.DOWNTREND)

    def test_uptrend_survives_close_below_ema_slow(self) -> None:
        # Bộ lọc duy trì chỉ ràng buộc EMA34 >= EMA89; vị trí của Close không tính.
        previous = StrategyState(
            trend=TrendState.UPTREND,
            protected_swing_low=95.0,
        )
        context = make_context(close=96.0, ema_fast=100.0, ema_slow=99.0)
        decision = evaluate_trend(context, previous, self.config)

        self.assertFalse(decision.broke_protected_low)
        self.assertTrue(decision.ema_up_maintain)
        self.assertEqual(decision.trend, TrendState.UPTREND)

    def test_maintenance_filter_can_be_disabled(self) -> None:
        config = StrategyConfig(
            require_trend_maintenance_filter=False, min_confirm_slope=0.0
        )
        previous = StrategyState(
            trend=TrendState.UPTREND,
            protected_swing_low=95.0,
        )
        context = make_context(close=98.0, ema_fast=99.0, ema_slow=100.0)
        decision = evaluate_trend(context, previous, config)

        self.assertTrue(decision.ema_up_maintain)
        self.assertEqual(decision.trend, TrendState.UPTREND)

    def test_downtrend_maintenance_is_symmetric(self) -> None:
        previous = StrategyState(
            trend=TrendState.DOWNTREND,
            protected_swing_high=105.0,
        )
        intact = make_context(close=100.5, ema_fast=100.0, ema_slow=101.0, slope=-1.0)
        self.assertEqual(
            evaluate_trend(intact, previous, self.config).trend,
            TrendState.DOWNTREND,
        )

        ema_flipped = make_context(close=95.0, ema_fast=101.0, ema_slow=100.0, slope=-1.0)
        self.assertEqual(
            evaluate_trend(ema_flipped, previous, self.config).trend,
            TrendState.SIDEWAY,
        )

        close_above_slow = make_context(
            close=101.5, ema_fast=100.0, ema_slow=101.0, slope=-1.0
        )
        self.assertEqual(
            evaluate_trend(close_above_slow, previous, self.config).trend,
            TrendState.DOWNTREND,
        )


class ConfirmSlopeTests(unittest.TestCase):
    """Bot 2 Step 1: độ dốc EMA34 trên 13 nến gần nhất là điều kiện bắt buộc thêm vào rule cũ."""

    def setUp(self) -> None:
        self.config = StrategyConfig(min_confirm_slope=0.0)

    def test_default_confirm_window_is_thirteen_candles(self) -> None:
        self.assertEqual(StrategyConfig().confirm_slope_length, 13)
        self.assertEqual(StrategyConfig().slope_length, 8)
        self.assertAlmostEqual(StrategyConfig().min_confirm_slope, 0.0)
        self.assertEqual(StrategyConfig().pivot_legs, 5)

    def test_uptrend_confirmation_needs_positive_confirm_slope(self) -> None:
        # Toàn bộ rule cũ thỏa (EMA filter, ratio, HH/HL) nhưng slope 13 nến không dương.
        for confirm_slope in (0.0, -0.3, None):
            context = make_context(close=105.0, confirm_slope=confirm_slope)
            decision = evaluate_trend(context, StrategyState(), self.config)
            self.assertTrue(decision.ema_up_filter)
            self.assertFalse(decision.slope_confirm_up)
            self.assertFalse(decision.uptrend_rule)
            self.assertEqual(decision.trend, TrendState.SIDEWAY, confirm_slope)
            self.assertIsNone(decision.protected_swing_low)

    def test_uptrend_confirmed_when_all_old_conditions_and_confirm_slope_pass(self) -> None:
        context = make_context(close=105.0, confirm_slope=0.3)
        decision = evaluate_trend(context, StrategyState(), self.config)
        self.assertTrue(decision.slope_confirm_up)
        self.assertEqual(decision.trend, TrendState.UPTREND)
        self.assertEqual(decision.protected_swing_low, 95.0)

    def test_downtrend_confirmation_needs_negative_confirm_slope(self) -> None:
        base = dict(
            close=95.0,
            ema_fast=100.0,
            ema_slow=101.0,
            slope=-1.0,
            positive_ratio=0.25,
            negative_ratio=0.75,
            previous_high=110.0,
            last_high=105.0,
            previous_low=100.0,
            last_low=90.0,
        )
        blocked = evaluate_trend(
            make_context(confirm_slope=0.2, **base), StrategyState(), self.config
        )
        self.assertTrue(blocked.ema_down_filter)
        self.assertFalse(blocked.slope_confirm_down)
        self.assertEqual(blocked.trend, TrendState.SIDEWAY)

        confirmed = evaluate_trend(
            make_context(confirm_slope=-0.2, **base), StrategyState(), self.config
        )
        self.assertEqual(confirmed.trend, TrendState.DOWNTREND)

    def test_held_uptrend_drops_to_sideway_when_confirm_slope_stops_rising(self) -> None:
        previous = StrategyState(trend=TrendState.UPTREND, protected_swing_low=95.0)
        # EMA34 >= EMA89 vẫn đúng (bộ lọc duy trì cũ thỏa) nhưng slope 13 nến về 0 / âm.
        for confirm_slope in (0.0, -0.1):
            context = make_context(
                close=104.0, ema_fast=100.0, ema_slow=99.0, confirm_slope=confirm_slope
            )
            decision = evaluate_trend(context, previous, self.config)
            self.assertTrue(decision.ema_up_maintain)
            self.assertEqual(decision.trend, TrendState.SIDEWAY, confirm_slope)
            self.assertTrue(decision.changed)
            self.assertIsNone(decision.protected_swing_low)

    def test_held_uptrend_flips_only_when_new_downtrend_fully_confirmed(self) -> None:
        previous = StrategyState(trend=TrendState.UPTREND, protected_swing_low=95.0)
        base = dict(
            close=95.0,
            slope=-1.0,
            confirm_slope=-0.4,
            positive_ratio=0.0,
            negative_ratio=1.0,
            previous_high=110.0,
            last_high=105.0,
            previous_low=100.0,
            last_low=96.0,
        )
        # EMA34 vẫn trên EMA89: slope 13 nến làm mất uptrend nhưng downtrend mới chưa
        # đủ điều kiện (EMA34 < EMA89 sai) -> SIDEWAY.
        decision = evaluate_trend(
            make_context(ema_fast=100.0, ema_slow=99.0, **base), previous, self.config
        )
        self.assertEqual(decision.trend, TrendState.SIDEWAY)

        # Toàn bộ điều kiện downtrend thỏa -> đổi thẳng sang DOWNTREND.
        decision = evaluate_trend(
            make_context(ema_fast=100.0, ema_slow=101.0, **base), previous, self.config
        )
        self.assertEqual(decision.trend, TrendState.DOWNTREND)
        self.assertEqual(decision.protected_swing_high, 105.0)

    def test_held_downtrend_drops_to_sideway_when_confirm_slope_stops_falling(self) -> None:
        previous = StrategyState(trend=TrendState.DOWNTREND, protected_swing_high=105.0)
        context = make_context(
            close=96.0, ema_fast=100.0, ema_slow=101.0, slope=-1.0, confirm_slope=0.1
        )
        decision = evaluate_trend(context, previous, self.config)
        self.assertTrue(decision.ema_down_maintain)
        self.assertFalse(decision.slope_confirm_down)
        self.assertEqual(decision.trend, TrendState.SIDEWAY)
        self.assertIsNone(decision.protected_swing_high)

    def test_small_confirm_slope_is_sideway_when_threshold_enabled(self) -> None:
        # Mốc cố định 0.2 giá/nến -> cần |slope| > 0.2 mỗi nến (ATR không liên quan).
        config = StrategyConfig(min_confirm_slope=0.2)

        weak = evaluate_trend(
            make_context(close=105.0, confirm_slope=0.15, atr=2.0),
            StrategyState(),
            config,
        )
        self.assertTrue(weak.ema_up_filter)
        self.assertAlmostEqual(weak.confirm_slope_threshold, 0.2)
        self.assertFalse(weak.slope_confirm_up)
        self.assertEqual(weak.trend, TrendState.SIDEWAY)

        strong = evaluate_trend(
            make_context(close=105.0, confirm_slope=0.25, atr=2.0),
            StrategyState(),
            config,
        )
        self.assertTrue(strong.slope_confirm_up)
        self.assertEqual(strong.trend, TrendState.UPTREND)

        exact = evaluate_trend(
            make_context(close=105.0, confirm_slope=0.2, atr=2.0),
            StrategyState(),
            config,
        )
        self.assertEqual(exact.trend, TrendState.SIDEWAY)

    def test_threshold_is_symmetric_for_downtrend(self) -> None:
        config = StrategyConfig(min_confirm_slope=0.2)
        base = dict(
            close=95.0,
            ema_fast=100.0,
            ema_slow=101.0,
            slope=-1.0,
            positive_ratio=0.25,
            negative_ratio=0.75,
            previous_high=110.0,
            last_high=105.0,
            previous_low=100.0,
            last_low=90.0,
            atr=2.0,
        )
        weak = evaluate_trend(make_context(confirm_slope=-0.15, **base), StrategyState(), config)
        self.assertEqual(weak.trend, TrendState.SIDEWAY)
        strong = evaluate_trend(make_context(confirm_slope=-0.25, **base), StrategyState(), config)
        self.assertEqual(strong.trend, TrendState.DOWNTREND)

    def test_held_trend_drops_to_sideway_when_slope_flattens_below_threshold(self) -> None:
        config = StrategyConfig(min_confirm_slope=0.2)
        previous = StrategyState(trend=TrendState.UPTREND, protected_swing_low=95.0)
        decision = evaluate_trend(
            make_context(close=104.0, ema_fast=100.0, ema_slow=99.0, confirm_slope=0.1, atr=2.0),
            previous,
            config,
        )
        self.assertTrue(decision.ema_up_maintain)
        self.assertEqual(decision.trend, TrendState.SIDEWAY)

    def test_threshold_does_not_depend_on_atr(self) -> None:
        # Mốc cố định theo giá/nến: không cần ATR, ATR = None vẫn xác nhận được trend.
        with_threshold = StrategyConfig(min_confirm_slope=0.2)
        decision = evaluate_trend(
            make_context(close=105.0, confirm_slope=5.0, atr=None), StrategyState(), with_threshold
        )
        self.assertAlmostEqual(decision.confirm_slope_threshold, 0.2)
        self.assertEqual(decision.trend, TrendState.UPTREND)
        decision = evaluate_trend(
            make_context(close=105.0, confirm_slope=0.1, atr=None), StrategyState(), with_threshold
        )
        self.assertEqual(decision.trend, TrendState.SIDEWAY)

        sign_only = StrategyConfig(min_confirm_slope=0.0)
        decision = evaluate_trend(
            make_context(close=105.0, confirm_slope=0.01, atr=None), StrategyState(), sign_only
        )
        self.assertEqual(decision.confirm_slope_threshold, 0.0)
        self.assertEqual(decision.trend, TrendState.UPTREND)

    def test_confirm_slope_applies_even_when_maintenance_filter_disabled(self) -> None:
        config = StrategyConfig(
            require_trend_maintenance_filter=False, min_confirm_slope=0.0
        )
        previous = StrategyState(trend=TrendState.UPTREND, protected_swing_low=95.0)
        context = make_context(
            close=98.0, ema_fast=99.0, ema_slow=100.0, confirm_slope=-0.2
        )
        decision = evaluate_trend(context, previous, config)
        self.assertTrue(decision.ema_up_maintain)
        self.assertEqual(decision.trend, TrendState.SIDEWAY)


if __name__ == "__main__":
    unittest.main()
