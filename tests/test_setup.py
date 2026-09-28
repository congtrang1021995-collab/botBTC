from __future__ import annotations

import unittest

from trading_bot.config import StrategyConfig
from trading_bot.core.models import SetupType, StrategyState, TrendState
from trading_bot.strategy.setup import evaluate_setup
from tests.helpers import make_context


class SetupTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = StrategyConfig()

    def test_sideway_is_always_no_trade(self) -> None:
        context = make_context(close=120.0)
        result = evaluate_setup(context, StrategyState(), self.config)
        self.assertTrue(result.no_trade)
        self.assertEqual(result.active, frozenset())
        self.assertEqual(result.direction, 0)

    def test_value_zone_accepts_equal_ema_but_rejects_equal_swing(self) -> None:
        state = StrategyState(trend=TrendState.UPTREND)
        at_ema = evaluate_setup(
            make_context(close=100.0, ema_fast=100.0, last_low=95.0),
            state,
            self.config,
        )
        self.assertIn(SetupType.VALUE_ZONE_LONG, at_ema.active)

        at_swing = evaluate_setup(
            make_context(close=95.0, ema_fast=100.0, last_low=95.0),
            state,
            self.config,
        )
        self.assertNotIn(SetupType.VALUE_ZONE_LONG, at_swing.active)

    def test_breakout_uses_close_and_strict_comparison(self) -> None:
        state = StrategyState(trend=TrendState.UPTREND)
        equal = evaluate_setup(
            make_context(close=110.0, last_high=110.0),
            state,
            self.config,
        )
        above = evaluate_setup(
            make_context(close=111.0, last_high=110.0),
            state,
            self.config,
        )
        self.assertNotIn(SetupType.BREAKOUT_LONG, equal.active)
        self.assertIn(SetupType.BREAKOUT_LONG, above.active)

    def test_mask_preserves_simultaneous_long_setups(self) -> None:
        state = StrategyState(trend=TrendState.UPTREND)
        result = evaluate_setup(
            make_context(
                close=111.0,
                ema_fast=115.0,
                ema_slow=105.0,
                last_high=110.0,
                last_low=95.0,
            ),
            state,
            self.config,
        )
        self.assertEqual(
            result.active,
            frozenset({SetupType.VALUE_ZONE_LONG, SetupType.BREAKOUT_LONG}),
        )
        self.assertEqual(result.direction, 1)
        self.assertEqual(result.mask, 5)

    def test_started_signal_is_emitted_only_on_false_to_true_edge(self) -> None:
        context = make_context(close=100.0, ema_fast=100.0, last_low=95.0)
        first = evaluate_setup(
            context,
            StrategyState(trend=TrendState.UPTREND),
            self.config,
        )
        second = evaluate_setup(
            context,
            StrategyState(
                trend=TrendState.UPTREND,
                active_setups=first.active,
            ),
            self.config,
        )
        self.assertEqual(first.started, frozenset({SetupType.VALUE_ZONE_LONG}))
        self.assertEqual(second.started, frozenset())


if __name__ == "__main__":
    unittest.main()

