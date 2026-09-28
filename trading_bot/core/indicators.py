from __future__ import annotations

from dataclasses import dataclass, field

from trading_bot.config import StrategyConfig
from trading_bot.core.models import Bar, IndicatorSnapshot


@dataclass(frozen=True, slots=True)
class EmaState:
    value: float | None = None


@dataclass(frozen=True, slots=True)
class IndicatorState:
    fast_ema: EmaState = field(default_factory=EmaState)
    slow_ema: EmaState = field(default_factory=EmaState)
    fast_ema_history: tuple[float, ...] = field(default_factory=tuple)
    previous_close: float | None = None
    true_range_history: tuple[float, ...] = field(default_factory=tuple)
    atr: float | None = None


def _update_ema(state: EmaState, price: float, length: int) -> EmaState:
    """Update an EMA with Pine-compatible first-source initialization."""
    if state.value is None:
        return EmaState(value=price)
    alpha = 2.0 / (length + 1.0)
    value = alpha * price + (1.0 - alpha) * state.value
    return EmaState(value=value)


def linear_regression_slope(values: tuple[float, ...]) -> float | None:
    """OLS slope where x grows from the oldest value to the newest value."""
    length = len(values)
    if length < 2:
        return None

    sum_x = sum(range(length))
    sum_y = sum(values)
    sum_xy = sum(x * y for x, y in enumerate(values))
    sum_xx = sum(x * x for x in range(length))
    denominator = length * sum_xx - sum_x * sum_x
    if denominator == 0:
        return None
    return (length * sum_xy - sum_x * sum_y) / denominator


def delta_ratios(values: tuple[float, ...]) -> tuple[float | None, float | None]:
    """Return positive/negative adjacent-delta ratios; zero counts only in denominator."""
    if len(values) < 2:
        return None, None
    deltas = tuple(newer - older for older, newer in zip(values, values[1:]))
    intervals = len(deltas)
    positive = sum(delta > 0.0 for delta in deltas) / intervals
    negative = sum(delta < 0.0 for delta in deltas) / intervals
    return positive, negative


def _update_atr(
    state: IndicatorState,
    high: float,
    low: float,
    close: float,
    length: int,
) -> tuple[tuple[float, ...], float | None]:
    previous_close = state.previous_close
    true_range = high - low
    if previous_close is not None:
        true_range = max(
            true_range,
            abs(high - previous_close),
            abs(low - previous_close),
        )

    history = (*state.true_range_history, true_range)[-length:]
    if state.atr is not None:
        atr = (state.atr * (length - 1) + true_range) / length
    elif len(history) == length:
        atr = sum(history) / length
    else:
        atr = None
    return history, atr


def update_indicators(
    state: IndicatorState,
    source: Bar | float,
    config: StrategyConfig,
) -> tuple[IndicatorState, IndicatorSnapshot]:
    if isinstance(source, Bar):
        close = source.close
        high = source.high
        low = source.low
    else:
        close = source
        high = source
        low = source

    fast = _update_ema(state.fast_ema, close, config.ema_fast_length)
    slow = _update_ema(state.slow_ema, close, config.ema_slow_length)

    history_length = max(config.slope_length, config.confirm_slope_length)
    history = state.fast_ema_history
    if fast.value is not None:
        history = (*history, fast.value)[-history_length:]

    slope = None
    positive_ratio = None
    negative_ratio = None
    if len(history) >= config.slope_length:
        window = history[-config.slope_length :]
        slope = linear_regression_slope(window)
        positive_ratio, negative_ratio = delta_ratios(window)

    # Bot 2 Step 1: độ dốc xác nhận trên confirm_slope_length nến gần nhất.
    confirm_slope = None
    if len(history) >= config.confirm_slope_length:
        confirm_slope = linear_regression_slope(history[-config.confirm_slope_length :])

    true_range_history, atr = _update_atr(
        state,
        high,
        low,
        close,
        config.atr_length,
    )

    next_state = IndicatorState(
        fast_ema=fast,
        slow_ema=slow,
        fast_ema_history=history,
        previous_close=close,
        true_range_history=true_range_history,
        atr=atr,
    )
    snapshot = IndicatorSnapshot(
        ema_fast=fast.value,
        ema_slow=slow.value,
        ema_slope=slope,
        ema_confirm_slope=confirm_slope,
        positive_delta_ratio=positive_ratio,
        negative_delta_ratio=negative_ratio,
        atr=atr,
    )
    return next_state, snapshot
