"""Public API for the modular investment-system bot."""

from trading_bot.config import StrategyConfig
from trading_bot.core.engine import TradingEngine
from trading_bot.core.models import Bar, EmaReference, PositionSide, SetupType, TrendState

__all__ = [
    "Bar",
    "EmaReference",
    "PositionSide",
    "SetupType",
    "StrategyConfig",
    "TradingEngine",
    "TrendState",
]
