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
direction's price data through the other's formula. high_volume_support and
low_volume_area_above (volume-profile refinements) stay bullish-only for now
— no live caller passes them for either direction yet, so there's no bearish
counterpart (a "resistance"/"high-volume area below" concept) to build until
one actually needs it.
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
) -> float:
    """
    Compute stop loss.
    Bullish: entry_zone_bound is entry_zone_lower; ATR stop = entry_zone_lower
    - (stop_atr_multiplier × ATR_14); stop always below entry_zone_lower.
    Bearish: entry_zone_bound is entry_zone_upper; ATR stop = entry_zone_upper
    + (stop_atr_multiplier × ATR_14); stop always above entry_zone_upper.
    high_volume_support (bullish only): use it instead of the ATR stop if
    it's tighter (closer to entry, i.e. less risk per trade).
    """
    if atr_14 <= 0:
        raise ValueError(f"atr_14 must be > 0, got {atr_14}")

    if direction == "bearish":
        return round(entry_zone_bound + (stop_atr_multiplier * atr_14), 4)

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
) -> Optional[float]:
    """
    Compute price target satisfying the minimum R:R.

    Bullish: target above entry. Priority: first low-volume area above entry
    (volume profile target), else entry + min_rr × (entry - stop). None if
    stop >= entry (invalid setup).
    Bearish: target below entry (mirror image): entry - min_rr × (stop -
    entry). None if stop <= entry (invalid setup). low_volume_area_above is
    bullish-only (see module docstring) — ignored for bearish.
    """
    if direction == "bearish":
        if stop <= entry:
            return None
        risk_per_share = stop - entry
        return round(entry - (min_rr * risk_per_share), 4)

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


def compute_pnl_surface(
    entry: float,
    stop: float,
    target: float,
    structure_multipliers: dict,
) -> dict:
    """
    Compute theoretical position value at Day 1, 5, 10, 15 under three scenarios.
    Returns dict: {day_1, day_5, day_10, day_15: {target_hit, flat, stop_hit}}
    Used for complex structure EV and open-position management alerts.
    """
    risk = entry - stop
    reward = target - entry

    # Structure-specific multipliers (numeric values only; string multipliers → 1.0 default)
    pm = structure_multipliers.get("profit_mult", 1.0)
    lm = structure_multipliers.get("loss_mult", 1.0)
    if not isinstance(pm, (int, float)):
        pm = 1.0
    if not isinstance(lm, (int, float)):
        lm = 1.0

    surface = {}
    for day in [1, 5, 10, 15]:
        t_scale = min(1.0, day / 15.0)
        surface[f"day_{day}"] = {
            "target_hit": round(reward * pm * t_scale, 2),
            "flat": 0.0,
            "stop_hit": round(-risk * lm * t_scale, 2),
        }
    return surface


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
