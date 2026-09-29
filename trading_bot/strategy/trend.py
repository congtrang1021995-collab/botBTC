from __future__ import annotations

from dataclasses import dataclass

from trading_bot.config import StrategyConfig
from trading_bot.core.models import BarContext, StrategyState, TrendState


@dataclass(frozen=True, slots=True)
class TrendDecision:
    trend: TrendState
    protected_swing_low: float | None
    protected_swing_high: float | None
    changed: bool
    higher_high: bool
    higher_low: bool
    lower_high: bool
    lower_low: bool
    ema_up_filter: bool
    ema_down_filter: bool
    ema_up_maintain: bool
    ema_down_maintain: bool
    slope_confirm_up: bool
    slope_confirm_down: bool
    confirm_slope_threshold: float | None
    uptrend_rule: bool
    downtrend_rule: bool
    broke_protected_low: bool
    broke_protected_high: bool


def evaluate_trend(
    context: BarContext,
    previous: StrategyState,
    config: StrategyConfig,
) -> TrendDecision:
    """Evaluate Step 1 without mutating the shared strategy state."""
    close = context.bar.close
    indicators = context.indicators
    swings = context.swings

    has_two_highs = swings.last_high is not None and swings.previous_high is not None
    has_two_lows = swings.last_low is not None and swings.previous_low is not None
    higher_high = has_two_highs and swings.last_high > swings.previous_high
    higher_low = has_two_lows and swings.last_low > swings.previous_low
    lower_high = has_two_highs and swings.last_high < swings.previous_high
    lower_low = has_two_lows and swings.last_low < swings.previous_low

    confirmed_up_structure = higher_high and higher_low
    confirmed_down_structure = lower_high and lower_low
    valid_up_structure = (
        confirmed_up_structure
        and swings.last_low is not None
        and close >= swings.last_low
    )
    valid_down_structure = (
        confirmed_down_structure
        and swings.last_high is not None
        and close <= swings.last_high
    )

    protected_low = previous.protected_swing_low
    protected_high = previous.protected_swing_high

    # Match Pine ordering: protection always follows the most recently confirmed
    # pivot of the active trend before the current close is checked against it.
    if previous.trend == TrendState.UPTREND and swings.confirmed_low is not None:
        protected_low = swings.confirmed_low.price
    if previous.trend == TrendState.DOWNTREND and swings.confirmed_high is not None:
        protected_high = swings.confirmed_high.price

    enough_ema_data = all(
        value is not None
        for value in (
            indicators.ema_fast,
            indicators.ema_slow,
            indicators.ema_slope,
            indicators.positive_delta_ratio,
            indicators.negative_delta_ratio,
        )
    )
    ema_up_filter = bool(
        enough_ema_data
        and close > indicators.ema_fast
        and indicators.ema_fast > indicators.ema_slow
        and indicators.ema_slope > 0.0
        and indicators.positive_delta_ratio >= config.min_positive_ratio
    )
    ema_down_filter = bool(
        enough_ema_data
        and close < indicators.ema_fast
        and indicators.ema_fast < indicators.ema_slow
        and indicators.ema_slope < 0.0
        and indicators.negative_delta_ratio >= config.min_negative_ratio
    )

    # Bộ lọc duy trì trend: nhẹ hơn bộ lọc xác nhận. Chỉ ràng buộc cấu trúc hai
    # đường EMA, không kiểm tra vị trí của Close, nên giá được phép hồi xuống dưới
    # cả hai EMA. Có thể tắt bằng config.require_trend_maintenance_filter.
    # Hai EMA bằng nhau chưa làm mất trend. Chỉ một giao cắt nghiêm ngặt sang
    # phía đối diện mới vô hiệu trend đang giữ.
    ema_up_maintain = (not config.require_trend_maintenance_filter) or bool(
        enough_ema_data and indicators.ema_fast >= indicators.ema_slow
    )
    ema_down_maintain = (not config.require_trend_maintenance_filter) or bool(
        enough_ema_data and indicators.ema_fast <= indicators.ema_slow
    )

    # Bot 2 Step 1: điều kiện bắt buộc thêm vào rule cũ. Độ dốc EMA34 trên
    # confirm_slope_length nến gần nhất phải cùng chiều với trend, cả khi xác
    # nhận trend mới lẫn khi duy trì trend đang giữ; không thỏa thì SIDEWAY.
    # Độ dốc phải vượt mốc cố định min_confirm_slope (đơn vị giá/nến, không theo
    # ATR); dốc quá ít vẫn là SIDEWAY. min_confirm_slope = 0 -> chỉ xét dấu.
    confirm_slope = indicators.ema_confirm_slope
    threshold: float | None = config.min_confirm_slope
    # 2026-09-29: mặc định bỏ điều kiện này (use_confirm_slope=False) -> luôn thỏa.
    slope_confirm_up = not config.use_confirm_slope or (
        confirm_slope is not None and threshold is not None and confirm_slope > threshold
    )
    slope_confirm_down = not config.use_confirm_slope or (
        confirm_slope is not None and threshold is not None and confirm_slope < -threshold
    )

    previous_uptrend_intact = (
        previous.trend == TrendState.UPTREND
        and protected_low is not None
        and close >= protected_low
    )
    previous_downtrend_intact = (
        previous.trend == TrendState.DOWNTREND
        and protected_high is not None
        and close <= protected_high
    )

    uptrend_rule = (
        ema_up_filter
        and slope_confirm_up
        and (valid_up_structure or previous_uptrend_intact)
    )
    downtrend_rule = (
        ema_down_filter
        and slope_confirm_down
        and (valid_down_structure or previous_downtrend_intact)
    )
    broke_protected_low = (
        previous.trend == TrendState.UPTREND
        and protected_low is not None
        and close < protected_low
    )
    broke_protected_high = (
        previous.trend == TrendState.DOWNTREND
        and protected_high is not None
        and close > protected_high
    )

    next_trend = previous.trend
    if previous.trend == TrendState.UPTREND:
        # Tạm thời không dùng Close phá protected swing để làm mất trend.
        if not (ema_up_maintain and slope_confirm_up):
            next_trend = TrendState.DOWNTREND if downtrend_rule else TrendState.SIDEWAY
    elif previous.trend == TrendState.DOWNTREND:
        if not (ema_down_maintain and slope_confirm_down):
            next_trend = TrendState.UPTREND if uptrend_rule else TrendState.SIDEWAY
    elif uptrend_rule:
        next_trend = TrendState.UPTREND
    elif downtrend_rule:
        next_trend = TrendState.DOWNTREND

    if next_trend == TrendState.UPTREND:
        if previous.trend != TrendState.UPTREND:
            protected_low = swings.last_low
        protected_high = None
    elif next_trend == TrendState.DOWNTREND:
        if previous.trend != TrendState.DOWNTREND:
            protected_high = swings.last_high
        protected_low = None
    else:
        protected_low = None
        protected_high = None

    return TrendDecision(
        trend=next_trend,
        protected_swing_low=protected_low,
        protected_swing_high=protected_high,
        changed=next_trend != previous.trend,
        higher_high=higher_high,
        higher_low=higher_low,
        lower_high=lower_high,
        lower_low=lower_low,
        ema_up_filter=ema_up_filter,
        ema_down_filter=ema_down_filter,
        ema_up_maintain=ema_up_maintain,
        ema_down_maintain=ema_down_maintain,
        slope_confirm_up=slope_confirm_up,
        slope_confirm_down=slope_confirm_down,
        confirm_slope_threshold=threshold,
        uptrend_rule=uptrend_rule,
        downtrend_rule=downtrend_rule,
        broke_protected_low=broke_protected_low,
        broke_protected_high=broke_protected_high,
    )
