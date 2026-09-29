"""Chạy Bot 2 tự đặt lệnh trên MT5 đang mở (tài khoản đang đăng nhập).

    python -m trading_bot.mt5                          # XAUUSD, H1 + M15, 0.1 lot
    python -m trading_bot.mt5 --tf H1 --volume 0.01
    python -m trading_bot.mt5 --dry-run                # chỉ in lệnh sẽ đặt, không gửi
    python -m trading_bot.mt5 --check                  # làm nóng, kiểm tra lệnh thử rồi thoát

Mỗi khung dùng một magic number riêng (H1=902060, M15=902015); bot không động vào
lệnh đặt tay hoặc của magic khác. Mỗi khung lọc lệnh theo trend khung kế trên
(M15 <- H1, H1 <- H4; ``--no-higher-filter`` để tắt). Trạng thái và log nằm ở ``outputs/mt5_live/``.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from trading_bot.core.higher_tf import HIGHER_TIMEFRAME
from trading_bot.mt5.broker import TIMEFRAME_MINUTES, Mt5Broker
from trading_bot.mt5.trader import LiveTrader

OUT_DIR = Path("outputs/mt5_live")


def main() -> None:
    parser = argparse.ArgumentParser(description="Bot 2 tự đặt lệnh trên MetaTrader 5.")
    parser.add_argument("symbol", nargs="?", default="XAUUSD")
    parser.add_argument("--tf", nargs="+", default=["H1", "M15"], choices=sorted(TIMEFRAME_MINUTES))
    parser.add_argument("--volume", type=float, default=0.1, help="Khối lượng mỗi lệnh (lot).")
    parser.add_argument("--warmup", type=int, default=3000, help="Số nến lịch sử làm nóng engine.")
    parser.add_argument("--server-tz", default="auto", help="auto | utc | ny7 | +3 ...")
    parser.add_argument("--dry-run", action="store_true", help="Không gửi lệnh, chỉ in.")
    parser.add_argument("--check", action="store_true", help="Làm nóng + kiểm tra lệnh thử rồi thoát.")
    parser.add_argument("--no-higher-filter", action="store_true",
                        help="Tắt lọc theo trend khung lớn (M15 <- H1, H1 <- H4).")
    parser.add_argument("--poll", type=float, default=2.0, help="Giây giữa hai lần kiểm tra nến.")
    args = parser.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    broker = Mt5Broker(args.symbol, server_tz=args.server_tz)
    print("Tài khoản:", broker.account_line())
    if not broker.algo_trading_enabled() and not args.dry_run:
        print("!! Nút Algo Trading trong MT5 đang TẮT: lệnh sẽ bị từ chối. Bấm nút "
              "'Algo Trading' trên thanh công cụ MT5 (chuyển sang xanh).")

    prefix = OUT_DIR / f"{broker.symbol}"  # tên mã thực của sàn (Exness: XAUUSDm)
    traders = [
        LiveTrader(
            broker, tf, volume=args.volume, warmup_bars=args.warmup, dry_run=args.dry_run,
            state_path=Path(f"{prefix}_{tf}_state.json"),
            log_path=Path(f"{prefix}_{tf}_log.jsonl"),
            higher_timeframe=None if args.no_higher_filter else HIGHER_TIMEFRAME.get(tf),
        )
        for tf in args.tf
    ]
    mode = "DRY-RUN (không gửi lệnh)" if args.dry_run else "ĐẶT LỆNH THẬT"
    filters = ", ".join(f"{t.timeframe}<-{t.higher_timeframe}" for t in traders if t.higher_timeframe)
    print(f"{broker.symbol} {' + '.join(args.tf)} | {args.volume} lot/lệnh | {mode}"
          f" | lọc trend khung lớn: {filters or 'tắt'}")

    if args.check:
        # Chỉ đọc: không gửi lệnh, không ghi state.
        for trader in traders:
            trader.dry_run = True
            trader.start()
        bid, ask = broker.bid_ask()
        print("Kiểm tra lệnh thử (order_check, không gửi):")
        print("  BUY :", broker.check_order("LONG", args.volume, ask - 20, ask + 200, traders[0].magic).message)
        print("  SELL:", broker.check_order("SHORT", args.volume, bid + 20, bid - 200, traders[0].magic).message)
        broker.shutdown()
        return

    for trader in traders:
        trader.start()
    print("Đang chờ nến đóng... (Ctrl+C để dừng; lệnh đang mở vẫn giữ SL/TP trên server)")
    try:
        while True:
            for trader in traders:
                try:
                    trader.poll()
                except Exception as exc:  # mất kết nối tạm thời: thử lại vòng sau
                    print(f"[{trader.timeframe}] lỗi: {exc!r}")
            time.sleep(args.poll)
    except KeyboardInterrupt:
        print("Đã dừng.")
    finally:
        broker.shutdown()


if __name__ == "__main__":
    main()
