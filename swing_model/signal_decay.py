"""
Re-scores open positions daily; flags early exit when confidence drops significantly
post-entry. Tracks confidence time series for each open position throughout the
5-15 day holding window. Fires early exit Discord alert if confidence drops > 10 points.
"""

from datetime import datetime, timezone
from typing import Optional


def rescore_open_positions(
    open_positions: list[dict],
    current_indicators: dict[str, dict],
    cfg: Optional[dict] = None,
) -> list[dict]:
    """
    Re-score all open positions with fresh indicator data.

    For each position:
    1. Pull current indicator values for that ticker
    2. Recompute confidence score using scoring.py
    3. Compare to entry confidence score
    4. Flag early exit if confidence drop > cfg['signal_decay']['early_exit_confidence_drop']
    5. Update trailing stop level
    6. Check time stop (Day 10 with < 30% of target profit)

    Returns list of updated position dicts with added fields:
    {
        ...original position fields...,
        current_confidence: float,
        confidence_drop: float,
        early_exit_flag: bool,
        time_stop_flag: bool,
        trailing_stop_current: float,
        days_held: int,
        pnl_pct_of_target: float,
        management_action: str,   # 'hold' | 'early_exit' | 'time_stop' | 'profit_target'
    }
    """
    # TODO: Phase 8 — implement daily re-scoring loop
    raise NotImplementedError("Phase 8")


def check_time_stop(
    position: dict,
    pnl_pct_of_target: float,
    day: int,
    time_stop_day: int = 10,
    min_progress_pct: float = 0.30,
) -> bool:
    """
    Return True if time stop should trigger.
    Trigger: day >= time_stop_day AND pnl_pct_of_target < min_progress_pct.
    """
    return day >= time_stop_day and pnl_pct_of_target < min_progress_pct


def compute_pnl_pct_of_target(
    current_price: float,
    entry_price: float,
    target_price: float,
    direction: str,
) -> float:
    """
    What % of the target profit has been achieved?
    Returns 0.0 if no progress, 1.0 if target hit, negative if loss.
    """
    if direction == "bullish":
        price_move = current_price - entry_price
        target_move = target_price - entry_price
    else:
        price_move = entry_price - current_price
        target_move = entry_price - target_price

    if target_move <= 0:
        return 0.0
    return price_move / target_move
