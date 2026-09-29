from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import timedelta

from trading_bot.backtest.metrics import (
    ClosedTrade,
    TradeMetrics,
    calculate_trade_metrics,
    extract_closed_trades,
)
from trading_bot.config import StrategyConfig, config_for_timeframe
from trading_bot.core.engine import ProcessResult, TradingEngine
from trading_bot.core.higher_tf import HigherTrendFeed, infer_minutes
from trading_bot.core.models import Bar


@dataclass(frozen=True, slots=True)
class BacktestReport:
    results: tuple[ProcessResult, ...]
    trades: tuple[ClosedTrade, ...]
    trade_metrics: TradeMetrics


def run_backtest(
    bars: Iterable[Bar],
    config: StrategyConfig | None = None,
    higher_bars: list[Bar] | None = None,
) -> list[ProcessResult]:
    """Replay closed bars through a fresh engine and return every snapshot.

    ``higher_bars``: nến khung lớn (Bot 2, lọc theo trend khung lớn đã đóng).
    """
    bars = list(bars)
    try:
        minutes = infer_minutes(bars)
    except ValueError:  # nến không có thời gian (test) -> không gắn tham số theo khung
        minutes = None
    engine = TradingEngine(config_for_timeframe(config, minutes))
    if not higher_bars:
        return [engine.process_bar(bar) for bar in bars]
    feed = HigherTrendFeed(infer_minutes(higher_bars), config)
    for hb in higher_bars:
        feed.add(hb.timestamp, hb.open, hb.high, hb.low, hb.close)
    step = timedelta(minutes=minutes)
    return [engine.process_bar(bar, feed.trend_at(bar.timestamp + step)) for bar in bars]


def run_backtest_report(
    bars: Iterable[Bar],
    config: StrategyConfig | None = None,
    higher_bars: list[Bar] | None = None,
) -> BacktestReport:
    """Replay bars and return snapshots, a trade ledger, and P&L metrics."""
    results = run_backtest(bars, config, higher_bars)
    trades = extract_closed_trades(results)
    return BacktestReport(
        results=tuple(results),
        trades=tuple(trades),
        trade_metrics=calculate_trade_metrics(trades),
    )
