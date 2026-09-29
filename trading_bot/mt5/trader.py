"""Gắn Bot 2 vào tài khoản MT5: engine là nguồn đúng, lệnh trên MT5 đi theo engine.

Mỗi khi một nến đóng, nến đó được đưa vào ``TradingEngine.process_bar`` giống hệt
backtest, rồi đồng bộ:

1. Lệnh vừa gửi lúc mở nến được gắn với lệnh engine mở tại Open nến đó (khóa = giờ nến
   vào lệnh + loại setup). Engine không mở (bị hủy) thì đóng lệnh MT5.
2. Lệnh engine còn mở: SL/TP trên MT5 được đặt bằng hard stop / TP của engine
   (trailing stop dời theo). Giá đã vượt SL/TP mới thì đóng market.
3. Lệnh engine đã đóng (đảo chiều trend, stop, TP) mà MT5 còn mở thì đóng market.
4. Engine có lệnh chờ vào tại Open nến kế tiếp -> gửi lệnh market ngay, kèm SL/TP.

Stop/TP trong nến do server MT5 tự khớp. Trạng thái (ticket <-> khóa) lưu JSON nên
khởi động lại vẫn nhận lại lệnh cũ; engine được làm nóng lại từ lịch sử.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Protocol

from trading_bot.config import StrategyConfig
from trading_bot.core.engine import ProcessResult, TradingEngine
from trading_bot.core.models import Bar, PendingEntry, PositionSide, PositionState
from trading_bot.mt5.broker import BrokerPosition, OrderResult, RawBar, TIMEFRAME_MINUTES
from trading_bot.strategy.exit import calculate_take_profit_price
from trading_bot.strategy.invalidation import apply_minimum_risk

SETUP_SHORT = {"BREAKOUT_LONG": "BOL", "BREAKOUT_SHORT": "BOS",
               "VALUE_ZONE_LONG": "VZL", "VALUE_ZONE_SHORT": "VZS"}
# Chỉ vào lệnh nếu còn trong phần đầu của nến (khởi động lại muộn thì bỏ tín hiệu).
MAX_ENTRY_DELAY_FRACTION = 0.25


class Broker(Protocol):
    def closed_bars(self, timeframe: str, count: int) -> list[RawBar]: ...
    def forming_bar_open(self, timeframe: str) -> datetime | None: ...
    def positions(self, magic: int) -> dict[int, BrokerPosition]: ...
    def bid_ask(self) -> tuple[float, float]: ...
    def open_market(self, side: str, volume: float, sl: float, tp: float,
                    magic: int, comment: str) -> OrderResult: ...
    def modify_sltp(self, ticket: int, sl: float, tp: float) -> OrderResult: ...
    def close(self, position: BrokerPosition, magic: int, comment: str) -> OrderResult: ...
    def round_price(self, price: float) -> float: ...


def magic_for(timeframe: str) -> int:
    return 902_000 + TIMEFRAME_MINUTES[timeframe]


@dataclass
class LiveTrader:
    broker: Broker
    timeframe: str
    volume: float = 0.1
    warmup_bars: int = 3000
    state_path: Path | None = None
    log_path: Path | None = None
    dry_run: bool = False
    config: StrategyConfig | None = None
    now: Callable[[], datetime] = lambda: datetime.now(timezone.utc)
    say: Callable[[str], None] = print
    magic: int = field(init=False)
    engine: TradingEngine = field(init=False)
    bar_times: list[datetime] = field(init=False, default_factory=list)
    # ticket -> {"signal": iso giờ nến tín hiệu, "setup": tên, "key": khóa hoặc None}
    tickets: dict[int, dict] = field(init=False, default_factory=dict)
    sent_signals: set[str] = field(init=False, default_factory=set)

    def __post_init__(self) -> None:
        self.magic = magic_for(self.timeframe)
        self.engine = TradingEngine(self.config)
        self._load_state()

    # ---- vòng đời ----------------------------------------------------------
    def start(self) -> None:
        bars = self.broker.closed_bars(self.timeframe, self.warmup_bars)
        for raw in bars:
            self._process(raw)
        state = self.engine.state.strategy
        self.say(f"[{self.timeframe}] làm nóng {len(bars)} nến "
                 f"{_fmt(bars[0].time)} → {_fmt(bars[-1].time)}, trend={state.trend.name}, "
                 f"lệnh engine đang mở={len(state.open_positions)}")
        for position in state.open_positions:
            self.say(f"[{self.timeframe}]   engine: {self._describe(position)}")
        self._sync(after_new_bar=True)
        self._save_state()

    def poll(self) -> bool:
        """Xử lý các nến vừa đóng; trả True nếu có nến mới."""
        last = self.bar_times[-1]
        fresh: list[RawBar] = []
        for count in (5, 50, 500):
            fresh = [b for b in self.broker.closed_bars(self.timeframe, count) if b.time > last]
            if len(fresh) < count:
                break
        if not fresh:
            return False
        for raw in fresh:
            result = self._process(raw)
            self._log_bar(result)
            self.say(self._status(result))
            for event in result.events:
                self.say(f"[{self.timeframe}]   >> {event.name} "
                         f"{json.dumps(event.payload, ensure_ascii=False, default=str)}")
        self._sync(after_new_bar=True)
        self._save_state()
        return True

    # ---- engine ------------------------------------------------------------
    def _process(self, raw: RawBar) -> ProcessResult:
        bar = Bar(index=len(self.bar_times), open=raw.open, high=raw.high, low=raw.low,
                  close=raw.close, timestamp=raw.time)
        self.bar_times.append(raw.time)
        return self.engine.process_bar(bar)

    def _key(self, position: PositionState) -> str:
        setup = position.source_setup.name if position.source_setup else "-"
        return f"{self.bar_times[position.entry_bar_index].isoformat()}|{setup}"

    # ---- đồng bộ engine -> MT5 ----------------------------------------------
    def _sync(self, after_new_bar: bool) -> None:
        strategy = self.engine.state.strategy
        engine_open = {self._key(p): p for p in strategy.open_positions}
        broker = self.broker.positions(self.magic)
        last_bar = self.bar_times[-1]
        step = timedelta(minutes=TIMEFRAME_MINUTES[self.timeframe])

        # Lệnh MT5 đã tự đóng (server khớp SL/TP) hoặc bị đóng tay.
        for ticket in [t for t in self.tickets if t not in broker]:
            info = self.tickets.pop(ticket)
            self._event("BROKER_POSITION_GONE", ticket=ticket, **info)

        for ticket, info in list(self.tickets.items()):
            position = broker[ticket]
            if info.get("key") is None:
                entry_time = datetime.fromisoformat(info["signal"]) + step
                key = f"{entry_time.isoformat()}|{info['setup']}"
                if key in engine_open:
                    info["key"] = key
                    self._event("BOUND", ticket=ticket, key=key)
                elif entry_time <= last_bar:
                    # Nến vào lệnh đã đóng mà engine không mở lệnh -> engine hủy.
                    self._close(position, "ENGINE_CANCELLED_ENTRY")
                    continue
                else:
                    continue  # nến vào lệnh chưa đóng
            engine_position = engine_open.get(info["key"])
            if engine_position is None:
                self._close(position, "ENGINE_CLOSED")
                continue
            self._mirror_stops(position, engine_position)

        for ticket, position in broker.items():
            if ticket not in self.tickets:
                self._event("UNKNOWN_BROKER_POSITION", ticket=ticket, side=position.side,
                            note="lệnh cùng magic không có trong state, bot không động vào")

        pending = strategy.pending_entry
        if after_new_bar and pending is not None:
            self._maybe_enter(pending, last_bar, step)

    def _mirror_stops(self, position: BrokerPosition, engine_position: PositionState) -> None:
        sl = self.broker.round_price(engine_position.hard_stop_price)
        tp = self.broker.round_price(engine_position.take_profit_price)
        if abs(sl - position.sl) < 1e-9 and abs(tp - position.tp) < 1e-9:
            return
        bid, ask = self.broker.bid_ask()
        # Giá hiện tại đã vượt mốc mới -> không đặt được SL/TP, đóng như engine sẽ làm.
        if position.side == "LONG" and not (sl < bid < tp):
            self._close(position, "PRICE_BEYOND_ENGINE_STOP_OR_TP")
            return
        if position.side == "SHORT" and not (tp < ask < sl):
            self._close(position, "PRICE_BEYOND_ENGINE_STOP_OR_TP")
            return
        if self.dry_run:
            self._event("DRY_MODIFY", ticket=position.ticket, sl=sl, tp=tp)
            return
        result = self.broker.modify_sltp(position.ticket, sl, tp)
        self._event("MODIFY_SLTP" if result.ok else "MODIFY_FAILED", ticket=position.ticket,
                    old_sl=position.sl, sl=sl, old_tp=position.tp, tp=tp, msg=result.message)

    def _maybe_enter(self, pending: PendingEntry, last_bar: datetime, step: timedelta) -> None:
        signal_index = pending.signal_bar_index
        signal_time = self.bar_times[signal_index]
        signal_iso = signal_time.isoformat()
        if signal_index != len(self.bar_times) - 1 or signal_iso in self.sent_signals:
            return
        setup = pending.source_setup.name
        side = pending.side
        late = self.now() - (signal_time + step)
        if late > step * MAX_ENTRY_DELAY_FRACTION:
            self._event("ENTRY_SKIPPED_LATE", signal=signal_iso, setup=setup,
                        late_seconds=int(late.total_seconds()))
            self.sent_signals.add(signal_iso)
            return
        if pending.hard_stop_price is None:
            self._event("ENTRY_SKIPPED_NO_STOP", signal=signal_iso, setup=setup)
            return
        bid, ask = self.broker.bid_ask()
        price = ask if side == PositionSide.LONG else bid
        cfg = self.engine.config
        sl = apply_minimum_risk(side, price, pending.hard_stop_price, cfg.min_initial_risk)
        try:
            tp = calculate_take_profit_price(side, price, sl, cfg.take_profit_r_multiple)
        except ValueError:
            self._event("ENTRY_SKIPPED_PRICE_BEYOND_STOP", signal=signal_iso, setup=setup,
                        price=price, stop=sl)
            self.sent_signals.add(signal_iso)
            return
        self.sent_signals.add(signal_iso)
        comment = f"bot2 {self.timeframe} {SETUP_SHORT.get(setup, setup)}"
        if self.dry_run:
            self._event("DRY_ENTRY", side=side.value, setup=setup, price=price, sl=sl, tp=tp,
                        volume=self.volume)
            return
        result = self.broker.open_market(side.value, self.volume, sl, tp, self.magic, comment)
        if result.ok and result.ticket is not None:
            self.tickets[result.ticket] = {"signal": signal_iso, "setup": setup, "key": None}
            self._event("ENTRY_SENT", ticket=result.ticket, side=side.value, setup=setup,
                        fill=result.price, sl=sl, tp=tp, volume=self.volume, msg=result.message)
        else:
            self._event("ENTRY_FAILED", side=side.value, setup=setup, sl=sl, tp=tp,
                        msg=result.message)

    def _close(self, position: BrokerPosition, reason: str) -> None:
        if self.dry_run:
            self._event("DRY_CLOSE", ticket=position.ticket, reason=reason)
            return
        result = self.broker.close(position, self.magic, f"bot2 {self.timeframe} {reason}"[:31])
        if result.ok:
            self.tickets.pop(position.ticket, None)
        self._event("CLOSE" if result.ok else "CLOSE_FAILED", ticket=position.ticket,
                    reason=reason, price=result.price, msg=result.message)

    # ---- lưu trạng thái / log ------------------------------------------------
    def _load_state(self) -> None:
        if self.state_path is None or not self.state_path.exists():
            return
        data = json.loads(self.state_path.read_text(encoding="utf-8"))
        self.tickets = {int(k): v for k, v in data.get("tickets", {}).items()}
        self.sent_signals = set(data.get("sent_signals", []))

    def _save_state(self) -> None:
        if self.state_path is None or self.dry_run:
            return
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        recent = sorted(self.sent_signals)[-200:]
        self.state_path.write_text(json.dumps(
            {"timeframe": self.timeframe, "magic": self.magic,
             "tickets": {str(k): v for k, v in self.tickets.items()},
             "sent_signals": recent}, ensure_ascii=False, indent=2), encoding="utf-8")

    def _event(self, name: str, **payload) -> None:
        self.say(f"[{self.timeframe}] ** {name} "
                 f"{json.dumps(payload, ensure_ascii=False, default=str)}")
        self._append({"type": "action", "tf": self.timeframe, "name": name,
                      "at": self.now().isoformat(), **payload})

    def _log_bar(self, result: ProcessResult) -> None:
        bar = result.context.bar
        self._append({"type": "bar", "tf": self.timeframe, "time": bar.timestamp.isoformat(),
                      "open": bar.open, "high": bar.high, "low": bar.low, "close": bar.close,
                      "trend": result.state.trend.name,
                      "open_positions": len(result.state.open_positions),
                      "events": [{"name": e.name, **e.payload} for e in result.events]})

    def _append(self, row: dict) -> None:
        if self.log_path is None:
            return
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")

    def _status(self, result: ProcessResult) -> str:
        bar, ind = result.context.bar, result.context.indicators
        ema = (f"EMA34={ind.ema_fast:.2f} EMA89={ind.ema_slow:.2f}"
               if ind.ema_fast is not None and ind.ema_slow is not None else "")
        setups = ",".join(s.name for s in sorted(result.state.active_setups, key=int)) or "-"
        return (f"[{self.timeframe}] {_fmt(bar.timestamp)} close={bar.close:.2f} {ema} "
                f"trend={result.state.trend.name} setup={setups} "
                f"lệnh engine={len(result.state.open_positions)} lệnh MT5={len(self.tickets)}")

    def _describe(self, position: PositionState) -> str:
        setup = position.source_setup.name if position.source_setup else "-"
        return (f"{position.side.value} {setup} vào {_fmt(self.bar_times[position.entry_bar_index])} "
                f"@{position.entry_price:.2f} SL={position.hard_stop_price:.2f} "
                f"TP={position.take_profit_price:.2f}")


LOCAL_TZ = timezone(timedelta(hours=7))


def _fmt(value: datetime) -> str:
    return value.astimezone(LOCAL_TZ).strftime("%Y-%m-%d %H:%M")
