from __future__ import annotations

from trading_bot.core.models import Bar, BarContext, IndicatorSnapshot, SwingSnapshot

_FOLLOW_SLOPE = object()


def make_bar(
    index: int,
    close: float,
    *,
    open_: float | None = None,
    high: float | None = None,
    low: float | None = None,
) -> Bar:
    resolved_open = close if open_ is None else open_
    resolved_high = max(close, resolved_open) + 1.0 if high is None else high
    resolved_low = min(close, resolved_open) - 1.0 if low is None else low
    return Bar(
        index=index,
        open=resolved_open,
        high=resolved_high,
        low=resolved_low,
        close=close,
    )


def make_context(
    *,
    close: float,
    index: int = 0,
    open_: float | None = None,
    high: float | None = None,
    low: float | None = None,
    ema_fast: float | None = 100.0,
    ema_slow: float | None = 99.0,
    slope: float | None = 1.0,
    confirm_slope: object = _FOLLOW_SLOPE,
    positive_ratio: float | None = 0.75,
    negative_ratio: float | None = 0.25,
    atr: float | None = None,
    previous_high: float | None = 100.0,
    last_high: float | None = 110.0,
    previous_low: float | None = 90.0,
    last_low: float | None = 95.0,
) -> BarContext:
    # Mặc định độ dốc xác nhận (13 nến) cùng dấu với slope cũ (8 nến).
    if confirm_slope is _FOLLOW_SLOPE:
        confirm_slope = slope
    return BarContext(
        bar=make_bar(index, close, open_=open_, high=high, low=low),
        indicators=IndicatorSnapshot(
            ema_fast=ema_fast,
            ema_slow=ema_slow,
            ema_slope=slope,
            ema_confirm_slope=confirm_slope,  # type: ignore[arg-type]
            positive_delta_ratio=positive_ratio,
            negative_delta_ratio=negative_ratio,
            atr=atr,
        ),
        swings=SwingSnapshot(
            previous_high=previous_high,
            last_high=last_high,
            previous_low=previous_low,
            last_low=last_low,
        ),
    )
