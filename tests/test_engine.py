from __future__ import annotations

import unittest

from trading_bot.config import StrategyConfig
from trading_bot.core.engine import EngineState, TradingEngine
from trading_bot.core.models import (
    PendingEntry,
    PositionSide,
    PositionState,
    PositionStatus,
    SetupType,
    StrategyState,
    TrendState,
)
from tests.helpers import make_bar


class EngineTests(unittest.TestCase):
    def test_engine_does_not_confirm_pivot_before_right_legs_exist(self) -> None:
        engine = TradingEngine(
            StrategyConfig(
                ema_fast_length=2,
                ema_slow_length=3,
                slope_length=2,
                pivot_legs=2,
            )
        )
        highs = (2.0, 3.0, 6.0, 4.0, 2.0)
        results = [
            engine.process_bar(make_bar(index, 1.0, high=high, low=0.0))
            for index, high in enumerate(highs)
        ]

        self.assertTrue(
            all(result.context.swings.confirmed_high is None for result in results[:4])
        )
        self.assertEqual(results[4].context.swings.confirmed_high.pivot_bar_index, 2)

    def test_engine_rejects_duplicate_or_out_of_order_bars(self) -> None:
        engine = TradingEngine()
        engine.process_bar(make_bar(5, 10.0))
        with self.assertRaises(ValueError):
            engine.process_bar(make_bar(5, 10.0))
        with self.assertRaises(ValueError):
            engine.process_bar(make_bar(4, 10.0))

    def test_strategy_modules_return_no_action_without_signal_or_position(self) -> None:
        result = TradingEngine().process_bar(make_bar(0, 10.0))
        self.assertFalse(result.entry.should_enter)
        self.assertEqual(result.position_size.quantity, 0.0)
        self.assertFalse(result.add.should_add)
        self.assertFalse(result.exit.should_exit)

    def test_confirmed_entry_uses_next_open_for_entry_r_and_take_profit(self) -> None:
        engine = TradingEngine(
            StrategyConfig(
                require_trend_maintenance_filter=False,
                exit_on_trend_loss=False,
            )
        )
        engine._state = EngineState(
            strategy=StrategyState(
                trend=TrendState.UPTREND,
                pending_entry=PendingEntry(
                    side=PositionSide.LONG,
                    source_setup=SetupType.BREAKOUT_LONG,
                    signal_bar_index=0,
                    trade_invalidation_price=95.0,
                    hard_stop_price=94.0,
                    stop_buffer=1.0,
                ),
            )
        )

        result = engine.process_bar(
            make_bar(1, 103.0, open_=103.0, high=104.0, low=100.0)
        )

        self.assertEqual(result.state.position.status, PositionStatus.OPEN)
        self.assertEqual(result.state.position.entry_price, 103.0)
        self.assertAlmostEqual(result.state.position.take_profit_price, 193.0)
        self.assertEqual(result.state.position.initial_hard_stop_price, 94.0)

    def test_engine_persists_trailing_stop_for_the_next_bar(self) -> None:
        engine = TradingEngine(
            StrategyConfig(
                require_trend_maintenance_filter=False,
                exit_on_trend_loss=False,
            )
        )
        engine._state = EngineState(
            strategy=StrategyState(
                trend=TrendState.UPTREND,
                position=PositionState(
                    status=PositionStatus.OPEN,
                    side=PositionSide.LONG,
                    entry_price=100.0,
                    initial_hard_stop_price=90.0,
                    hard_stop_price=90.0,
                    take_profit_price=150.0,
                    size=1.0,
                ),
            )
        )

        result = engine.process_bar(
            make_bar(1, 105.0, open_=100.0, high=110.1, low=99.0)
        )

        self.assertEqual(result.state.position.hard_stop_price, 100.0)
        self.assertIn("TRAILING_STOP_UPDATED", {e.name for e in result.events})

        stopped = engine.process_bar(
            make_bar(2, 100.5, open_=101.0, high=102.0, low=99.0)
        )
        self.assertTrue(stopped.invalidation.hard_stop_triggered)
        self.assertEqual(stopped.invalidation.exit_price, 100.0)
        self.assertEqual(stopped.invalidation.reason, "TRAILING_STOP_INTRABAR_EXIT")
        self.assertEqual(stopped.state.position.status, PositionStatus.FLAT)

    def test_engine_opens_another_same_direction_trade(self) -> None:
        # Bot 2: lệnh thứ hai phải thuộc loại setup khác (Value Zone đang mở, Breakout vào thêm).
        engine = TradingEngine(
            StrategyConfig(
                require_trend_maintenance_filter=False,
                exit_on_trend_loss=False,
            )
        )
        existing = PositionState(
            trade_id="LONG-existing",
            status=PositionStatus.OPEN,
            side=PositionSide.LONG,
            entry_price=100.0,
            entry_bar_index=0,
            source_setup=SetupType.VALUE_ZONE_LONG,
            trade_invalidation_price=90.0,
            initial_hard_stop_price=89.0,
            hard_stop_price=89.0,
            take_profit_price=155.0,
            stop_buffer=1.0,
            size=1.0,
        )
        engine._state = EngineState(
            strategy=StrategyState(
                trend=TrendState.UPTREND,
                pending_entry=PendingEntry(
                    side=PositionSide.LONG,
                    source_setup=SetupType.BREAKOUT_LONG,
                    signal_bar_index=0,
                    trade_invalidation_price=95.0,
                    hard_stop_price=94.0,
                    stop_buffer=1.0,
                ),
                position=existing,
                positions=(existing,),
            )
        )

        result = engine.process_bar(
            make_bar(1, 103.0, open_=103.0, high=104.0, low=99.0)
        )

        self.assertTrue(result.entry.should_enter)
        self.assertEqual(len(result.state.open_positions), 2)
        self.assertEqual(result.state.open_positions[0], existing)
        self.assertEqual(result.state.open_positions[1].entry_price, 103.0)
        self.assertNotEqual(
            result.state.open_positions[0].trade_id,
            result.state.open_positions[1].trade_id,
        )
        self.assertEqual(
            sum(event.name == "POSITION_OPENED" for event in result.events),
            1,
        )
    def _breakout_long(self, *, hard_stop: float) -> PositionState:
        return PositionState(
            trade_id="LONG-existing",
            status=PositionStatus.OPEN,
            side=PositionSide.LONG,
            entry_price=100.0,
            entry_bar_index=0,
            source_setup=SetupType.BREAKOUT_LONG,
            trade_invalidation_price=hard_stop + 1.0,
            initial_hard_stop_price=hard_stop,
            hard_stop_price=hard_stop,
            take_profit_price=155.0,
            stop_buffer=1.0,
            size=1.0,
        )

    def _pending_breakout_long(self) -> PendingEntry:
        return PendingEntry(
            side=PositionSide.LONG,
            source_setup=SetupType.BREAKOUT_LONG,
            signal_bar_index=0,
            trade_invalidation_price=95.0,
            hard_stop_price=94.0,
            stop_buffer=1.0,
        )

    def test_engine_cancels_pending_entry_when_setup_slot_is_full(self) -> None:
        engine = TradingEngine(StrategyConfig(exit_on_trend_loss=False))
        existing = self._breakout_long(hard_stop=89.0)
        engine._state = EngineState(
            strategy=StrategyState(
                trend=TrendState.UPTREND,
                pending_entry=self._pending_breakout_long(),
                position=existing,
                positions=(existing,),
            )
        )

        result = engine.process_bar(make_bar(1, 103.0, open_=103.0, high=104.0, low=99.0))

        self.assertFalse(result.entry.should_enter)
        self.assertTrue(result.entry.cancelled)
        self.assertEqual(result.entry.reason, "PENDING_ENTRY_CANCELLED_SETUP_SLOT_FULL")
        self.assertEqual(result.state.open_positions, (existing,))
        self.assertIn("ENTRY_CANCELLED", {event.name for event in result.events})

    def test_engine_frees_setup_slot_when_existing_trade_stops_in_same_bar(self) -> None:
        # Lệnh Breakout cũ bị hard stop trong nến; lệnh Breakout chờ khớp tại Open vẫn vào.
        engine = TradingEngine(StrategyConfig(exit_on_trend_loss=False))
        existing = self._breakout_long(hard_stop=100.5)
        engine._state = EngineState(
            strategy=StrategyState(
                trend=TrendState.UPTREND,
                pending_entry=self._pending_breakout_long(),
                position=existing,
                positions=(existing,),
            )
        )

        result = engine.process_bar(make_bar(1, 103.0, open_=103.0, high=104.0, low=99.0))

        self.assertTrue(result.entry.should_enter)
        names = [event.name for event in result.events]
        self.assertIn("POSITION_CLOSED_HARD_STOP", names)
        self.assertIn("POSITION_OPENED", names)
        self.assertEqual(len(result.state.open_positions), 1)
        self.assertEqual(result.state.open_positions[0].entry_price, 103.0)
        self.assertEqual(result.state.open_positions[0].source_setup, SetupType.BREAKOUT_LONG)

    def test_each_overlapping_trade_exits_independently(self) -> None:
        engine = TradingEngine(
            StrategyConfig(
                require_trend_maintenance_filter=False,
                exit_on_trend_loss=False,
            )
        )
        first = PositionState(
            trade_id="LONG-1",
            status=PositionStatus.OPEN,
            side=PositionSide.LONG,
            entry_price=100.0,
            entry_bar_index=0,
            initial_hard_stop_price=90.0,
            hard_stop_price=90.0,
            take_profit_price=150.0,
            size=1.0,
        )
        second = PositionState(
            trade_id="LONG-2",
            status=PositionStatus.OPEN,
            side=PositionSide.LONG,
            entry_price=140.0,
            entry_bar_index=0,
            initial_hard_stop_price=120.0,
            hard_stop_price=120.0,
            take_profit_price=240.0,
            size=2.0,
        )
        engine._state = EngineState(
            strategy=StrategyState(
                trend=TrendState.UPTREND,
                position=second,
                positions=(first, second),
            )
        )

        result = engine.process_bar(
            make_bar(1, 145.0, open_=140.0, high=151.0, low=130.0)
        )

        self.assertEqual(result.state.open_positions, (second,))
        close_events = [
            event
            for event in result.events
            if event.name == "POSITION_CLOSED_TAKE_PROFIT"
        ]
        self.assertEqual(len(close_events), 1)
        self.assertEqual(close_events[0].payload["trade_id"], "LONG-1")
        self.assertEqual(close_events[0].payload["pnl"], 50.0)

if __name__ == "__main__":
    unittest.main()
