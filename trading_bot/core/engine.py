from __future__ import annotations

from dataclasses import dataclass, field, replace

from trading_bot.config import StrategyConfig
from trading_bot.core.indicators import IndicatorState, update_indicators
from trading_bot.core.models import (
    Bar,
    BarContext,
    EngineEvent,
    PositionSide,
    PositionState,
    PositionStatus,
    StrategyState,
)
from trading_bot.core.swings import SwingState, update_swings
from trading_bot.strategy.add import AddDecision, evaluate_add
from trading_bot.strategy.entry import EntryDecision, evaluate_entry
from trading_bot.strategy.exit import (
    ExitDecision,
    calculate_take_profit_price,
    evaluate_exit,
)
from trading_bot.strategy.invalidation import (
    InvalidationDecision,
    apply_minimum_risk,
    evaluate_invalidation,
)
from trading_bot.strategy.position_size import (
    PositionSizeDecision,
    calculate_position_size,
)
from trading_bot.strategy.setup import SetupDecision, evaluate_setup
from trading_bot.strategy.trend import TrendDecision, evaluate_trend


@dataclass(frozen=True, slots=True)
class MarketState:
    indicators: IndicatorState = field(default_factory=IndicatorState)
    swings: SwingState = field(default_factory=SwingState)
    last_bar_index: int | None = None


@dataclass(frozen=True, slots=True)
class AccountState:
    """Vốn và chi phí đã thực hiện. Chỉ cập nhật khi một lệnh đóng."""

    equity: float = 0.0
    realized_pnl: float = 0.0


@dataclass(frozen=True, slots=True)
class EngineState:
    market: MarketState = field(default_factory=MarketState)
    strategy: StrategyState = field(default_factory=StrategyState)
    account: AccountState = field(default_factory=AccountState)


@dataclass(frozen=True, slots=True)
class ProcessResult:
    context: BarContext
    state: StrategyState
    account: AccountState
    trend: TrendDecision
    setup: SetupDecision
    entry: EntryDecision
    invalidation: InvalidationDecision
    invalidations: tuple[InvalidationDecision, ...]
    position_size: PositionSizeDecision
    add: AddDecision
    exit: ExitDecision
    exits: tuple[ExitDecision, ...]
    events: tuple[EngineEvent, ...]


def _position_snapshot(positions: tuple[PositionState, ...]) -> PositionState:
    """Keep the old ``state.position`` view usable for single-trade callers."""
    return positions[-1] if positions else PositionState()


def _with_positions(
    state: StrategyState,
    positions: tuple[PositionState, ...],
) -> StrategyState:
    return replace(
        state,
        positions=positions,
        position=_position_snapshot(positions),
    )


class TradingEngine:
    """Own state commits and orchestrate the seven modules per closed bar."""

    def __init__(self, config: StrategyConfig | None = None) -> None:
        self.config = config or StrategyConfig()
        self._state = EngineState(
            account=AccountState(equity=self.config.initial_equity)
        )
        self._next_trade_number = 1

    @property
    def state(self) -> EngineState:
        return self._state

    def reset(self) -> None:
        self._state = EngineState(
            account=AccountState(equity=self.config.initial_equity)
        )
        self._next_trade_number = 1

    def _settle(
        self,
        position: PositionState,
        exit_price: float,
        account: AccountState,
    ) -> tuple[float, AccountState]:
        """Ghi nhận P&L thực hiện của một lệnh vừa đóng."""
        direction = 1.0 if position.side == PositionSide.LONG else -1.0
        pnl = (exit_price - position.entry_price) * direction * position.size
        updated = replace(
            account,
            equity=account.equity + pnl,
            realized_pnl=account.realized_pnl + pnl,
        )
        return pnl, updated

    def _closes_within_bar(
        self,
        context: BarContext,
        strategy: StrategyState,
        position: PositionState,
    ) -> bool:
        """Lệnh này có bị hard stop / trailing stop / TP trong nến hiện tại không.

        Chỉ dùng để Step 3 biết slot còn trống. Không tính thoát tại Close khi mất
        trend vì Pine chạy Step 4 sau Step 3. Các quyết định thật được tính lại ở
        vòng invalidation/exit phía dưới với cùng dữ liệu, nên kết quả đồng nhất.
        """
        scoped = replace(
            strategy,
            pending_entry=None,
            position=position,
            positions=(position,),
        )
        decision = evaluate_invalidation(context, scoped, self.config)
        if decision.hard_stop_triggered or decision.trade_invalidated:
            return True
        if decision.stop_updated:
            position = replace(position, hard_stop_price=decision.hard_stop_price)
            scoped = replace(scoped, position=position, positions=(position,))
        return evaluate_exit(context, scoped, self.config).should_exit

    def process_bar(self, bar: Bar) -> ProcessResult:
        """Process one closed bar. Bars must arrive in strictly increasing order."""
        last_index = self._state.market.last_bar_index
        if last_index is not None and bar.index <= last_index:
            raise ValueError(
                f"bar index must increase: received {bar.index} after {last_index}"
            )

        indicator_state, indicators = update_indicators(
            self._state.market.indicators,
            bar,
            self.config,
        )
        swing_state, swings = update_swings(
            self._state.market.swings,
            bar,
            self.config.pivot_legs,
        )
        context = BarContext(bar=bar, indicators=indicators, swings=swings)

        previous_positions: list[PositionState] = []
        for position in self._state.strategy.open_positions:
            if position.trade_id is None:
                side_name = position.side.value if position.side is not None else "TRADE"
                position = replace(
                    position,
                    trade_id=f"{side_name}-{self._next_trade_number}",
                )
                self._next_trade_number += 1
            previous_positions.append(position)
        previous_strategy = _with_positions(
            self._state.strategy,
            tuple(previous_positions),
        )
        trend = evaluate_trend(context, previous_strategy, self.config)
        strategy_after_trend = replace(
            previous_strategy,
            trend=trend.trend,
            protected_swing_low=trend.protected_swing_low,
            protected_swing_high=trend.protected_swing_high,
        )

        setup = evaluate_setup(context, strategy_after_trend, self.config)
        strategy_after_setup = replace(
            strategy_after_trend,
            active_setups=setup.active,
        )

        # Bot 2: Step 3 nhìn danh sách lệnh tại Close nến, sau khi các lệnh bị
        # stop / chạm TP trong nến đã đóng (khớp Pine: Step 0 đối soát trade đóng
        # trước Step 3). Nhờ vậy slot theo loại setup được giải phóng ngay nến đó.
        entry_view_positions = tuple(
            position
            for position in strategy_after_setup.open_positions
            if not self._closes_within_bar(context, strategy_after_setup, position)
        )
        entry = evaluate_entry(
            context,
            _with_positions(strategy_after_setup, entry_view_positions),
            self.config,
            setup.started,
        )
        strategy_after_entry = replace(
            strategy_after_setup,
            value_zone_entry_side=entry.value_zone_entry_side,
            value_zone_entry_ema=entry.value_zone_entry_ema,
            pending_entry=entry.pending_entry,
        )

        account = self._state.account
        positions = list(strategy_after_entry.open_positions)
        position_size = PositionSizeDecision()
        opened_position: PositionState | None = None
        if entry.should_enter and entry.executed_entry is not None:
            executed = entry.executed_entry
            if executed.hard_stop_price is not None and entry.entry_price is not None:
                # Bot 2: 1R tối thiểu tính từ giá khớp thực tế.
                executed = replace(
                    executed,
                    hard_stop_price=apply_minimum_risk(
                        executed.side,
                        entry.entry_price,
                        executed.hard_stop_price,
                        self.config.min_initial_risk,
                    ),
                )
            position_size = calculate_position_size(
                context,
                replace(strategy_after_entry, pending_entry=executed),
                self.config,
                equity=account.equity,
                entry_price=entry.entry_price,
            )
            sized_entry = position_size.pending_entry
            try:
                take_profit_price = (
                    calculate_take_profit_price(
                        executed.side,
                        entry.entry_price,
                        executed.hard_stop_price,
                        self.config.take_profit_r_multiple,
                    )
                    if sized_entry is not None
                    else None
                )
            except ValueError:
                take_profit_price = None

            if sized_entry is None or take_profit_price is None:
                entry = replace(
                    entry,
                    should_enter=False,
                    cancelled=True,
                    executed_entry=None,
                    reason=(
                        position_size.reason
                        if sized_entry is None
                        else "INVALID_ENTRY_RISK"
                    ),
                )
            else:
                sized_entry = replace(
                    sized_entry,
                    take_profit_price=take_profit_price,
                )
                entry = replace(entry, executed_entry=sized_entry)
                trade_id = f"{sized_entry.side.value}-{self._next_trade_number}"
                self._next_trade_number += 1
                opened_position = PositionState(
                    trade_id=trade_id,
                    status=PositionStatus.OPEN,
                    side=sized_entry.side,
                    entry_price=entry.entry_price,
                    entry_bar_index=bar.index,
                    source_setup=sized_entry.source_setup,
                    trade_invalidation_price=sized_entry.trade_invalidation_price,
                    initial_hard_stop_price=sized_entry.hard_stop_price,
                    hard_stop_price=sized_entry.hard_stop_price,
                    take_profit_price=take_profit_price,
                    stop_buffer=sized_entry.stop_buffer,
                    size=sized_entry.quantity,
                )
                positions.append(opened_position)
                strategy_after_entry = _with_positions(
                    strategy_after_entry,
                    tuple(positions),
                )

        # Prepare the newly scheduled order independently of all live trades.
        pending_invalidation = evaluate_invalidation(
            context,
            replace(
                strategy_after_entry,
                position=PositionState(),
                positions=(),
            ),
            self.config,
        )

        # Every entry is a separate trade with its own frozen stop, trailing stop,
        # take-profit, P&L and exit lifecycle.
        position_invalidations: list[InvalidationDecision] = []
        surviving_positions: list[PositionState] = []
        invalidation_closes: list[
            tuple[PositionState, InvalidationDecision, float]
        ] = []
        for position in positions:
            decision = evaluate_invalidation(
                context,
                replace(
                    strategy_after_entry,
                    pending_entry=None,
                    position=position,
                    positions=(position,),
                ),
                self.config,
            )
            position_invalidations.append(decision)
            if (
                decision.hard_stop_triggered
                or decision.trade_invalidated
                or decision.trend_lost
            ):
                pnl, account = self._settle(
                    position,
                    decision.exit_price,
                    account,
                )
                invalidation_closes.append((position, decision, pnl))
                continue
            if decision.stop_updated:
                position = replace(
                    position,
                    hard_stop_price=decision.hard_stop_price,
                )
            surviving_positions.append(position)

        strategy_after_invalidation = _with_positions(
            replace(
                strategy_after_entry,
                pending_entry=pending_invalidation.pending_entry,
            ),
            tuple(surviving_positions),
        )

        if not entry.should_enter:
            position_size = calculate_position_size(
                context,
                strategy_after_invalidation,
                self.config,
                equity=account.equity,
            )
        sized_pending = position_size.pending_entry if not entry.should_enter else None
        strategy_after_size = replace(
            strategy_after_invalidation,
            pending_entry=sized_pending,
        )

        # Step 6 never changes an existing trade. New confirmed entries are handled
        # by Step 3 as independent same-direction trades.
        add = evaluate_add(context, strategy_after_size, self.config)

        exit_decisions: list[ExitDecision] = []
        final_positions: list[PositionState] = []
        take_profit_closes: list[tuple[PositionState, ExitDecision, float]] = []
        for position in surviving_positions:
            exit_decision = evaluate_exit(
                context,
                replace(
                    strategy_after_size,
                    position=position,
                    positions=(position,),
                ),
                self.config,
            )
            exit_decisions.append(exit_decision)
            if exit_decision.should_exit:
                pnl, account = self._settle(
                    position,
                    exit_decision.exit_price,
                    account,
                )
                take_profit_closes.append((position, exit_decision, pnl))
            else:
                final_positions.append(position)

        strategy_after_exit = _with_positions(
            strategy_after_size,
            tuple(final_positions),
        )

        events: list[EngineEvent] = []
        if trend.changed:
            events.append(
                EngineEvent(
                    name="TREND_CHANGED",
                    bar_index=bar.index,
                    payload={
                        "previous": previous_strategy.trend.name,
                        "current": trend.trend.name,
                    },
                )
            )
        for setup_type in sorted(setup.started, key=int):
            events.append(
                EngineEvent(
                    name="SETUP_STARTED",
                    bar_index=bar.index,
                    payload={"setup": setup_type.name},
                )
            )
        for setup_type in sorted(setup.ended, key=int):
            events.append(
                EngineEvent(
                    name="SETUP_ENDED",
                    bar_index=bar.index,
                    payload={"setup": setup_type.name},
                )
            )
        if entry.scheduled and strategy_after_size.pending_entry is not None:
            prepared = strategy_after_size.pending_entry
            events.append(
                EngineEvent(
                    name="ENTRY_SCHEDULED",
                    bar_index=bar.index,
                    payload={
                        "side": entry.side.value,
                        "setup": entry.source_setup.name,
                        "entry_timing": "NEXT_BAR_OPEN",
                        "hard_stop": prepared.hard_stop_price,
                        "take_profit": None,
                        "quantity": prepared.quantity,
                    },
                )
            )
        if entry.cancelled or pending_invalidation.setup_invalidated:
            events.append(
                EngineEvent(
                    name="ENTRY_CANCELLED",
                    bar_index=bar.index,
                    payload={
                        "reason": (
                            entry.reason
                            if entry.cancelled
                            else pending_invalidation.reason
                        )
                    },
                )
            )
        if entry.should_enter and opened_position is not None:
            entry_payload = {
                "trade_id": opened_position.trade_id,
                "side": entry.side.value,
                "price": entry.entry_price,
                "setup": entry.source_setup.name,
                "signal_bar_index": entry.signal_bar_index,
                "hard_stop": entry.executed_entry.hard_stop_price,
                "take_profit": opened_position.take_profit_price,
                "quantity": entry.executed_entry.quantity,
            }
            events.append(
                EngineEvent(
                    name="ENTRY_SIGNAL",
                    bar_index=bar.index,
                    payload=entry_payload,
                )
            )
            events.append(
                EngineEvent(
                    name="POSITION_OPENED",
                    bar_index=bar.index,
                    payload=entry_payload,
                )
            )

        take_profit_ids = {
            position.trade_id for position, _, _ in take_profit_closes
        }
        for position, decision, pnl in invalidation_closes:
            if decision.hard_stop_triggered:
                event_name = "POSITION_CLOSED_HARD_STOP"
            else:
                event_name = (
                    "POSITION_CLOSED_TRADE_INVALIDATION"
                    if decision.trade_invalidated
                    else "POSITION_CLOSED_TREND_LOST"
                )
            events.append(
                EngineEvent(
                    name=event_name,
                    bar_index=bar.index,
                    payload={
                        "trade_id": position.trade_id,
                        "exit_price": decision.exit_price,
                        "reason": decision.reason,
                        "pnl": pnl,
                    },
                )
            )

        for position, decision in zip(positions, position_invalidations):
            if (
                decision.stop_updated
                and position.trade_id not in take_profit_ids
            ):
                events.append(
                    EngineEvent(
                        name="TRAILING_STOP_UPDATED",
                        bar_index=bar.index,
                        payload={
                            "trade_id": position.trade_id,
                            "previous_stop": decision.previous_hard_stop_price,
                            "new_stop": decision.hard_stop_price,
                        },
                    )
                )

        for position, decision, pnl in take_profit_closes:
            events.append(
                EngineEvent(
                    name="POSITION_CLOSED_TAKE_PROFIT",
                    bar_index=bar.index,
                    payload={
                        "trade_id": position.trade_id,
                        "exit_price": decision.exit_price,
                        "take_profit": decision.take_profit_price,
                        "reason": decision.reason,
                        "pnl": pnl,
                    },
                )
            )

        self._state = EngineState(
            market=MarketState(
                indicators=indicator_state,
                swings=swing_state,
                last_bar_index=bar.index,
            ),
            strategy=strategy_after_exit,
            account=account,
        )
        invalidation = (
            pending_invalidation
            if pending_invalidation.reason != "NO_INVALIDATION"
            else position_invalidations[0]
            if position_invalidations
            else pending_invalidation
        )
        exit_decision = exit_decisions[0] if exit_decisions else ExitDecision()
        return ProcessResult(
            context=context,
            state=strategy_after_exit,
            account=account,
            trend=trend,
            setup=setup,
            entry=entry,
            invalidation=invalidation,
            invalidations=tuple(position_invalidations),
            position_size=position_size,
            add=add,
            exit=exit_decision,
            exits=tuple(exit_decisions),
            events=tuple(events),
        )