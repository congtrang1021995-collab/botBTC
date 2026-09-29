from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from trading_bot.config import StrategyConfig
from trading_bot.core.models import (
    PendingEntry,
    PositionSide,
    PositionState,
    PositionStatus,
    SetupType,
    StrategyState,
)
from trading_bot.mt5.broker import resolve_symbol, BrokerPosition, OrderResult, RawBar
from trading_bot.mt5.trader import LiveTrader

T0 = datetime(2026, 9, 29, 0, 0, tzinfo=timezone.utc)
HOUR = timedelta(hours=1)


class FakeBroker:
    def __init__(self) -> None:
        self.bars = [RawBar(T0 + i * HOUR, 100.0, 101.0, 99.0, 100.0) for i in range(3)]
        self.bid, self.ask = 100.0, 100.2
        self.open: dict[int, BrokerPosition] = {}
        self.calls: list[tuple] = []
        self.next_ticket = 1

    def closed_bars(self, timeframe, count):
        return self.bars[-count:]

    def forming_bar_open(self, timeframe):
        return self.bars[-1].time + HOUR

    def positions(self, magic):
        return dict(self.open)

    def bid_ask(self):
        return self.bid, self.ask

    def round_price(self, price):
        return round(price, 2)

    def open_market(self, side, volume, sl, tp, magic, comment):
        ticket = self.next_ticket
        self.next_ticket += 1
        price = self.ask if side == "LONG" else self.bid
        self.open[ticket] = BrokerPosition(ticket, side, volume, price, sl, tp, comment)
        self.calls.append(("open", side, volume, round(sl, 2), round(tp, 2)))
        return OrderResult(True, ticket, price)

    def modify_sltp(self, ticket, sl, tp):
        self.open[ticket] = replace(self.open[ticket], sl=sl, tp=tp)
        self.calls.append(("modify", ticket, sl, tp))
        return OrderResult(True)

    def close(self, position, magic, comment):
        self.open.pop(position.ticket)
        self.calls.append(("close", position.ticket, comment))
        return OrderResult(True, price=self.bid)


class StubEngine:
    """Engine giả: trạng thái được test đặt trực tiếp."""

    def __init__(self) -> None:
        self.config = StrategyConfig()
        self.strategy = StrategyState()
        self.processed = 0
        self.atr = None

    @property
    def state(self):
        return SimpleNamespace(strategy=self.strategy,
                               market=SimpleNamespace(indicators=SimpleNamespace(atr=self.atr)))

    def process_bar(self, bar):
        self.processed += 1
        return SimpleNamespace(
            context=SimpleNamespace(bar=bar, indicators=SimpleNamespace(ema_fast=None, ema_slow=None)),
            state=self.strategy, events=(),
        )


def make_trader(broker, engine, now, **kwargs) -> LiveTrader:
    trader = LiveTrader(broker, "H1", volume=0.1, now=lambda: now[0], say=lambda _: None, **kwargs)
    trader.engine = engine
    return trader


def pending(signal_index: int, stop: float) -> PendingEntry:
    return PendingEntry(side=PositionSide.LONG, source_setup=SetupType.BREAKOUT_LONG,
                        signal_bar_index=signal_index, hard_stop_price=stop, quantity=1.0)


def engine_position(entry_index: int, stop: float, tp: float) -> PositionState:
    return PositionState(status=PositionStatus.OPEN, side=PositionSide.LONG, entry_price=100.2,
                         entry_bar_index=entry_index, source_setup=SetupType.BREAKOUT_LONG,
                         hard_stop_price=stop, initial_hard_stop_price=stop,
                         take_profit_price=tp, size=1.0, trade_id="LONG-1")


class LiveTraderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.broker = FakeBroker()
        self.engine = StubEngine()
        self.now = [T0 + 3 * HOUR + timedelta(seconds=5)]

    def test_pending_entry_sends_market_order_with_min_risk_and_10r_tp(self) -> None:
        self.engine.strategy = StrategyState(pending_entry=pending(2, stop=97.0))
        trader = make_trader(self.broker, self.engine, self.now)
        trader.start()
        # Giá khớp 100.2, stop 97 -> 1R = 3.2 < 10 -> nới stop về 90.2, TP = 100.2 + 100.
        self.assertEqual(self.broker.calls, [("open", "LONG", 0.1, 90.2, 200.2)])
        self.assertIsNone(trader.tickets[1]["key"])

    def test_min_risk_widens_to_atr_multiple(self) -> None:
        # ATR nến tín hiệu 5 -> mốc = max(10, 4 x 5) = 20 -> stop 80.2, TP = 100.2 + 200.
        self.engine.config = StrategyConfig(min_initial_risk_atr_multiplier=4.0)
        self.engine.atr = 5.0
        self.engine.strategy = StrategyState(pending_entry=pending(2, stop=97.0))
        make_trader(self.broker, self.engine, self.now).start()
        self.assertEqual(self.broker.calls, [("open", "LONG", 0.1, 80.2, 300.2)])

    def test_late_signal_is_skipped(self) -> None:
        self.engine.strategy = StrategyState(pending_entry=pending(2, stop=80.0))
        self.now[0] = T0 + 3 * HOUR + timedelta(minutes=30)
        trader = make_trader(self.broker, self.engine, self.now)
        trader.start()
        self.assertEqual(self.broker.calls, [])

    def test_bind_then_mirror_trailing_stop_then_close_on_engine_exit(self) -> None:
        self.engine.strategy = StrategyState(pending_entry=pending(2, stop=80.0))
        trader = make_trader(self.broker, self.engine, self.now)
        trader.start()
        # Nến vào lệnh (index 3) đóng: engine mở lệnh với SL/TP tính từ Open.
        self.broker.bars.append(RawBar(T0 + 3 * HOUR, 100.0, 105.0, 99.0, 104.0))
        self.engine.strategy = StrategyState(positions=(engine_position(3, 80.0, 300.0),))
        self.broker.bid, self.broker.ask = 104.0, 104.2
        trader.poll()
        self.assertTrue(trader.tickets[1]["key"].endswith("|BREAKOUT_LONG"))
        self.assertEqual(self.broker.calls[-1], ("modify", 1, 80.0, 300.0))
        # Trailing stop dời lên.
        self.broker.bars.append(RawBar(T0 + 4 * HOUR, 104.0, 130.0, 103.0, 128.0))
        self.engine.strategy = StrategyState(positions=(engine_position(3, 100.2, 300.0),))
        self.broker.bid, self.broker.ask = 128.0, 128.2
        trader.poll()
        self.assertEqual(self.broker.calls[-1], ("modify", 1, 100.2, 300.0))
        # Engine đóng lệnh (đảo chiều trend) -> đóng lệnh MT5.
        self.broker.bars.append(RawBar(T0 + 5 * HOUR, 128.0, 129.0, 110.0, 111.0))
        self.engine.strategy = StrategyState()
        trader.poll()
        self.assertEqual(self.broker.calls[-1][0:2], ("close", 1))
        self.assertEqual(trader.tickets, {})

    def test_entry_cancelled_by_engine_closes_broker_position(self) -> None:
        self.engine.strategy = StrategyState(pending_entry=pending(2, stop=80.0))
        trader = make_trader(self.broker, self.engine, self.now)
        trader.start()
        self.broker.bars.append(RawBar(T0 + 3 * HOUR, 100.0, 101.0, 99.0, 100.0))
        self.engine.strategy = StrategyState()
        trader.poll()
        self.assertEqual(self.broker.calls[-1][0:2], ("close", 1))

    def test_price_beyond_new_stop_closes_at_market(self) -> None:
        self.engine.strategy = StrategyState(pending_entry=pending(2, stop=80.0))
        trader = make_trader(self.broker, self.engine, self.now)
        trader.start()
        self.broker.bars.append(RawBar(T0 + 3 * HOUR, 100.0, 101.0, 99.0, 100.0))
        self.engine.strategy = StrategyState(positions=(engine_position(3, 101.0, 300.0),))
        trader.poll()  # bid 100 < SL mới 101
        self.assertEqual(self.broker.calls[-1][0:2], ("close", 1))

    def test_restart_restores_ticket_mapping_without_resending(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "state.json"
            self.engine.strategy = StrategyState(pending_entry=pending(2, stop=80.0))
            make_trader(self.broker, self.engine, self.now, state_path=state).start()
            again = make_trader(self.broker, StubEngine(), self.now, state_path=state)
            again.engine.strategy = StrategyState(pending_entry=pending(2, stop=80.0))
            again.start()
            self.assertEqual([c[0] for c in self.broker.calls], ["open"])
            self.assertIn(1, again.tickets)


class HigherTimeframeBroker(FakeBroker):
    """Nến H1 + H4 riêng; H4 đang chạy do test đặt."""

    def __init__(self) -> None:
        super().__init__()
        self.h4 = [RawBar(T0 - 4 * HOUR * (3 - i), 100.0, 101.0, 99.0, 100.0) for i in range(3)]
        self.h4_forming = T0

    def closed_bars(self, timeframe, count):
        return (self.h4 if timeframe == "H4" else self.bars)[-count:]

    def forming_bar_open(self, timeframe):
        return self.h4_forming if timeframe == "H4" else self.bars[-1].time + HOUR


class RecordingEngine(StubEngine):
    def __init__(self) -> None:
        super().__init__()
        self.higher_trends: list = []

    def process_bar(self, bar, higher_trend=None):
        self.higher_trends.append(higher_trend)
        return super().process_bar(bar)


class HigherTimeframeTraderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.broker = HigherTimeframeBroker()
        self.engine = RecordingEngine()
        self.now = [T0 + 3 * HOUR + timedelta(seconds=5)]

    def test_warmup_loads_higher_bars_and_passes_trend(self) -> None:
        trader = make_trader(self.broker, self.engine, self.now, higher_timeframe="H4")
        trader.start()
        self.assertEqual(len(trader.higher), 3)
        self.assertEqual(len(self.engine.higher_trends), 3)
        self.assertTrue(all(t is not None for t in self.engine.higher_trends))

    def test_waits_for_higher_bar_that_closes_with_base_bar(self) -> None:
        trader = make_trader(self.broker, self.engine, self.now, higher_timeframe="H4")
        trader.start()
        # H1 03:00 đóng lúc 04:00 = lúc H4 00:00 đóng, nhưng MT5 chưa có H4 00:00 -> chờ.
        self.broker.bars.append(RawBar(T0 + 3 * HOUR, 100.0, 101.0, 99.0, 100.0))
        self.now[0] = T0 + 4 * HOUR + timedelta(seconds=2)
        self.assertFalse(trader.poll())
        self.assertEqual(len(self.engine.higher_trends), 3)
        self.broker.h4.append(RawBar(T0, 100.0, 101.0, 99.0, 100.0))
        self.broker.h4_forming = T0 + 4 * HOUR
        self.assertTrue(trader.poll())
        self.assertEqual(len(trader.higher), 4)
        self.assertEqual(len(self.engine.higher_trends), 4)

    def test_gives_up_waiting_after_timeout(self) -> None:
        trader = make_trader(self.broker, self.engine, self.now, higher_timeframe="H4")
        trader.start()
        self.broker.bars.append(RawBar(T0 + 3 * HOUR, 100.0, 101.0, 99.0, 100.0))
        self.now[0] = T0 + 4 * HOUR + timedelta(seconds=2)
        self.assertFalse(trader.poll())
        self.now[0] += timedelta(seconds=200)
        self.assertTrue(trader.poll())


if __name__ == "__main__":
    unittest.main()


class ResolveSymbolTests(unittest.TestCase):
    def test_suffix_symbol_of_broker_is_found(self) -> None:
        names = ["XAUUSD247m", "XAUUSDm", "XAUEURm"]
        fake = SimpleNamespace(
            symbol_info=lambda n: object() if n in names else None,
            symbols_get=lambda pattern: [SimpleNamespace(name=n) for n in names
                                         if n.startswith(pattern.rstrip("*"))],
        )
        self.assertEqual(resolve_symbol(fake, "XAUUSD"), "XAUUSDm")
        self.assertEqual(resolve_symbol(fake, "XAUUSDm"), "XAUUSDm")
        self.assertEqual(resolve_symbol(fake, "BTCUSD"), "BTCUSD")
