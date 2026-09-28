from __future__ import annotations

from dataclasses import dataclass

from trading_bot.config import StrategyConfig
from trading_bot.core.models import BarContext, StrategyState


@dataclass(frozen=True, slots=True)
class AddDecision:
    should_add: bool = False
    quantity: float = 0.0
    reason: str = "POSITION_ADD_DISABLED"


def evaluate_add(
    context: BarContext,
    state: StrategyState,
    config: StrategyConfig,
) -> AddDecision:
    """Never resize an existing trade; new signals create separate trades."""
    del context, state, config
    return AddDecision()
