# Dữ liệu backtest

Đặt file CSV dữ liệu giá vào thư mục này, rồi chạy:

```bash
python -m trading_bot.backtest data/<tên file>.csv --trades-out data/<tên file>-trades.csv
```

Xem lệnh trên biểu đồ nến bằng chart mẫu (chi tiết ở `data/chart_template/README.md`):

```bash
python data/chart_template/build_chart.py "Dữ liệu/XAU" --symbol XAU/USD --tf H1
```

## Yêu cầu tối thiểu

File cần có dòng tiêu đề và bốn cột `open,high,low,close` (không phân biệt hoa thường).
Cột thời gian là tùy chọn nhưng nên có — chấp nhận các tên `timestamp`, `time`, `date`,
`datetime`, và các định dạng ISO-8601 (`2026-01-02`, `2026-01-02T09:15:00+07:00`) hoặc
Unix epoch (giây hoặc mili giây). Mọi cột thừa đều được bỏ qua, nên file xuất thẳng từ
TradingView dùng được luôn.

Dòng phải xếp theo thời gian tăng dần, cũ trước mới sau.

## Xuất từ TradingView

Mở chart đúng mã và đúng khung thời gian, chọn biểu tượng mũi tên xuống ở góc trên bên
phải (Export chart data), chọn khoảng thời gian rồi tải file .csv về và bỏ vào đây.

## Lưu ý về bước giá

`StrategyConfig.minimum_tick` phải khớp với bước giá thật của mã đang test, vì giá kích
hoạt lệnh chờ là "đỉnh nến + 1 tick". Mặc định là 0.01.
