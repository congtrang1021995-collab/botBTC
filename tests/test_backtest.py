from __future__ import annotations

import unittest
from types import SimpleNamespace

from trading_bot.backtest import (
    calculate_metrics,
    calculate_trade_metrics,
    extract_closed_trades,
    run_backtest,
)
from trading_bot.config import StrategyConfig
from trading_bot.core.models import EngineEvent, PositionSide, SetupType, TrendState
from tests.helpers import make_bar


class BacktestTests(unittest.TestCase):
    def test_runner_replays_bars_and_builds_step_1_3_metrics(self) -> None:
        bars = [make_bar(index, 10.0 + index) for index in range(3)]
        results = run_backtest(
            bars,
            StrategyConfig(
                ema_fast_length=2,
                ema_slow_length=3,
                slope_length=2,
                pivot_legs=1,
            ),
        )
        metrics = calculate_metrics(results)

        self.assertEqual(metrics.total_bars, 3)
        self.assertEqual(metrics.trend_bars[TrendState.SIDEWAY], 3)
        self.assertEqual(metrics.sideway_ratio, 1.0)
        self.assertEqual(metrics.trend_changes, 0)
        self.assertEqual(metrics.entry_signals[PositionSide.LONG], 0)
        self.assertEqual(metrics.entry_signals[PositionSide.SHORT], 0)

    def test_trade_ledger_and_metrics_use_closed_engine_events(self) -> None:
        def result(
            bar_index: int,
            events: tuple[EngineEvent, ...],
            setup: SetupType | None = None,
        ) -> SimpleNamespace:
            return SimpleNamespace(
                context=SimpleNamespace(bar=SimpleNamespace(index=bar_index)),
                entry=SimpleNamespace(source_setup=setup),
                events=events,
            )

        results = [
            result(
                1,
                (
                    EngineEvent(
                        "POSITION_OPENED",
                        1,
                        {
                            "side": "LONG",
                            "price": 100.0,
                            "hard_stop": 90.0,
                            "take_profit": 150.0,
                            "quantity": 1.0,
                        },
                    ),
                ),
                SetupType.BREAKOUT_LONG,
            ),
            result(
                4,
                (
                    EngineEvent(
                        "POSITION_CLOSED_TAKE_PROFIT",
                        4,
                        {
                            "exit_price": 150.0,
                            "reason": "TAKE_PROFIT_EXIT",
                        },
                    ),
                ),
            ),
            result(
                6,
                (
                    EngineEvent(
                        "POSITION_OPENED",
                        6,
                        {
                            "side": "SHORT",
                            "price": 100.0,
                            "hard_stop": 110.0,
                            "take_profit": 74.0,
                            "quantity": 1.0,
                        },
                    ),
                ),
                SetupType.BREAKOUT_SHORT,
            ),
            result(
                8,
                (
                    EngineEvent(
                        "POSITION_CLOSED_HARD_STOP",
                        8,
                        {
                            "exit_price": 110.0,
                            "reason": "HARD_STOP_INTRABAR_EXIT",
                        },
                    ),
                ),
            ),
        ]

        trades = extract_closed_trades(results)
        metrics = calculate_trade_metrics(trades)

        self.assertEqual(len(trades), 2)
        self.assertEqual(trades[0].r_multiple, 5.0)
        self.assertEqual(trades[0].bars_held, 3)
        self.assertEqual(trades[1].r_multiple, -1.0)
        self.assertEqual(metrics.total_trades, 2)
        self.assertEqual(metrics.wins, 1)
        self.assertEqual(metrics.losses, 1)
        self.assertEqual(metrics.win_rate, 0.5)
        self.assertEqual(metrics.net_profit, 40.0)
        self.assertEqual(metrics.profit_factor, 5.0)
        self.assertAlmostEqual(metrics.average_r, 2.0)
        self.assertAlmostEqual(metrics.cumulative_r, 4.0)
        self.assertEqual(metrics.max_drawdown_r, 1.0)

    def test_trade_ledger_matches_overlapping_trades_by_id(self) -> None:
        def result(
            events: tuple[EngineEvent, ...],
            setup: SetupType | None = None,
        ) -> SimpleNamespace:
            return SimpleNamespace(
                entry=SimpleNamespace(source_setup=setup),
                events=events,
            )

        results = [
            result(
                (
                    EngineEvent(
                        "POSITION_OPENED",
                        1,
                        {
                            "trade_id": "LONG-1",
                            "side": "LONG",
                            "price": 100.0,
                            "hard_stop": 90.0,
                            "take_profit": 150.0,
                            "quantity": 1.0,
                        },
                    ),
                ),
                SetupType.BREAKOUT_LONG,
            ),
            result(
                (
                    EngineEvent(
                        "POSITION_OPENED",
                        2,
                        {
                            "trade_id": "LONG-2",
                            "side": "LONG",
                            "price": 110.0,
                            "hard_stop": 100.0,
                            "take_profit": 160.0,
                            "quantity": 2.0,
                        },
                    ),
                ),
                SetupType.VALUE_ZONE_LONG,
            ),
            result(
                (
                    EngineEvent(
                        "POSITION_CLOSED_HARD_STOP",
                        3,
                        {
                            "trade_id": "LONG-2",
                            "exit_price": 100.0,
                            "reason": "HARD_STOP_INTRABAR_EXIT",
                        },
                    ),
                )
            ),
            result(
                (
                    EngineEvent(
                        "POSITION_CLOSED_TAKE_PROFIT",
                        4,
                        {
                            "trade_id": "LONG-1",
                            "exit_price": 150.0,
                            "reason": "TAKE_PROFIT_EXIT",
                        },
                    ),
                )
            ),
        ]

        trades = extract_closed_trades(results)

        self.assertEqual(len(trades), 2)
        self.assertEqual(trades[0].entry_price, 110.0)
        self.assertEqual(trades[0].pnl, -20.0)
        self.assertEqual(trades[1].entry_price, 100.0)
        self.assertEqual(trades[1].pnl, 50.0)

if __name__ == "__main__":
    unittest.main()
