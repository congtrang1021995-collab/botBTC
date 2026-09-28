from __future__ import annotations

import unittest

from trading_bot.config import StrategyConfig
from trading_bot.core.engine import EngineState, TradingEngine
from trading_bot.core.models import (
    PositionSide,
    PositionState,
    PositionStatus,
    StrategyState,
    TrendState,
)
from trading_bot.strategy.exit import (
    calculate_take_profit_price,
    evaluate_exit,
)
from tests.helpers import make_context


def open_position(side: PositionSide, target: float) -> StrategyState:
    return StrategyState(
        trend=TrendState.UPTREND if side == PositionSide.LONG else TrendState.DOWNTREND,
        position=PositionState(
            status=PositionStatus.OPEN,
            side=side,
            entry_price=100.0,
            hard_stop_price=90.0 if side == PositionSide.LONG else 110.0,
            take_profit_price=target,
            size=1.0,
        )
    )


class ExitTests(unittest.TestCase):
    def test_default_take_profit_multiple_is_ten_r(self) -> None:
        self.assertEqual(StrategyConfig().take_profit_r_multiple, 10.0)

    def test_take_profit_is_five_r_for_long_and_short(self) -> None:
        self.assertEqual(
            calculate_take_profit_price(PositionSide.LONG, 100.0, 90.0, 5.0),
            150.0,
        )
        self.assertEqual(
            calculate_take_profit_price(PositionSide.SHORT, 100.0, 110.0, 5.0),
            50.0,
        )

    def test_long_exits_at_target_when_intrabar_high_touches(self) -> None:
        result = evaluate_exit(
            make_context(close=112.0, open_=110.0, high=115.0, low=109.0),
            open_position(PositionSide.LONG, 115.0),
            StrategyConfig(),
        )
        self.assertTrue(result.should_exit)
        self.assertEqual(result.exit_price, 115.0)
        self.assertEqual(result.reason, "TAKE_PROFIT_EXIT")

    def test_short_exits_at_target_when_intrabar_low_touches(self) -> None:
        result = evaluate_exit(
            make_context(close=88.0, open_=90.0, high=91.0, low=85.0),
            open_position(PositionSide.SHORT, 85.0),
            StrategyConfig(),
        )
        self.assertTrue(result.should_exit)
        self.assertEqual(result.exit_price, 85.0)
        self.assertEqual(result.reason, "TAKE_PROFIT_EXIT")

    def test_favorable_gap_exits_at_open(self) -> None:
        result = evaluate_exit(
            make_context(close=117.0, open_=116.0, high=118.0, low=116.0),
            open_position(PositionSide.LONG, 115.0),
            StrategyConfig(),
        )
        self.assertTrue(result.should_exit)
        self.assertEqual(result.exit_price, 116.0)
        self.assertEqual(result.reason, "TAKE_PROFIT_GAP_EXIT")

    def test_position_remains_open_before_target(self) -> None:
        result = evaluate_exit(
            make_context(close=110.0, open_=108.0, high=114.9, low=107.0),
            open_position(PositionSide.LONG, 115.0),
            StrategyConfig(),
        )
        self.assertFalse(result.should_exit)
        self.assertEqual(result.reason, "TAKE_PROFIT_NOT_REACHED")

    def test_engine_closes_the_entire_position_at_take_profit(self) -> None:
        engine = TradingEngine(StrategyConfig(exit_on_trend_loss=False))
        engine._state = EngineState(
            strategy=StrategyState(
                trend=TrendState.UPTREND,
                position=PositionState(
                    status=PositionStatus.OPEN,
                    side=PositionSide.LONG,
                    entry_price=100.0,
                    trade_invalidation_price=90.0,
                    initial_hard_stop_price=89.0,
                    hard_stop_price=89.0,
                    take_profit_price=155.0,
                    size=1.0,
                )
            )
        )

        result = engine.process_bar(
            make_context(
                close=112.0,
                open_=110.0,
                high=155.0,
                low=109.0,
            ).bar
        )

        self.assertTrue(result.exit.should_exit)
        self.assertEqual(result.exit.exit_price, 155.0)
        self.assertEqual(result.state.position.status, PositionStatus.FLAT)
        self.assertIn(
            "POSITION_CLOSED_TAKE_PROFIT",
            {event.name for event in result.events},
        )

    def test_engine_gives_hard_stop_priority_when_both_levels_are_touched(self) -> None:
        engine = TradingEngine(StrategyConfig(exit_on_trend_loss=False))
        engine._state = EngineState(
            strategy=StrategyState(
                trend=TrendState.UPTREND,
                position=PositionState(
                    status=PositionStatus.OPEN,
                    side=PositionSide.LONG,
                    entry_price=100.0,
                    trade_invalidation_price=90.0,
                    initial_hard_stop_price=89.0,
                    hard_stop_price=89.0,
                    take_profit_price=155.0,
                    size=1.0,
                )
            )
        )

        result = engine.process_bar(
            make_context(
                close=105.0,
                open_=100.0,
                high=156.0,
                low=88.0,
            ).bar
        )

        event_names = {event.name for event in result.events}
        self.assertTrue(result.invalidation.hard_stop_triggered)
        self.assertFalse(result.exit.should_exit)
        self.assertIn("POSITION_CLOSED_HARD_STOP", event_names)
        self.assertNotIn("POSITION_CLOSED_TAKE_PROFIT", event_names)


if __name__ == "__main__":
    unittest.main()
