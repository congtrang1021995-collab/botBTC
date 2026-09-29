# TRADING BOT 2 — SPECIFICATION (BẢN NHÁP)

> **Trạng thái: rule đang xây.** File này được sao chép từ spec v1.5 của bot gốc ngày
> 2026-09-24 để làm điểm xuất phát. Bot 2 giữ toàn bộ rule cũ và bổ sung từng điều kiện
> mới; mỗi điều kiện được chốt sẽ được cập nhật vào code và test tương ứng.
>
> Đã chốt (2026-09-24) — **Step 1 v1.6**: thêm điều kiện bắt buộc *độ dốc EMA34 trong
> 13 nến gần nhất phải cùng chiều trend* và *vượt một mốc tối thiểu cố định*; dốc ít hoặc
> ngược chiều thì `SIDEWAY` (mục 4.1, 8.1, 9–11).
>
> Cập nhật 2026-09-24: `n2` đổi từ 7 → **13** nến sau khi soát BTC H1 (cửa sổ 7 nến làm
> EMA34 "phẳng" ngay khi giá kéo về EMA34 nên Value Zone gần như không còn vào lệnh).
>
> Cập nhật 2026-09-24 (lần 2): bỏ ngưỡng theo ATR. Mốc độ dốc là một số cố định theo đơn vị
> giá/nến (`min_confirm_slope`), từng đặt mặc định 5 cho BTC H1.
>
> Cập nhật 2026-09-25 — **Step 1 v1.7**: `min_confirm_slope` mặc định **0** (chỉ xét dấu
> độ dốc 13 nến, không cần mốc 5; input vẫn giữ để thử nghiệm) và `k` nâng từ 3 → **5**
> nến mỗi bên khi xác nhận pivot (mục 2, 4.1, 6). Các step khác giữ nguyên.
>
> Đã chốt (2026-09-24) — **Step 4**: giữ rule **đảo chiều trend thì đóng lệnh** tại
> Close (`exit_on_trend_reversal = true`); trend về `SIDEWAY` không đóng lệnh
> (`exit_on_trend_loss = false` mặc định, mục 26).
>
> Đã chốt (2026-09-24) — **Step 3/6**: tối đa 2 lệnh nắm giữ, mỗi loại setup
> (Breakout, Value Zone) 1 lệnh (`max_trades_per_setup_family = 1`, mục 20, 27).
>
> Cập nhật 2026-09-28 — **Step 4/7**: TP nâng từ 5R lên **10R**
> (`take_profit_r_multiple = 10`); trailing nối dài tới 9 bậc: vượt `nR` thì stop lên
> `(n-1)R`, n = 1..9 (vượt 9R lên +8R) (mục 20.1, 25.1, 29).
>
> Cập nhật 2026-09-28 — **Step 3**: Value Zone đã xác nhận nhưng bị chặn vì slot Value Zone
> đầy thì **xóa trạng thái chờ và EMA tham chiếu**; không chờ slot trống rồi vào muộn. Muốn
> vào lại phải có Value Zone Setup mới (mục 21, 28).
>
> Cập nhật 2026-09-28 — **Step 4**: **1R tối thiểu 10 giá** (`min_initial_risk = 10`). Khi
> khớp lệnh mà giá khớp cách hard stop nhỏ hơn mốc thì nới stop ra đúng mốc; TP 10R và
> trailing tính theo 1R mới. Khối lượng vẫn cố định, không đổi theo 1R (mục 25).
>
> Cập nhật 2026-09-29 — **Step 1 v1.8**: **bỏ điều kiện độ dốc EMA34 13 nến** (mặc định
> `use_confirm_slope = false`, Pine input `Dùng điều kiện độ dốc n2` tắt). Trend quay về rule
> cũ v1.5 với `k = 5`: duy trì chỉ cần `EMA34 >= EMA89` (mục 4.1, 8.1). Lý do: backtest MT5
> XAUUSD 2025-01→2026-09 — ở bước xác nhận điều kiện không có tác dụng (điều kiện 8 nến đã bao
> hàm), ở bước duy trì làm ~45% số nến thành `SIDEWAY` và cắt lệnh Value Zone. H1: +33.4R →
> +58.6R; M15: +24.6R → +78.3R; thời gian giữ lệnh / đóng lệnh khi đảo chiều không chậm hơn.
>
> Cập nhật 2026-09-29 — **Step 3 v1.9**: **lọc tín hiệu theo trend khung lớn** — M15 lọc theo
> H1, H1 lọc theo H4, kiểu **lỏng** (`higher_tf_filter = "lenient"`): bỏ tín hiệu khi trend nến
> khung lớn đã đóng **ngược hướng**; khung lớn `SIDEWAY` vẫn vào (mục 22.1). Backtest MT5 XAUUSD
> 2025-01→2026-09: M15 +78.3R → +139.8R (DD 27.0 → 17.6R), H1 +58.6R → +74.6R (DD 18.6 → 15.3R).

## Step 1–3 — Trend, Setup & Entry v1.9 (Bot 2)

Tài liệu này là file đặc tả trung tâm của bot. Các bước tiếp theo sẽ được bổ sung tuần tự vào chính file này theo thứ tự:

1. Trend
2. Setup
3. Entry
4. Invalidation
5. Position Size
6. Add
7. Exit
8. Backtest & P&L
9. Historical Data Input

File code đi kèm là `02_TRADING_BOT.pine` (Pine Script v6), dùng trước hết để
quan sát và backtest trực quan trên TradingView. Step 1 phân loại trạng thái thị
trường, Step 2 phát hiện setup và Step 3 xác nhận tín hiệu để vào tại Open nến kế
tiếp. Hard stop được chốt tại nến xác nhận; 1R, TP và khối lượng theo rủi ro được
tính từ giá Open thực tế.

---

## 1. Mục tiêu

Với mỗi nến đã đóng, Step 1 trả về đúng một trong ba trạng thái:

```text
UPTREND
DOWNTREND
SIDEWAY
```

`SIDEWAY` là trạng thái mặc định khi dữ liệu chưa đủ hoặc khi không thỏa toàn bộ điều kiện của uptrend/downtrend.

## 2. Input và giá trị mặc định

| Input | Mặc định | Ý nghĩa |
|---|---:|---|
| `ema_fast_length` | 34 | Chu kỳ EMA nhanh |
| `ema_slow_length` | 89 | Chu kỳ EMA chậm |
| `n` | 8 | Số giá trị EMA34 dùng để đo slope và độ ổn định |
| `use_confirm_slope` | false | **Bot 2 (v1.8).** Bật điều kiện độ dốc `n2` nến ở mục 4.1. Mặc định tắt từ 2026-09-29 |
| `n2` (`confirm_slope_length`) | 13 | **Bot 2.** Số giá trị EMA34 gần nhất dùng đo độ dốc xác nhận bắt buộc (mục 4.1) |
| `min_confirm_slope` | 0 | **Bot 2.** Mốc độ dốc tối thiểu của EMA34, đơn vị giá mỗi nến, cố định (không theo ATR). Mặc định `0` = chỉ xét dấu (chốt 2026-09-25); đặt > 0 để đòi dốc vượt mốc (mục 4.1) |
| `k` | 5 | Số nến trái và phải dùng để xác nhận pivot (**Bot 2:** nâng từ 3 → 5 ngày 2026-09-25) |
| `min_positive_ratio` | 0.75 | Tỷ lệ delta dương tối thiểu cho uptrend |
| `min_negative_ratio` | 0.75 | Tỷ lệ delta âm tối thiểu cho downtrend |
| `require_trend_maintenance_filter` | true | Bắt buộc bộ lọc duy trì EMA khi giữ trend (mục 8.1) |

Baseline bot gốc là `n = 8`, `k = 3`; Bot 2 dùng `n = 8`, `k = 5`. Hai giá trị này vẫn là input, không khóa cứng.

Các bộ tham số gợi ý để so sánh:

| Kiểu | n | k | Kỳ vọng |
|---|---:|---:|---|
| Nhạy | 5 | 2 | Nhận trend sớm hơn, dễ nhiễu hơn |
| Cân bằng | 8 | 3 | Baseline v1 |
| Chậm/sạch | 10 | 4 | Ít flip hơn, xác nhận trễ hơn |

## 3. Quy ước dữ liệu

- Mọi quyết định dùng dữ liệu của nến đã đóng. Code strategy mặc định chỉ tính khi nến đóng (`calc_on_every_tick = false`).
- `Close`, `High`, `Low` là dữ liệu OHLC của symbol và timeframe đang mở trên TradingView.
- So sánh là so sánh nghiêm ngặt: `>` và `<`. Hai giá trị bằng nhau không tạo HH/HL/LH/LL và delta bằng 0 không được tính là tăng hoặc giảm.
- Không dùng dữ liệu tương lai. Một pivot tại nến `i` chỉ được xác nhận sau khi đã có đủ `k` nến bên phải, nên tín hiệu pivot luôn trễ `k` nến.
- Khi chưa có ít nhất hai swing high và hai swing low đã xác nhận, cấu trúc giá chưa đủ dữ liệu và kết quả là `SIDEWAY`.
- V1 không có ngưỡng dung sai theo tick, phần trăm hoặc ATR; không có giới hạn tuổi tối đa của swing; không xử lý đa khung thời gian.

## 4. EMA và linear-regression slope

```text
EMA34 = EMA(Close, 34)
EMA89 = EMA(Close, 89)
```

Slope được tính bằng hồi quy tuyến tính OLS trên đúng `n` giá trị EMA34 gần nhất. Trục `x` chạy theo thời gian từ cũ đến mới:

```text
x = 0, 1, ..., n - 1
y = EMA34 từ nến cũ nhất đến nến hiện tại

slope =
    [n × Σ(xy) - Σx × Σy]
    / [n × Σ(x²) - (Σx)²]
```

Diễn giải:

```text
slope > 0  → EMA34 có hướng tăng tổng thể
slope < 0  → EMA34 có hướng giảm tổng thể
slope = 0  → không xác nhận hướng
```

V1 chỉ kiểm tra dấu của slope, chưa chuẩn hóa slope theo giá hoặc ATR và chưa đặt `min_slope`.

### 4.1. Độ dốc xác nhận trên 13 nến (Bot 2, v1.6 → v1.7; **tắt mặc định từ v1.8**)

> **v1.8 (2026-09-29):** điều kiện này **không còn áp dụng** mặc định
> (`use_confirm_slope = false`): `Confirm_Slope_Up` và `Confirm_Slope_Down` luôn coi là thỏa,
> nên mục 8.1–11 quay về rule cũ. Phần dưới giữ lại để tham chiếu khi bật lại input.

Bot 2 tính thêm một độ dốc thứ hai bằng đúng công thức OLS ở trên nhưng trên `n2 = 13`
giá trị EMA34 gần nhất (tính cả nến hiện tại):

```text
Confirm_Slope = Linear_Regression_Slope(EMA34, n2)
Slope_Threshold = min_confirm_slope                    (mốc cố định, đơn vị giá/nến; 0 = chỉ xét dấu)

Confirm_Slope_Up   = Confirm_Slope >  Slope_Threshold
Confirm_Slope_Down = Confirm_Slope < -Slope_Threshold
```

- Đây là điều kiện **bắt buộc thêm vào**, không thay thế điều kiện nào của rule cũ.
- Áp dụng ở cả hai chỗ: xác nhận trend mới (mục 9, 10) và duy trì trend đang giữ (mục 8.1).
- **Mốc mặc định 0 — chỉ xét dấu (v1.7, 2026-09-25):** `Confirm_Slope > 0` là đủ cho
  uptrend, `< 0` cho downtrend; đúng bằng 0 là `SIDEWAY`. Input `min_confirm_slope` vẫn
  giữ: đặt > 0 thì độ dốc (đơn vị giá/nến, không theo ATR) phải vượt mốc đó, dốc ít vẫn là
  `SIDEWAY`. Lịch sử: từng dùng `0.06 × ATR(13)` rồi mốc cố định `5` cho BTC H1 (đều bỏ);
  ATR co lại khi giá đi ngang nhưng dốc co nhanh hơn, còn mốc cố định thì phụ thuộc mức giá
  từng mã nên người dùng chốt bỏ mốc.
- Không thỏa (độ dốc trong khoảng `[-Slope_Threshold, Slope_Threshold]`, ngược chiều, hoặc
  chưa đủ `n2` giá trị) thì trend là `SIDEWAY`, trừ khi nến đó đồng thời thỏa toàn bộ điều
  kiện xác nhận của trend ngược lại (mục 11).
- Slope cũ (`n = 8`) và tỷ lệ delta vẫn giữ nguyên vai trò trong `EMA_Up_Filter`/`EMA_Down_Filter`.
- Python: `IndicatorSnapshot.ema_confirm_slope`; Pine: `emaFastConfirmSlope`.

## 5. Độ ổn định của EMA34

Với `n` giá trị EMA34 có `n - 1` khoảng thay đổi:

```text
Delta_i = EMA34 mới hơn - EMA34 liền trước nó
```

```text
Positive_Delta_Ratio = Count(Delta_i > 0) / (n - 1)
Negative_Delta_Ratio = Count(Delta_i < 0) / (n - 1)
```

Delta bằng 0 vẫn nằm trong mẫu số nhưng không nằm trong tử số nào. Vì vậy một EMA đi ngang nhiều sẽ khó vượt ngưỡng 75%.

## 6. Swing High và Swing Low

Nến tại vị trí `i` là Swing High khi:

```text
High[i] > High của từng nến trong k nến bên trái
AND
High[i] > High của từng nến trong k nến bên phải
```

Nến tại vị trí `i` là Swing Low khi:

```text
Low[i] < Low của từng nến trong k nến bên trái
AND
Low[i] < Low của từng nến trong k nến bên phải
```

Nếu có một mức bằng nhau trong cửa sổ so sánh, pivot không được xác nhận. Bot lưu độc lập:

```text
Last_Swing_High
Previous_Swing_High
Last_Swing_Low
Previous_Swing_Low
```

V1 không bắt buộc swing high và swing low phải xuất hiện xen kẽ. Đây là đúng với rule đã chốt: so sánh hai swing gần nhất của từng loại.

## 7. Cấu trúc giá

```text
Higher_High = Last_Swing_High > Previous_Swing_High
Higher_Low  = Last_Swing_Low  > Previous_Swing_Low
Lower_High  = Last_Swing_High < Previous_Swing_High
Lower_Low   = Last_Swing_Low  < Previous_Swing_Low
```

```text
Confirmed_Uptrend_Structure = Higher_High AND Higher_Low
Confirmed_Downtrend_Structure = Lower_High AND Lower_Low
```

Để tránh dùng một cấu trúc cũ sau khi giá đã phá điểm bảo vệ:

```text
Valid_Confirmed_Uptrend_Structure =
    Confirmed_Uptrend_Structure
    AND Close >= Last_Swing_Low

Valid_Confirmed_Downtrend_Structure =
    Confirmed_Downtrend_Structure
    AND Close <= Last_Swing_High
```

## 8. Swing bảo vệ và duy trì trạng thái trend

HH và HL dùng để khởi tạo/xác nhận uptrend. Sau khi uptrend đã được xác nhận, bot không yêu cầu liên tục phải có HH mới.

Quy tắc cụ thể của V1:

- Khi chuyển vào `UPTREND`, `Protected_Swing_Low` được đặt bằng `Last_Swing_Low` đã xác nhận.
- Khi đang `UPTREND`, `Protected_Swing_Low` luôn được thay bằng Swing Low mới nhất ngay khi swing đó được xác nhận, kể cả khi mức mới thấp hơn mức cũ.
- `Close < Protected_Swing_Low` tạm thời không làm mất uptrend. Mức này vẫn được cập nhật theo Swing Low gần nhất và dùng cho hard stop và chẩn đoán.
- Downtrend hoàn toàn đối xứng: `Protected_Swing_High` luôn bằng Swing High được xác nhận gần nhất; `Close > Protected_Swing_High` tạm thời không làm mất downtrend.
- Sau khi trend đã được xác nhận, giá được phép hồi qua EMA và phá swing bảo vệ. Trạng thái trend chỉ bị mất theo bộ lọc EMA ở mục 8.1.

### 8.1. Bộ lọc duy trì trend

Bộ lọc xác nhận trend mới gộp hai điều kiện có bản chất khác nhau: vị trí của `Close` so với EMA, và cấu trúc giữa hai đường EMA. Nhịp hồi trong một trend lành mạnh làm hỏng điều kiện thứ nhất nhưng không được phép làm hỏng điều kiện thứ hai. Vì vậy V1.3 tách riêng một bộ lọc duy trì, nhẹ hơn bộ lọc xác nhận:

```text
EMA_Up_Maintenance_Filter = EMA34 >= EMA89
EMA_Down_Maintenance_Filter = EMA34 <= EMA89
```

Bot 2 (v1.6–v1.7, **tắt từ v1.8**) bổ sung: trend đang giữ chỉ được duy trì khi **đồng thời** bộ lọc EMA ở trên
thỏa **và** `Confirm_Slope_Up` (uptrend) / `Confirm_Slope_Down` (downtrend) thỏa (mục 4.1).
Độ dốc EMA34 trên 13 nến về 0 hoặc đổi chiều làm mất trend ngay tại nến đó, kể cả khi
`EMA34` vẫn nằm đúng phía so với `EMA89`.

- Bộ lọc duy trì không kiểm tra slope, ratio, và hoàn toàn không kiểm tra vị trí của `Close`. Giá được phép hồi xuống dưới cả EMA34 lẫn EMA89 mà trend vẫn còn, nên cả hai nhánh của Value Zone Setup ở Step 2 đều giữ nguyên hiệu lực.
- Uptrend mất chỉ khi `EMA34 < EMA89`; `EMA34 = EMA89` chưa làm mất trend. Downtrend đối xứng: chỉ mất khi `EMA34 > EMA89`.
- `require_trend_maintenance_filter = false` tắt bộ lọc EMA nhưng **không** tắt điều kiện độ dốc 13 nến của Bot 2; khi đó trend chỉ mất khi `Confirm_Slope` không còn cùng chiều.

Protected Swing vẫn được cập nhật theo cùng định nghĩa để phục vụ quản trị rủi ro, nhưng không tham gia quyết định mất trend trong cấu hình hiện tại.

## 9. Rule UPTREND

```text
EMA_Up_Filter =
    Close > EMA34
    AND EMA34 > EMA89
    AND Linear_Regression_Slope(EMA34, n) > 0
    AND Positive_Delta_Ratio >= min_positive_ratio
```

```text
Up_Structure_Pass =
    Valid_Confirmed_Uptrend_Structure
    OR
    (
        Previous_Trend = UPTREND
        AND Close >= Protected_Swing_Low
    )
```

```text
New_Uptrend_Confirmation = EMA_Up_Filter AND Up_Structure_Pass AND Confirm_Slope_Up
```

`New_Uptrend_Confirmation` dùng để khởi tạo uptrend từ `SIDEWAY`. Khi đã ở `UPTREND`, trạng thái chỉ được duy trì bằng `EMA_Up_Maintenance_Filter`; vị trí của `Close` so với EMA hoặc Protected Swing không làm mất trend.

Do `Close > EMA34 > EMA89`, không cần lặp thêm điều kiện `Close > EMA89`.

## 10. Rule DOWNTREND

```text
EMA_Down_Filter =
    Close < EMA34
    AND EMA34 < EMA89
    AND Linear_Regression_Slope(EMA34, n) < 0
    AND Negative_Delta_Ratio >= min_negative_ratio
```

```text
Down_Structure_Pass =
    Valid_Confirmed_Downtrend_Structure
    OR
    (
        Previous_Trend = DOWNTREND
        AND Close <= Protected_Swing_High
    )
```

```text
New_Downtrend_Confirmation = EMA_Down_Filter AND Down_Structure_Pass AND Confirm_Slope_Down
```

`New_Downtrend_Confirmation` dùng để khởi tạo downtrend từ `SIDEWAY`. Khi đã ở `DOWNTREND`, trạng thái chỉ được duy trì bằng `EMA_Down_Maintenance_Filter`; vị trí của `Close` so với EMA hoặc Protected Swing không làm mất trend.

## 11. Rule SIDEWAY và thứ tự quyết định

```text
IF Previous_Trend == UPTREND
    IF NOT (EMA_Up_Maintenance_Filter AND Confirm_Slope_Up)
        Trend = DOWNTREND nếu New_Downtrend_Confirmation, ngược lại SIDEWAY
    ELSE
        Trend = UPTREND

ELSE IF Previous_Trend == DOWNTREND
    IF NOT (EMA_Down_Maintenance_Filter AND Confirm_Slope_Down)
        Trend = UPTREND nếu New_Uptrend_Confirmation, ngược lại SIDEWAY
    ELSE
        Trend = DOWNTREND

ELSE
    IF New_Uptrend_Confirmation
        Trend = UPTREND
    ELSE IF New_Downtrend_Confirmation
        Trend = DOWNTREND
    ELSE
        Trend = SIDEWAY
```

Việc tách “xác nhận trend mới” và “duy trì trend đã xác nhận” loại bỏ mâu thuẫn logic giữa Step 1 và Value Zone Setup. Nếu cứ bắt `UPTREND` phải có `Close > EMA34` trên chính nến hiện tại thì `VALUE_ZONE_LONG_SETUP` với `Close <= EMA34` sẽ không bao giờ xuất hiện; chiều Short cũng tương tự.

Điều cần nới ra chỉ là vị trí của `Close` so với EMA. Điều kiện `EMA34 > EMA89` không thuộc nhóm đó: EMA34 cắt xuống dưới EMA89 nghĩa là cấu trúc trend đã đổi chứ không phải nhịp hồi. V1.2 nới cả cụm nên uptrend vẫn sống sót sau khi hai EMA đã đảo chiều, và bot có thể vào Long trong nền EMA xấu. V1.3 sửa đúng chỗ đó bằng bộ lọc duy trì ở mục 8.1.

## 12. Output của Step 1

Code Step 1 cung cấp:

- EMA34 và EMA89 trên chart.
- Dấu pivot high/low tại đúng nến pivot (xuất hiện sau độ trễ `k`).
- Màu nền cho `UPTREND`, `DOWNTREND`, `SIDEWAY`.
- Đường swing bảo vệ đang hoạt động.
- Dashboard chẩn đoán slope, ratio và HH/HL/LH/LL; series `EMA Confirm Slope (Bot 2)` trong Data Window.
- Alert khi trạng thái trend thay đổi.
- Series số `Trend State`: `1 = UPTREND`, `-1 = DOWNTREND`, `0 = SIDEWAY` trong Data Window.

Code Step 2 bổ sung marker, dashboard, alert khi setup mới xuất hiện và các series máy đọc để nối Step 3.

## 13. Kiểm thử tối thiểu trước khi chốt Step 1

1. Kiểm tra pivot chỉ xuất hiện sau đúng `k` nến và được vẽ lùi về nến pivot.
2. Kiểm tra slope dương trên dãy EMA tăng, âm trên dãy EMA giảm.
3. Kiểm tra ratio dùng mẫu số `n - 1`, bao gồm cả delta bằng 0 trong mẫu số.
4. Kiểm tra thiếu một trong HH hoặc HL thì không khởi tạo uptrend.
5. Kiểm tra uptrend vẫn tiếp tục khi `Close < Protected_Swing_Low`; kiểm tra đối xứng cho downtrend.
6. Kiểm tra uptrend vẫn được giữ khi `Close <= EMA34` và cả khi `Close <= EMA89`, miễn là `EMA34 >= EMA89`, để Value Zone Long có thể kích hoạt; kiểm tra đối xứng cho downtrend.
6b. Kiểm tra uptrend chỉ mất khi `EMA34 < EMA89`; trường hợp bằng nhau vẫn giữ trend. Kiểm tra đối xứng cho downtrend.
7. Kiểm tra phá swing bảo vệ không làm đổi trend nhưng cờ chẩn đoán và mức swing vẫn được giữ.
8. Kiểm tra toàn bộ logic đối xứng cho downtrend.
9. So sánh ba bộ `5/2`, `8/3`, `10/4` trên cùng symbol, timeframe và khoảng thời gian.
10. (Bot 2) Toàn bộ rule cũ thỏa nhưng `Confirm_Slope` bằng 0, ngược chiều hoặc thiếu dữ liệu → không khởi tạo trend, kết quả `SIDEWAY`.
11. (Bot 2) Trend đang giữ với `EMA34` vẫn đúng phía `EMA89` nhưng `Confirm_Slope` về 0 hoặc đổi chiều → `SIDEWAY` ngay nến đó; nếu nến đó thỏa toàn bộ xác nhận trend ngược lại → đổi thẳng sang trend đó.
12. (Bot 2) Điều kiện độ dốc 13 nến vẫn áp dụng khi `require_trend_maintenance_filter = false`.
13. (Bot 2) Slope xác nhận có giá trị từ nến thứ `n2` (13), slope cũ từ nến thứ 8; cửa sổ EMA34 giữ `max(n, n2)` giá trị.
14. (Bot 2) Với `min_confirm_slope = 0.2`: slope 0.15 → `SIDEWAY`, slope 0.25 → `UPTREND`, slope đúng bằng 0.2 → `SIDEWAY`; đối xứng cho downtrend; trend đang giữ mất khi slope tụt xuống dưới mốc.
15. (Bot 2) Mốc không phụ thuộc ATR: ATR chưa có vẫn xác nhận được trend; mốc = 0 chỉ xét dấu.

Khi đánh giá tham số, không chỉ nhìn lợi nhuận (Step 1 chưa có lệnh). Nên ghi nhận: số lần đổi trạng thái, độ trễ so với quan sát thủ công, thời lượng trung bình mỗi trend, và tỷ lệ nến bị phân loại `SIDEWAY`.

---

## Step 2 — Setup

### 14. Mục tiêu và quy ước

Step 2 kiểm tra hai nhóm setup, đối xứng cho Long và Short:

```text
VALUE_ZONE_SETUP
BREAKOUT_SETUP
```

Quy ước bắt buộc:

- `Close` của nến đã đóng là giá tham chiếu duy nhất. Không dùng `High`, `Low`, giá realtime hoặc râu nến để kích hoạt setup.
- `SIDEWAY = NO_TRADE`: khi `Trend == SIDEWAY`, cả bốn setup đều trả về `FALSE`.
- Step 2 chỉ phát hiện setup, chưa phải Entry và chưa đặt lệnh.
- Không có volume filter, khoảng breakout tối thiểu, ATR buffer hoặc số nến xác nhận bổ sung trong v1.
- Hai công tắc `enableValueZoneSetup` và `enableBreakoutSetup` mặc định bật chỉ phục vụ kiểm thử; chúng không thay đổi nội dung rule.

### 15. Tái sử dụng Swing/Pivot từ Step 1

Step 2 không định nghĩa lại Pivot/Swing. Hai mức dùng trong rule là alias của swing nghiêm ngặt mới nhất đã được Step 1 xác nhận:

```text
Last_Important_Swing_High = Last_Swing_High
Last_Important_Swing_Low  = Last_Swing_Low
```

Nếu mức swing cần dùng chưa tồn tại, setup tương ứng là `FALSE`. `Last_Important_Swing_High/Low` dùng để kiểm tra setup, còn `Protected_Swing_Low/High` của Step 1 dùng để duy trì hoặc vô hiệu trạng thái trend; không trộn hai vai trò này.

### 16. VALUE_ZONE_SETUP

```text
VALUE_ZONE_LONG_SETUP =
    Trend == UPTREND
    AND (Close <= EMA34 OR Close <= EMA89)
    AND Close > Last_Important_Swing_Low
```

Ý nghĩa:

- `Trend == UPTREND`: chỉ tìm cơ hội Long thuận trend đã xác nhận.
- `Close <= EMA34 OR Close <= EMA89`: giá đóng cửa đã hồi về ít nhất một trong hai vùng giá trị EMA.
- `Close > Last_Important_Swing_Low`: giá tham chiếu vẫn nằm trên Swing Low quan trọng gần nhất.

```text
VALUE_ZONE_SHORT_SETUP =
    Trend == DOWNTREND
    AND (Close >= EMA34 OR Close >= EMA89)
    AND Close < Last_Important_Swing_High
```

Ý nghĩa:

- `Trend == DOWNTREND`: chỉ tìm cơ hội Short thuận trend đã xác nhận.
- `Close >= EMA34 OR Close >= EMA89`: giá đóng cửa đã hồi về ít nhất một trong hai vùng giá trị EMA.
- `Close < Last_Important_Swing_High`: giá tham chiếu vẫn nằm dưới Swing High quan trọng gần nhất.

Rule giữ nguyên toán tử `OR` đã chốt. Do Step 1 thường có `EMA34 > EMA89` trong uptrend, điều kiện Long sẽ bắt đầu đúng khi `Close <= EMA34`; trong downtrend thường có `EMA34 < EMA89`, điều kiện Short sẽ bắt đầu đúng khi `Close >= EMA34`.

### 17. BREAKOUT_SETUP

```text
BREAKOUT_LONG_SETUP =
    Trend == UPTREND
    AND Close > Last_Important_Swing_High
```

- `Trend == UPTREND`: breakout chỉ được giao dịch Long thuận trend.
- `Close > Last_Important_Swing_High`: giá đóng cửa đã vượt Swing High quan trọng gần nhất.

```text
BREAKOUT_SHORT_SETUP =
    Trend == DOWNTREND
    AND Close < Last_Important_Swing_Low
```

- `Trend == DOWNTREND`: breakout chỉ được giao dịch Short thuận trend.
- `Close < Last_Important_Swing_Low`: giá đóng cửa đã xuyên Swing Low quan trọng gần nhất.

### 18. Output của Step 2

Code giữ riêng bốn biến Boolean để Step 3 có thể sử dụng trực tiếp:

```text
valueZoneLongSetup
valueZoneShortSetup
breakoutLongSetup
breakoutShortSetup
```

Các output tổng hợp:

```text
setupDirection:  1 = LONG, -1 = SHORT, 0 = không có setup/NO_TRADE
setupMask:       1 = VZ Long, 2 = VZ Short, 4 = Breakout Long, 8 = Breakout Short
```

Mask cho phép giữ đủ thông tin nếu hai setup cùng đúng trên một nến. Marker và alert chỉ phát một lần khi biến setup chuyển từ `FALSE` sang `TRUE`; Boolean vẫn giữ `TRUE` trong toàn bộ thời gian điều kiện còn hợp lệ.

### 19. Kiểm thử tối thiểu cho Step 2

1. Với `SIDEWAY`, xác nhận cả bốn setup luôn `FALSE` và dashboard hiện `NO_TRADE`.
2. Với uptrend còn nguyên, đưa `Close` xuống EMA34/89 nhưng vẫn trên `Last_Important_Swing_Low`; xác nhận Value Zone Long xuất hiện.
3. Kiểm tra `Close == EMA34` hoặc `Close == EMA89` vẫn đạt điều kiện Value Zone vì rule dùng `<=`/`>=`.
4. Kiểm tra `Close == Last_Important_Swing_Low/High` không đạt Value Zone vì điều kiện bảo vệ dùng `>`/`<` nghiêm ngặt.
5. Với uptrend, đóng cửa vượt `Last_Important_Swing_High`; xác nhận Breakout Long. Kiểm tra đối xứng cho Short.
6. Xác nhận râu nến vượt swing nhưng `Close` chưa vượt không kích hoạt Breakout.
7. Xác nhận Step 2 dùng đúng swing đã có từ Step 1 và không sinh thêm pivot độc lập.

## Kiến trúc implementation Python

Python là implementation chính cho module hóa, test tự động và backtest. Pine
Script tiếp tục là bản đối chiếu trực quan trên TradingView. Cả hai phải tuân theo
rule trong file đặc tả này.

### Hợp đồng chung

- `BarContext` là snapshot chỉ đọc của nến đang xử lý: OHLC, EMA, slope, ratio và
  swing đã xác nhận.
- `StrategyState` là state tồn tại xuyên các nến: trend, swing bảo vệ, tập setup
  đang active và trạng thái position.
- Chỉ `TradingEngine` được commit state. Mỗi module nhận context/state và trả về
  một decision, không tự sửa state dùng chung.
- Dữ liệu phải được đưa vào theo thứ tự tăng dần và mỗi lần gọi engine đại diện
  cho một nến đã đóng.
- Setup được lưu bằng tập cờ/bitmask, không ép thành một enum duy nhất, vì Value
  Zone và Breakout cùng hướng có thể đồng thời đúng.

### Thứ tự điều phối

```text
Closed Bar
    -> Indicators / Confirmed Swings
    -> Trend
    -> Setup
    -> Entry Confirmation
    -> Freeze Swing + Hard Stop

Next Bar Open
    -> Entry Fill
    -> Position Size + TP from Actual Open
    -> Invalidation
    -> Add
    -> Exit
    -> Commit State + Emit Events
```

Step 3–7 đã có rule được chốt bên dưới. Không module nào được tự suy diễn rule
khi rule đó chưa được chốt trong tài liệu này.

### Quy ước Invalidation cho các bước sau

Ba khái niệm phải được giữ riêng:

- `Setup Invalidation`: setup hết hiệu lực trước khi vào lệnh.
- `Trade Invalidation`: luận điểm giao dịch sai sau khi đã vào lệnh.
- `Hard Stop`: mức stop thực tế, có thể bao gồm buffer riêng.

## Step 3 — Entry

### 20. Quy ước chung

- Chỉ dùng dữ liệu của nến đã đóng để xác nhận tín hiệu.
- Mỗi tín hiệu xác nhận sinh ra một lệnh market để khớp tại `Open` của nến kế
  tiếp. Hard stop được chốt tại nến xác nhận; 1R, TP và khối lượng theo rủi ro chỉ
  được chốt khi biết giá `Open` thực tế (mục 20.1).
- `Close == EMA` hoặc `Close == Important Swing` chưa phải là xác nhận; các
  phép so sánh Entry đều nghiêm ngặt.
- Râu nến vượt EMA hoặc swing nhưng `Close` chưa vượt không có giá trị xác nhận.
- Mỗi tín hiệu chỉ tạo một Entry. Giao dịch mở thêm là giao dịch độc lập; không gộp giá vào, hard stop hoặc TP với giao dịch cũ.
- **Bot 2 — giới hạn nắm giữ:** mỗi loại setup chỉ giữ tối đa `max_trades_per_setup_family`
  (mặc định 1) lệnh đang mở, tính chung Long/Short của loại đó. Vì chỉ có hai loại setup
  (Breakout, Value Zone) nên tối đa 2 lệnh nắm giữ cùng lúc: 1 Breakout + 1 Value Zone.
  Tín hiệu mới của loại đã có lệnh mở bị bỏ qua (Value Zone đang chờ vẫn giữ trạng thái
  chờ và có thể xác nhận lại khi slot trống); tín hiệu của loại còn lại vào bình thường.
  Đặt `0` để bỏ giới hạn như bot gốc.
- Slot được xét tại `Close` nến tín hiệu **sau khi** các lệnh bị hard stop / trailing stop /
  TP trong nến đó đã đóng (Pine: Step 0 đối soát trade đóng trước Step 3; Python: engine
  loại các lệnh sẽ đóng trong nến khỏi danh sách mà Step 3 nhìn thấy). Thoát tại Close khi
  mất trend (nếu bật lại) không giải phóng slot trong cùng nến.
- Nếu Value Zone và Breakout cùng xác nhận một hướng trên một nến, Breakout được
  ưu tiên và chỉ tạo một Entry. Nếu slot Breakout đã đầy, Value Zone được vào thay.

### 20.1. Entry tại Open nến kế tiếp

Tại nến xác nhận, bot đóng băng swing bảo vệ và hard stop ban đầu:

```text
Hard_Stop     = Frozen_Swing -/+ Stop_Buffer   (theo Step 4)
```

Tại `Open` của nến ngay sau nến xác nhận:

```text
Entry_Price   = Open thực tế
Risk_Distance = abs(Entry_Price - Hard_Stop)
Long_TP       = Entry_Price + 10.0 * Risk_Distance
Short_TP      = Entry_Price - 10.0 * Risk_Distance
```

- Lệnh luôn khớp tại Open nến kế tiếp; không dùng High/Low nến xác nhận ± 1 tick.
- Không còn stop-entry, stop-limit, trần gap hoặc lệnh chờ sống qua nhiều nến.
- Gap tại Open làm thay đổi Entry, Risk Distance, TP và khối lượng theo rủi ro.
- Trong mỗi thời điểm chỉ giữ tối đa một Entry đã xác nhận chờ Open kế tiếp. Sau khi lệnh đó khớp, tín hiệu mới cùng chiều vẫn được xác nhận và tạo một giao dịch độc lập tiếp theo.

Hệ quả kiến trúc: không bước nào cần tính lại giữa nến. Script chỉ chạy đúng một
lần mỗi nến đóng, nên backtest và chạy thật đi theo cùng một đường.

### 21. Entry từ Value Zone

Khi một Value Zone Setup mới xuất hiện, Step 3 chuyển sang trạng thái chờ và ghi
nhớ EMA tham chiếu. Với Long, nếu `Close <= EMA89` thì chọn EMA89, ngược lại chọn
EMA34. Với Short, nếu `Close >= EMA89` thì chọn EMA89, ngược lại chọn EMA34.

Không xác nhận Entry ngay trên nến bắt đầu setup. Từ nến sau trở đi:

```text
VALUE_ZONE_LONG_ENTRY_CONFIRMED =
    Waiting_Value_Zone_Long
    AND Trend == UPTREND
    AND Close > Entry_EMA
    AND Close > Last_Important_Swing_Low
```

```text
VALUE_ZONE_SHORT_ENTRY_CONFIRMED =
    Waiting_Value_Zone_Short
    AND Trend == DOWNTREND
    AND Close < Entry_EMA
    AND Close < Last_Important_Swing_High
```

Sau khi xác nhận, Long/Short vào tại Open nến kế tiếp theo mục 20.1. Trạng thái
chờ Value Zone bị xóa sau khi xác nhận hoặc khi trend đổi hướng, giá đóng cửa
chạm/phá Important Swing bảo vệ setup, hoặc đang có một Entry khác chờ khớp.

Bot 2 (2026-09-28): trạng thái chờ cũng bị xóa khi `VALUE_ZONE_*_ENTRY_CONFIRMED` đúng
nhưng slot Value Zone đã đầy (reason `VALUE_ZONE_SLOT_FULL`, mục 27). Nếu không, mốc EMA
cũ có thể kích hoạt nhiều giờ sau khi lệnh cũ đóng, lúc giá đã rời xa vùng giá trị (stop
theo swing cũ nên 1R bị phình to). Khi chưa xác nhận (Close chưa lấy lại EMA) thì slot đầy
không hủy trạng thái chờ.

### 22. Entry từ Breakout

```text
BREAKOUT_LONG_ENTRY_CONFIRMED =
    Trend == UPTREND
    AND Close > Last_Important_Swing_High
```

```text
BREAKOUT_SHORT_ENTRY_CONFIRMED =
    Trend == DOWNTREND
    AND Close < Last_Important_Swing_Low
```

Tín hiệu chỉ được tạo tại cạnh chuyển `FALSE -> TRUE` của Breakout Setup. Long
hoặc Short vào tại Open nến kế tiếp theo mục 20.1.

### 22.1. Lọc theo trend khung lớn (Bot 2, 2026-09-29)

Mỗi khung giao dịch lọc theo khung ngay trên nó:

| Khung giao dịch | Khung lọc |
|---|---|
| M15 | H1 |
| H1 | H4 |
| Khung khác | không lọc |

`Higher_Trend` là trend Step 1 (cùng rule, cùng tham số) của **nến khung lớn mới nhất đã đóng
tại thời điểm nến khung nhỏ đóng**. Ví dụ nến M15 09:45–10:00 dùng nến H1 09:00–10:00 (cùng
đóng lúc 10:00); nến M15 10:00–10:15 vẫn dùng H1 09:00–10:00. Không dùng nến khung lớn đang chạy.

```text
Lỏng (mặc định, higher_tf_filter = "lenient"):
    Long  bị bỏ khi Higher_Trend == DOWNTREND
    Short bị bỏ khi Higher_Trend == UPTREND
Chặt (higher_tf_filter = "strict"):
    Long  cần Higher_Trend == UPTREND
    Short cần Higher_Trend == DOWNTREND
```

- Chỉ xét tín hiệu vừa xác nhận ở nến này (sau khi đã qua slot và điều kiện cùng chiều vị
  thế). Tín hiệu bị bỏ thì **xóa luôn trạng thái chờ và EMA tham chiếu của Value Zone**; muốn
  vào lại cần setup mới (giống khi slot đầy, mục 21). Reason: `HIGHER_TF_TREND_FILTER`.
- Không ảnh hưởng trend, setup, stop, TP hay việc đóng lệnh của khung nhỏ.
- Chưa có nến khung lớn nào đã đóng thì không lọc.
- Python: `TradingEngine.process_bar(bar, higher_trend)`, trend khung lớn lấy từ
  `trading_bot.core.higher_tf.HigherTrendFeed`; backtest `--higher <csv khung lớn>`. Bot MT5 tự
  lấy khung lớn (`--no-higher-filter` để tắt) và chờ nến khung lớn cùng giờ đóng xuất hiện
  (tối đa 120 giây). Pine: input `Lọc theo trend khung lớn` (`request.security`, không nhìn trước).
- Lý do (MT5 XAUUSD 2025-01→2026-09): 362/947 lệnh M15 ngược trend H1 tổng −53.5R; lọc lỏng tốt
  hơn lọc chặt (lệnh lúc khung lớn `SIDEWAY` vẫn có lãi). Thêm H4 vào bộ lọc M15 không cải thiện.

### 23. Output của Step 3

Step 3 trả về tối thiểu: trạng thái chờ Value Zone, EMA tham chiếu, Entry đã xác
nhận chờ Open kế tiếp, hướng Entry, setup nguồn, chỉ số nến xác nhận, chỉ số nến
Entry và giá Open thực tế. Step 3 chưa tính khối lượng; phần đó thuộc Step 5.

### 24. Kiểm thử tối thiểu cho Step 3

1. Value Zone Long/Short chỉ được arm khi setup mới xuất hiện.
2. Long chỉ xác nhận khi `Close > Entry_EMA`; Short chỉ xác nhận khi `Close < Entry_EMA`.
3. `Close == Entry_EMA` không xác nhận.
4. Xác nhận không tạo Entry trên cùng nến; Entry khớp đúng Open nến kế tiếp.
5. Chạm/phá Important Swing hoặc đổi trend sẽ hủy trạng thái chờ Value Zone.
6. Breakout Long/Short tạo Entry next-open tại cạnh setup mới.
6b. Gap tại Open vẫn khớp tại Open thực tế.
6c. TP và khối lượng theo rủi ro được tính từ Open thực tế, không từ nến xác nhận.
7. Râu nến vượt mức nhưng Close chưa vượt không xác nhận.
8. Breakout được ưu tiên nếu đồng thời có xác nhận Value Zone cùng hướng.
9. Khi đã có position cùng chiều, tín hiệu mới vẫn tạo Entry; mỗi Entry có `trade_id`, giá vào, hard stop, trailing stop, TP và P&L riêng.

## Step 4 — Invalidation

### 25. Mức vô hiệu và hard stop

Khi Entry được xác nhận, mức bảo vệ được đóng băng theo swing bảo vệ hiện tại:

- Long dùng `Protected Swing Low`.
- Short dùng `Protected Swing High`.
- Mức này không dời theo swing mới trong suốt vòng đời vị thế.

Khoảng đệm hard stop:

```text
Stop Buffer = max(3 * Minimum Tick, ATR(13) * Stop ATR Multiplier)
```

`Stop ATR Multiplier` mặc định là `0.30`.

Hard stop ban đầu được đặt dưới swing bảo vệ đối với Long và trên swing bảo vệ
đối với Short. Sau khi vào lệnh, stop đang hoạt động được phép dời theo mục 25.1.

**Bot 2 (2026-09-28) — 1R tối thiểu.** Khi lệnh khớp tại Open nến kế tiếp:

```text
Long:  nếu Hard Stop < Entry và Entry - Hard Stop < Min Initial Risk -> Hard Stop = Entry - Min Initial Risk
Short: nếu Hard Stop > Entry và Hard Stop - Entry < Min Initial Risk -> Hard Stop = Entry + Min Initial Risk
```

`Min Initial Risk` (`min_initial_risk`, Pine `1R tối thiểu`) mặc định **10**, đơn vị giá;
`0` = tắt. Stop sau khi nới là hard stop ban đầu dùng định nghĩa 1R cho TP (mục 29) và
trailing (mục 25.1). Nếu giá khớp đã vượt qua stop (gap) thì giữ nguyên để lệnh bị hủy như
cũ (`INVALID_ENTRY_RISK`). Khối lượng vẫn theo Step 5, không đổi theo độ lớn 1R.
Lý do: trên XAU các stop quá sát (1R vài giá) bị quét sớm và lãi bằng tiền không đáng kể;
backtest XAUUSDT Futures (12/2025→09/2026) mốc 10 tốt hơn 5/15/20 ở cả H1 và 15p.

### 25.1. Trailing stop theo R

`1R` luôn là khoảng cách tuyệt đối từ Entry thực tế tới hard stop ban đầu. Việc
dời stop không làm thay đổi định nghĩa này.

| Lợi nhuận tốt nhất đã vượt | Stop mới |
|---|---|
| `1R` | Entry (`0R`) |
| `2R` | `+1R` |
| `3R` | `+2R` |
| `4R` | `+3R` |
| `5R` | `+4R` |
| `6R` | `+5R` |
| `7R` | `+6R` |
| `8R` | `+7R` |
| `9R` | `+8R` |

- Các điều kiện là nghiêm ngặt: chạm đúng mốc chưa kích hoạt, giá phải vượt mốc.
- Long dùng `High`, Short dùng `Low` để đo mức lợi nhuận tốt nhất của nến.
- Stop chỉ được dời theo hướng bảo vệ vị thế, tuyệt đối không hạ ngược.
- Vì engine xử lý OHLC khi nến đóng, stop mới có hiệu lực từ nến kế tiếp. Nếu
  cùng một nến vừa vượt ngưỡng vừa đi qua stop mới, bot không giả định thứ tự
  intrabar và không hồi tố một lệnh thoát tại stop mới.
- Pine và Python đều lưu riêng hard stop ban đầu để tính R, đồng thời lưu stop
  đang hoạt động để đặt lệnh bảo vệ.
- Backtest ghi lý do `TRAILING_STOP_INTRABAR_EXIT` hoặc
  `TRAILING_STOP_GAP_EXIT` khi vị thế thoát tại stop đã được dời.

### 26. Thứ tự thoát lệnh

1. Nếu Open gap xuyên stop đang hoạt động, thoát tại Open.
2. Nếu giá chạm stop đang hoạt động trong nến, thoát tại stop đó.
3. **(Bot 2) Đảo chiều trend:** nếu chưa chạm hard stop nhưng trend đã chuyển sang
   chiều ngược với lệnh, thoát toàn bộ tại Close:
   - Long: `Trend == DOWNTREND`.
   - Short: `Trend == UPTREND`.
   Backtest ghi lý do `TREND_REVERSAL_CLOSE_EXIT`.
4. *(Bot 2: mặc định tắt, `exit_on_trend_loss = false`)* Rule bot gốc: thoát tại Close
   khi trend không còn đúng hướng của lệnh, kể cả về `SIDEWAY`:
   - Long: `Trend != UPTREND`.
   - Short: `Trend != DOWNTREND`.
   Khi bật, lý do ghi là `TREND_LOST_CLOSE_EXIT` cho cả hai trường hợp.

**Bot 2 (2026-09-24) giữ rule đảo chiều, bỏ rule mất trend về SIDEWAY.** Trend về
`SIDEWAY` không tự đóng lệnh: lệnh đã mở chỉ đóng bằng hard stop, trailing stop theo R
(mục 25.1), Take Profit (Step 7) hoặc khi trend **đảo chiều**. Lý do: với điều kiện độ
dốc 13 nến (mục 4.1) trend về `SIDEWAY` thường xuyên hơn, thoát tại Close mỗi lần như vậy
cắt lệnh quá sớm; nhưng trend đảo hẳn sang chiều ngược là mất luận điểm giao dịch nên vẫn
đóng lệnh. Trạng thái trend vẫn quyết định việc **mở** lệnh mới (Step 2, 3).

`exit_on_trend_reversal = true` và `exit_on_trend_loss = false` là mặc định của Bot 2
(Python); Pine tương ứng input `Thoát lệnh khi trend đảo chiều` bật và `Thoát lệnh khi
mất trend, kể cả SIDEWAY` tắt. Rule thoát riêng khi Close phá Protected Swing vẫn bị vô
hiệu hóa; Protected Swing vẫn dùng để tính Hard Stop.

Stop đang hoạt động vẫn là lệnh nằm sẵn trên sàn và luôn được ưu tiên: nếu giá
chạm stop trong nến thì lệnh đã đóng ở đó rồi, quy tắc thoát tại Close không còn
gì để làm.

Đặt `exit_on_trend_loss = true` để đóng cả khi trend về `SIDEWAY` như bot gốc;
đặt `exit_on_trend_reversal = false` để tắt hẳn mọi rule thoát theo trend.

Setup đang theo dõi hết hiệu lực khi có setup mới thay thế hoặc khi trend đổi.
Không mô phỏng phí giao dịch và trượt giá. Trường hợp gap xuyên hard stop vẫn dùng
Open thực tế làm giá thoát.

## Step 5 — Position Size

Hai mô hình, chọn bằng `risk_model`.

**`fixed_quantity`** — mọi lệnh dùng cùng một khối lượng `fixed_position_size`.
Đơn giản, nhưng rủi ro tiền thật của mỗi lệnh tỷ lệ thuận với khoảng cách stop,
nên các chỉ số theo `R` không so sánh được giữa các lệnh với nhau.

**`fixed_risk`** — khối lượng suy ra từ ngân sách rủi ro:

```text
Risk_Amount   = Equity * risk_per_trade_fraction
Risk_Per_Unit = abs(Actual Entry Open - Hard Stop Price)
Quantity      = Risk_Amount / Risk_Per_Unit
```

- `Equity` là vốn tại thời điểm đặt lệnh: vốn ban đầu cộng P&L đã thực hiện, trừ
  phí đã trả. P&L chưa thực hiện của các giao dịch đang mở không được cộng vào
  ngân sách rủi ro cho Entry mới.
- `quantity_step > 0` thì làm tròn xuống theo bước. `maximum_quantity > 0` là trần
  khối lượng. Khối lượng sau khi làm tròn nhỏ hơn `minimum_quantity`, hoặc bằng 0,
  thì bỏ Entry thay vì vào lệnh với khối lượng không hợp lệ.
- Rủi ro đo từ giá Open thực tế, cùng mốc với TP, nên một lệnh thua đúng kế hoạch
  mất tròn `risk_per_trade_fraction` của vốn, còn một lệnh chạm TP được 10 lần con
  số đó. Gap đã được phản ánh trực tiếp vào Entry Price và Risk Per Unit.
- Python/backtest tính quantity chính xác từ Open thực tế. TradingView phải gửi
  quantity trước khi Open nến kế tiếp tồn tại, nên Pine chỉ có thể ước tính quantity
  `% vốn` từ Close nến xác nhận; chế độ `fixed_quantity` không có sai lệch này.

## Step 6 — Multiple Entries

### 27. Nhiều giao dịch độc lập cùng chiều — Bot 2: tối đa 2 lệnh, mỗi loại setup 1 lệnh

- Mỗi tín hiệu Entry được xác nhận tại Step 3 mở một giao dịch mới, kể cả khi đã
  có giao dịch cùng chiều đang `OPEN`, **miễn là loại setup của tín hiệu chưa có lệnh
  mở** (mục 20). Tổng số lệnh nắm giữ tối đa là 2: một từ Breakout, một từ Value Zone.
- Các giao dịch cùng chiều không được gộp thành một giao dịch trung bình. Mỗi giao
  dịch giữ riêng `trade_id`, giá vào, frozen swing, hard stop ban đầu, trailing
  stop, TP 10R, khối lượng và P&L.
- Không mở chồng ngược chiều. Tất cả giao dịch của trend cũ phải đóng theo Step 4
  trước khi hệ thống mở giao dịch theo hướng mới.
- Module Add vẫn không tự tăng khối lượng của một giao dịch đã tồn tại; việc mở
  thêm chỉ xuất phát từ một tín hiệu Entry mới hợp lệ.
- Quy tắc áp dụng đối xứng cho Long và Short.
- Pine đặt `pyramiding = 100` làm trần kỹ thuật; giới hạn thực tế do input
  `Số lệnh mở tối đa mỗi loại setup` (mặc định 1) quyết định, đếm trên mảng
  `tradeSources` của các trade đang mở.

### 28. Output và kiểm thử tối thiểu cho Step 6

Step 6 vẫn trả về `should_add = FALSE`, `quantity = 0` và reason
`POSITION_ADD_DISABLED`; các lệnh mở thêm đi qua Step 3 chứ không qua Add.

Kiểm thử tối thiểu:

1. Position Long từ Value Zone đang mở vẫn nhận Entry Long từ Breakout (và ngược lại).
2. Position từ Breakout đang mở chặn tín hiệu Breakout mới (reason `BREAKOUT_SLOT_FULL`);
   Value Zone đang mở chặn xác nhận Value Zone mới (`VALUE_ZONE_SLOT_FULL`) và xóa trạng thái chờ
   (2026-09-28); slot trống ở nến sau cũng không vào lệnh nếu chưa có setup Value Zone mới.
3. Hai lệnh (1 Breakout + 1 Value Zone) đang mở chặn mọi tín hiệu mới.
4. Breakout và Value Zone cùng xác nhận khi slot Breakout đầy → vào Value Zone.
5. Lệnh cũ bị hard stop trong nến giải phóng slot ngay nến đó (engine); lệnh chờ khớp tại Open cùng loại vẫn vào.
6. `max_trades_per_setup_family = 0` khôi phục hành vi không giới hạn.
7. Mỗi Entry giữ stop, TP, khối lượng và vòng đời thoát lệnh riêng.
8. Tín hiệu ngược chiều không mở chồng lên vị thế hiện tại.
9. Sổ backtest ghép đúng từng sự kiện mở/đóng bằng `trade_id` khi các lệnh chồng thời gian.

## Step 7 — Exit

### 29. Take Profit cố định 10R

Khoảng rủi ro ban đầu (`1R`) được chốt khi lệnh khớp tại Open nến sau:

```text
Risk Distance = abs(Actual Entry Open - Hard Stop Price)
```

Mức Take Profit:

```text
Long TP  = Actual Entry Open + 10.0 * Risk Distance
Short TP = Actual Entry Open - 10.0 * Risk Distance
```

- Hard stop ban đầu được chốt tại nến xác nhận; TP chỉ được tính sau khi biết giá
  Open thực tế của nến vào lệnh. Trailing không làm thay đổi TP hoặc 1R ban đầu.
- TP không thay đổi trong suốt vòng đời position.
- Không chốt lời từng phần; khi TP được kích hoạt, đóng toàn bộ position.
- Nếu Open gap vượt TP theo hướng có lợi, thoát tại Open thực tế.
- Nếu giá chạm TP trong nến, thoát tại đúng mức TP.
- Nếu một nến có thể đã chạm cả hard stop và TP mà không có dữ liệu intrabar,
  ưu tiên hard stop theo thứ tự điều phối Step 4 trước Step 7. Đây là giả định
  bảo thủ để tránh ghi nhận kết quả tốt hơn dữ liệu cho phép chứng minh.
- Ngoài TP này, trailing stop và các điều kiện Invalidation ở Step 4, không có
  thoát theo thời gian hoặc điều kiện Exit bổ sung khác.

### 30. Output và kiểm thử tối thiểu cho Step 7

Step 7 trả về tối thiểu: `should_exit`, `exit_price`, `take_profit_price` và
`reason`. Khi TP được kích hoạt, `TradingEngine` đóng toàn bộ position và phát
event `POSITION_CLOSED_TAKE_PROFIT`.

Kiểm thử tối thiểu:

1. Long TP nằm cao hơn giá Open vào lệnh đúng 10 lần khoảng cách tới hard stop.
2. Short TP nằm thấp hơn Entry theo công thức đối xứng.
3. Râu nến chạm TP đóng toàn bộ position tại TP.
4. Gap vượt TP đóng position tại Open thực tế.
5. Chưa chạm TP thì position giữ nguyên.
6. Nếu cùng nến chạm cả hard stop và TP, hard stop được ưu tiên.
7. Stop lần lượt lên Entry, +1R, +2R, ... +8R khi lợi nhuận vượt 1R, 2R, 3R, ... 9R.
8. Stop mới không áp dụng hồi tố trong chính nến vừa kích hoạt và không bao giờ
   dời ngược.

## Step 8 — Backtest & P&L

### 31. Sổ giao dịch

Backtest phát lại dữ liệu nến qua `TradingEngine` và tạo một dòng cho mỗi giao
dịch đã đóng. Mỗi dòng lưu: hướng, setup nguồn, bar/giá Entry, bar/giá Exit,
hard stop ban đầu, TP, khối lượng, lý do thoát, số nến nắm giữ, P&L và kết quả
theo đơn vị `R`.

```text
Long P&L  = (Exit Price - Entry Price) * Quantity
Short P&L = (Entry Price - Exit Price) * Quantity
Initial Risk = abs(Entry Price - Hard Stop Price) * Quantity
R Multiple = P&L / Initial Risk
```

Phiên bản này không mô phỏng phí giao dịch và trượt giá. Gap qua stop hoặc TP dùng
giá Open thực tế do engine cung cấp.

`AccountState` theo dõi vốn qua từng nến và luôn thỏa:

```text
equity = initial_equity + realized_pnl
```

Bên cạnh lời lỗ bằng tiền, bộ chỉ số còn trả về thống kê tỷ lệ lệnh:

- `wins`, `losses`, `breakeven`, `win_rate`, `loss_rate`.
- `average_win`, `average_loss`, `payoff_ratio` (lãi trung bình chia lỗ trung bình),
  `expectancy` (lời lỗ trung bình mỗi lệnh).
- `largest_win`, `largest_loss`, `max_consecutive_wins`, `max_consecutive_losses`.
- `calculate_trade_breakdown` tách toàn bộ các chỉ số trên theo từng loại setup và
  theo hướng lệnh, để biết nhánh nào đang gánh và nhánh nào đang lỗ.
- `count_exit_reasons` đếm số lệnh theo lý do thoát hiện hành: hard stop, mất trend
  hoặc chạm TP. Nhãn phá swing đã đóng băng chỉ được giữ để đọc dữ liệu lịch sử.

### 32. Chỉ số kết quả

Backtest tổng hợp tối thiểu:

- Tổng số giao dịch, số thắng, số thua và hòa vốn.
- Win rate.
- Gross profit, gross loss và net profit.
- Profit factor; để `None` khi không có giao dịch thua.
- Average R, cumulative R và max drawdown tính theo R.

Giao dịch còn mở khi hết dữ liệu không được tự đóng giả định và không đi vào
thống kê giao dịch đã hoàn tất.

## Step 9 — Historical Data Input

### 33. Định dạng CSV

Backtest nhận file CSV có header, không phân biệt chữ hoa/thường. Bốn cột bắt
buộc là `open`, `high`, `low`, `close`. Cột `timestamp` là tùy chọn và dùng
chuẩn ISO-8601; cột `volume` hoặc các cột khác được phép tồn tại nhưng hiện chưa
được strategy sử dụng.

- Dòng trống được bỏ qua.
- Nếu có timestamp, thời gian phải tăng nghiêm ngặt; không chấp nhận trùng hoặc
  đảo thứ tự.
- OHLC phải hợp lệ theo cùng validation của `Bar`.
- Index nội bộ được đánh lại tuần tự từ 0 theo thứ tự dòng dữ liệu.

### 34. Lệnh chạy backtest

```text
python -m trading_bot.backtest data.csv --trades-out trades.csv
```

Lệnh in summary JSON ra terminal. `--trades-out` là tùy chọn; khi dùng, toàn bộ
giao dịch đã đóng được xuất thành CSV UTF-8 có BOM để mở thuận tiện trong Excel.
