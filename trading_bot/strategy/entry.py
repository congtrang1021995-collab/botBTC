from __future__ import annotations

from dataclasses import dataclass

from trading_bot.config import StrategyConfig
from trading_bot.core.models import (
    BarContext,
    EmaReference,
    PendingEntry,
    PositionSide,
    SetupType,
    StrategyState,
    TrendState,
)


@dataclass(frozen=True, slots=True)
class EntryDecision:
    should_enter: bool = False
    side: PositionSide | None = None
    entry_price: float | None = None
    source_setup: SetupType | None = None
    signal_bar_index: int | None = None
    entry_bar_index: int | None = None
    executed_entry: PendingEntry | None = None
    cancelled: bool = False
    pending_entry: PendingEntry | None = None
    value_zone_entry_side: PositionSide | None = None
    value_zone_entry_ema: EmaReference | None = None
    reason: str = "NO_ENTRY"

    @property
    def scheduled(self) -> bool:
        return self.pending_entry is not None


def evaluate_entry(
    context: BarContext,
    state: StrategyState,
    config: StrategyConfig,
    started_setups: frozenset[SetupType] = frozenset(),
) -> EntryDecision:
    """Evaluate Step 3: tín hiệu đã xác nhận khớp tại Open nến kế tiếp.

    Bot 2: mỗi loại setup (Breakout / Value Zone) chỉ giữ tối đa
    ``config.max_trades_per_setup_family`` lệnh đang mở, nên tổng tối đa 2 lệnh.
    """
    if state.pending_entry is not None:
        pending = state.pending_entry
        if any(position.side != pending.side for position in state.open_positions):
            return EntryDecision(
                cancelled=True,
                reason="PENDING_ENTRY_CANCELLED_OPPOSITE_POSITION_OPEN",
            )
        if not _family_slot_available(state, pending.source_setup, config):
            return EntryDecision(
                cancelled=True,
                reason="PENDING_ENTRY_CANCELLED_SETUP_SLOT_FULL",
            )
        if pending.hard_stop_price is None:
            return EntryDecision(
                cancelled=True,
                reason="PENDING_ENTRY_NOT_READY",
            )
        if context.bar.index <= pending.signal_bar_index:
            return EntryDecision(
                side=pending.side,
                source_setup=pending.source_setup,
                signal_bar_index=pending.signal_bar_index,
                pending_entry=pending,
                reason="WAITING_FOR_NEXT_BAR_OPEN",
            )
        return EntryDecision(
            should_enter=True,
            side=pending.side,
            entry_price=context.bar.open,
            source_setup=pending.source_setup,
            signal_bar_index=pending.signal_bar_index,
            entry_bar_index=context.bar.index,
            executed_entry=pending,
            reason="NEXT_BAR_OPEN_ENTRY",
        )

    waiting_side = state.value_zone_entry_side
    waiting_ema = state.value_zone_entry_ema


    last_low = context.swings.last_low
    last_high = context.swings.last_high
    close = context.bar.close

    if waiting_side == PositionSide.LONG and (
        state.trend != TrendState.UPTREND
        or last_low is None
        or close <= last_low
    ):
        waiting_side = None
        waiting_ema = None
    elif waiting_side == PositionSide.SHORT and (
        state.trend != TrendState.DOWNTREND
        or last_high is None
        or close >= last_high
    ):
        waiting_side = None
        waiting_ema = None

    # Bot 2: slot theo loại setup. Một loại đã có lệnh mở thì tín hiệu mới của
    # loại đó bị bỏ qua; loại còn lại vẫn được vào bình thường.
    blocked_reason: str | None = None

    # Breakout has priority if both setup families confirm on the same bar.
    for breakout_setup, side, reason in (
        (SetupType.BREAKOUT_LONG, PositionSide.LONG, "BREAKOUT_LONG_CONFIRMED"),
        (SetupType.BREAKOUT_SHORT, PositionSide.SHORT, "BREAKOUT_SHORT_CONFIRMED"),
    ):
        if breakout_setup in started_setups and _same_direction_or_flat(state, side):
            if _family_slot_available(state, breakout_setup, config):
                return _scheduled_entry(context, side, breakout_setup, reason)
            blocked_reason = "BREAKOUT_SLOT_FULL"

    reference_value = _ema_value(context, waiting_ema)
    value_zone_long_confirmed = (
        waiting_side == PositionSide.LONG
        and state.trend == TrendState.UPTREND
        and reference_value is not None
        and close > reference_value
        and _same_direction_or_flat(state, PositionSide.LONG)
    )
    value_zone_short_confirmed = (
        waiting_side == PositionSide.SHORT
        and state.trend == TrendState.DOWNTREND
        and reference_value is not None
        and close < reference_value
        and _same_direction_or_flat(state, PositionSide.SHORT)
    )
    # Bot 2 Step 3 (2026-09-28): tín hiệu Value Zone bị chặn vì slot đầy thì xóa
    # mốc EMA đang nhớ, tránh bắn lại muộn khi giá đã rời xa vùng giá trị. Muốn vào
    # lại phải có setup Value Zone mới.
    if value_zone_long_confirmed:
        if _family_slot_available(state, SetupType.VALUE_ZONE_LONG, config):
            return _scheduled_entry(
                context,
                PositionSide.LONG,
                SetupType.VALUE_ZONE_LONG,
                "VALUE_ZONE_LONG_CONFIRMED",
            )
        blocked_reason = "VALUE_ZONE_SLOT_FULL"
        waiting_side = None
        waiting_ema = None
    if value_zone_short_confirmed:
        if _family_slot_available(state, SetupType.VALUE_ZONE_SHORT, config):
            return _scheduled_entry(
                context,
                PositionSide.SHORT,
                SetupType.VALUE_ZONE_SHORT,
                "VALUE_ZONE_SHORT_CONFIRMED",
            )
        blocked_reason = "VALUE_ZONE_SLOT_FULL"
        waiting_side = None
        waiting_ema = None

    if (
        SetupType.VALUE_ZONE_LONG in started_setups
        and _same_direction_or_flat(state, PositionSide.LONG)
    ):
        return EntryDecision(
            value_zone_entry_side=PositionSide.LONG,
            value_zone_entry_ema=_select_long_ema(context),
            reason="VALUE_ZONE_LONG_ARMED",
        )
    if (
        SetupType.VALUE_ZONE_SHORT in started_setups
        and _same_direction_or_flat(state, PositionSide.SHORT)
    ):
        return EntryDecision(
            value_zone_entry_side=PositionSide.SHORT,
            value_zone_entry_ema=_select_short_ema(context),
            reason="VALUE_ZONE_SHORT_ARMED",
        )

    if blocked_reason is not None:
        reason = blocked_reason
    elif waiting_side:
        reason = "WAITING_FOR_EMA_CONFIRMATION"
    else:
        reason = "NO_ENTRY"
    return EntryDecision(
        value_zone_entry_side=waiting_side,
        value_zone_entry_ema=waiting_ema,
        reason=reason,
    )


def setup_family(setup: SetupType) -> str:
    """Nhóm setup: Breakout hoặc Value Zone, không phân biệt Long/Short."""
    if setup in (SetupType.BREAKOUT_LONG, SetupType.BREAKOUT_SHORT):
        return "BREAKOUT"
    return "VALUE_ZONE"


def open_trades_in_family(state: StrategyState, family: str) -> int:
    return sum(
        1
        for position in state.open_positions
        if position.source_setup is not None
        and setup_family(position.source_setup) == family
    )


def _family_slot_available(
    state: StrategyState,
    setup: SetupType,
    config: StrategyConfig,
) -> bool:
    """Bot 2: mỗi loại setup chỉ giữ tối đa max_trades_per_setup_family lệnh mở."""
    limit = config.max_trades_per_setup_family
    if limit <= 0:
        return True
    return open_trades_in_family(state, setup_family(setup)) < limit


def _same_direction_or_flat(
    state: StrategyState,
    side: PositionSide,
) -> bool:
    """Only same-direction trades may overlap."""
    return all(position.side == side for position in state.open_positions)

def _scheduled_entry(
    context: BarContext,
    side: PositionSide,
    source_setup: SetupType,
    reason: str,
) -> EntryDecision:
    pending = PendingEntry(
        side=side,
        source_setup=source_setup,
        signal_bar_index=context.bar.index,
    )
    return EntryDecision(
        side=side,
        source_setup=source_setup,
        signal_bar_index=context.bar.index,
        pending_entry=pending,
        reason=reason,
    )


def _ema_value(
    context: BarContext,
    reference: EmaReference | None,
) -> float | None:
    if reference == EmaReference.FAST:
        return context.indicators.ema_fast
    if reference == EmaReference.SLOW:
        return context.indicators.ema_slow
    return None


def _select_long_ema(context: BarContext) -> EmaReference:
    slow = context.indicators.ema_slow
    if slow is not None and context.bar.close <= slow:
        return EmaReference.SLOW
    return EmaReference.FAST


def _select_short_ema(context: BarContext) -> EmaReference:
    slow = context.indicators.ema_slow
    if slow is not None and context.bar.close >= slow:
        return EmaReference.SLOW
    return EmaReference.FAST
