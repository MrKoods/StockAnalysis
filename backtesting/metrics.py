"""
Win rate, R:R, drawdown, Sharpe -- confidence calibration, per-regime stats,
stress test results. All metrics computed on the test (out-of-sample) set only.
"""

import math
from pathlib import Path
from typing import Optional

import pandas as pd


def _is_win(o: dict) -> bool:
    """
    A trade is a win if:
    - It hit the target price, OR
    - It was time-stopped out at a profit (pnl_pct > 0).
    Time stops at profit are genuine wins — the strategy made money on the trade.
    """
    if o.get("outcome") == "win":
        return True
    if o.get("outcome") == "time_stop" and float(o.get("pnl_pct", 0.0)) > 0:
        return True
    return False


def compute_win_rate(outcomes: list[dict]) -> float:
    """Compute win rate from list of trade outcome dicts. Returns 0.0 if no trades."""
    if not outcomes:
        return 0.0
    wins = sum(1 for o in outcomes if _is_win(o))
    return wins / len(outcomes)


def compute_avg_rr(outcomes: list[dict]) -> float:
    """
    Compute average achieved R:R ratio for winning trades only.
    Measures how much R winning trades captured on average —
    target hits score ~3.0R, profitable time stops score a partial R.
    """
    wins = [o for o in outcomes if _is_win(o) and "achieved_rr" in o]
    if not wins:
        return 0.0
    return sum(o["achieved_rr"] for o in wins) / len(wins)


def compute_max_drawdown(equity_curve: pd.Series) -> float:
    """
    Peak-to-trough drawdown on the equity curve.
    Returns drawdown as a positive fraction (e.g., 0.15 for 15% drawdown).
    """
    if equity_curve.empty:
        return 0.0
    rolling_max = equity_curve.cummax()
    drawdown = (equity_curve - rolling_max) / rolling_max
    return float(abs(drawdown.min()))


def compute_sharpe(returns: pd.Series, risk_free_rate: float = 0.05) -> float:
    """Annualized Sharpe ratio on daily returns series."""
    if returns.empty or returns.std() == 0:
        return 0.0
    daily_rf = risk_free_rate / 252
    excess = returns - daily_rf
    return float((excess.mean() / returns.std()) * math.sqrt(252))


def per_regime_metrics(outcomes: list[dict]) -> dict:
    """
    Split outcomes by regime and compute metrics for each.
    Model must meet thresholds in all four regimes independently.
    Returns dict: {regime -> {win_rate, avg_rr, trade_count}}
    """
    regimes = {}
    for o in outcomes:
        regime = o.get("regime", "unknown")
        regimes.setdefault(regime, []).append(o)

    result = {}
    for regime, regime_outcomes in regimes.items():
        result[regime] = {
            "win_rate": compute_win_rate(regime_outcomes),
            "avg_rr": compute_avg_rr(regime_outcomes),
            "trade_count": len(regime_outcomes),
        }
    return result


def compute_consecutive_losses(outcomes: list[dict]) -> int:
    """Return the maximum consecutive loss streak in the outcome list."""
    max_consec = 0
    current = 0
    for o in outcomes:
        if _is_win(o):
            current = 0
        else:
            current += 1
            max_consec = max(max_consec, current)
    return max_consec


def run_sensitivity_analysis(
    historical_data: dict,
    thresholds: Optional[list[int]] = None,
) -> pd.DataFrame:
    """
    Run backtest across 5 confidence thresholds (Clarification 3).
    For each threshold: qualifying trades, win rate, avg R:R, signal frequency, max consecutive losses.
    Returns DataFrame with columns: threshold, qualifying_trades, win_rate, avg_rr, signals_per_month, max_consec_losses.
    Saves to backtesting/reports/sensitivity_analysis.csv.
    """
    if thresholds is None:
        thresholds = [85, 87, 90, 92, 95]
    rows = []
    for threshold in thresholds:
        # Filter outcomes from historical_data by confidence threshold
        all_outcomes = historical_data.get("outcomes", [])
        qualifying = [o for o in all_outcomes if float(o.get("confidence", 0)) >= threshold]

        if not qualifying:
            rows.append({
                "threshold": threshold,
                "qualifying_trades": 0,
                "win_rate": 0.0,
                "avg_rr": 0.0,
                "signals_per_month": 0.0,
                "max_consec_losses": 0,
            })
            continue

        months = historical_data.get("test_months", 1)
        rows.append({
            "threshold": threshold,
            "qualifying_trades": len(qualifying),
            "win_rate": round(compute_win_rate(qualifying), 4),
            "avg_rr": round(compute_avg_rr(qualifying), 2),
            "signals_per_month": round(len(qualifying) / max(months, 1), 2),
            "max_consec_losses": compute_consecutive_losses(qualifying),
        })

    df = pd.DataFrame(rows)

    report_dir = Path("backtesting/reports")
    report_dir.mkdir(parents=True, exist_ok=True)
    df.to_csv(report_dir / "sensitivity_analysis.csv", index=False)

    return df


def calibrate_weights(outcomes: list[dict], current_weights: dict) -> dict:
    """
    Calibrate confidence scoring weights using backtesting outcomes on the train set.
    Returns updated weights dict. Changes > 5pp require version increment.

    Strategy: for each sub-signal, compute average contribution in winning vs losing trades.
    Sub-signals that add more value in winners get a slight weight increase.
    Change is capped at 10pp per calibration cycle.
    """
    if not outcomes:
        return current_weights

    new_weights = dict(current_weights)
    wins = [o for o in outcomes if o.get("outcome") == "win"]
    losses = [o for o in outcomes if o.get("outcome") == "loss"]

    for key in current_weights:
        win_vals = [float(o.get(key, 0)) for o in wins if key in o]
        loss_vals = [float(o.get(key, 0)) for o in losses if key in o]

        if not win_vals or not loss_vals:
            continue

        win_avg = sum(win_vals) / len(win_vals)
        loss_avg = sum(loss_vals) / len(loss_vals)

        # If winners have higher sub-signal scores → upweight slightly
        if win_avg > loss_avg:
            delta = min(0.02, (win_avg - loss_avg) / win_avg * 0.05)
        elif loss_avg > win_avg:
            delta = -min(0.02, (loss_avg - win_avg) / loss_avg * 0.05)
        else:
            delta = 0.0

        # Cap at 10pp total change per calibration cycle
        delta = max(-0.10, min(0.10, delta))
        new_weights[key] = round(max(0.0, current_weights[key] + delta), 4)

    return new_weights
