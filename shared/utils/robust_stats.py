"""
Robust (outlier-resistant) statistics — currently just the modified z-score
used to flag an EV/$/day reading that's out of line with a structure's own
trailing history (see paper_runner.py's ev_outlier check). A plain mean/std
z-score is itself corrupted by the outlier it's trying to detect (one huge
value drags the mean toward it and inflates the std, shrinking its own
z-score) — median/MAD is resistant to exactly that.
"""

from typing import Optional

# Iglewicz & Hoaglin's (1993) standard cutoff for the modified z-score — the
# commonly cited threshold for "this observation is probably not part of the
# same distribution," not a value picked to match one specific incident.
DEFAULT_OUTLIER_THRESHOLD = 3.5

# 0.6745 = the 75th percentile of a standard normal distribution — the
# constant that rescales MAD so the modified z-score has the same expected
# scale as a normal-distribution z-score (Iglewicz & Hoaglin, 1993).
_MAD_TO_SIGMA = 0.6745


def robust_z_score(value: float, historical_values: list[float]) -> Optional[float]:
    """
    Modified (MAD-based) z-score of `value` against `historical_values`:
    0.6745 * (value - median) / MAD, where MAD is the median absolute
    deviation from the median. Unlike a mean/std z-score, a single extreme
    historical value can't drag the median or MAD toward it the way it would
    drag a mean and inflate a std — the reference distribution stays
    resistant to the very outliers it's meant to catch.

    Returns None when there isn't enough history to judge from (fewer than 5
    points) or when MAD is 0 (every historical value identical — any
    deviation at all would divide by zero; there's no meaningful "typical
    spread" to compare against).
    """
    if len(historical_values) < 5:
        return None

    sorted_vals = sorted(historical_values)
    n = len(sorted_vals)
    median = (
        sorted_vals[n // 2] if n % 2 == 1
        else (sorted_vals[n // 2 - 1] + sorted_vals[n // 2]) / 2.0
    )

    abs_deviations = sorted([abs(v - median) for v in historical_values])
    mad = (
        abs_deviations[n // 2] if n % 2 == 1
        else (abs_deviations[n // 2 - 1] + abs_deviations[n // 2]) / 2.0
    )
    if mad == 0:
        return None

    return _MAD_TO_SIGMA * (value - median) / mad


def is_outlier(value: float, historical_values: list[float], threshold: float = DEFAULT_OUTLIER_THRESHOLD) -> bool:
    """True when robust_z_score's magnitude clears `threshold`. False (not True)
    when there isn't enough history to judge — silence, not a false alarm, is
    the right default while data is still thin."""
    z = robust_z_score(value, historical_values)
    return z is not None and abs(z) >= threshold
