# Investment System Bot 2 (bot mới, rule đang xây)

Đây là bot duy nhất của dự án. Bot 2 xuất phát từ bản sao của bot gốc ngày 2026-09-24
(spec v1.5, Pine v3.2); bot gốc đã được xóa ngày 2026-09-29. Các chỗ ghi "bot gốc" trong
tài liệu chỉ mô tả rule cũ để so sánh.

Mọi lệnh bên dưới chạy từ trong thư mục `bot2/`. Dữ liệu giá tải thủ công nằm ở
`Dữ liệu/` (chỉ trên máy, không đưa lên GitHub), ví dụ:

```bash
python -m trading_bot.backtest "Dữ liệu/XAU/XAU-USD_1Hour_BID_2025-01-01_to_2025-01-31_Etc_UTC.csv"
```

```bash
python data/chart_template/build_chart.py "Dữ liệu/XAU" --symbol XAU/USD --tf H1
```

**Dữ liệu Binance thực tế** (API public, không cần key; mặc định BTCUSDT H1 Spot,
thêm `--market futures` để dùng USDT-M Futures). Chỉ lấy nến đã đóng.

```bash
python -m trading_bot.data BTCUSDT --interval 1h --days 365
```

Lệnh trên lưu `data/binance/btcusdt_1h_spot.csv`, dùng thẳng cho backtest và chart.
Theo dõi tín hiệu realtime: engine làm nóng bằng 1000 nến gần nhất, rồi mỗi khi có nến
đóng thì in trend/setup/sự kiện. Chế độ này **không đặt lệnh thật**; `--log` ghi sự kiện
ra JSONL, còn `--once` chỉ in trạng thái hiện tại.

```bash
python -m trading_bot.live BTCUSDT --interval 1h --log outputs/live_btcusdt_1h.jsonl
```

**Chart live** (Trade Explorer với giá cập nhật liên tục): bấm đúp `live_chart.bat` hoặc
chạy lệnh dưới, trình duyệt mở `http://localhost:8765`. Mặc định BTCUSDT Futures H1 từ
2025-01-01. Nến đang chạy và EMA tạm tính nhảy theo WebSocket Binance (bị chặn thì tự
chuyển sang REST mỗi 2 giây). Mỗi khi nến đóng, Bot2 chạy lại bằng code hiện tại và
danh sách lệnh tự cập nhật. Chỉ theo dõi, không đặt lệnh.

```bash
python data/chart_template/live_server.py --market futures --interval 1h
```

**Chart live trên GitHub Pages** (https://congtrang1021995-collab.github.io/botBTC/): không cần
server. Trình duyệt người xem tự tải nến Binance Futures, chạy chính code Python Bot2 bằng
Pyodide (`web/worker.js`) và nhận giá realtime qua WebSocket; nến đóng thì Bot2 tính lại. Mỗi
lần push lên `main`, GitHub Actions chạy test, dựng `_site/` bằng `web/build_site.py` rồi
đăng lên Pages, nên sửa rule xong push là trang dùng rule mới. Nút **Khung** (5p / 15p /
1h / 4h / Ngày) đổi khung ngay trong trang và chạy Bot2 trên chính khung đó.

Tính sẵn (seed): mỗi lần deploy và mỗi ngày lúc 09:30 giờ VN, `web/build_seeds.py` tải lịch sử
từ data.binance.vision rồi chạy Bot2 bằng CPython. Kết quả gồm dữ liệu chart (`seed/*.json`) và
trạng thái Bot2 (`seed/*.pkl`, pickle của `IncrementalChart`, xem
`data/chart_template/incremental.py`). Lịch sử seed: 270 ngày cho 5p, 1000 ngày cho 15p, từ
2020 cho 1h / 4h / Ngày. Trình duyệt tải seed, hiện chart ngay rồi chỉ tính thêm các nến sau
seed. Dữ liệu chart và trạng thái Bot2 của từng khung được lưu trong IndexedDB, nên lần sau mở
lại hiện ngay. Seed và bản lưu gắn với mã phiên bản code, nên code đổi thì tự tính lại. Nếu không
có seed (tải lỗi, hoặc `?start=` sớm hơn seed), trang tải nến song song rồi chạy Bot2 từ đầu
trong trình duyệt. Lịch sử dự phòng khi đó: 30 ngày cho 5p, 90 ngày cho 15p, từ 2025 cho 1h, từ
2022 cho 4h, từ đầu cho Ngày. Pickle chỉ nạp được khi Actions dùng cùng phiên bản Python với
Pyodide (3.13). Tham số URL tùy chọn:
`?symbol=ETHUSDT&interval=4h&market=spot&start=2025-06-01`. Người xem cần truy cập được
Binance (bị chặn ở Mỹ). Xem thử trên máy: `python web/build_site.py` rồi
`python -m http.server 8766 --directory _site`.

**MetaTrader 5 (đặt lệnh thật trên tài khoản đang đăng nhập)** — cần Windows, MT5 đang mở
và `python -m pip install MetaTrader5 pandas`. Tải nến ra CSV (giờ đổi về UTC, chỉ nến đã
đóng; nhớ đặt `Tools → Options → Charts → Max bars = Unlimited`):

```bash
python exness_mt5_fetch.py XAUUSD --tf H1 --start 2025-01-01
```

Bot tự giao dịch: bấm đúp `mt5_bot.bat` (XAUUSD, H1 + M15, 0.1 lot) hoặc chạy lệnh dưới.
Nút **Algo Trading** trong MT5 phải bật. Mỗi nến đóng, engine Bot2 chạy giống backtest và
lệnh MT5 đi theo engine: có lệnh chờ thì vào market ngay đầu nến kế tiếp kèm SL (1R tối
thiểu) và TP 10R; sau đó SL/TP trên MT5 được đặt bằng hard stop / trailing / TP của engine;
engine đóng lệnh (đảo chiều trend…) thì đóng market. Mỗi khung một magic number (H1=902060,
M15=902015), không động vào lệnh đặt tay. Lệnh engine đã mở từ trước khi bật bot không được
vào bù. Trạng thái và log ở `outputs/mt5_live/`; tắt bật lại vẫn nhận lại lệnh cũ.

```bash
python -m trading_bot.mt5 XAUUSD --tf H1 M15 --volume 0.1
```

`--check` làm nóng rồi kiểm tra lệnh thử bằng `order_check` (không gửi), `--dry-run` chạy
liên tục nhưng chỉ in lệnh sẽ đặt. Mỗi khung tự lấy nến khung kế trên để lọc lệnh theo trend
(M15 <- H1, H1 <- H4); `--no-higher-filter` để tắt.

**Chart Vàng dùng nến MT5** — mở MT5 rồi bấm đúp `mt5_feed.bat` (`python mt5_feed.py XAUUSD`):
cầu nối đọc nến XAUUSD từ MT5 (giờ đổi về UTC), dựng trang chart và tự mở
http://127.0.0.1:8770/?symbol=XAUUSDT&interval=15m; giá cập nhật mỗi giây. Để cửa sổ đó mở là
xem được, không cần bật lại mỗi lần tải trang. Trang GitHub Pages `?symbol=XAUUSDT` cũng gọi cầu
nối này nhưng nhiều trình duyệt chặn trang công khai gọi vào 127.0.0.1, nên dùng địa chỉ local.
`&feed=binance` để dùng lại XAUUSDT Futures của Binance. Nến MT5 không có seed tính sẵn: lần đầu
Bot2 chạy trong trình duyệt, sau đó lưu IndexedDB.

**Điều kiện mới đã chốt**

- 2026-09-24 — Step 1 v1.6: độ dốc EMA34 (OLS) trên 13 nến gần nhất phải cùng chiều
  trend, áp cho cả xác nhận trend mới và duy trì trend; không thỏa thì `SIDEWAY`.
  Input `confirm_slope_length=13` (Python) / `n2` (Pine); ban đầu 7, đổi thành 13 cùng
  ngày sau khi soát BTC H1 (7 nến làm mất trend ngay khi giá kéo về EMA34). Rule cũ giữ nguyên.
- 2026-09-24 — Step 1 v1.6 (bổ sung): độ dốc so với một **mốc cố định**
  `min_confirm_slope` (đơn vị giá/nến, từng mặc định `5` cho BTC H1). Ngưỡng theo ATR
  (`0.06 × ATR`) đã bỏ cùng ngày.
- 2026-09-25 — Step 1 v1.7: `min_confirm_slope` mặc định **0** (chỉ xét dấu độ dốc 13
  nến, không cần mốc 5; input vẫn giữ để thử) và `k` pivot nâng **3 → 5** nến mỗi bên
  (`pivot_legs=5`, Pine `k`). Các step khác giữ nguyên.
- 2026-09-24 — Step 4: giữ rule **đảo chiều trend thì đóng lệnh** tại Close
  (`exit_on_trend_reversal=True`, Pine: `Thoát lệnh khi trend đảo chiều`); trend về
  SIDEWAY không đóng lệnh (`exit_on_trend_loss=False` mặc định, bật để đóng cả khi
  SIDEWAY như bot gốc). Lý do thoát mới: `TREND_REVERSAL_CLOSE_EXIT`.
- 2026-09-24 — Step 3/6: tối đa 2 lệnh nắm giữ, mỗi loại setup (Breakout / Value
  Zone) 1 lệnh. `max_trades_per_setup_family=1` (Pine: `Số lệnh mở tối đa mỗi loại
  setup`); đặt `0` để bỏ giới hạn. Slot xét sau khi lệnh bị stop/TP trong nến đã đóng.
- 2026-09-28 — Step 3: Value Zone đã xác nhận (Close lấy lại EMA) nhưng slot Value Zone
  đầy thì xóa trạng thái chờ, không vào muộn khi slot trống; cần setup Value Zone mới.
  Trước đây mốc EMA được giữ và có thể bắn lệnh nhiều giờ sau (vd. BTC 15p 27/08/2026,
  1R gấp ~4 lần bình thường).
- 2026-09-28 — Step 4: **1R tối thiểu 10 giá** (`min_initial_risk=10`, Pine `1R tối thiểu`).
  Giá khớp cách hard stop dưới 10 thì nới stop ra đúng 10; TP 10R và trailing theo 1R mới.
  Khối lượng vẫn cố định (không đổi theo 1R). Đặt `0` để tắt.
- 2026-09-29 — Step 1 v1.8: **bỏ điều kiện độ dốc EMA34 13 nến** (`use_confirm_slope=False`
  mặc định, Pine `Dùng điều kiện độ dốc n2` tắt). Trend quay về rule cũ với `k=5`. Backtest
  MT5 XAUUSD 2025-01→2026-09: H1 +33.4R → +58.6R, M15 +24.6R → +78.3R; điều kiện này chỉ
  làm trend về SIDEWAY nhiều hơn và cắt lệnh Value Zone, không giúp đóng lệnh sớm hơn.
- 2026-09-29 — Step 3 v1.9: **lọc tín hiệu theo trend khung lớn** — M15 lọc theo H1, H1 lọc
  theo H4, kiểu lỏng (`higher_tf_filter="lenient"`: bỏ khi khung lớn ngược hướng, SIDEWAY vẫn
  vào). Backtest MT5 XAUUSD: M15 +78.3R → +139.8R, H1 +58.6R → +74.6R. Áp dụng ở backtest
  (`--higher`), bot MT5, chart live (15m/1h) và Pine.

---

Phần dưới đây kế thừa README của bot gốc, mô tả rule đang chạy trong code này.

Implementation Python theo kiến trúc module cho hệ thống trong
`01_TRADING_BOT_SPEC.md`. File `02_TRADING_BOT.pine` được giữ làm bản đối chiếu
trực quan trên TradingView.

## Trạng thái

- Step 1 — Trend: đã triển khai, kèm bộ lọc duy trì trend (spec mục 8.1). Uptrend
  chỉ mất khi `EMA34 < EMA89`, downtrend chỉ mất khi `EMA34 > EMA89`; hai EMA bằng
  nhau chưa làm mất trend và Close phá Protected Swing tạm thời không làm đổi trend.
  **Bot 2 (v1.6–v1.7, tắt mặc định từ v1.8 — `use_confirm_slope=False`):** điều kiện độ dốc EMA34 trên 13 nến gần nhất
  (`confirm_slope_length=13`) phải cùng chiều trend ở cả xác nhận và duy trì; dốc bằng 0
  hoặc ngược chiều thì `SIDEWAY`. Mốc `min_confirm_slope` mặc định 0 (chỉ xét dấu), đặt > 0
  để đòi dốc vượt mốc. Pivot dùng `pivot_legs=5`. Điều kiện này không tắt được bằng
  `require_trend_maintenance_filter=False`.
  Tắt bộ lọc EMA bằng
  `require_trend_maintenance_filter=False` (Python) hoặc bỏ chọn `Chỉ giữ trend khi
  EMA34/EMA89 chưa cắt ngược` (Pine); khi đó Step 1 tiếp tục giữ trend hiện tại.
- Step 2 — Setup: đã triển khai.
- Step 3 — Entry: Value Zone chờ Close lấy lại EMA đã ghi nhớ; Breakout xác nhận
  khi setup chuyển `FALSE -> TRUE`. Cả hai vào lệnh tại Open nến kế tiếp. Mỗi tín
  hiệu hợp lệ mở một giao dịch độc lập. **Bot 2:** mỗi loại setup chỉ giữ 1 lệnh
  đang mở, nên tối đa 2 lệnh (1 Breakout + 1 Value Zone); tín hiệu của loại đã có
  lệnh mở bị bỏ qua (Value Zone bị bỏ qua thì xóa luôn trạng thái chờ). Không còn dùng stop-entry tại đỉnh/đáy nến xác nhận ± 1 tick.
- Step 4 — Invalidation: đã triển khai hard stop. **Bot 2 đóng lệnh tại Close khi trend
  đảo chiều** (`exit_on_trend_reversal=True`); trend về SIDEWAY không đóng lệnh
  (`exit_on_trend_loss=False` mặc định, bật để đóng như bot gốc).
  **Bot 2:** 1R tối thiểu 10 giá — stop sát hơn được nới ra khi khớp lệnh (`min_initial_risk`).
  Rule thoát riêng khi Close phá Protected Swing đã đóng băng hiện tạm thời bị vô
  hiệu hóa. Stop được dời theo lợi nhuận: vượt 1R về Entry, vượt 2R lên +1R,
  vượt 3R lên +2R, ... vượt 9R lên +8R (Bot 2, 2026-09-28: vượt nR -> +(n-1)R,
  n = 1..9). Tắt quy tắc mất trend bằng
  `exit_on_trend_loss=False`.
- Step 5 — Position Size: mặc định `fixed_quantity` — mọi lệnh cùng một khối lượng.
  Có sẵn `fixed_risk` (suy khối lượng từ `risk_per_trade_fraction` và khoảng cách từ
  giá Open thực tế tới hard stop) nhưng chưa bật.
- Step 6 — Multiple Entries: cho phép giao dịch cùng chiều chồng nhau trong giới
  hạn **tối đa 2 lệnh, mỗi loại setup 1 lệnh** (Bot 2). Mỗi giao dịch giữ riêng giá
  vào, stop, TP, khối lượng và P&L; module Add vẫn không tự tăng khối lượng của
  một giao dịch cũ.
- Step 7 — Exit: Take Profit cố định 10R (Bot 2, 2026-09-28; trước đó 5R) tính từ giá Open thực tế của nến vào
  lệnh; không chốt từng phần.
- Step 8 — Backtest & P&L: sổ giao dịch, P&L bằng tiền, R-multiple, max drawdown
  theo R, cùng bộ thống kê tỷ lệ lệnh (win rate, loss rate, lãi/lỗ trung bình,
  payoff ratio, expectancy, chuỗi thắng/thua dài nhất) và bảng tách theo loại setup,
  theo hướng lệnh, theo lý do thoát.
- Step 9 — Historical Data: đã đọc được CSV OHLC và xuất summary JSON/trade log.
- Backtest không tính phí giao dịch và trượt giá.
- Chưa đặt lệnh thật.

## Kiến trúc

```text
trading_bot/
  config.py
  core/
    models.py
    indicators.py
    swings.py
    engine.py
  strategy/
    trend.py
    setup.py
    entry.py
    invalidation.py
    position_size.py
    add.py
    exit.py
  backtest/
    runner.py
    metrics.py
tests/
```

`TradingEngine` là nơi duy nhất commit state. Mỗi module strategy là hàm thuần:
nhận context/state và trả decision. `BarContext` chỉ tồn tại cho nến hiện tại;
`StrategyState` được giữ xuyên suốt quá trình chạy.

## Chạy test

```bash
python -m unittest discover -s tests -v
```

Project hiện chỉ dùng Python standard library.

## Chạy backtest với CSV

File đầu vào cần các cột `open,high,low,close`; có thể thêm `timestamp` theo
ISO-8601 và `volume`.

```bash
python -m trading_bot.backtest data.csv --trades-out trades.csv
python -m trading_bot.backtest data/mt5/MetaQuotes-Demo_XAUUSD_M15.csv --higher data/mt5/MetaQuotes-Demo_XAUUSD_H1.csv
```

Summary được in dạng JSON. Tham số `--trades-out` là tùy chọn. `--higher` là CSV nến khung lớn
để lọc lệnh theo trend (M15 dùng H1, H1 dùng H4); bỏ trống thì không lọc.

## Dùng trên TradingView

`02_TRADING_BOT.pine` là một strategy duy nhất và chỉ chiếm một suất chỉ báo trên
biểu đồ. EMA 34, EMA 89 và ATR 13 đã được tính ngay trong strategy;
không cần thêm chỉ báo rời. Với gói Basic, hãy xóa các EMA rời trước khi thêm bot.

Bar Magnifier được tắt vì dữ liệu khung nhỏ dùng cho tính năng này yêu cầu gói
TradingView cao hơn. Strategy vẫn mô phỏng lệnh theo dữ liệu OHLC của khung thời
gian đang mở.

Từ bản `v2.8 Basic`, tín hiệu được xác nhận tại Close và market order khớp tại
Open nến kế tiếp. `calc_on_order_fills` được bật để lấy giá khớp thực tế, sau đó
tính 1R/TP và đặt bracket stop/TP.

Bản `v2.9 Basic` thêm trailing stop theo ba mốc 0,5R / 1R / 1,2R. `1R` luôn
được đo từ Entry tới hard stop ban đầu; stop mới được tính khi nến đóng và có hiệu
lực từ nến kế tiếp.

Bản `v3.0 Basic` nâng TP lên 2,6R và thay trailing bằng hai mốc: vượt 1R đưa
stop về Entry, vượt 2R đưa stop lên +1R.

Bản `v3.1 Basic` nâng TP lên 5R và nối dài trailing: vượt 3R đưa stop lên +2R,
vượt 4R đưa stop lên +3R; hai mốc 1R và 2R được giữ nguyên.

Bản `v3.2 Basic` cho phép mỗi tín hiệu hợp lệ mở thêm một giao dịch cùng chiều.
Mỗi giao dịch dùng ID, hard stop, trailing stop và TP riêng; Pine đặt giới hạn
pyramiding mặc định là 100 giao dịch mở cùng chiều.

Bản `v2.5 Basic` từng thêm mô hình khối lượng theo rủi ro và trần gap; trần gap đã
được loại bỏ ở v2.8 khi chuyển sang Entry tại Open nến kế tiếp.
Bản `v2.6 Basic` thêm quy tắc thoát lệnh khi mất trend.

Lưu ý TradingView: market order phải nhận quantity trước khi Open nến kế tiếp tồn
tại. Vì vậy chế độ `% vốn` trong Pine ước tính quantity bằng Close nến xác nhận;
Python tính chính xác quantity từ Open thực tế. Mô hình `fixed_quantity` khớp hoàn
toàn giữa hai bản.

Phí giao dịch và trượt giá nằm ở tab Properties của strategy trên TradingView.
Backtest Python không mô phỏng phí, nên hai bên chỉ khớp khi để Properties bằng 0.

Hai đường EMA tích hợp được hiển thị mặc định. Có thể tắt chúng bằng tùy chọn
`Hiện EMA 34/89 tích hợp` mà không làm thay đổi logic giao dịch.
