"""Chart Trade Explorer live: giá Binance cập nhật liên tục + Bot2 tính lại mỗi khi nến đóng.

    python data/chart_template/live_server.py                 # BTCUSDT Futures H1, http://localhost:8765
    python data/chart_template/live_server.py --market spot --interval 15m --port 8800

- Trình duyệt nhận nến đang chạy trực tiếp từ WebSocket Binance (dự phòng: hỏi server mỗi 2 giây).
- Server tải lịch sử một lần, sau đó cứ ~20 giây kiểm tra nến mới đóng; có nến mới thì chạy lại
  backtest Bot2 bằng code hiện tại và trang tự nạp lệnh mới, giữ nguyên khung nhìn.
Chỉ theo dõi — không đặt lệnh thật.
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
import webbrowser
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from build_chart import TEMPLATE, build_payload  # noqa: E402
from trading_bot.data.binance import (  # noqa: E402
    BASE_URLS,
    INTERVAL_MS,
    fetch_klines,
    http_get_json,
    klines_to_bars,
)

LIVE_JS = HERE / "live.js"
# Futures: luồng kline nằm ở /market/ws (đường /ws cũ vẫn kết nối nhưng không gửi kline).
WS_BASE = {"spot": "wss://stream.binance.com:9443/ws", "futures": "wss://fstream.binance.com/market/ws"}
TF_LABEL = {"1h": "H1", "2h": "H2", "4h": "H4", "1d": "D1"}


class LiveFeed:
    def __init__(self, symbol: str, interval: str, market: str, start: datetime) -> None:
        self.symbol, self.interval, self.market = symbol, interval, market
        self.source = f"Binance {'Futures' if market == 'futures' else 'Spot'} (live)"
        self.lock = threading.Lock()
        self.wake = threading.Event()
        self.version = 0
        self.payload_json = b""
        print(f"Đang tải lịch sử {symbol} {interval} {market} từ {start:%Y-%m-%d}...", flush=True)
        self.klines = fetch_klines(symbol, interval, market=market, start=start)
        if not self.klines:
            raise SystemExit("Binance không trả về nến nào.")
        self._rebuild()

    def _rebuild(self) -> None:
        began = time.perf_counter()
        payload = build_payload(klines_to_bars(self.klines))
        payload["src"] = self.source
        data = json.dumps(payload, ensure_ascii=True, separators=(",", ":")).encode()
        with self.lock:
            self.version += 1
            self.payload_json = data
        last = self.klines[-1]
        opened = sum(1 for trade in payload["trades"] if trade.get("open"))
        print(f"[{_now()}] nến đóng gần nhất {_local(last.open_time)} close={last.close:,.2f} · "
              f"{len(payload['trades'])} lệnh ({opened} đang mở) · backtest {time.perf_counter() - began:.1f}s",
              flush=True)

    def poll_forever(self, every: float = 20.0) -> None:
        while True:
            self.wake.wait(every)
            self.wake.clear()
            try:
                start = self.klines[-1].open_time + timedelta(milliseconds=INTERVAL_MS[self.interval])
                new = fetch_klines(self.symbol, self.interval, market=self.market, start=start)
                new = [k for k in new if k.open_time > self.klines[-1].open_time]
                if new:
                    self.klines.extend(new)
                    self._rebuild()
            except Exception as exc:  # mạng chập chờn: thử lại ở vòng sau
                print(f"[{_now()}] lỗi lấy dữ liệu: {exc}", flush=True)

    def forming_kline(self) -> dict:
        url = f"{BASE_URLS[self.market]}?symbol={self.symbol}&interval={self.interval}&limit=1"
        row = http_get_json(url, retries=1)[0]
        return {"time": int(row[0]) // 1000, "open": float(row[1]), "high": float(row[2]),
                "low": float(row[3]), "close": float(row[4])}

    def page(self) -> bytes:
        tf = TF_LABEL.get(self.interval, self.interval)
        label = f"{self.symbol}{'.P' if self.market == 'futures' else ''}"
        with self.lock:
            data = self.payload_json.decode()
        html = (TEMPLATE.read_text(encoding="utf-8")
                .replace("__TITLE__", f"{label} {tf} Bot2 Live")
                .replace("__SYMBOL__", label)
                .replace("__TF__", tf)
                .replace("__DATA_JSON__", data))
        config = json.dumps({"symbol": self.symbol, "interval": self.interval,
                             "ws": f"{WS_BASE[self.market]}/{self.symbol.lower()}@kline_{self.interval}",
                             "version": self.version})
        return (html + f"\n<script>window.LIVE_CONFIG={config};</script>\n"
                f"<script>{LIVE_JS.read_text(encoding='utf-8')}</script>\n").encode("utf-8")


def make_handler(feed: LiveFeed):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            path = self.path.split("?")[0]
            try:
                if path == "/":
                    self._send(feed.page(), "text/html; charset=utf-8")
                elif path == "/api/version":
                    with feed.lock:
                        body = json.dumps({"version": feed.version}).encode()
                    self._send(body, "application/json")
                elif path == "/api/data":
                    with feed.lock:
                        body = b'{"version":%d,"data":%s}' % (feed.version, feed.payload_json)
                    self._send(body, "application/json")
                elif path == "/api/tick":
                    self._send(json.dumps(feed.forming_kline()).encode(), "application/json")
                elif path == "/api/refresh":
                    feed.wake.set()
                    self._send(b"{}", "application/json")
                else:
                    self.send_error(404)
            except (BrokenPipeError, ConnectionResetError):
                pass
            except Exception as exc:
                self.send_error(502, str(exc))

        def _send(self, body: bytes, content_type: str) -> None:
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args) -> None:  # tắt log từng request
            pass

    return Handler


def _now() -> str:
    return datetime.now(timezone(timedelta(hours=7))).strftime("%H:%M:%S")


def _local(value: datetime) -> str:
    return value.astimezone(timezone(timedelta(hours=7))).strftime("%Y-%m-%d %H:%M")


def main() -> None:
    parser = argparse.ArgumentParser(description="Chart Bot2 live với giá Binance.")
    parser.add_argument("symbol", nargs="?", default="BTCUSDT")
    parser.add_argument("--interval", default="1h", choices=sorted(INTERVAL_MS))
    parser.add_argument("--market", default="futures", choices=["spot", "futures"])
    parser.add_argument("--start", default="2025-01-01", help="Ngày bắt đầu lịch sử (UTC).")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true", help="Không tự mở trình duyệt.")
    args = parser.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    start = datetime.fromisoformat(args.start).replace(tzinfo=timezone.utc)
    feed = LiveFeed(args.symbol.upper(), args.interval, args.market, start)
    threading.Thread(target=feed.poll_forever, daemon=True).start()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(feed))
    url = f"http://localhost:{args.port}/"
    print(f"Chart live: {url}  (Ctrl+C để dừng)", flush=True)
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Đã dừng.")


if __name__ == "__main__":
    main()
