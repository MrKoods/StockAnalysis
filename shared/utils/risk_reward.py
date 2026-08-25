"""
SHARED: ATR-based + volume-profile stop/target math, R:R ratio calculation.
Entry zone formula (exact per scope, bullish case):
  Lower = max(current_close, breakout_level) - (0.25 × ATR_14)
  Upper = max(current_close, breakout_level) + (0.25 × ATR_14)
  Stop  = entry_zone_lower - (2.0 × ATR_14)   OR nearest high-vol support node (whichever is closer)
  Target = next low-volume area above entry; must satisfy ≥ 1:3 R:R

Bearish is the mirror image throughout (breakdown level instead of breakout
level, stop above entry instead of below, target below entry instead of
above) — every function below takes an explicit direction param rather than
having a separate bearish_* function, so a caller can't accidentally run one
direction's price data through the other's formula. high_volume_resistance
and low_volume_area_below are the bearish mirrors of high_volume_support and
low_volume_area_above (volume-profile refinements) — technical_common.py has
computed both mirrors since the bearish path shipped (v2.2.58), but this
module only accepted the bullish pair until now; both directions get the
tighter, real-support/resistance-aware stop/target instead of always falling
back to pure ATR/min-R:R math.
"""

from typing import Optional


def compute_entry_zone(
    current_close: float,
    level: float,
    atr_14: float,
    half_width_atr: float = 0.25,
    direction: str = "bullish",
) -> tuple[float, float]:
    """
    Compute entry zone as (lower, upper).

    Bullish: anchor = max(current_close, level) — level is the breakout
    (rolling high) — a confirmed breakout can be higher than the current
    close, and entry shouldn't anchor below it.
    Bearish: anchor = min(current_close, level) — level is the breakdown
    (rolling low) — the mirror case, a confirmed breakdown can be lower than
    the current close.
    """
    if atr_14 <= 0:
        # A vendor data glitch (bad/negative ATR) must not silently produce an
        # inverted or zero-width entry zone — every downstream stop/target
        # calculation assumes a positive ATR.
        raise ValueError(f"atr_14 must be > 0, got {atr_14}")

    anchor = min(current_close, level) if direction == "bearish" else max(current_close, level)
    lower = anchor - (half_width_atr * atr_14)
    upper = anchor + (half_width_atr * atr_14)
    return round(lower, 4), round(upper, 4)


def compute_stop_loss(
    entry_zone_bound: float,
    atr_14: float,
    high_volume_support: Optional[float] = None,
    stop_atr_multiplier: float = 2.0,
    direction: str = "bullish",
    high_volume_resistance: Optional[float] = None,
) -> float:
    """
    Compute stop loss.
    Bullish: entry_zone_bound is entry_zone_lower; ATR stop = entry_zone_lower
    - (stop_atr_multiplier × ATR_14); stop always below entry_zone_lower.
    high_volume_support: use it instead of the ATR stop if it's tighter
    (closer to entry, i.e. less risk per trade).
    Bearish: entry_zone_bound is entry_zone_upper; ATR stop = entry_zone_upper
    + (stop_atr_multiplier × ATR_14); stop always above entry_zone_upper.
    high_volume_resistance (the bearish mirror of high_volume_support): same
    tighter-stop preference, mirrored above entry instead of below.
    """
    if atr_14 <= 0:
        raise ValueError(f"atr_14 must be > 0, got {atr_14}")

    if direction == "bearish":
        atr_stop = entry_zone_bound + (stop_atr_multiplier * atr_14)

        if high_volume_resistance is not None and high_volume_resistance > entry_zone_bound:
            # Use the HVN stop if it's tighter than the ATR stop (closer to entry)
            if high_volume_resistance < atr_stop:
                return round(high_volume_resistance, 4)

        return round(atr_stop, 4)

    atr_stop = entry_zone_bound - (stop_atr_multiplier * atr_14)

    if high_volume_support is not None and high_volume_support < entry_zone_bound:
        # Use the HVN stop if it's tighter than the ATR stop (closer to entry)
        if high_volume_support > atr_stop:
            return round(high_volume_support, 4)

    return round(atr_stop, 4)


def compute_target(
    entry: float,
    stop: float,
    low_volume_area_above: Optional[float] = None,
    min_rr: float = 3.0,
    direction: str = "bullish",
    low_volume_area_below: Optional[float] = None,
) -> Optional[float]:
    """
    Compute price target satisfying the minimum R:R.

    Bullish: target above entry. Priority: first low-volume area above entry
    (volume profile target), else entry + min_rr × (entry - stop). None if
    stop >= entry (invalid setup).
    Bearish: target below entry (mirror image). Priority: first low-volume
    area below entry (low_volume_area_below, the bearish mirror of
    low_volume_area_above), else entry - min_rr × (stop - entry). None if
    stop <= entry (invalid setup).
    """
    if direction == "bearish":
        if stop <= entry:
            return None
        risk_per_share = stop - entry
        min_target = entry - (min_rr * risk_per_share)

        if low_volume_area_below is not None and low_volume_area_below <= min_target:
            return round(low_volume_area_below, 4)

        return round(min_target, 4)

    if stop >= entry:
        return None

    risk_per_share = entry - stop
    min_target = entry + (min_rr * risk_per_share)

    if low_volume_area_above is not None and low_volume_area_above >= min_target:
        return round(low_volume_area_above, 4)

    # Fallback: exact 1:3 R:R target
    return round(min_target, 4)


def compute_rr_ratio(entry: float, stop: float, target: float, direction: str = "bullish") -> float:
    """
    Bullish: R:R = (target - entry) / (entry - stop). Returns 0.0 if stop >= entry.
    Bearish: R:R = (entry - target) / (stop - entry). Returns 0.0 if stop <= entry.
    """
    if direction == "bearish":
        if stop <= entry:
            return 0.0
        return round((entry - target) / (stop - entry), 2)

    if stop >= entry:
        return 0.0
    return round((target - entry) / (entry - stop), 2)


def compute_trailing_stop(
    direction: str,
    highest_close_since_entry: float,
    lowest_close_since_entry: float,
    atr_14: float,
    trailing_multiplier: float = 1.5,
) -> float:
    """
    Dynamic trailing stop, updated daily throughout the holding period.
    Bullish: stop = highest_close_since_entry - (trailing_multiplier × ATR_14)
    Bearish: stop = lowest_close_since_entry + (trailing_multiplier × ATR_14)
    Stop never moves against the position (ratchets only in favorable direction).
    """
    if direction == "bullish":
        return round(highest_close_since_entry - (trailing_multiplier * atr_14), 4)
    return round(lowest_close_since_entry + (trailing_multiplier * atr_14), 4)


def compute_trade_setup(
    current_close: float,
    breakout_level: float,
    atr_14: float,
    high_volume_support: Optional[float] = None,
    low_volume_area_above: Optional[float] = None,
    min_rr: float = 3.0,
) -> dict:
    """
    Convenience wrapper: compute full trade setup (entry zone, stop, target, R:R).
    Returns dict with all fields needed by trade_selector.py and discord_alerts.py.
    """
    lower, upper = compute_entry_zone(current_close, breakout_level, atr_14)
    entry_mid = (lower + upper) / 2
    stop = compute_stop_loss(lower, atr_14, high_volume_support)
    target = compute_target(entry_mid, stop, low_volume_area_above, min_rr)
    rr = compute_rr_ratio(entry_mid, stop, target) if target is not None else 0.0

    return {
        "entry_zone_lower": lower,
        "entry_zone_upper": upper,
        "entry_mid": round(entry_mid, 4),
        "stop_loss": stop,
        "target": target,
        "rr_ratio": rr,
        "risk_per_share": round(entry_mid - stop, 4),
        "reward_per_share": round((target - entry_mid) if target else 0.0, 4),
        "meets_min_rr": rr >= min_rr,
    }
