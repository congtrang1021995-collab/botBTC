from __future__ import annotations

import math
from dataclasses import dataclass, replace

from trading_bot.config import StrategyConfig
from trading_bot.core.models import BarContext, PendingEntry, StrategyState


@dataclass(frozen=True, slots=True)
class PositionSizeDecision:
    quantity: float = 0.0
    pending_entry: PendingEntry | None = None
    risk_amount: float | None = None
    reason: str = "NO_PENDING_ENTRY"


def calculate_position_size(
    context: BarContext,
    state: StrategyState,
    config: StrategyConfig,
    equity: float | None = None,
    entry_price: float | None = None,
) -> PositionSizeDecision:
    """Step 5: khối lượng cố định, hoặc suy từ ngân sách rủi ro mỗi lệnh."""
    del context
    pending = state.pending_entry
    if pending is None:
        return PositionSizeDecision()
    if pending.hard_stop_price is None:
        return PositionSizeDecision(reason="MISSING_HARD_STOP")

    if config.risk_model == "fixed_quantity":
        sized = replace(pending, quantity=config.fixed_position_size)
        return PositionSizeDecision(
            quantity=config.fixed_position_size,
            pending_entry=sized,
            reason="FIXED_POSITION_SIZE",
        )

    if entry_price is None:
        return PositionSizeDecision(
            pending_entry=pending,
            reason="WAITING_FOR_ENTRY_PRICE",
        )

    # Rủi ro mỗi đơn vị chỉ được chốt khi biết Open thực tế của nến vào lệnh.
    risk_per_unit = abs(entry_price - pending.hard_stop_price)
    available_equity = config.initial_equity if equity is None else equity
    risk_amount = available_equity * config.risk_per_trade_fraction
    if risk_per_unit <= 0.0 or risk_amount <= 0.0:
        return PositionSizeDecision(reason="INVALID_RISK_INPUTS")

    quantity = risk_amount / risk_per_unit
    if config.quantity_step > 0.0:
        quantity = math.floor(quantity / config.quantity_step) * config.quantity_step
    if config.maximum_quantity > 0.0:
        quantity = min(quantity, config.maximum_quantity)
    if quantity <= 0.0 or quantity < config.minimum_quantity:
        # Ngân sách rủi ro không đủ cho một đơn vị: bỏ lệnh chờ.
        return PositionSizeDecision(
            risk_amount=risk_amount,
            reason="RISK_BUDGET_TOO_SMALL",
        )

    sized = replace(pending, quantity=quantity)
    return PositionSizeDecision(
        quantity=quantity,
        pending_entry=sized,
        risk_amount=risk_amount,
        reason="RISK_BASED_SIZE",
    )
