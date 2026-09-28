from __future__ import annotations

from dataclasses import dataclass, field

from trading_bot.core.models import Bar, PivotConfirmation, PivotKind, SwingSnapshot


@dataclass(frozen=True, slots=True)
class SwingPoint:
    price: float
    bar_index: int


@dataclass(frozen=True, slots=True)
class SwingState:
    window: tuple[Bar, ...] = field(default_factory=tuple)
    previous_high: SwingPoint | None = None
    last_high: SwingPoint | None = None
    previous_low: SwingPoint | None = None
    last_low: SwingPoint | None = None


def _is_strict_high(window: tuple[Bar, ...], center: int) -> bool:
    candidate = window[center].high
    return all(candidate > bar.high for index, bar in enumerate(window) if index != center)


def _is_strict_low(window: tuple[Bar, ...], center: int) -> bool:
    candidate = window[center].low
    return all(candidate < bar.low for index, bar in enumerate(window) if index != center)


def update_swings(
    state: SwingState,
    bar: Bar,
    legs: int,
) -> tuple[SwingState, SwingSnapshot]:
    """Confirm a pivot only after `legs` bars have closed on its right."""
    window_size = legs * 2 + 1
    window = (*state.window, bar)[-window_size:]
    previous_high = state.previous_high
    last_high = state.last_high
    previous_low = state.previous_low
    last_low = state.last_low
    confirmed_high = None
    confirmed_low = None

    if len(window) == window_size:
        center = legs
        pivot_bar = window[center]

        if _is_strict_high(window, center):
            confirmed_high = PivotConfirmation(
                kind=PivotKind.HIGH,
                price=pivot_bar.high,
                pivot_bar_index=pivot_bar.index,
                confirmation_bar_index=bar.index,
            )
            previous_high, last_high = last_high, SwingPoint(
                price=pivot_bar.high,
                bar_index=pivot_bar.index,
            )

        if _is_strict_low(window, center):
            confirmed_low = PivotConfirmation(
                kind=PivotKind.LOW,
                price=pivot_bar.low,
                pivot_bar_index=pivot_bar.index,
                confirmation_bar_index=bar.index,
            )
            previous_low, last_low = last_low, SwingPoint(
                price=pivot_bar.low,
                bar_index=pivot_bar.index,
            )

    next_state = SwingState(
        window=window,
        previous_high=previous_high,
        last_high=last_high,
        previous_low=previous_low,
        last_low=last_low,
    )
    snapshot = SwingSnapshot(
        previous_high=None if previous_high is None else previous_high.price,
        last_high=None if last_high is None else last_high.price,
        previous_high_bar=None if previous_high is None else previous_high.bar_index,
        last_high_bar=None if last_high is None else last_high.bar_index,
        previous_low=None if previous_low is None else previous_low.price,
        last_low=None if last_low is None else last_low.price,
        previous_low_bar=None if previous_low is None else previous_low.bar_index,
        last_low_bar=None if last_low is None else last_low.bar_index,
        confirmed_high=confirmed_high,
        confirmed_low=confirmed_low,
    )
    return next_state, snapshot

