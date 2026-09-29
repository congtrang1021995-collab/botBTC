"""Cầu nối nến MT5 cho trang Bot2 Live: mở http://127.0.0.1:8770/?symbol=XAUUSDT&interval=15m

    python mt5_feed.py                 # XAUUSD trên MT5 đang mở, cổng 8770
    python mt5_feed.py XAUUSDm --port 8770

Trả nến đúng dạng REST kline Binance ([open_ms, o, h, l, c, volume, close_ms], giờ UTC) để
web/app.js dùng chung code. Chạy trên máy có MT5 đang mở và đã đăng nhập.
Cầu nối phục vụ luôn trang chart (dựng _site/ bằng web/build_site.py) để trang và dữ liệu cùng
địa chỉ: trình duyệt chặn trang GitHub Pages gọi vào 127.0.0.1 (Local Network Access, adblock).
    GET /info                                   tài khoản, mã, giờ server
    GET /klines?interval=15m&startTime=<ms>&limit=1500
    GET /klines?interval=15m&limit=1            nến đang chạy
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
from datetime import datetime, timedelta, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from trading_bot.mt5.broker import Mt5Broker

ROOT = Path(__file__).resolve().parent
SITE = ROOT / "_site"

INTERVALS = {"1m": "M1", "5m": "M5", "15m": "M15", "30m": "M30", "1h": "H1", "4h": "H4", "1d": "D1"}
MINUTES = {"M1": 1, "M5": 5, "M15": 15, "M30": 30, "H1": 60, "H4": 240, "D1": 1440}


class Feed:
    def __init__(self, broker: Mt5Broker) -> None:
        self.broker = broker
        self.lock = threading.Lock()   # thư viện MetaTrader5 không an toàn khi gọi song song

    def info(self) -> dict:
        with self.lock:
            acc = self.broker.mt5.account_info()
        return {"symbol": self.broker.symbol, "server": acc.server, "login": acc.login,
                "server_tz": self.broker.server_tz, "digits": self.broker.digits}

    def klines(self, interval: str, start_ms: int | None, limit: int) -> list[list]:
        tf = INTERVALS[interval]
        mt5, code = self.broker.mt5, self.broker._tf(tf)
        with self.lock:
            if start_ms is None:
                rates = mt5.copy_rates_from_pos(self.broker.symbol, code, 0, limit)
            else:
                # MT5 hiểu mốc là giờ server (>= UTC) nên lấy dư vài nến đầu rồi lọc theo UTC.
                start = datetime.fromtimestamp(start_ms / 1000, tz=timezone.utc)
                span = timedelta(minutes=MINUTES[tf] * (limit + 1)) + timedelta(days=4)
                rates = mt5.copy_rates_range(self.broker.symbol, code, start, start + span)
        if rates is None:
            raise RuntimeError(f"MT5 không trả nến {tf}: {mt5.last_error()}")
        out, step = [], MINUTES[tf] * 60_000
        for r in rates:
            t = int(self.broker.to_utc(int(r["time"])).timestamp() * 1000)
            if start_ms is None or t >= start_ms:
                out.append([t, float(r["open"]), float(r["high"]), float(r["low"]), float(r["close"]),
                            int(r["tick_volume"]), t + step - 1])
        return out[:limit]


def make_handler(feed: Feed):
    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs) -> None:
            super().__init__(*args, directory=str(SITE), **kwargs)

        def end_headers(self) -> None:
            if not self.path.startswith(("/info", "/klines")):
                self.send_header("Cache-Control", "no-cache")
            super().end_headers()

        def _send(self, code: int, body: object) -> None:
            data = json.dumps(body, separators=(",", ":")).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Private-Network", "true")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_OPTIONS(self) -> None:  # preflight của Chrome (Private/Local Network Access)
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET")
            self.send_header("Access-Control-Allow-Headers", "*")
            self.send_header("Access-Control-Allow-Private-Network", "true")
            self.end_headers()

        def do_GET(self) -> None:
            url = urlparse(self.path)
            q = {k: v[0] for k, v in parse_qs(url.query).items()}
            try:
                if url.path == "/info":
                    self._send(200, feed.info())
                elif url.path == "/klines":
                    interval = q.get("interval", "1h")
                    if interval not in INTERVALS:
                        return self._send(400, {"error": f"interval {interval} không hỗ trợ"})
                    start = int(q["startTime"]) if "startTime" in q else None
                    limit = max(1, min(int(q.get("limit", 1500)), 5000))
                    self._send(200, feed.klines(interval, start, limit))
                else:
                    super().do_GET()
            except Exception as exc:
                self._send(500, {"error": str(exc)})

        def log_message(self, *args) -> None:
            pass

    return Handler


def main() -> None:
    parser = argparse.ArgumentParser(description="Cầu nối nến MT5 cho trang Bot2 Live.")
    parser.add_argument("symbol", nargs="?", default="XAUUSD")
    parser.add_argument("--port", type=int, default=8770)
    parser.add_argument("--no-browser", action="store_true", help="Không tự mở trình duyệt.")
    parser.add_argument("--server-tz", default="auto", help="auto | utc | ny7 | +3 ...")
    args = parser.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    sys.path.insert(0, str(ROOT / "web"))
    import build_site
    build_site.build(SITE)
    feed = Feed(Mt5Broker(args.symbol, server_tz=args.server_tz))
    print("Tài khoản:", feed.broker.account_line())
    server = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(feed))
    link = f"http://127.0.0.1:{args.port}/?symbol=XAUUSDT&interval=15m"
    print(f"Nến MT5 {args.symbol} — mở chart: {link}  (đóng cửa sổ này để dừng)")
    if not args.no_browser:
        import webbrowser
        webbrowser.open(link)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        feed.broker.shutdown()


if __name__ == "__main__":
    main()
