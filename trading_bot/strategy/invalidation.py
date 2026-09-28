from __future__ import annotations

from dataclasses import dataclass, replace

from trading_bot.config import StrategyConfig
from trading_bot.core.models import (
    BarContext,
    PendingEntry,
    PositionSide,
    PositionStatus,
    StrategyState,
    TrendState,
)


@dataclass(frozen=True, slots=True)
class InvalidationDecision:
    setup_invalidated: bool = False
    trade_invalidated: bool = False
    trend_lost: bool = False
    setup_invalidation_price: float | None = None
    trade_invalidation_price: float | None = None
    hard_stop_price: float | None = None
    previous_hard_stop_price: float | None = None
    stop_buffer: float | None = None
    stop_updated: bool = False
    hard_stop_triggered: bool = False
    exit_price: float | None = None
    pending_entry: PendingEntry | None = None
    reason: str = "NO_INVALIDATION"


def evaluate_invalidation(
    context: BarContext,
    state: StrategyState,
    config: StrategyConfig,
) -> InvalidationDecision:
    """Prepare initial stops and evaluate the active position's hard stop."""
    pending = state.pending_entry
    if pending is not None and pending.hard_stop_price is None:
        reference = (
            state.protected_swing_low
            if pending.side == PositionSide.LONG
            else state.protected_swing_high
        )
        if reference is None:
            return InvalidationDecision(
                setup_invalidated=True,
                reason="MISSING_PROTECTED_SWING",
            )

        atr_buffer = (
            context.indicators.atr * config.stop_atr_multiplier
            if context.indicators.atr is not None
            else 0.0
        )
        buffer = max(3.0 * config.minimum_tick, atr_buffer)
        hard_stop = (
            reference - buffer
            if pending.side == PositionSide.LONG
            else reference + buffer
        )
        prepared = replace(
            pending,
            trade_invalidation_price=reference,
            hard_stop_price=hard_stop,
            stop_buffer=buffer,
        )
        return InvalidationDecision(
            setup_invalidation_price=reference,
            trade_invalidation_price=reference,
            hard_stop_price=hard_stop,
            stop_buffer=buffer,
            pending_entry=prepared,
            reason="INITIAL_STOP_PREPARED",
        )

    position = state.position
    if position.status != PositionStatus.OPEN or position.hard_stop_price is None:
        return InvalidationDecision(pending_entry=pending)

    hard_stop = position.hard_stop_price
    is_trailing_stop = (
        position.initial_hard_stop_price is not None
        and hard_stop != position.initial_hard_stop_price
    )
    reference = position.trade_invalidation_price
    # Mất trend là mất luận điểm giao dịch: thoát ngay tại Close, không chờ hard stop.
    # Bot 2: mặc định chỉ đóng khi trend ĐẢO CHIỀU (Long gặp DOWNTREND, Short gặp
    # UPTREND); trend về SIDEWAY chỉ đóng khi exit_on_trend_loss bật (bot gốc).
    own_trend = (
        TrendState.UPTREND
        if position.side == PositionSide.LONG
        else TrendState.DOWNTREND
    )
    opposite_trend = (
        TrendState.DOWNTREND
        if position.side == PositionSide.LONG
        else TrendState.UPTREND
    )
    trend_reversed = config.exit_on_trend_reversal and state.trend == opposite_trend
    trend_lost_any = config.exit_on_trend_loss and state.trend != own_trend
    trend_lost = trend_reversed or trend_lost_any
    trend_exit_reason = (
        "TREND_REVERSAL_CLOSE_EXIT"
        if trend_reversed and not trend_lost_any
        else "TREND_LOST_CLOSE_EXIT"
    )
    # Ở nến khớp lệnh, mốc giá đầu tiên là giá khớp chứ không phải giá mở cửa.
    first_price = (
        position.entry_price
        if position.entry_bar_index == context.bar.index
        and position.entry_price is not None
        else context.bar.open
    )
    if position.side == PositionSide.LONG:
        if first_price <= hard_stop:
            return _hard_stop_result(
                reference, hard_stop, first_price, is_trailing_stop
            )
        if context.bar.low <= hard_stop:
            return _hard_stop_result(
                reference, hard_stop, hard_stop, is_trailing_stop
            )
    elif position.side == PositionSide.SHORT:
        if first_price >= hard_stop:
            return _hard_stop_result(
                reference, hard_stop, first_price, is_trailing_stop
            )
        if context.bar.high >= hard_stop:
            return _hard_stop_result(
                reference, hard_stop, hard_stop, is_trailing_stop
            )

    trailed_stop = calculate_trailing_stop(
        position.side,
        position.entry_price,
        (
            position.initial_hard_stop_price
            if position.initial_hard_stop_price is not None
            else hard_stop
        ),
        hard_stop,
        context.bar.high if position.side == PositionSide.LONG else context.bar.low,
    )

    return InvalidationDecision(
        trend_lost=trend_lost,
        trade_invalidation_price=reference,
        hard_stop_price=trailed_stop,
        previous_hard_stop_price=hard_stop,
        stop_buffer=position.stop_buffer,
        stop_updated=trailed_stop != hard_stop and not trend_lost,
        exit_price=context.bar.close if trend_lost else None,
        reason=trend_exit_reason if trend_lost else "POSITION_VALID",
    )


def apply_minimum_risk(
    side: PositionSide,
    entry_price: float,
    hard_stop_price: float,
    min_risk: float,
) -> float:
    """Bot 2: nới hard stop để 1R (giá khớp -> stop) không nhỏ hơn min_risk.

    Chỉ nới khi stop nằm đúng phía giá khớp; stop đã bị giá khớp vượt qua (gap)
    giữ nguyên để lệnh bị hủy như trước.
    """
    if min_risk <= 0.0:
        return hard_stop_price
    if side == PositionSide.LONG:
        if hard_stop_price < entry_price and entry_price - hard_stop_price < min_risk:
            return entry_price - min_risk
    elif hard_stop_price > entry_price and hard_stop_price - entry_price < min_risk:
        return entry_price + min_risk
    return hard_stop_price


TRAIL_MAX_TRIGGER_R = 9


def calculate_trailing_stop(
    side: PositionSide | None,
    entry_price: float | None,
    initial_hard_stop_price: float,
    current_hard_stop_price: float,
    favorable_price: float,
) -> float:
    """Return the next-bar stop from the best favorable price on this bar.

    The initial stop stays frozen as the definition of 1R. Thresholds are
    strict (price must move beyond 1R, 2R, ... 9R), and a stop can only
    become more protective.
    """
    if entry_price is None or side is None:
        return current_hard_stop_price

    risk_distance = abs(entry_price - initial_hard_stop_price)
    if risk_distance <= 0.0:
        return current_hard_stop_price

    direction = 1.0 if side == PositionSide.LONG else -1.0
    favorable_r = (favorable_price - entry_price) * direction / risk_distance
    # Bot 2 (2026-09-28): vượt nR -> stop lên (n-1)R, n = 1..9 (vượt 9R -> +8R).
    locked_r: float | None = None
    for trigger_r in range(TRAIL_MAX_TRIGGER_R, 0, -1):
        if favorable_r > trigger_r:
            locked_r = float(trigger_r - 1)
            break

    if locked_r is None:
        return current_hard_stop_price

    candidate = entry_price + direction * locked_r * risk_distance
    if side == PositionSide.LONG:
        return max(current_hard_stop_price, candidate)
    return min(current_hard_stop_price, candidate)


def _hard_stop_result(
    reference: float | None,
    hard_stop: float,
    exit_price: float,
    is_trailing_stop: bool = False,
) -> InvalidationDecision:
    stop_name = "TRAILING_STOP" if is_trailing_stop else "HARD_STOP"
    fill_name = "GAP_EXIT" if exit_price != hard_stop else "INTRABAR_EXIT"
    return InvalidationDecision(
        trade_invalidation_price=reference,
        hard_stop_price=hard_stop,
        hard_stop_triggered=True,
        exit_price=exit_price,
        reason=f"{stop_name}_{fill_name}",
    )
