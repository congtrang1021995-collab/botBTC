from __future__ import annotations

import random
import unittest
from dataclasses import replace

from trading_bot.backtest import run_backtest_report
from trading_bot.backtest.metrics import calculate_trade_breakdown, count_exit_reasons
from trading_bot.config import StrategyConfig
from trading_bot.core.models import (
    Bar,
    PositionState,
    PositionStatus,
    PendingEntry,
    PositionSide,
    SetupType,
    StrategyState,
    TrendState,
)
from trading_bot.strategy.invalidation import evaluate_invalidation
from trading_bot.strategy.position_size import calculate_position_size
from tests.helpers import make_context


def _synthetic_bars(seed: int = 7, count: int = 800) -> list[Bar]:
    """Chuỗi giá giả lập cố định: tăng, giảm, rồi tăng lại."""
    random.seed(seed)
    bars: list[Bar] = []
    price = 100.0
    for index in range(count):
        drift = 0.35 if index < 250 else (-0.40 if index < 450 else 0.30)
        price = max(5.0, price + drift + random.uniform(-1.6, 1.6))
        open_ = price + random.uniform(-0.5, 0.5)
        high = max(open_, price) + random.uniform(0.0, 1.2)
        low = min(open_, price) - random.uniform(0.0, 1.2)
        bars.append(Bar(index=index, open=open_, high=high, low=low, close=price))
    return bars


def _pending_long(hard_stop: float) -> PendingEntry:
    return PendingEntry(
        side=PositionSide.LONG,
        source_setup=SetupType.BREAKOUT_LONG,
        signal_bar_index=0,
        trade_invalidation_price=hard_stop + 0.4,
        hard_stop_price=hard_stop,
    )


class PositionSizeTests(unittest.TestCase):
    def test_risk_based_size_waits_until_actual_open_is_known(self) -> None:
        config = StrategyConfig(risk_model="fixed_risk")
        state = StrategyState(pending_entry=_pending_long(95.0))

        decision = calculate_position_size(make_context(close=100.0), state, config)

        self.assertEqual(decision.reason, "WAITING_FOR_ENTRY_PRICE")
        self.assertIsNotNone(decision.pending_entry)
        self.assertEqual(decision.quantity, 0.0)

    def test_risk_based_size_uses_actual_entry_to_stop_distance(self) -> None:
        config = StrategyConfig(
            risk_model="fixed_risk",
            risk_per_trade_fraction=0.01,
            initial_equity=100_000.0,
        )
        state = StrategyState(pending_entry=_pending_long(95.0))
        decision = calculate_position_size(
            make_context(close=100.0), state, config, entry_price=100.0
        )

        self.assertEqual(decision.reason, "RISK_BASED_SIZE")
        self.assertAlmostEqual(decision.quantity, 200.0)
        self.assertAlmostEqual(decision.risk_amount, 1_000.0)

    def test_quantity_step_rounds_down(self) -> None:
        config = StrategyConfig(
            risk_model="fixed_risk",
            risk_per_trade_fraction=0.01,
            initial_equity=100_000.0,
            quantity_step=100.0,
        )
        state = StrategyState(pending_entry=_pending_long(96.5))
        decision = calculate_position_size(
            make_context(close=100.0), state, config, entry_price=100.0
        )

        self.assertAlmostEqual(decision.quantity, 200.0)

    def test_equity_overrides_initial_equity(self) -> None:
        config = StrategyConfig(risk_model="fixed_risk", initial_equity=100_000.0)
        state = StrategyState(pending_entry=_pending_long(95.0))
        decision = calculate_position_size(
            make_context(close=100.0),
            state,
            config,
            equity=50_000.0,
            entry_price=100.0,
        )
        self.assertAlmostEqual(decision.quantity, 100.0)

    def test_budget_too_small_drops_the_pending_order(self) -> None:
        config = StrategyConfig(
            risk_model="fixed_risk",
            risk_per_trade_fraction=0.01,
            initial_equity=1_000.0,
            quantity_step=100.0,
        )
        state = StrategyState(pending_entry=_pending_long(95.0))
        decision = calculate_position_size(
            make_context(close=100.0), state, config, entry_price=100.0
        )

        self.assertEqual(decision.reason, "RISK_BUDGET_TOO_SMALL")
        self.assertIsNone(decision.pending_entry)

class TrendExitTests(unittest.TestCase):
    """Mất trend là mất luận điểm: đóng lệnh ngay tại Close."""

    def _open_long(self) -> StrategyState:
        return StrategyState(
            trend=TrendState.UPTREND,
            protected_swing_low=95.0,
            position=PositionState(
                status=PositionStatus.OPEN,
                side=PositionSide.LONG,
                entry_price=100.0,
                entry_bar_index=0,
                trade_invalidation_price=95.0,
                hard_stop_price=94.6,
                take_profit_price=108.1,
                size=1.0,
            ),
        )

    def test_long_exits_at_close_when_trend_is_lost(self) -> None:
        state = replace(self._open_long(), trend=TrendState.SIDEWAY)
        decision = evaluate_invalidation(
            make_context(index=5, close=101.0, low=99.0, high=102.0),
            state,
            StrategyConfig(exit_on_trend_loss=True),
        )
        self.assertTrue(decision.trend_lost)
        self.assertFalse(decision.hard_stop_triggered)
        self.assertEqual(decision.exit_price, 101.0)
        self.assertEqual(decision.reason, "TREND_LOST_CLOSE_EXIT")

    def test_bot2_keeps_position_when_trend_turns_sideway_by_default(self) -> None:
        # Bot 2: trend về SIDEWAY không đóng lệnh (exit_on_trend_loss=False mặc định).
        self.assertFalse(StrategyConfig().exit_on_trend_loss)
        self.assertTrue(StrategyConfig().exit_on_trend_reversal)
        state = replace(self._open_long(), trend=TrendState.SIDEWAY)
        decision = evaluate_invalidation(
            make_context(index=5, close=101.0, low=99.0, high=102.0),
            state,
            StrategyConfig(),
        )
        self.assertFalse(decision.trend_lost)
        self.assertEqual(decision.reason, "POSITION_VALID")

    def test_bot2_long_exits_at_close_when_trend_reverses_to_downtrend(self) -> None:
        state = replace(self._open_long(), trend=TrendState.DOWNTREND)
        decision = evaluate_invalidation(
            make_context(index=5, close=101.0, low=99.0, high=102.0),
            state,
            StrategyConfig(),
        )
        self.assertTrue(decision.trend_lost)
        self.assertFalse(decision.hard_stop_triggered)
        self.assertEqual(decision.exit_price, 101.0)
        self.assertEqual(decision.reason, "TREND_REVERSAL_CLOSE_EXIT")

    def test_bot2_short_exits_at_close_when_trend_reverses_to_uptrend(self) -> None:
        state = StrategyState(
            trend=TrendState.UPTREND,
            position=PositionState(
                status=PositionStatus.OPEN,
                side=PositionSide.SHORT,
                entry_price=100.0,
                trade_invalidation_price=105.0,
                initial_hard_stop_price=105.4,
                hard_stop_price=105.4,
                take_profit_price=73.0,
                size=1.0,
            ),
        )
        decision = evaluate_invalidation(
            make_context(index=5, close=99.0, low=98.0, high=101.0),
            state,
            StrategyConfig(),
        )
        self.assertTrue(decision.trend_lost)
        self.assertEqual(decision.exit_price, 99.0)
        self.assertEqual(decision.reason, "TREND_REVERSAL_CLOSE_EXIT")

    def test_trend_reversal_exit_can_be_disabled(self) -> None:
        state = replace(self._open_long(), trend=TrendState.DOWNTREND)
        decision = evaluate_invalidation(
            make_context(index=5, close=101.0, low=99.0, high=102.0),
            state,
            StrategyConfig(exit_on_trend_reversal=False),
        )
        self.assertFalse(decision.trend_lost)
        self.assertEqual(decision.reason, "POSITION_VALID")

    def test_trend_loss_option_reports_legacy_reason_on_reversal(self) -> None:
        state = replace(self._open_long(), trend=TrendState.DOWNTREND)
        decision = evaluate_invalidation(
            make_context(index=5, close=101.0, low=99.0, high=102.0),
            state,
            StrategyConfig(exit_on_trend_loss=True),
        )
        self.assertTrue(decision.trend_lost)
        self.assertEqual(decision.reason, "TREND_LOST_CLOSE_EXIT")

    def test_position_is_kept_while_the_trend_holds(self) -> None:
        decision = evaluate_invalidation(
            make_context(index=5, close=101.0, low=99.0, high=102.0),
            self._open_long(),
            StrategyConfig(),
        )
        self.assertFalse(decision.trend_lost)
        self.assertEqual(decision.reason, "POSITION_VALID")

    def test_hard_stop_keeps_priority_over_trend_loss(self) -> None:
        state = replace(self._open_long(), trend=TrendState.SIDEWAY)
        decision = evaluate_invalidation(
            make_context(index=5, close=96.0, low=94.0, high=102.0),
            state,
            StrategyConfig(exit_on_trend_loss=True),
        )
        self.assertTrue(decision.hard_stop_triggered)
        self.assertEqual(decision.exit_price, 94.6)

    def test_trend_exit_can_be_disabled(self) -> None:
        state = replace(self._open_long(), trend=TrendState.SIDEWAY)
        decision = evaluate_invalidation(
            make_context(index=5, close=101.0, low=99.0, high=102.0),
            state,
            StrategyConfig(exit_on_trend_loss=False),
        )
        self.assertFalse(decision.trend_lost)
        self.assertEqual(decision.reason, "POSITION_VALID")

    def test_backtest_applies_trailing_stop_updates(self) -> None:
        bars = _synthetic_bars()
        report = run_backtest_report(bars, StrategyConfig(minimum_tick=0.01, min_confirm_slope=0.0))
        self.assertTrue(report.trades)
        self.assertTrue(
            any(
                event.name == "TRAILING_STOP_UPDATED"
                for result in report.results
                for event in result.events
            )
        )


class AccountAndStatsTests(unittest.TestCase):
    def test_equity_tracks_realized_pnl(self) -> None:
        bars = _synthetic_bars()
        config = StrategyConfig(minimum_tick=0.01, initial_equity=1_000_000.0, min_confirm_slope=0.0)
        report = run_backtest_report(bars, config)
        account = report.results[-1].account

        self.assertAlmostEqual(
            account.equity,
            config.initial_equity + account.realized_pnl,
            places=6,
        )
        self.assertGreater(report.trade_metrics.total_trades, 0)

    def test_win_and_loss_ratios_add_up(self) -> None:
        bars = _synthetic_bars()
        metrics = run_backtest_report(
            bars, StrategyConfig(minimum_tick=0.01, min_confirm_slope=0.0)
        ).trade_metrics

        self.assertEqual(
            metrics.wins + metrics.losses + metrics.breakeven,
            metrics.total_trades,
        )
        self.assertAlmostEqual(
            metrics.win_rate + metrics.loss_rate,
            (metrics.wins + metrics.losses) / metrics.total_trades,
        )
        self.assertGreaterEqual(metrics.max_consecutive_wins, 1)
        self.assertGreaterEqual(metrics.average_win, 0.0)
        self.assertLessEqual(metrics.average_loss, 0.0)

    def test_breakdown_splits_by_setup_and_side(self) -> None:
        bars = _synthetic_bars()
        trades = list(run_backtest_report(bars, StrategyConfig(minimum_tick=0.01, min_confirm_slope=0.0)).trades)
        breakdown = calculate_trade_breakdown(trades)

        self.assertTrue(any(label.startswith("setup:") for label in breakdown))
        self.assertTrue(any(label.startswith("side:") for label in breakdown))
        side_total = sum(
            metrics.total_trades
            for label, metrics in breakdown.items()
            if label.startswith("side:")
        )
        self.assertEqual(side_total, len(trades))


if __name__ == "__main__":
    unittest.main()
