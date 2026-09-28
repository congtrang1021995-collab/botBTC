"""Chạy Bot 2 trên dữ liệu realtime (chỉ theo dõi tín hiệu, không đặt lệnh)."""

from trading_bot.live.monitor import LiveMonitor, run_forever

__all__ = ["LiveMonitor", "run_forever"]
