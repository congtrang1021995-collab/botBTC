from __future__ import annotations

import unittest

from trading_bot.config import StrategyConfig
from trading_bot.core.models import (
    PositionSide,
    PositionState,
    PositionStatus,
    StrategyState,
)
from trading_bot.strategy.add import evaluate_add
from tests.helpers import make_context


class AddTests(unittest.TestCase):
    def test_long_position_is_never_increased(self) -> None:
        state = StrategyState(
            position=PositionState(
                status=PositionStatus.OPEN,
                side=PositionSide.LONG,
                entry_price=100.0,
                size=1.0,
            )
        )

        result = evaluate_add(make_context(close=105.0), state, StrategyConfig())

        self.assertFalse(result.should_add)
        self.assertEqual(result.quantity, 0.0)
        self.assertEqual(result.reason, "POSITION_ADD_DISABLED")

    def test_short_position_is_never_increased(self) -> None:
        state = StrategyState(
            position=PositionState(
                status=PositionStatus.OPEN,
                side=PositionSide.SHORT,
                entry_price=100.0,
                size=1.0,
            )
        )

        result = evaluate_add(make_context(close=95.0), state, StrategyConfig())

        self.assertFalse(result.should_add)
        self.assertEqual(result.quantity, 0.0)
        self.assertEqual(result.reason, "POSITION_ADD_DISABLED")

    def test_flat_state_does_not_create_an_add(self) -> None:
        result = evaluate_add(
            make_context(close=100.0),
            StrategyState(),
            StrategyConfig(),
        )

        self.assertFalse(result.should_add)
        self.assertEqual(result.quantity, 0.0)
        self.assertEqual(result.reason, "POSITION_ADD_DISABLED")


if __name__ == "__main__":
    unittest.main()
