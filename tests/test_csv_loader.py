from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from trading_bot.backtest import load_bars_csv


class CsvLoaderTests(unittest.TestCase):
    @staticmethod
    def _load(content: str):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bars.csv"
            path.write_text(content, encoding="utf-8")
            return load_bars_csv(path)

    def test_loads_ohlc_with_optional_timestamp_and_volume(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bars.csv"
            path.write_text(
                "timestamp,open,high,low,close,volume\n"
                "2026-01-01T09:00:00+07:00,100,105,99,104,1000\n"
                "2026-01-01T10:00:00+07:00,104,108,103,107,1200\n",
                encoding="utf-8",
            )

            bars = load_bars_csv(path)

        self.assertEqual(len(bars), 2)
        self.assertEqual(bars[0].index, 0)
        self.assertEqual(bars[1].index, 1)
        self.assertEqual(bars[1].close, 107.0)
        self.assertIsNotNone(bars[0].timestamp)

    def test_rejects_missing_ohlc_column(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bars.csv"
            path.write_text("open,high,close\n100,105,104\n", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "missing required columns: low"):
                load_bars_csv(path)

    def test_rejects_duplicate_or_out_of_order_timestamp(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bars.csv"
            path.write_text(
                "timestamp,open,high,low,close\n"
                "2026-01-01T10:00:00,100,105,99,104\n"
                "2026-01-01T09:00:00,104,108,103,107\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "must increase strictly"):
                load_bars_csv(path)

    def test_tradingview_export_columns_are_accepted(self) -> None:
        # Cột thời gian tên "time", giá trị Unix epoch, kèm cột chỉ báo thừa.
        bars = self._load(
            "time,open,high,low,close,Volume,EMA34\n"
            "1704153600,100.0,101.0,99.0,100.5,1000,\n"
            "1704240000,100.5,102.0,100.0,101.5,1200,100.2\n"
        )

        self.assertEqual(len(bars), 2)
        self.assertEqual(bars[0].timestamp.year, 2024)
        self.assertEqual(bars[1].close, 101.5)

    def test_space_separated_datetime_is_accepted(self) -> None:
        bars = self._load(
            "date,open,high,low,close\n"
            "2026-01-02 09:15:00,100.0,101.0,99.0,100.5\n"
            "2026-01-02 09:30:00,100.5,102.0,100.0,101.5\n"
        )

        self.assertEqual(len(bars), 2)
        self.assertEqual(bars[0].timestamp.hour, 9)


if __name__ == "__main__":
    unittest.main()
