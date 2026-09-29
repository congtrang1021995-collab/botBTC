from __future__ import annotations

import argparse
import csv
import json
from dataclasses import asdict
from pathlib import Path

from trading_bot.backtest.csv_loader import load_bars_csv
from trading_bot.backtest.metrics import (
    calculate_trade_breakdown,
    count_exit_reasons,
)
from trading_bot.backtest.runner import BacktestReport, run_backtest_report


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the Investment System Bot backtest on an OHLC CSV file."
    )
    parser.add_argument("csv_file", type=Path)
    parser.add_argument(
        "--trades-out",
        type=Path,
        help="Optional path for the closed-trade ledger CSV.",
    )
    parser.add_argument(
        "--higher",
        type=Path,
        help="CSV nến khung lớn để lọc lệnh theo trend (Bot 2: M15 <- H1, H1 <- H4).",
    )
    args = parser.parse_args()

    bars = load_bars_csv(args.csv_file)
    higher_bars = load_bars_csv(args.higher) if args.higher is not None else None
    report = run_backtest_report(bars, higher_bars=higher_bars)
    if args.trades_out is not None:
        _write_trades(args.trades_out, report)

    payload = {
        "input_bars": len(bars),
        "higher_file": str(args.higher) if args.higher else None,
        "closed_trades": len(report.trades),
        "open_position_at_end": bool(
            report.results and report.results[-1].state.open_positions
        ),
        "open_positions_at_end": (
            len(report.results[-1].state.open_positions) if report.results else 0
        ),
        "metrics": asdict(report.trade_metrics),
        "exit_reasons": count_exit_reasons(list(report.trades)),
        "breakdown": {
            label: asdict(metrics)
            for label, metrics in calculate_trade_breakdown(
                list(report.trades)
            ).items()
        },
        "account": asdict(report.results[-1].account) if report.results else None,
        "trades_file": str(args.trades_out) if args.trades_out else None,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _write_trades(path: Path, report: BacktestReport) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "side",
        "source_setup",
        "entry_bar_index",
        "exit_bar_index",
        "entry_price",
        "exit_price",
        "hard_stop_price",
        "take_profit_price",
        "quantity",
        "exit_reason",
        "pnl",
        "initial_risk",
        "r_multiple",
        "bars_held",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for trade in report.trades:
            row = asdict(trade)
            row["side"] = trade.side.value
            row["source_setup"] = (
                trade.source_setup.name if trade.source_setup is not None else ""
            )
            writer.writerow(row)


if __name__ == "__main__":
    main()
