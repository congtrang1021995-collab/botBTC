"""Lớp mỏng quanh thư viện ``MetaTrader5``: lấy nến, đặt / sửa / đóng lệnh.

Chỉ chạy trên Windows, cần MT5 đang mở và đã đăng nhập. Thư viện được import khi
khởi tạo để phần còn lại của bot (và test trên CI) không phụ thuộc vào nó.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

TIMEFRAME_MINUTES = {"M1": 1, "M5": 5, "M15": 15, "M30": 30, "H1": 60, "H4": 240, "D1": 1440}
NEW_YORK = ZoneInfo("America/New_York")
RETCODE_DONE = 10009


@dataclass(frozen=True, slots=True)
class RawBar:
    time: datetime  # UTC, giờ mở nến
    open: float
    high: float
    low: float
    close: float


@dataclass(frozen=True, slots=True)
class BrokerPosition:
    ticket: int
    side: str  # "LONG" / "SHORT"
    volume: float
    price_open: float
    sl: float
    tp: float
    comment: str


@dataclass(frozen=True, slots=True)
class OrderResult:
    ok: bool
    ticket: int | None = None
    price: float | None = None
    message: str = ""


class Mt5Broker:
    def __init__(self, symbol: str, server_tz: str = "auto", deviation: int = 20) -> None:
        import MetaTrader5 as mt5

        self.mt5 = mt5
        if not mt5.initialize():
            raise RuntimeError(f"Không kết nối được MT5: {mt5.last_error()}")
        info = mt5.symbol_info(symbol)
        if info is None or not mt5.symbol_select(symbol, True):
            raise RuntimeError(f"MT5 không có mã {symbol}")
        self.symbol = symbol
        self.digits = info.digits
        self.point = info.point
        self.stops_level = info.trade_stops_level * info.point
        self.deviation = deviation
        self.filling = (
            mt5.ORDER_FILLING_FOK if info.filling_mode & 1
            else mt5.ORDER_FILLING_IOC if info.filling_mode & 2
            else mt5.ORDER_FILLING_RETURN
        )
        self.server_tz = self._detect_server_tz() if server_tz == "auto" else server_tz

    # ---- thông tin chung -------------------------------------------------
    def account_line(self) -> str:
        acc = self.mt5.account_info()
        return (f"{acc.login} {acc.server} số dư {acc.balance:.2f} {acc.currency} "
                f"(giờ server: {self.server_tz})")

    def algo_trading_enabled(self) -> bool:
        return bool(self.mt5.terminal_info().trade_allowed)

    def round_price(self, price: float) -> float:
        return round(price, self.digits)

    def bid_ask(self) -> tuple[float, float]:
        tick = self.mt5.symbol_info_tick(self.symbol)
        return tick.bid, tick.ask

    # ---- giờ server -> UTC ------------------------------------------------
    def _detect_server_tz(self) -> str:
        """Exness chạy UTC+0; MetaQuotes-Demo và đa số broker dùng giờ New York + 7."""
        tick = self.mt5.symbol_info_tick(self.symbol)
        now = datetime.now(timezone.utc)
        if tick is not None and abs(tick.time - now.timestamp()) < 6 * 3600:
            offset = round((tick.time - now.timestamp()) / 3600)
            ny7 = round(now.astimezone(NEW_YORK).utcoffset().total_seconds() / 3600) + 7
            if offset == 0:
                return "utc"
            if offset == ny7:
                return "ny7"
            return f"{offset:+d}"
        server = self.mt5.account_info().server.lower()
        return "utc" if "exness" in server else "ny7"

    def to_utc(self, server_epoch: int) -> datetime:
        naive = datetime(1970, 1, 1) + timedelta(seconds=server_epoch)
        if self.server_tz == "utc":
            return naive.replace(tzinfo=timezone.utc)
        if self.server_tz == "ny7":
            return (naive - timedelta(hours=7)).replace(tzinfo=NEW_YORK).astimezone(timezone.utc)
        return (naive - timedelta(hours=int(self.server_tz))).replace(tzinfo=timezone.utc)

    # ---- nến --------------------------------------------------------------
    def _tf(self, timeframe: str) -> int:
        return getattr(self.mt5, f"TIMEFRAME_{timeframe}")

    def closed_bars(self, timeframe: str, count: int) -> list[RawBar]:
        """``count`` nến đã đóng gần nhất, cũ trước (bỏ nến đang chạy ở vị trí 0)."""
        rates = self.mt5.copy_rates_from_pos(self.symbol, self._tf(timeframe), 1, count)
        if rates is None:
            raise RuntimeError(f"Không lấy được nến {timeframe}: {self.mt5.last_error()}")
        return [
            RawBar(self.to_utc(int(r["time"])), float(r["open"]), float(r["high"]),
                   float(r["low"]), float(r["close"]))
            for r in rates
        ]

    def forming_bar_open(self, timeframe: str) -> datetime | None:
        rates = self.mt5.copy_rates_from_pos(self.symbol, self._tf(timeframe), 0, 1)
        return self.to_utc(int(rates[0]["time"])) if rates is not None and len(rates) else None

    # ---- lệnh -------------------------------------------------------------
    def positions(self, magic: int) -> dict[int, BrokerPosition]:
        rows = self.mt5.positions_get(symbol=self.symbol) or ()
        return {
            p.ticket: BrokerPosition(
                p.ticket, "LONG" if p.type == self.mt5.POSITION_TYPE_BUY else "SHORT",
                p.volume, p.price_open, p.sl, p.tp, p.comment,
            )
            for p in rows if p.magic == magic
        }

    def open_market(self, side: str, volume: float, sl: float, tp: float,
                    magic: int, comment: str) -> OrderResult:
        bid, ask = self.bid_ask()
        request = {
            "action": self.mt5.TRADE_ACTION_DEAL,
            "symbol": self.symbol,
            "volume": volume,
            "type": self.mt5.ORDER_TYPE_BUY if side == "LONG" else self.mt5.ORDER_TYPE_SELL,
            "price": ask if side == "LONG" else bid,
            "sl": self.round_price(sl),
            "tp": self.round_price(tp),
            "deviation": self.deviation,
            "magic": magic,
            "comment": comment[:31],
            "type_time": self.mt5.ORDER_TIME_GTC,
            "type_filling": self.filling,
        }
        result = self._send(request)
        if not result.ok:
            return result
        # Lệnh market trả về ticket order; position cùng số ticket trong tài khoản hedging.
        for _ in range(10):
            for ticket, pos in self.positions(magic).items():
                if ticket == result.ticket:
                    return OrderResult(True, ticket, pos.price_open, result.message)
            time.sleep(0.2)
        return result

    def modify_sltp(self, ticket: int, sl: float, tp: float) -> OrderResult:
        return self._send({
            "action": self.mt5.TRADE_ACTION_SLTP,
            "symbol": self.symbol,
            "position": ticket,
            "sl": self.round_price(sl),
            "tp": self.round_price(tp),
        })

    def close(self, position: BrokerPosition, magic: int, comment: str) -> OrderResult:
        bid, ask = self.bid_ask()
        return self._send({
            "action": self.mt5.TRADE_ACTION_DEAL,
            "symbol": self.symbol,
            "position": position.ticket,
            "volume": position.volume,
            "type": self.mt5.ORDER_TYPE_SELL if position.side == "LONG" else self.mt5.ORDER_TYPE_BUY,
            "price": bid if position.side == "LONG" else ask,
            "deviation": self.deviation,
            "magic": magic,
            "comment": comment[:31],
            "type_time": self.mt5.ORDER_TIME_GTC,
            "type_filling": self.filling,
        })

    def check_order(self, side: str, volume: float, sl: float, tp: float, magic: int) -> OrderResult:
        """Kiểm tra lệnh với server (ký quỹ, filling, SL/TP) mà không gửi."""
        bid, ask = self.bid_ask()
        request = {
            "action": self.mt5.TRADE_ACTION_DEAL, "symbol": self.symbol, "volume": volume,
            "type": self.mt5.ORDER_TYPE_BUY if side == "LONG" else self.mt5.ORDER_TYPE_SELL,
            "price": ask if side == "LONG" else bid, "sl": self.round_price(sl),
            "tp": self.round_price(tp), "deviation": self.deviation, "magic": magic,
            "type_time": self.mt5.ORDER_TIME_GTC, "type_filling": self.filling,
        }
        res = self.mt5.order_check(request)
        if res is None:
            return OrderResult(False, message=str(self.mt5.last_error()))
        return OrderResult(res.retcode == 0, message=f"{res.retcode} {res.comment}")

    def _send(self, request: dict) -> OrderResult:
        res = self.mt5.order_send(request)
        if res is None:
            return OrderResult(False, message=str(self.mt5.last_error()))
        ok = res.retcode == RETCODE_DONE
        return OrderResult(ok, res.order or None, res.price or None, f"{res.retcode} {res.comment}")

    def shutdown(self) -> None:
        self.mt5.shutdown()
