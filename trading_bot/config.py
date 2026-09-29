from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class StrategyConfig:
    """Configuration shared by all strategy modules."""

    ema_fast_length: int = 34
    ema_slow_length: int = 89
    slope_length: int = 8
    # Bot 2 Step 1 (2026-09-29): BỎ điều kiện độ dốc EMA34 n2 nến (mặc định False).
    # Ablation XAU MT5 H1/M15: ở bước xác nhận không có tác dụng (8 nến đã bao hàm),
    # ở bước duy trì làm trend về SIDEWAY ~45% số nến và cắt lệnh Value Zone.
    # True = bật lại (xác nhận + duy trì) như spec v1.7.
    use_confirm_slope: bool = False
    # Số giá trị EMA34 gần nhất dùng đo độ dốc xác nhận (chỉ khi use_confirm_slope).
    confirm_slope_length: int = 13
    # Bot 2 Step 1: mốc độ dốc tối thiểu của EMA34, đơn vị GIÁ mỗi nến, cố định
    # (không theo ATR). UPTREND cần Confirm_Slope > mốc, DOWNTREND cần < -mốc.
    # 2026-09-25: người dùng chốt mốc = 0 -> chỉ xét dấu (dương/âm), không cần mốc 5.
    min_confirm_slope: float = 0.0
    # Bot 2 Step 1 (2026-09-25): k nến mỗi bên xác nhận pivot nâng từ 3 -> 5.
    pivot_legs: int = 5
    min_positive_ratio: float = 0.75
    min_negative_ratio: float = 0.75
    require_trend_maintenance_filter: bool = True
    # Step 4 — Bot 2 (2026-09-24): trend về SIDEWAY không đóng lệnh; lệnh chỉ đóng
    # bằng hard stop / trailing stop / TP. Bật exit_on_trend_loss=True để đóng cả khi
    # mất trend về SIDEWAY như bot gốc.
    exit_on_trend_loss: bool = False
    # Step 4 — Bot 2 giữ rule đảo chiều (2026-09-24): trend đảo sang chiều ngược với
    # lệnh (Long gặp DOWNTREND, Short gặp UPTREND) -> đóng toàn bộ lệnh tại Close.
    exit_on_trend_reversal: bool = True
    enable_value_zone_setup: bool = True
    enable_breakout_setup: bool = True
    # Bot 2 Step 3/6 (2026-09-24): số lệnh đang mở tối đa cho MỖI loại setup
    # (Breakout, Value Zone). 1 = tối đa 2 lệnh nắm giữ. 0 = không giới hạn (bot gốc).
    max_trades_per_setup_family: int = 1
    atr_length: int = 13
    stop_atr_multiplier: float = 0.30
    # Bot 2 (2026-09-28): 1R tối thiểu, đơn vị GIÁ. Khi khớp lệnh mà khoảng cách
    # giá khớp -> hard stop nhỏ hơn mốc thì nới stop ra đủ mốc (TP/trailing tính
    # theo 1R mới). 0 = tắt. Đo trên XAU (1R trung vị ~45 giá); BTC hầu như không chạm.
    min_initial_risk: float = 10.0
    minimum_tick: float = 0.01
    fixed_position_size: float = 1.0
    # Bot 2 (2026-09-28): TP nâng từ 5R lên 10R.
    take_profit_r_multiple: float = 10.0
    # Step 5 — mô hình khối lượng. "fixed_quantity" giữ hành vi cũ;
    # "fixed_risk" suy khối lượng từ ngân sách rủi ro và khoảng cách stop.
    risk_model: str = "fixed_quantity"
    risk_per_trade_fraction: float = 0.01
    initial_equity: float = 100_000.0
    quantity_step: float = 0.0
    minimum_quantity: float = 0.0
    maximum_quantity: float = 0.0

    def __post_init__(self) -> None:
        if self.ema_fast_length < 1:
            raise ValueError("ema_fast_length must be >= 1")
        if self.ema_slow_length < 2:
            raise ValueError("ema_slow_length must be >= 2")
        if self.slope_length < 2:
            raise ValueError("slope_length must be >= 2")
        if self.confirm_slope_length < 2:
            raise ValueError("confirm_slope_length must be >= 2")
        if self.min_confirm_slope < 0.0:
            raise ValueError("min_confirm_slope must be >= 0")
        if self.pivot_legs < 1:
            raise ValueError("pivot_legs must be >= 1")
        if not 0.0 <= self.min_positive_ratio <= 1.0:
            raise ValueError("min_positive_ratio must be in [0, 1]")
        if not 0.0 <= self.min_negative_ratio <= 1.0:
            raise ValueError("min_negative_ratio must be in [0, 1]")
        if self.atr_length < 1:
            raise ValueError("atr_length must be >= 1")
        if self.max_trades_per_setup_family < 0:
            raise ValueError("max_trades_per_setup_family must be >= 0")
        if self.stop_atr_multiplier < 0.0:
            raise ValueError("stop_atr_multiplier must be >= 0")
        if self.min_initial_risk < 0.0:
            raise ValueError("min_initial_risk must be >= 0")
        if self.minimum_tick <= 0.0:
            raise ValueError("minimum_tick must be > 0")
        if self.fixed_position_size <= 0.0:
            raise ValueError("fixed_position_size must be > 0")
        if self.take_profit_r_multiple <= 0.0:
            raise ValueError("take_profit_r_multiple must be > 0")
        if self.risk_model not in {"fixed_quantity", "fixed_risk"}:
            raise ValueError("risk_model must be 'fixed_quantity' or 'fixed_risk'")
        if not 0.0 < self.risk_per_trade_fraction <= 1.0:
            raise ValueError("risk_per_trade_fraction must be in (0, 1]")
        if self.initial_equity <= 0.0:
            raise ValueError("initial_equity must be > 0")
        if self.quantity_step < 0.0:
            raise ValueError("quantity_step must be >= 0")
        if self.minimum_quantity < 0.0:
            raise ValueError("minimum_quantity must be >= 0")
        if self.maximum_quantity < 0.0:
            raise ValueError("maximum_quantity must be >= 0")
        if 0.0 < self.maximum_quantity < self.minimum_quantity:
            raise ValueError("maximum_quantity must be >= minimum_quantity")
