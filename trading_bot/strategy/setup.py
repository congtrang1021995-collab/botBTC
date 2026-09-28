from __future__ import annotations

from dataclasses import dataclass

from trading_bot.config import StrategyConfig
from trading_bot.core.models import BarContext, SetupType, StrategyState, TrendState


LONG_SETUPS = frozenset({SetupType.VALUE_ZONE_LONG, SetupType.BREAKOUT_LONG})
SHORT_SETUPS = frozenset({SetupType.VALUE_ZONE_SHORT, SetupType.BREAKOUT_SHORT})


@dataclass(frozen=True, slots=True)
class SetupDecision:
    active: frozenset[SetupType]
    started: frozenset[SetupType]
    ended: frozenset[SetupType]
    direction: int
    mask: int
    no_trade: bool


def evaluate_setup(
    context: BarContext,
    state_after_trend: StrategyState,
    config: StrategyConfig,
) -> SetupDecision:
    """Evaluate all Step 2 rules without mutating shared state."""
    trend = state_after_trend.trend
    close = context.bar.close
    fast = context.indicators.ema_fast
    slow = context.indicators.ema_slow
    last_high = context.swings.last_high
    last_low = context.swings.last_low
    active: set[SetupType] = set()

    if trend == TrendState.UPTREND:
        if (
            config.enable_value_zone_setup
            and fast is not None
            and slow is not None
            and last_low is not None
            and (close <= fast or close <= slow)
            and close > last_low
        ):
            active.add(SetupType.VALUE_ZONE_LONG)
        if (
            config.enable_breakout_setup
            and last_high is not None
            and close > last_high
        ):
            active.add(SetupType.BREAKOUT_LONG)

    elif trend == TrendState.DOWNTREND:
        if (
            config.enable_value_zone_setup
            and fast is not None
            and slow is not None
            and last_high is not None
            and (close >= fast or close >= slow)
            and close < last_high
        ):
            active.add(SetupType.VALUE_ZONE_SHORT)
        if (
            config.enable_breakout_setup
            and last_low is not None
            and close < last_low
        ):
            active.add(SetupType.BREAKOUT_SHORT)

    frozen_active = frozenset(active)
    started = frozen_active - state_after_trend.active_setups
    ended = state_after_trend.active_setups - frozen_active
    has_long = bool(frozen_active & LONG_SETUPS)
    has_short = bool(frozen_active & SHORT_SETUPS)
    direction = 1 if has_long else -1 if has_short else 0
    mask = sum(int(setup) for setup in frozen_active)

    return SetupDecision(
        active=frozen_active,
        started=started,
        ended=ended,
        direction=direction,
        mask=mask,
        no_trade=trend == TrendState.SIDEWAY,
    )

