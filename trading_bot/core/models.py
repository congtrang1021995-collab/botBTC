from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, IntEnum, IntFlag
from typing import Any


class TrendState(IntEnum):
    DOWNTREND = -1
    SIDEWAY = 0
    UPTREND = 1


class SetupType(IntFlag):
    VALUE_ZONE_LONG = 1
    VALUE_ZONE_SHORT = 2
    BREAKOUT_LONG = 4
    BREAKOUT_SHORT = 8


class PositionSide(Enum):
    LONG = "LONG"
    SHORT = "SHORT"


class EmaReference(Enum):
    FAST = "EMA_FAST"
    SLOW = "EMA_SLOW"


class PositionStatus(Enum):
    FLAT = "FLAT"
    OPEN = "OPEN"


class PivotKind(Enum):
    HIGH = "HIGH"
    LOW = "LOW"


@dataclass(frozen=True, slots=True)
class Bar:
    index: int
    open: float
    high: float
    low: float
    close: float
    timestamp: datetime | None = None

    def __post_init__(self) -> None:
        if self.index < 0:
            raise ValueError("bar index must be >= 0")
        if self.high < self.low:
            raise ValueError("bar high must be >= low")
        if not self.low <= self.open <= self.high:
            raise ValueError("bar open must be inside [low, high]")
        if not self.low <= self.close <= self.high:
            raise ValueError("bar close must be inside [low, high]")


@dataclass(frozen=True, slots=True)
class IndicatorSnapshot:
    ema_fast: float | None = None
    ema_slow: float | None = None
    ema_slope: float | None = None
    # Bot 2: độ dốc EMA34 trên confirm_slope_length nến gần nhất.
    ema_confirm_slope: float | None = None
    positive_delta_ratio: float | None = None
    negative_delta_ratio: float | None = None
    atr: float | None = None


@dataclass(frozen=True, slots=True)
class PivotConfirmation:
    kind: PivotKind
    price: float
    pivot_bar_index: int
    confirmation_bar_index: int


@dataclass(frozen=True, slots=True)
class SwingSnapshot:
    previous_high: float | None = None
    last_high: float | None = None
    previous_high_bar: int | None = None
    last_high_bar: int | None = None
    previous_low: float | None = None
    last_low: float | None = None
    previous_low_bar: int | None = None
    last_low_bar: int | None = None
    confirmed_high: PivotConfirmation | None = None
    confirmed_low: PivotConfirmation | None = None


@dataclass(frozen=True, slots=True)
class BarContext:
    bar: Bar
    indicators: IndicatorSnapshot
    swings: SwingSnapshot


@dataclass(frozen=True, slots=True)
class PositionState:
    status: PositionStatus = PositionStatus.FLAT
    side: PositionSide | None = None
    entry_price: float | None = None
    entry_bar_index: int | None = None
    source_setup: SetupType | None = None
    trade_invalidation_price: float | None = None
    initial_hard_stop_price: float | None = None
    hard_stop_price: float | None = None
    take_profit_price: float | None = None
    stop_buffer: float | None = None
    size: float = 0.0
    add_count: int = 0
    trade_id: str | None = None


@dataclass(frozen=True, slots=True)
class PendingEntry:
    """Tín hiệu đã xác nhận, chờ khớp tại Open của nến kế tiếp."""

    side: PositionSide
    source_setup: SetupType
    signal_bar_index: int
    trade_invalidation_price: float | None = None
    hard_stop_price: float | None = None
    take_profit_price: float | None = None
    stop_buffer: float | None = None
    quantity: float = 0.0


@dataclass(frozen=True, slots=True)
class StrategyState:
    trend: TrendState = TrendState.SIDEWAY
    protected_swing_low: float | None = None
    protected_swing_high: float | None = None
    active_setups: frozenset[SetupType] = field(default_factory=frozenset)
    setup_invalidation_price: float | None = None
    value_zone_entry_side: PositionSide | None = None
    value_zone_entry_ema: EmaReference | None = None
    pending_entry: PendingEntry | None = None
    position: PositionState = field(default_factory=PositionState)
    positions: tuple[PositionState, ...] = field(default_factory=tuple)

    @property
    def open_positions(self) -> tuple[PositionState, ...]:
        """Return every live trade, with legacy single-position compatibility."""
        if self.positions:
            return tuple(
                position
                for position in self.positions
                if position.status == PositionStatus.OPEN
            )
        if self.position.status == PositionStatus.OPEN:
            return (self.position,)
        return ()

    @property
    def setup_mask(self) -> int:
        return sum(int(setup) for setup in self.active_setups)

    @property
    def setup_direction(self) -> int:
        has_long = bool(
            self.active_setups
            & {SetupType.VALUE_ZONE_LONG, SetupType.BREAKOUT_LONG}
        )
        has_short = bool(
            self.active_setups
            & {SetupType.VALUE_ZONE_SHORT, SetupType.BREAKOUT_SHORT}
        )
        return 1 if has_long else -1 if has_short else 0


@dataclass(frozen=True, slots=True)
class EngineEvent:
    name: str
    bar_index: int
    payload: dict[str, Any] = field(default_factory=dict)
