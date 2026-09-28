from __future__ import annotations

import unittest
from dataclasses import replace

from trading_bot.config import StrategyConfig
from trading_bot.core.models import (
    EmaReference,
    PositionSide,
    PositionState,
    PositionStatus,
    SetupType,
    StrategyState,
    TrendState,
)
from trading_bot.strategy.entry import evaluate_entry
from tests.helpers import make_context


class EntryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = StrategyConfig()

    @staticmethod
    def _ready(pending, *, hard_stop: float, invalidation: float = 95.0):
        return replace(
            pending,
            trade_invalidation_price=invalidation,
            hard_stop_price=hard_stop,
            stop_buffer=0.4,
        )

    def test_value_zone_long_waits_then_enters_at_next_open(self) -> None:
        armed = evaluate_entry(
            make_context(close=99.0, ema_fast=100.0, ema_slow=95.0),
            StrategyState(trend=TrendState.UPTREND),
            self.config,
            frozenset({SetupType.VALUE_ZONE_LONG}),
        )
        self.assertEqual(armed.value_zone_entry_side, PositionSide.LONG)
        self.assertEqual(armed.value_zone_entry_ema, EmaReference.FAST)

        confirmed = evaluate_entry(
            make_context(index=1, close=101.0, ema_fast=100.0, ema_slow=96.0),
            StrategyState(
                trend=TrendState.UPTREND,
                value_zone_entry_side=armed.value_zone_entry_side,
                value_zone_entry_ema=armed.value_zone_entry_ema,
            ),
            self.config,
        )
        self.assertFalse(confirmed.should_enter)
        self.assertTrue(confirmed.scheduled)

        entered = evaluate_entry(
            make_context(index=2, open_=103.0, close=100.0),
            StrategyState(
                trend=TrendState.UPTREND,
                pending_entry=self._ready(confirmed.pending_entry, hard_stop=94.6),
            ),
            self.config,
        )
        self.assertTrue(entered.should_enter)
        self.assertEqual(entered.entry_price, 103.0)
        self.assertEqual(entered.signal_bar_index, 1)
        self.assertEqual(entered.entry_bar_index, 2)
        self.assertEqual(entered.reason, "NEXT_BAR_OPEN_ENTRY")

    def test_value_zone_long_uses_slow_ema_after_deeper_pullback(self) -> None:
        result = evaluate_entry(
            make_context(close=94.0, ema_fast=100.0, ema_slow=95.0, last_low=90.0),
            StrategyState(trend=TrendState.UPTREND),
            self.config,
            frozenset({SetupType.VALUE_ZONE_LONG}),
        )
        self.assertEqual(result.value_zone_entry_ema, EmaReference.SLOW)

    def test_value_zone_short_is_symmetric(self) -> None:
        armed = evaluate_entry(
            make_context(close=101.0, ema_fast=100.0, ema_slow=105.0, last_high=110.0),
            StrategyState(trend=TrendState.DOWNTREND),
            self.config,
            frozenset({SetupType.VALUE_ZONE_SHORT}),
        )
        confirmed = evaluate_entry(
            make_context(index=1, close=99.0, ema_fast=100.0, ema_slow=105.0, last_high=110.0),
            StrategyState(
                trend=TrendState.DOWNTREND,
                value_zone_entry_side=armed.value_zone_entry_side,
                value_zone_entry_ema=armed.value_zone_entry_ema,
            ),
            self.config,
        )
        entered = evaluate_entry(
            make_context(index=2, open_=97.0, close=101.0),
            StrategyState(
                trend=TrendState.DOWNTREND,
                pending_entry=self._ready(confirmed.pending_entry, hard_stop=110.4, invalidation=110.0),
            ),
            self.config,
        )
        self.assertTrue(entered.should_enter)
        self.assertEqual(entered.entry_price, 97.0)

    def test_close_equal_to_reference_ema_does_not_confirm(self) -> None:
        result = evaluate_entry(
            make_context(close=100.0, ema_fast=100.0, last_low=95.0),
            StrategyState(
                trend=TrendState.UPTREND,
                value_zone_entry_side=PositionSide.LONG,
                value_zone_entry_ema=EmaReference.FAST,
            ),
            self.config,
        )
        self.assertFalse(result.scheduled)
        self.assertEqual(result.reason, "WAITING_FOR_EMA_CONFIRMATION")

    def test_value_zone_wait_is_cancelled_at_important_swing(self) -> None:
        result = evaluate_entry(
            make_context(close=95.0, ema_fast=100.0, last_low=95.0),
            StrategyState(
                trend=TrendState.UPTREND,
                value_zone_entry_side=PositionSide.LONG,
                value_zone_entry_ema=EmaReference.FAST,
            ),
            self.config,
        )
        self.assertIsNone(result.value_zone_entry_side)
        self.assertIsNone(result.value_zone_entry_ema)

    def test_breakout_long_enters_at_next_bar_open(self) -> None:
        confirmed = evaluate_entry(
            make_context(close=111.0, last_high=110.0),
            StrategyState(trend=TrendState.UPTREND),
            self.config,
            frozenset({SetupType.BREAKOUT_LONG}),
        )
        entered = evaluate_entry(
            make_context(index=1, open_=113.0, close=112.0),
            StrategyState(
                trend=TrendState.UPTREND,
                pending_entry=self._ready(confirmed.pending_entry, hard_stop=94.6),
            ),
            self.config,
        )
        self.assertTrue(entered.should_enter)
        self.assertEqual(entered.entry_price, 113.0)
        self.assertEqual(entered.source_setup, SetupType.BREAKOUT_LONG)

    def test_breakout_short_enters_at_next_bar_open(self) -> None:
        confirmed = evaluate_entry(
            make_context(close=89.0, last_low=90.0),
            StrategyState(trend=TrendState.DOWNTREND),
            self.config,
            frozenset({SetupType.BREAKOUT_SHORT}),
        )
        entered = evaluate_entry(
            make_context(index=1, open_=87.0, close=88.0),
            StrategyState(
                trend=TrendState.DOWNTREND,
                pending_entry=self._ready(confirmed.pending_entry, hard_stop=110.4, invalidation=110.0),
            ),
            self.config,
        )
        self.assertTrue(entered.should_enter)
        self.assertEqual(entered.entry_price, 87.0)

    def test_breakout_has_priority_over_waiting_value_zone(self) -> None:
        result = evaluate_entry(
            make_context(close=111.0, ema_fast=100.0, last_high=110.0),
            StrategyState(
                trend=TrendState.UPTREND,
                value_zone_entry_side=PositionSide.LONG,
                value_zone_entry_ema=EmaReference.FAST,
            ),
            self.config,
            frozenset({SetupType.BREAKOUT_LONG}),
        )
        self.assertEqual(result.source_setup, SetupType.BREAKOUT_LONG)
        self.assertIsNone(result.value_zone_entry_side)

    def test_confirmed_signal_does_not_enter_on_the_signal_bar(self) -> None:
        confirmed = evaluate_entry(
            make_context(index=5, close=111.0, last_high=110.0),
            StrategyState(trend=TrendState.UPTREND),
            self.config,
            frozenset({SetupType.BREAKOUT_LONG}),
        )
        result = evaluate_entry(
            make_context(index=5, open_=112.0, close=111.0),
            StrategyState(
                trend=TrendState.UPTREND,
                pending_entry=self._ready(confirmed.pending_entry, hard_stop=94.6),
            ),
            self.config,
        )
        self.assertFalse(result.should_enter)
        self.assertEqual(result.reason, "WAITING_FOR_NEXT_BAR_OPEN")

    def test_same_direction_signal_is_scheduled_while_position_is_open(self) -> None:
        result = evaluate_entry(
            make_context(close=111.0, last_high=110.0),
            StrategyState(
                trend=TrendState.UPTREND,
                position=PositionState(
                    status=PositionStatus.OPEN,
                    side=PositionSide.LONG,
                    entry_price=100.0,
                    size=1.0,
                ),
            ),
            self.config,
            frozenset({SetupType.BREAKOUT_LONG}),
        )

        self.assertTrue(result.scheduled)
        self.assertEqual(result.side, PositionSide.LONG)
        self.assertEqual(result.reason, "BREAKOUT_LONG_CONFIRMED")
    def test_opposite_direction_signal_is_not_scheduled(self) -> None:
        result = evaluate_entry(
            make_context(close=111.0, last_high=110.0),
            StrategyState(
                trend=TrendState.UPTREND,
                position=PositionState(
                    status=PositionStatus.OPEN,
                    side=PositionSide.SHORT,
                    entry_price=120.0,
                    size=1.0,
                ),
            ),
            self.config,
            frozenset({SetupType.BREAKOUT_LONG}),
        )

        self.assertFalse(result.scheduled)
        self.assertEqual(result.reason, "NO_ENTRY")


def _open_long(setup: SetupType, trade_id: str) -> PositionState:
    return PositionState(
        trade_id=trade_id,
        status=PositionStatus.OPEN,
        side=PositionSide.LONG,
        entry_price=100.0,
        source_setup=setup,
        size=1.0,
    )


class SetupSlotTests(unittest.TestCase):
    """Bot 2: tối đa 2 lệnh nắm giữ — mỗi loại setup (Breakout / Value Zone) 1 lệnh."""

    def setUp(self) -> None:
        self.config = StrategyConfig()
        self.assertEqual(self.config.max_trades_per_setup_family, 1)

    def _state(self, *positions: PositionState, **kwargs) -> StrategyState:
        return StrategyState(
            trend=TrendState.UPTREND,
            positions=positions,
            position=positions[-1] if positions else PositionState(),
            **kwargs,
        )

    def test_breakout_blocked_while_a_breakout_trade_is_open(self) -> None:
        result = evaluate_entry(
            make_context(close=111.0, last_high=110.0),
            self._state(_open_long(SetupType.BREAKOUT_LONG, "LONG-1")),
            self.config,
            frozenset({SetupType.BREAKOUT_LONG}),
        )
        self.assertFalse(result.scheduled)
        self.assertEqual(result.reason, "BREAKOUT_SLOT_FULL")

    def test_breakout_allowed_while_only_a_value_zone_trade_is_open(self) -> None:
        result = evaluate_entry(
            make_context(close=111.0, last_high=110.0),
            self._state(_open_long(SetupType.VALUE_ZONE_LONG, "LONG-1")),
            self.config,
            frozenset({SetupType.BREAKOUT_LONG}),
        )
        self.assertTrue(result.scheduled)
        self.assertEqual(result.source_setup, SetupType.BREAKOUT_LONG)

    def test_value_zone_confirmation_blocked_by_full_slot_clears_waiting_state(self) -> None:
        result = evaluate_entry(
            make_context(close=101.0, ema_fast=100.0, ema_slow=96.0),
            self._state(
                _open_long(SetupType.VALUE_ZONE_LONG, "LONG-1"),
                value_zone_entry_side=PositionSide.LONG,
                value_zone_entry_ema=EmaReference.FAST,
            ),
            self.config,
        )
        self.assertFalse(result.scheduled)
        self.assertEqual(result.reason, "VALUE_ZONE_SLOT_FULL")
        # Bot 2 Step 3 (2026-09-28): tín hiệu bị chặn vì slot đầy thì xóa mốc nhớ.
        self.assertIsNone(result.value_zone_entry_side)
        self.assertIsNone(result.value_zone_entry_ema)

    def test_blocked_value_zone_does_not_fire_after_slot_frees(self) -> None:
        blocked = evaluate_entry(
            make_context(close=101.0, ema_fast=100.0, ema_slow=96.0),
            self._state(
                _open_long(SetupType.VALUE_ZONE_LONG, "LONG-1"),
                value_zone_entry_side=PositionSide.LONG,
                value_zone_entry_ema=EmaReference.FAST,
            ),
            self.config,
        )
        # Nến sau: lệnh Value Zone cũ đã đóng, Close vẫn trên EMA -> không vào muộn.
        later = evaluate_entry(
            make_context(index=11, close=108.0, ema_fast=101.0, ema_slow=97.0),
            self._state(
                value_zone_entry_side=blocked.value_zone_entry_side,
                value_zone_entry_ema=blocked.value_zone_entry_ema,
            ),
            self.config,
        )
        self.assertFalse(later.scheduled)
        self.assertEqual(later.reason, "NO_ENTRY")

    def test_waiting_state_kept_while_close_has_not_reclaimed_ema_and_slot_full(self) -> None:
        result = evaluate_entry(
            make_context(close=99.0, ema_fast=100.0, ema_slow=96.0),
            self._state(
                _open_long(SetupType.VALUE_ZONE_LONG, "LONG-1"),
                value_zone_entry_side=PositionSide.LONG,
                value_zone_entry_ema=EmaReference.FAST,
            ),
            self.config,
        )
        # Chưa xác nhận thì chưa bị chặn -> vẫn chờ.
        self.assertEqual(result.reason, "WAITING_FOR_EMA_CONFIRMATION")
        self.assertEqual(result.value_zone_entry_side, PositionSide.LONG)
        self.assertEqual(result.value_zone_entry_ema, EmaReference.FAST)

    def test_value_zone_allowed_while_only_a_breakout_trade_is_open(self) -> None:
        result = evaluate_entry(
            make_context(close=101.0, ema_fast=100.0, ema_slow=96.0),
            self._state(
                _open_long(SetupType.BREAKOUT_LONG, "LONG-1"),
                value_zone_entry_side=PositionSide.LONG,
                value_zone_entry_ema=EmaReference.FAST,
            ),
            self.config,
        )
        self.assertTrue(result.scheduled)
        self.assertEqual(result.source_setup, SetupType.VALUE_ZONE_LONG)

    def test_two_open_trades_block_every_new_signal(self) -> None:
        state = self._state(
            _open_long(SetupType.BREAKOUT_LONG, "LONG-1"),
            _open_long(SetupType.VALUE_ZONE_LONG, "LONG-2"),
            value_zone_entry_side=PositionSide.LONG,
            value_zone_entry_ema=EmaReference.FAST,
        )
        # Breakout và Value Zone cùng xác nhận trên một nến: cả hai đều bị chặn.
        result = evaluate_entry(
            make_context(close=111.0, ema_fast=100.0, ema_slow=96.0, last_high=110.0),
            state,
            self.config,
            frozenset({SetupType.BREAKOUT_LONG}),
        )
        self.assertFalse(result.scheduled)
        self.assertIn(result.reason, {"BREAKOUT_SLOT_FULL", "VALUE_ZONE_SLOT_FULL"})

    def test_breakout_priority_falls_back_to_value_zone_when_breakout_slot_full(self) -> None:
        result = evaluate_entry(
            make_context(close=111.0, ema_fast=100.0, ema_slow=96.0, last_high=110.0),
            self._state(
                _open_long(SetupType.BREAKOUT_LONG, "LONG-1"),
                value_zone_entry_side=PositionSide.LONG,
                value_zone_entry_ema=EmaReference.FAST,
            ),
            self.config,
            frozenset({SetupType.BREAKOUT_LONG}),
        )
        self.assertTrue(result.scheduled)
        self.assertEqual(result.source_setup, SetupType.VALUE_ZONE_LONG)

    def test_zero_limit_restores_unlimited_same_direction_entries(self) -> None:
        result = evaluate_entry(
            make_context(close=111.0, last_high=110.0),
            self._state(_open_long(SetupType.BREAKOUT_LONG, "LONG-1")),
            StrategyConfig(max_trades_per_setup_family=0),
            frozenset({SetupType.BREAKOUT_LONG}),
        )
        self.assertTrue(result.scheduled)

    def test_pending_entry_cancelled_when_slot_is_still_full(self) -> None:
        pending = replace(
            evaluate_entry(
                make_context(close=111.0, last_high=110.0),
                StrategyState(trend=TrendState.UPTREND),
                self.config,
                frozenset({SetupType.BREAKOUT_LONG}),
            ).pending_entry,
            trade_invalidation_price=95.0,
            hard_stop_price=94.6,
            stop_buffer=0.4,
        )
        result = evaluate_entry(
            make_context(index=1, open_=112.0, close=113.0),
            self._state(_open_long(SetupType.BREAKOUT_LONG, "LONG-1"), pending_entry=pending),
            self.config,
        )
        self.assertTrue(result.cancelled)
        self.assertEqual(result.reason, "PENDING_ENTRY_CANCELLED_SETUP_SLOT_FULL")

    def test_opposite_direction_is_still_rejected_before_slot_check(self) -> None:
        short = replace(_open_long(SetupType.BREAKOUT_LONG, "SHORT-1"), side=PositionSide.SHORT)
        result = evaluate_entry(
            make_context(close=111.0, last_high=110.0),
            self._state(short),
            self.config,
            frozenset({SetupType.BREAKOUT_LONG}),
        )
        self.assertFalse(result.scheduled)
        self.assertEqual(result.reason, "NO_ENTRY")


if __name__ == "__main__":
    unittest.main()
