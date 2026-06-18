def compute_rr_ratio(entry: float, stop: float, target: float) -> float:
    """Return the reward-to-risk ratio given entry, stop-loss, and price target."""
    risk = abs(entry - stop)
    if risk == 0.0:
        return 0.0
    return abs(target - entry) / risk


def compute_stop_level(entry: float, atr: float, atr_multiplier: float) -> float:
    """Return a stop-loss level placed ATR-based distance below entry (for a long position)."""
    return entry - atr_multiplier * atr


def compute_target_level(entry: float, stop: float, min_rr: float) -> float:
    """Return the minimum price target required to achieve the specified R:R ratio."""
    risk = abs(entry - stop)
    direction = 1.0 if stop < entry else -1.0
    return entry + direction * risk * min_rr


def meets_minimum_rr(entry: float, stop: float, target: float, min_rr: float) -> bool:
    """Return True if the trade setup meets or exceeds the minimum required R:R threshold."""
    return compute_rr_ratio(entry, stop, target) >= min_rr
