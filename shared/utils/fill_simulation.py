"""
SHARED: Entry-zone fill confirmation — walks bars looking for the first one
where price actually trades into a signal's entry zone, the same real-world
"is this a filled position or a still-pending conditional order" question
paper trading and the backtest both need to answer identically.

Extracted from paper_trading/paper_updater.py (2026-08-19) so backtesting/
simulation.py can share the exact same fill logic instead of assuming every
signal fills at the signal bar's own close — a systematic optimism bias
toward breakouts that gap and run without ever pulling back into the zone
(see Signal Integrity Audit finding A.1). Two independent copies of this
logic would be a parity bug waiting to happen the first time either one
changed; one shared function structurally can't drift from itself.
"""

from typing import Optional

import pandas as pd

# Trading days a breakout/breakdown entry order is allowed to sit unfilled
# before the signal is treated as stale and expired — no capital was ever
# really at risk. Matches paper_trading/paper_updater.py's own constant.
FILL_WINDOW_DAYS = 5


def find_fill(
    df: pd.DataFrame,
    entry_zone_lower: float,
    entry_zone_upper: float,
    direction: str = "bullish",
    window_days: int = FILL_WINDOW_DAYS,
) -> Optional[dict]:
    """
    Walk bars chronologically looking for the first bar where price actually
    trades into the entry zone. Bullish zones sit at/above the price at
    signal time (breakout trigger), so they fill when price rises into them
    (High >= entry_zone_lower); bearish zones sit at/below it (breakdown
    trigger), filling when price falls into them (Low <= entry_zone_upper).

    Returns:
      {"fill_date": Timestamp, "fill_price": float, "bars_from_fill": df from
        that bar onward} on fill
      {"expired": True, "last_date": Timestamp} if window_days pass with no fill
      None if still inside the window and not filled yet (caller should wait)

    fill_price is the boundary that was actually confirmed reached (the
    trigger price), UNLESS the bar's Open already gapped past it — same
    "worse of trigger-vs-open" convention outcome resolution uses for a stop
    hit.
    """
    bearish = direction == "bearish"
    trading_days = 0

    for bar_date, bar in df.iterrows():
        trading_days += 1
        high = float(bar["High"])
        low = float(bar["Low"])
        open_px = float(bar["Open"])

        filled = (low <= entry_zone_upper) if bearish else (high >= entry_zone_lower)
        if filled:
            fill_price = min(entry_zone_upper, open_px) if bearish else max(entry_zone_lower, open_px)
            return {
                "fill_date": bar_date,
                "fill_price": fill_price,
                "bars_from_fill": df[df.index >= bar_date],
            }

        if trading_days >= window_days:
            return {"expired": True, "last_date": bar_date}

    return None  # Still within the fill window, not triggered yet
