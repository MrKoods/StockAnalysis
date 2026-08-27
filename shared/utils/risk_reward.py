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
    min_stop_atr_multiple: float = 1.0,
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

    min_stop_atr_multiple (2026-08-26, v2.2.104): floor on how tight the HVN
    stop is allowed to pull the stop in, in ATR terms. The ATR stop can only
    ever be LOOSENED by this function, never tightened — a nearby high-volume
    node was previously accepted no matter how close it sat, and a stop inside
    one day's typical range is hit by ordinary noise rather than by the thesis
    being wrong. Measured live 2026-08-26: SBUX stopped at 0.83 x ATR and QCOM
    at 0.88 x ATR, versus ~2.25 for the picks that fell back to the ATR stop.
    A too-tight stop is doubly bad here, because target = min_rr x stop
    distance: it produces an easily-triggered stop AND a small target, so the
    trade is likely to be stopped out on noise before its own modest target is
    reached. Set to 0 to restore the old unbounded behaviour.
    """
    if atr_14 <= 0:
        raise ValueError(f"atr_14 must be > 0, got {atr_14}")

    if direction == "bearish":
        atr_stop = entry_zone_bound + (stop_atr_multiplier * atr_14)

        if high_volume_resistance is not None and high_volume_resistance > entry_zone_bound:
            # Use the HVN stop if it's tighter than the ATR stop (closer to entry)
            # — but never tighter than min_stop_atr_multiple x ATR (mirror of
            # the bullish floor below).
            if high_volume_resistance < atr_stop:
                # Bearish mirror: stop sits ABOVE entry, so a tighter stop is a
                # LOWER price — the distance floor becomes a price floor, max().
                min_allowed_stop_price = entry_zone_bound + (min_stop_atr_multiple * atr_14)
                return round(max(high_volume_resistance, min_allowed_stop_price), 4)

        return round(atr_stop, 4)

    atr_stop = entry_zone_bound - (stop_atr_multiplier * atr_14)

    if high_volume_support is not None and high_volume_support < entry_zone_bound:
        # Use the HVN stop if it's tighter than the ATR stop (closer to entry)
        # — but never tighter than min_stop_atr_multiple x ATR. See _floor.
        if high_volume_support > atr_stop:
            # Bullish: the stop sits BELOW entry, so a TIGHTER stop is a HIGHER
            # price. The floor on stop DISTANCE is therefore a ceiling on stop
            # PRICE — hence min(), not max(). An HVN further out than the floor
            # is left exactly where it is; only a too-close one is pushed away.
            max_allowed_stop_price = entry_zone_bound - (min_stop_atr_multiple * atr_14)
            return round(min(high_volume_support, max_allowed_stop_price), 4)

    return round(atr_stop, 4)


def reachable_move(atr_14: float, holding_days: int, max_target_atr_multiple: float) -> float:
    """
    Largest price move worth targeting inside `holding_days`, in dollars.

    max_target_atr_multiple x ATR x sqrt(holding_days). The sqrt is the
    random-walk scaling of volatility with time — a stock does not travel
    ATR x N over N days, it travels roughly ATR x sqrt(N), so a target set as
    a flat multiple of ATR silently gets harder the shorter the window.

    Deliberately a coarse feasibility bound, not a forecast: it answers "is
    this target in the same postcode as what this stock actually does in two
    weeks", which is the question a fixed min_rr multiple never asks.
    """
    if atr_14 <= 0 or holding_days <= 0:
        return float("inf")
    return max_target_atr_multiple * atr_14 * (holding_days ** 0.5)


def compute_target(
    entry: float,
    stop: float,
    low_volume_area_above: Optional[float] = None,
    min_rr: float = 3.0,
    direction: str = "bullish",
    low_volume_area_below: Optional[float] = None,
    atr_14: Optional[float] = None,
    holding_days: Optional[int] = None,
    max_target_atr_multiple: float = 2.5,
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

    atr_14/holding_days/max_target_atr_multiple (2026-08-26, v2.2.104): bound
    the volume-profile target by what the stock can plausibly travel in the
    holding window — see reachable_move(). The volume-profile branch used to
    accept ANY low-volume area beyond the min_rr target, with no upper limit,
    on the reasoning that price moves quickly through thin volume. True in
    principle, but it says nothing about WHEN. Measured live 2026-08-26, QCOM
    drew a low-volume pocket 65.84 away against a 5.63 stop distance — an
    11.69:1 target needing a +39% move, or 3.26x its expected 10-day range,
    inside a 10-day time stop. Every other pick that day sat at 0.79-2.14x.

    An out-of-range volume level is DISCARDED rather than clamped to the
    ceiling: the pocket was the entire justification for reaching past min_rr,
    and if it is unreachable there is no evidence for any intermediate target
    either — so the min_rr target stands. The min_rr target itself is never
    capped: shrinking it would quietly violate the configured minimum R:R,
    and a min_rr target that is itself unreachable means the STOP is too wide
    for the window, which is a sizing question, not a target question.

    Both optional — omit either and the volume-profile branch behaves exactly
    as it did before.
    """
    ceiling = (
        reachable_move(atr_14, holding_days, max_target_atr_multiple)
        if atr_14 is not None and holding_days is not None
        else float("inf")
    )

    if direction == "bearish":
        if stop <= entry:
            return None
        risk_per_share = stop - entry
        min_target = entry - (min_rr * risk_per_share)

        if low_volume_area_below is not None and low_volume_area_below <= min_target:
            if (entry - low_volume_area_below) <= ceiling:
                return round(low_volume_area_below, 4)

        return round(min_target, 4)

    if stop >= entry:
        return None

    risk_per_share = entry - stop
    min_target = entry + (min_rr * risk_per_share)

    if low_volume_area_above is not None and low_volume_area_above >= min_target:
        if (low_volume_area_above - entry) <= ceiling:
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
