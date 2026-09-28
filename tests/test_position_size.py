from __future__ import annotations

import unittest

from trading_bot.config import StrategyConfig
from trading_bot.core.models import PendingEntry, PositionSide, SetupType, StrategyState
from trading_bot.strategy.position_size import calculate_position_size
from tests.helpers import make_context


class PositionSizeTests(unittest.TestCase):
    def test_pending_entry_receives_fixed_size_one(self) -> None:
        pending = PendingEntry(
            side=PositionSide.LONG,
            source_setup=SetupType.BREAKOUT_LONG,
            signal_bar_index=3,
            trade_invalidation_price=95.0,
            hard_stop_price=94.6,
            stop_buffer=0.4,
        )
        result = calculate_position_size(
            make_context(close=100.0),
            StrategyState(pending_entry=pending),
            StrategyConfig(fixed_position_size=1.0),
        )
        self.assertEqual(result.quantity, 1.0)
        self.assertEqual(result.pending_entry.quantity, 1.0)
        self.assertEqual(result.reason, "FIXED_POSITION_SIZE")


if __name__ == "__main__":
    unittest.main()
