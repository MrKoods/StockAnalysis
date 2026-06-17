# SHARED: Risk/reward ratio calculation and stop/target level math.
# The same formula applies to swing and day candidates — only the inputs differ (support/resistance
# levels, position size, and minimum R:R threshold come from each model's config).


def compute_rr_ratio(entry: float, stop: float, target: float) -> float:
    """Return the reward-to-risk ratio given entry, stop-loss, and price target."""
    pass


def compute_stop_level(entry: float, atr: float, atr_multiplier: float) -> float:
    """Return a stop-loss level placed ATR-based distance below (long) or above (short) entry."""
    pass


def compute_target_level(entry: float, stop: float, min_rr: float) -> float:
    """Return the minimum price target required to achieve the specified R:R ratio."""
    pass


def meets_minimum_rr(entry: float, stop: float, target: float, min_rr: float) -> bool:
    """Return True if the trade setup meets or exceeds the minimum required R:R threshold."""
    pass
