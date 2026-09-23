"""
Live-data-driven follow-up to bearish_exit_sizing_sweep.py — that sweep found
evidence the fixed 3R target might be oversized for the bearish side. A
2026-09-23 review of real paper-trading data (33 resolved trades, both
directions, both tracks) found the same symptom on the BULLISH side too: real
max-favorable-excursion averaged 1.3x ATR (median 0.78x) against a target
sitting around 6x ATR, and stop width vs. realized excursion were
uncorrelated (r=0.04) — ruling out "the stop is too wide" (compute_target's
own documented reasoning for never capping the min_rr fallback branch) as the
explanation for either direction.

This sweeps min_rr symmetrically across BOTH directions at once (via the new
min_rr_bullish/min_rr_bearish params on _simulate_test_signals — see its
docstring), using the same walk-forward-pooled methodology as the bearish
sweeps, across all 4 sector datasets. Unlike bearish_exit_sizing_sweep.py
(which pools bearish-only outcomes), this pools ALL outcomes — the question
here is what target sizing maximizes expectancy for the strategy as traded,
not just one direction's slice of it.

Usage: python -m backtesting.min_rr_sweep
"""

from pathlib import Path

import pandas as pd

from backtesting.backtest_engine import _SECTOR_DATASETS
from backtesting.walk_forward import run_walk_forward
from backtesting.metrics import (
    compute_win_rate, compute_avg_rr, compute_sharpe, compute_r_multiples,
    bootstrap_expectancy_ci, _build_equity_curve, _trades_per_year,
)
from backtesting.run_backtest import load_historical_data
from shared.utils.logger import get_logger

logger = get_logger(__name__)

VARIANTS = {
    "baseline_3.0R": {"min_rr_bullish": 3.0, "min_rr_bearish": 3.0},
    "target_2.5R": {"min_rr_bullish": 2.5, "min_rr_bearish": 2.5},
    "target_2.0R": {"min_rr_bullish": 2.0, "min_rr_bearish": 2.0},
    "target_1.5R": {"min_rr_bullish": 1.5, "min_rr_bearish": 1.5},
    "target_1.2R": {"min_rr_bullish": 1.2, "min_rr_bearish": 1.2},
    "target_1.0R": {"min_rr_bullish": 1.0, "min_rr_bearish": 1.0},
}


def _pooled_metrics(outcomes: list[dict]) -> dict:
    if not outcomes:
        return {"n_trades": 0, "win_rate": None, "avg_rr": None, "sharpe": None,
                "expectancy_mean_r": None, "expectancy_ci_lower": None, "expectancy_ci_upper": None}
    chrono = sorted(outcomes, key=lambda o: o.get("exit_date") or o.get("signal_date") or "")
    equity_curve = _build_equity_curve(chrono)
    trade_returns = equity_curve.pct_change().dropna()
    sharpe = compute_sharpe(trade_returns, periods_per_year=_trades_per_year(chrono)) if len(chrono) > 1 else 0.0
    r_multiples = compute_r_multiples(outcomes)
    ci = bootstrap_expectancy_ci(r_multiples)
    return {
        "n_trades": len(outcomes),
        "win_rate": round(compute_win_rate(outcomes), 4),
        "avg_rr": round(compute_avg_rr(outcomes), 2),
        "sharpe": round(sharpe, 2),
        "expectancy_mean_r": round(ci["mean_r"], 3),
        "expectancy_ci_lower": round(ci["ci_lower"], 3),
        "expectancy_ci_upper": round(ci["ci_upper"], 3),
    }


def run_sweep() -> pd.DataFrame:
    rows = []
    for variant_name, signal_kwargs in VARIANTS.items():
        pooled_all_sectors = []
        for sector, (data_dir, benchmark) in _SECTOR_DATASETS.items():
            historical_data = load_historical_data(data_dir)
            if not historical_data:
                continue
            kwargs = {**signal_kwargs, "benchmark_ticker": benchmark}
            logger.info(f"{variant_name} / {sector}: running walk-forward with {kwargs}")
            windows = run_walk_forward(historical_data, signal_kwargs=kwargs, include_outcomes=True)
            outcomes = [o for w in windows for o in w.get("outcomes", [])]
            metrics = _pooled_metrics(outcomes)
            rows.append({"variant": variant_name, "sector": sector, **metrics})
            pooled_all_sectors.extend(outcomes)

        if pooled_all_sectors:
            rows.append({
                "variant": variant_name, "sector": "ALL (pooled)",
                **_pooled_metrics(pooled_all_sectors),
            })

    df = pd.DataFrame(rows)
    report_dir = Path("backtesting/reports")
    report_dir.mkdir(parents=True, exist_ok=True)
    df.to_csv(report_dir / "min_rr_sweep.csv", index=False)
    return df


def main() -> None:
    print("Sweeping min_rr (both directions, symmetric) against real historical data, "
          "pooled across walk-forward windows, all 4 sectors...\n")
    df = run_sweep()
    pd.set_option("display.width", 200)
    print(df.to_string(index=False))
    print("\nSaved to backtesting/reports/min_rr_sweep.csv")

    pooled_only = df[df["sector"] == "ALL (pooled)"].sort_values("expectancy_ci_lower", ascending=False)
    if not pooled_only.empty:
        print("\n=== Pooled-across-sectors ranking (by expectancy CI lower bound — the real go-live metric) ===\n")
        print(pooled_only.to_string(index=False))


if __name__ == "__main__":
    main()
