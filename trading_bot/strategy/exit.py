from __future__ import annotations

from dataclasses import dataclass

from trading_bot.config import StrategyConfig
from trading_bot.core.models import (
    BarContext,
    PositionSide,
    PositionStatus,
    StrategyState,
)


@dataclass(frozen=True, slots=True)
class ExitDecision:
    should_exit: bool = False
    exit_price: float | None = None
    take_profit_price: float | None = None
    reason: str = "NO_OPEN_POSITION"


def calculate_take_profit_price(
    side: PositionSide,
    entry_price: float,
    hard_stop_price: float,
    r_multiple: float,
) -> float:
    """Return the fixed R-multiple target measured from entry to hard stop."""
    risk_distance = abs(entry_price - hard_stop_price)
    if risk_distance <= 0.0:
        raise ValueError("entry price and hard stop must define positive risk")
    if side == PositionSide.LONG:
        if hard_stop_price >= entry_price:
            raise ValueError("long hard stop must be below entry price")
        return entry_price + r_multiple * risk_distance
    if hard_stop_price <= entry_price:
        raise ValueError("short hard stop must be above entry price")
    return entry_price - r_multiple * risk_distance


def evaluate_exit(
    context: BarContext,
    state: StrategyState,
    config: StrategyConfig,
) -> ExitDecision:
    """Exit at the configured fixed-R take-profit target when price reaches it."""
    del config
    position = state.position
    target = position.take_profit_price
    if position.status != PositionStatus.OPEN or position.side is None:
        return ExitDecision()
    if target is None:
        return ExitDecision(reason="MISSING_TAKE_PROFIT")

    bar = context.bar
    # Ở nến khớp lệnh, mốc giá đầu tiên là giá khớp chứ không phải giá mở cửa.
    first_price = (
        position.entry_price
        if position.entry_bar_index == bar.index and position.entry_price is not None
        else bar.open
    )
    if position.side == PositionSide.LONG:
        if first_price >= target:
            return ExitDecision(True, first_price, target, "TAKE_PROFIT_GAP_EXIT")
        if bar.high >= target:
            return ExitDecision(True, target, target, "TAKE_PROFIT_EXIT")
    else:
        if first_price <= target:
            return ExitDecision(True, first_price, target, "TAKE_PROFIT_GAP_EXIT")
        if bar.low <= target:
            return ExitDecision(True, target, target, "TAKE_PROFIT_EXIT")

    return ExitDecision(take_profit_price=target, reason="TAKE_PROFIT_NOT_REACHED")
