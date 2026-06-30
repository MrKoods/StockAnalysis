"""
Forward-testing win rate, R:R, and EV vs. theoretical.
Pass/fail criteria for Phase 13 go-live decision.

Pass criteria (all three required simultaneously):
- Win rate >= 80% sustained over minimum 60 trading days
- Average R:R >= 1:3 maintained
- Actual slippage within 10% of modeled estimates over the same period
"""

from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd


_PASS_CRITERIA = {
    "min_win_rate": 0.80,
    "min_avg_rr": 3.0,
    "max_slippage_excess_pct": 0.10,
    "min_trading_days": 60,
}


def evaluate_paper_trading_pass(
    trade_outcomes: list[dict],
    fill_log: list[dict],
    trading_days_elapsed: int,
) -> dict:
    """
    Evaluate whether paper trading has passed the Phase 13 go-live criteria.

    Returns dict:
    {
        overall_pass: bool,
        win_rate: float,
        win_rate_pass: bool,
        avg_rr: float,
        rr_pass: bool,
        avg_slippage_excess: float,
        slippage_pass: bool,
        trading_days_elapsed: int,
        duration_pass: bool,
        failures: list[str],
    }
    """
    failures = []

    # Win rate
    wins = sum(1 for o in trade_outcomes if o.get("outcome") == "win")
    win_rate = wins / len(trade_outcomes) if trade_outcomes else 0.0
    win_rate_pass = win_rate >= _PASS_CRITERIA["min_win_rate"]
    if not win_rate_pass:
        failures.append(f"win_rate_{win_rate:.1%}_below_80pct")

    # Average R:R — measured on winning trades only (avg win / 1 unit risk)
    rr_values = [float(o.get("achieved_rr", 0.0)) for o in trade_outcomes if o.get("outcome") == "win"]
    avg_rr = sum(rr_values) / len(rr_values) if rr_values else 0.0
    rr_pass = avg_rr >= _PASS_CRITERIA["min_avg_rr"]
    if not rr_pass:
        failures.append(f"avg_rr_{avg_rr:.2f}_below_3.0")

    # Slippage
    slippage_excess = _compute_slippage_excess(fill_log)
    slippage_pass = slippage_excess <= _PASS_CRITERIA["max_slippage_excess_pct"]
    if not slippage_pass:
        failures.append(f"slippage_excess_{slippage_excess:.1%}_above_10pct")

    # Duration
    duration_pass = trading_days_elapsed >= _PASS_CRITERIA["min_trading_days"]
    if not duration_pass:
        failures.append(f"only_{trading_days_elapsed}_trading_days_need_60")

    overall_pass = win_rate_pass and rr_pass and slippage_pass and duration_pass

    return {
        "overall_pass": overall_pass,
        "win_rate": round(win_rate, 4),
        "win_rate_pass": win_rate_pass,
        "avg_rr": round(avg_rr, 2),
        "rr_pass": rr_pass,
        "avg_slippage_excess": round(slippage_excess, 4),
        "slippage_pass": slippage_pass,
        "trading_days_elapsed": trading_days_elapsed,
        "duration_pass": duration_pass,
        "failures": failures,
    }


def compute_forward_ev_accuracy(
    outcomes: list[dict],
) -> float:
    """
    Compare actual trade outcomes against theoretical EV from alert time.
    Returns ratio of actual_avg_pnl / theoretical_ev (1.0 = perfect calibration).
    """
    if not outcomes:
        return 0.0

    actual_pnls = [float(o.get("pnl_pct", 0.0)) for o in outcomes]
    theoretical_evs = [float(o.get("theoretical_ev", 0.0)) for o in outcomes]

    actual_avg = sum(actual_pnls) / len(actual_pnls) if actual_pnls else 0.0
    theoretical_avg = sum(theoretical_evs) / len(theoretical_evs) if theoretical_evs else 0.0

    if theoretical_avg == 0:
        return 0.0
    return round(actual_avg / theoretical_avg, 4)


def _compute_slippage_excess(fill_log: list[dict]) -> float:
    """
    Compute how much actual slippage exceeded the modeled slippage estimate.
    Returns excess as a fraction (0.0 = on-model, 0.15 = 15% worse than modeled).
    """
    if not fill_log:
        return 0.0

    actual_slippages = [abs(float(f.get("slippage_pct", 0.0))) for f in fill_log]
    modeled_slippages = [abs(float(f.get("modeled_slippage_pct", 0.005))) for f in fill_log]

    avg_actual = sum(actual_slippages) / len(actual_slippages)
    avg_modeled = sum(modeled_slippages) / len(modeled_slippages)

    if avg_modeled <= 0:
        return 0.0

    excess = (avg_actual - avg_modeled) / avg_modeled
    return max(0.0, excess)
