"""
Win rate, R:R, drawdown, Sharpe -- confidence calibration, per-regime stats,
stress test results. All metrics computed on the test (out-of-sample) set only.
"""

import math
from pathlib import Path
from typing import Optional

import numpy as np
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


def compute_r_multiples(outcomes: list[dict]) -> list[float]:
    """
    Per-trade achieved R multiple for every outcome (wins negative-free, losses
    negative) — unlike compute_avg_rr, which only averages winning trades to
    describe "how much winners capture," this is every qualifying trade's
    contribution to expectancy, win or loss.
    """
    return [float(o["achieved_rr"]) for o in outcomes if "achieved_rr" in o]


def bootstrap_expectancy_ci(
    r_multiples: list[float],
    n_bootstrap: int = 10000,
    ci: float = 0.95,
    seed: Optional[int] = 42,
) -> dict:
    """
    Bootstrap confidence interval on mean per-trade R-expectancy.

    Resamples r_multiples with replacement n_bootstrap times, computing the
    mean each time, then reads off the (1-ci)/2 and 1-(1-ci)/2 percentiles as
    the CI bounds. This answers "how confident can we be the true expectancy
    is above zero (or some threshold)" — a flat win-rate/R:R pair alone can't,
    since it says nothing about sample-size-driven uncertainty and can't be
    satisfied by mutually offsetting numbers the way e.g. "80% win rate at a
    1.8 average R:R" can look decisive while still resting on a small sample.

    seed defaults to a fixed value (not None) so this function is deterministic
    across repeated calls with the same input — this gates a real go-live
    decision, and a pass/fail flipping between runs on the same data purely
    from resampling noise would undermine trust in the gate itself. Pass
    seed=None for a fresh random draw if ever needed for research purposes.

    Returns {"mean_r": ..., "ci_lower": ..., "ci_upper": ..., "n_trades": ...}.
    All fields are 0.0 (n_trades=0) when r_multiples is empty.
    """
    if not r_multiples:
        return {"mean_r": 0.0, "ci_lower": 0.0, "ci_upper": 0.0, "n_trades": 0}

    values = np.array(r_multiples, dtype=float)
    rng = np.random.default_rng(seed)
    boot_means = np.empty(n_bootstrap)
    for i in range(n_bootstrap):
        sample = rng.choice(values, size=len(values), replace=True)
        boot_means[i] = sample.mean()

    alpha = (1.0 - ci) / 2.0
    return {
        "mean_r": float(values.mean()),
        "ci_lower": float(np.percentile(boot_means, alpha * 100)),
        "ci_upper": float(np.percentile(boot_means, (1.0 - alpha) * 100)),
        "n_trades": len(r_multiples),
    }


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


def compute_sharpe(returns: pd.Series, risk_free_rate: float = 0.05, periods_per_year: float = 252) -> float:
    """
    Annualized Sharpe ratio. `periods_per_year` must match what one step in `returns`
    represents: 252 for a true daily-returns series, or the actual observed trade
    frequency when each step is one trade rather than one calendar day (a trade-level
    equity curve stepped through sqrt(252) would overstate annualized Sharpe by
    treating ~149 trades/multi-year backtest as if they were 252 independent
    observations per year).
    """
    if returns.empty or returns.std() == 0:
        return 0.0
    period_rf = risk_free_rate / periods_per_year
    excess = returns - period_rf
    return float((excess.mean() / returns.std()) * math.sqrt(periods_per_year))


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
    outcomes: list[dict],
    test_months: float = 1.0,
    thresholds: Optional[list[int]] = None,
) -> pd.DataFrame:
    """
    Run backtest across 5 confidence thresholds (Clarification 3).
    For each threshold: qualifying trades, win rate, avg R:R, signal frequency, max consecutive losses.

    `outcomes` should be the full unfiltered out-of-sample signal set (see
    backtest_engine._get_test_outcomes) — this function does the threshold
    filtering itself, once per threshold, rather than expecting pre-filtered input.

    Returns DataFrame with columns: threshold, qualifying_trades, win_rate, avg_rr, signals_per_month, max_consec_losses.
    Saves to backtesting/reports/sensitivity_analysis.csv.
    """
    if thresholds is None:
        thresholds = [85, 87, 90, 92, 95]
    rows = []
    for threshold in thresholds:
        qualifying = [o for o in outcomes if float(o.get("confidence", 0)) >= threshold]

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

        rows.append({
            "threshold": threshold,
            "qualifying_trades": len(qualifying),
            "win_rate": round(compute_win_rate(qualifying), 4),
            "avg_rr": round(compute_avg_rr(qualifying), 2),
            "signals_per_month": round(len(qualifying) / max(test_months, 1.0), 2),
            "max_consec_losses": compute_consecutive_losses(qualifying),
        })

    df = pd.DataFrame(rows)

    report_dir = Path("backtesting/reports")
    report_dir.mkdir(parents=True, exist_ok=True)
    df.to_csv(report_dir / "sensitivity_analysis.csv", index=False)

    return df


def _trades_per_year(outcomes: list[dict]) -> float:
    """
    Actual trade frequency, for Sharpe annualization. An equity curve stepped one
    point per trade is not a daily series — sqrt(252) would treat ~149 trades over
    a multi-year backtest as if they were 252 independent observations every year.
    Falls back to 252 (the old behavior) when there isn't enough date info to infer
    a real trade frequency, rather than raising or silently returning 0.
    """
    dates = []
    for o in outcomes:
        try:
            dates.append(pd.Timestamp(o.get("exit_date")))
        except Exception:
            continue
    if len(dates) < 2:
        return 252.0
    span_years = (max(dates) - min(dates)).days / 365.25
    if span_years <= 0:
        return 252.0
    return len(outcomes) / span_years


def _build_equity_curve(outcomes: list[dict], starting_equity: float = 15000.0) -> pd.Series:
    """Build equity curve from ordered trade outcomes."""
    equity = starting_equity
    values = [equity]

    for o in outcomes:
        pnl_pct = float(o.get("pnl_pct", 0.0))
        risk_pct = 0.01  # Fixed 1% risk per trade
        risk_dollars = equity * risk_pct
        entry = o.get("entry_price", 1.0) or 1.0
        stop = o.get("stop", entry * 0.97) or entry * 0.97

        # Normalize: pnl as fraction of risk
        risk_dist = abs(float(entry) - float(stop)) / float(entry) if float(entry) > 0 else 0.03
        dollar_pnl = risk_dollars * (pnl_pct / risk_dist) if risk_dist > 0 else risk_dollars * pnl_pct
        equity += dollar_pnl
        values.append(max(0.0, equity))

    if not values:
        return pd.Series([starting_equity])
    return pd.Series(values)


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
