"""Dữ liệu Trade Explorer dựng nối tiếp từng nến.

Chỉ giữ những gì chart cần (OHLC, EMA, sổ lệnh, lịch sử stop của lệnh đang mở) thay vì toàn bộ
ProcessResult của mọi nến, nên nhẹ bộ nhớ và pickle được. Nạp lại bằng pickle rồi ``add`` các
nến mới là tiếp tục đúng chỗ, không phải chạy lại lịch sử. Kết quả giống hệt chạy một lượt.
"""

from __future__ import annotations

from dataclasses import asdict

from trading_bot.backtest.metrics import ClosedTradeTracker, calculate_trade_metrics
from trading_bot.config import StrategyConfig
from trading_bot.core.engine import TradingEngine
from trading_bot.core.models import Bar, PositionSide


def r2(value: float | None) -> float | None:
    return None if value is None else round(value, 2)


class IncrementalChart:
    def __init__(self, config: StrategyConfig | None = None) -> None:
        self.engine = TradingEngine(config)
        self.tracker = ClosedTradeTracker()
        self.t: list[int] = []
        self.o: list[float] = []
        self.h: list[float] = []
        self.l: list[float] = []
        self.c: list[float] = []
        self.e34: list[float | None] = []
        self.e89: list[float | None] = []
        self.closed: list = []            # ClosedTrade theo thứ tự đóng
        self.closed_stops: list[list] = []
        # (side, entry_bar) -> {bar j: hard stop sau Close nến j}; stop này có hiệu lực ở nến j+1.
        self.stop_hist: dict[tuple[PositionSide, int], dict[int, float | None]] = {}
        self.open_positions: tuple = ()

    def __len__(self) -> int:
        return len(self.t)

    def add(self, bar: Bar) -> None:
        if bar.index != len(self.t):
            raise ValueError(f"bar index {bar.index} phải bằng {len(self.t)}")
        result = self.engine.process_bar(bar)
        self.t.append(int(bar.timestamp.timestamp()))
        self.o.append(round(bar.open, 3))
        self.h.append(round(bar.high, 3))
        self.l.append(round(bar.low, 3))
        self.c.append(round(bar.close, 3))
        self.e34.append(r2(result.context.indicators.ema_fast))
        self.e89.append(r2(result.context.indicators.ema_slow))

        for trade in self.tracker.feed(result):
            direction = 1.0 if trade.side == PositionSide.LONG else -1.0
            initial = r2(trade.entry_price - direction * trade.initial_risk / trade.quantity)
            self.closed.append(trade)
            self.closed_stops.append(self._stops(trade.side, trade.entry_bar_index,
                                                 trade.exit_bar_index, initial))

        # Ghi stop sau nến này cho lệnh đang mở (lệnh đầu tiên khớp chiều + nến vào lệnh).
        j = bar.index
        seen: set[tuple[PositionSide, int]] = set()
        for position in result.state.open_positions:
            key = (position.side, position.entry_bar_index)
            if key in seen:
                continue
            seen.add(key)
            self.stop_hist.setdefault(key, {})[j] = position.hard_stop_price
        for key in [k for k in self.stop_hist if k not in seen]:
            del self.stop_hist[key]
        self.open_positions = result.state.open_positions

    def _stops(self, side: PositionSide, entry: int, exit_: int, initial: float) -> list:
        hist = self.stop_hist.get((side, entry), {})
        stops = [initial]
        for bar_index in range(entry + 1, exit_ + 1):
            stop = hist.get(bar_index - 1)
            stops.append(r2(stop) if stop else stops[-1])
        return stops

    def payload(self) -> dict:
        trades = []
        for trade, stops in zip(self.closed, self.closed_stops):
            trades.append({
                "id": 0, "ei": trade.entry_bar_index, "xi": trade.exit_bar_index,
                "side": trade.side.value,
                "setup": trade.source_setup.name if trade.source_setup else "",
                "entry": r2(trade.entry_price), "exit": r2(trade.exit_price),
                "sl": stops[0], "tp": r2(trade.take_profit_price),
                "reason": trade.exit_reason, "pnl": r2(trade.pnl), "r": round(trade.r_multiple, 3),
                "stops": stops,
            })
        last_index = len(self.t) - 1
        for position in self.open_positions:
            if position.size <= 0 or position.entry_bar_index is None:
                continue
            initial = r2(position.initial_hard_stop_price)
            trades.append({
                "id": 0, "ei": position.entry_bar_index, "xi": last_index,
                "side": position.side.value,
                "setup": position.source_setup.name if position.source_setup else "",
                "entry": r2(position.entry_price), "exit": None, "sl": initial,
                "tp": r2(position.take_profit_price), "reason": "OPEN", "pnl": None, "r": None,
                "stops": self._stops(position.side, position.entry_bar_index, last_index, initial),
                "open": True,
            })
        # Engine trả lệnh theo thứ tự đóng; xếp lại theo nến vào lệnh để duyệt theo thời gian.
        trades.sort(key=lambda x: (x["ei"], x["xi"]))
        for number, trade in enumerate(trades, start=1):
            trade["id"] = number
        metrics = calculate_trade_metrics(list(self.closed))
        return {
            "t": list(self.t), "o": list(self.o), "h": list(self.h), "l": list(self.l),
            "c": list(self.c), "e34": list(self.e34), "e89": list(self.e89),
            "trades": trades,
            "m": {k: (round(v, 4) if isinstance(v, float) else v) for k, v in asdict(metrics).items()},
        }
