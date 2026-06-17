# DAY-ONLY: Intraday-specific indicator math — VWAP, opening range, and relative volume.
# These calculations only make sense on intraday bar data; they have no swing model equivalent.


def compute_vwap(bars: list[dict]) -> float:
    """Return the volume-weighted average price across all bars from market open to the current bar."""
    pass


def compute_opening_range(bars: list[dict], range_minutes: int) -> dict:
    """Return the high and low of the opening range defined by the first N minutes after open."""
    pass


def compute_relative_volume(current_volume: float, same_time_yesterday_volume: float) -> float:
    """Return today's cumulative volume relative to the same elapsed time yesterday (ratio)."""
    pass


def is_above_vwap(current_price: float, vwap: float, tolerance_pct: float = 0.0) -> bool:
    """Return True if current price is above VWAP, with optional tolerance band for pullback-to-VWAP holds."""
    pass


def broke_opening_range_high(current_price: float, opening_range: dict) -> bool:
    """Return True if the current price has broken above the opening range high."""
    pass


def broke_opening_range_low(current_price: float, opening_range: dict) -> bool:
    """Return True if the current price has broken below the opening range low."""
    pass
