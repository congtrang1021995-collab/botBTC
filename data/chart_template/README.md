# Chart mẫu — Trade Explorer

Mẫu chuẩn để xem kết quả backtest trên biểu đồ nến. Dùng cho mọi mã và mọi lần chạy.

- `template.html`: giao diện (Lightweight Charts 4.2.0 từ jsDelivr), có placeholder
  `__TITLE__`, `__SYMBOL__`, `__TF__`, `__DATA_JSON__`.
- `build_chart.py`: chạy lại backtest bằng code hiện tại và xuất một file HTML độc lập.

## Chạy

```bash
python data/chart_template/build_chart.py "Dữ liệu/XAU" --symbol XAU/USD --tf H1
python data/chart_template/build_chart.py "Dữ liệu/BTC" --symbol BTC/USD
python data/chart_template/build_chart.py outputs/xau_combined_2025-01_to_2026-09.csv --symbol XAU/USD --out outputs/xau.html
```

Đầu vào có thể là một hoặc nhiều file CSV, hoặc một thư mục (lấy mọi `*.csv` theo tên,
nến trùng thời gian bị bỏ qua). Mặc định file ra nằm ở
`outputs/<mã>-<khung>-trade-explorer.html`.

## Chế độ live

`live_server.py` phục vụ cùng `template.html` ở `http://localhost:8765`, thêm `live.js`
để nhận nến đang chạy từ WebSocket Binance. Mỗi khi nến đóng, server chạy lại backtest và
gọi `window.TradeChart.update(data)` để thay dữ liệu tại chỗ, giữ nguyên khung nhìn. Bản
tĩnh (`build_chart.py`) không nạp `live.js`; dùng `--source` để ghi nguồn giá lên trang.
Luồng kline của Binance Futures nằm ở `wss://fstream.binance.com/market/ws/...`: đường
`/ws` cũ vẫn kết nối được nhưng không gửi kline.

## Nội dung chart

- Nến, EMA34 (xanh dương), EMA89 (cam).
- Mỗi lệnh: vùng xanh Entry→TP, vùng đỏ Entry→SL ban đầu, nét chấm xám là Entry,
  nét đứt bậc thang là trailing stop thực tế theo từng nến (stop chốt ở Close nến trước,
  có hiệu lực từ nến sau).
- Mũi tên ▲/▼ là điểm vào, chấm tròn là điểm thoát (xanh thắng / đỏ thua / xám hòa).
- Zoom/kéo dãn, xem nhanh 1N/1T/1Th/3Th, nhảy tới ngày, UTC+7 ↔ UTC, bật/tắt từng lớp,
  danh sách lệnh lọc theo setup/kết quả/lý do thoát, phím ←/→ để duyệt lệnh.

## Lưu ý kỹ thuật

- Vùng TP/SL được vẽ bằng series primitive, không dùng line series — line series nối liền
  các lệnh với nhau qua khoảng trống.
- `timeScale().logicalToCoordinate()` chỉ nhận index nguyên; nửa nến phải tự cộng/trừ
  bằng nửa khoảng cách giữa hai nến.
