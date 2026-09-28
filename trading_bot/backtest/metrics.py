from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from math import isclose

from trading_bot.core.engine import ProcessResult
from trading_bot.core.models import PositionSide, SetupType, TrendState


@dataclass(frozen=True, slots=True)
class DiagnosticMetrics:
    total_bars: int
    trend_bars: dict[TrendState, int]
    trend_changes: int
    setup_starts: dict[SetupType, int]
    entry_signals: dict[PositionSide, int]
    sideway_ratio: float


@dataclass(frozen=True, slots=True)
class ClosedTrade:
    side: PositionSide
    source_setup: SetupType | None
    entry_bar_index: int
    exit_bar_index: int
    entry_price: float
    exit_price: float
    hard_stop_price: float
    take_profit_price: float
    quantity: float
    exit_reason: str
    pnl: float
    initial_risk: float
    r_multiple: float
    bars_held: int


@dataclass(frozen=True, slots=True)
class TradeMetrics:
    total_trades: int
    wins: int
    losses: int
    breakeven: int
    win_rate: float
    gross_profit: float
    gross_loss: float
    net_profit: float
    profit_factor: float | None
    average_r: float
    cumulative_r: float
    max_drawdown_r: float
    loss_rate: float = 0.0
    average_win: float = 0.0
    average_loss: float = 0.0
    payoff_ratio: float | None = None
    expectancy: float = 0.0
    largest_win: float = 0.0
    largest_loss: float = 0.0
    max_consecutive_wins: int = 0
    max_consecutive_losses: int = 0


def calculate_metrics(results: list[ProcessResult]) -> DiagnosticMetrics:
    trend_bars = Counter(result.state.trend for result in results)
    setup_starts: Counter[SetupType] = Counter()
    entry_signals: Counter[PositionSide] = Counter()
    trend_changes = 0
    for result in results:
        trend_changes += int(result.trend.changed)
        setup_starts.update(result.setup.started)
        if result.entry.should_enter and result.entry.side is not None:
            entry_signals[result.entry.side] += 1

    total = len(results)
    sideway_ratio = trend_bars[TrendState.SIDEWAY] / total if total else 0.0
    return DiagnosticMetrics(
        total_bars=total,
        trend_bars={state: trend_bars[state] for state in TrendState},
        trend_changes=trend_changes,
        setup_starts={setup: setup_starts[setup] for setup in SetupType},
        entry_signals={side: entry_signals[side] for side in PositionSide},
        sideway_ratio=sideway_ratio,
    )


_CLOSE_EVENTS = frozenset({
    "POSITION_CLOSED_HARD_STOP",
    "POSITION_CLOSED_TRADE_INVALIDATION",
    "POSITION_CLOSED_TREND_LOST",
    "POSITION_CLOSED_TAKE_PROFIT",
})


class ClosedTradeTracker:
    """Ghi sổ lệnh từ sự kiện engine theo từng nến — dùng được nối tiếp (chart live)."""

    def __init__(self) -> None:
        self.open_trades: dict[str, dict[str, object]] = {}
        self.legacy_trade_number = 0

    def feed(self, result: ProcessResult) -> list[ClosedTrade]:
        """Xử lý sự kiện của một nến, trả các lệnh vừa đóng trong nến đó."""
        closed: list[ClosedTrade] = []
        close_events = _CLOSE_EVENTS
        for event in result.events:
            if event.name == "POSITION_OPENED":
                trade_id = event.payload.get("trade_id")
                if trade_id is None:
                    self.legacy_trade_number += 1
                    trade_id = f"LEGACY-{self.legacy_trade_number}"
                trade_id = str(trade_id)
                if trade_id in self.open_trades:
                    raise ValueError(f"duplicate open trade id: {trade_id}")
                source_setup = event.payload.get("setup")
                if source_setup is not None:
                    source_setup = SetupType[str(source_setup)]
                else:
                    source_setup = result.entry.source_setup
                self.open_trades[trade_id] = {
                    "side": PositionSide(event.payload["side"]),
                    "source_setup": source_setup,
                    "entry_bar_index": event.bar_index,
                    "entry_price": float(event.payload["price"]),
                    "hard_stop_price": float(event.payload["hard_stop"]),
                    "take_profit_price": float(event.payload["take_profit"]),
                    "quantity": float(event.payload["quantity"]),
                }
                continue

            if event.name not in close_events:
                continue
            trade_id = event.payload.get("trade_id")
            if trade_id is None:
                if len(self.open_trades) != 1:
                    raise ValueError(
                        f"received {event.name} without an unambiguous trade id"
                    )
                trade_id = next(iter(self.open_trades))
            open_trade = self.open_trades.pop(str(trade_id), None)
            if open_trade is None:
                raise ValueError(
                    f"received {event.name} without active trade {trade_id}"
                )

            side = open_trade["side"]
            entry_price = float(open_trade["entry_price"])
            exit_price = float(event.payload["exit_price"])
            quantity = float(open_trade["quantity"])
            direction = 1.0 if side == PositionSide.LONG else -1.0
            pnl = (exit_price - entry_price) * direction * quantity
            initial_risk = (
                abs(entry_price - float(open_trade["hard_stop_price"])) * quantity
            )
            if initial_risk <= 0.0:
                raise ValueError("trade initial risk must be positive")

            closed.append(
                ClosedTrade(
                    side=side,
                    source_setup=open_trade["source_setup"],
                    entry_bar_index=int(open_trade["entry_bar_index"]),
                    exit_bar_index=event.bar_index,
                    entry_price=entry_price,
                    exit_price=exit_price,
                    hard_stop_price=float(open_trade["hard_stop_price"]),
                    take_profit_price=float(open_trade["take_profit_price"]),
                    quantity=quantity,
                    exit_reason=str(event.payload["reason"]),
                    pnl=pnl,
                    initial_risk=initial_risk,
                    r_multiple=pnl / initial_risk,
                    bars_held=event.bar_index - int(open_trade["entry_bar_index"]),
                )
            )

        return closed


def extract_closed_trades(results: list[ProcessResult]) -> list[ClosedTrade]:
    """Build a closed-trade ledger from engine events, including overlaps."""
    tracker = ClosedTradeTracker()
    trades: list[ClosedTrade] = []
    for result in results:
        trades.extend(tracker.feed(result))
    return trades


def calculate_trade_metrics(trades: list[ClosedTrade]) -> TradeMetrics:
    wins = sum(trade.pnl > 0.0 and not isclose(trade.pnl, 0.0) for trade in trades)
    losses = sum(trade.pnl < 0.0 and not isclose(trade.pnl, 0.0) for trade in trades)
    breakeven = len(trades) - wins - losses
    gross_profit = sum(max(trade.pnl, 0.0) for trade in trades)
    gross_loss = sum(max(-trade.pnl, 0.0) for trade in trades)
    net_profit = gross_profit - gross_loss
    total = len(trades)
    cumulative_r = sum(trade.r_multiple for trade in trades)

    equity_r = 0.0
    peak_r = 0.0
    max_drawdown_r = 0.0
    streak_wins = 0
    streak_losses = 0
    max_consecutive_wins = 0
    max_consecutive_losses = 0
    for trade in trades:
        equity_r += trade.r_multiple
        peak_r = max(peak_r, equity_r)
        max_drawdown_r = max(max_drawdown_r, peak_r - equity_r)
        if trade.pnl > 0.0 and not isclose(trade.pnl, 0.0):
            streak_wins += 1
            streak_losses = 0
        elif trade.pnl < 0.0 and not isclose(trade.pnl, 0.0):
            streak_losses += 1
            streak_wins = 0
        else:
            streak_wins = 0
            streak_losses = 0
        max_consecutive_wins = max(max_consecutive_wins, streak_wins)
        max_consecutive_losses = max(max_consecutive_losses, streak_losses)

    winning = [trade.pnl for trade in trades if trade.pnl > 0.0]
    losing = [trade.pnl for trade in trades if trade.pnl < 0.0]
    average_win = sum(winning) / len(winning) if winning else 0.0
    average_loss = sum(losing) / len(losing) if losing else 0.0

    return TradeMetrics(
        total_trades=total,
        wins=wins,
        losses=losses,
        breakeven=breakeven,
        win_rate=wins / total if total else 0.0,
        gross_profit=gross_profit,
        gross_loss=gross_loss,
        net_profit=net_profit,
        profit_factor=gross_profit / gross_loss if gross_loss else None,
        average_r=cumulative_r / total if total else 0.0,
        cumulative_r=cumulative_r,
        max_drawdown_r=max_drawdown_r,
        loss_rate=losses / total if total else 0.0,
        average_win=average_win,
        average_loss=average_loss,
        payoff_ratio=(
            average_win / abs(average_loss) if average_loss != 0.0 else None
        ),
        expectancy=net_profit / total if total else 0.0,
        largest_win=max(winning) if winning else 0.0,
        largest_loss=min(losing) if losing else 0.0,
        max_consecutive_wins=max_consecutive_wins,
        max_consecutive_losses=max_consecutive_losses,
    )


def calculate_trade_breakdown(
    trades: list[ClosedTrade],
) -> dict[str, TradeMetrics]:
    """Tách kết quả theo loại setup và theo hướng lệnh."""
    groups: dict[str, list[ClosedTrade]] = {}
    for trade in trades:
        setup_name = (
            trade.source_setup.name if trade.source_setup is not None else "UNKNOWN"
        )
        groups.setdefault(f"setup:{setup_name}", []).append(trade)
        groups.setdefault(f"side:{trade.side.name}", []).append(trade)
    return {
        label: calculate_trade_metrics(group)
        for label, group in sorted(groups.items())
    }


def count_exit_reasons(trades: list[ClosedTrade]) -> dict[str, int]:
    """Đếm số lệnh theo lý do thoát."""
    counter: Counter[str] = Counter(trade.exit_reason for trade in trades)
    return dict(sorted(counter.items()))
