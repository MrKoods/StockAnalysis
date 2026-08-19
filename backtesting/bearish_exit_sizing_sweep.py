"""
Follow-up to bearish_rsi_band_sweep.py (CHANGELOG v2.2.58): the RSI band sweep
found raising the oversold floor improves bearish win rate (32%->43%) but
Sharpe stays deeply negative throughout — the entry filter isn't the main
problem. This sweeps the EXIT side instead: min_rr_bearish/
stop_atr_multiplier_bearish (see _simulate_test_signals' docstring),
testing whether a breakdown simply doesn't continue down far/fast enough
within the 15-day holding period to reach an ATR-sized 3R target the way a
breakout continues up (avg R:R sat at 0.7-1.3 against the 3R target with a
large time_stop share in the original result — consistent with an oversized
target, not a bad entry).

Uses the same walk-forward-pooled methodology as bearish_rsi_band_sweep.py
and entry_filter_variants.py, across all 4 sector datasets. Holds the RSI
band at the best-Sharpe candidate from the prior sweep (30-55) rather than
the original 18-55 mirror, so this isolates the exit-sizing effect on top of
that finding instead of confounding the two.

Usage: python -m backtesting.bearish_exit_sizing_sweep
"""

from pathlib import Path

import pandas as pd

from backtesting.backtest_engine import _SECTOR_DATASETS
from backtesting.walk_forward import run_walk_forward
from backtesting.metrics import compute_win_rate, compute_avg_rr, compute_sharpe, _build_equity_curve, _trades_per_year
from backtesting.run_backtest import load_historical_data
from shared.utils.logger import get_logger

logger = get_logger(__name__)

_BASE_RSI = {"rsi_min_bearish": 30.0, "rsi_max_bearish": 55.0}

VARIANTS = {
    "baseline_3R_2xATR": {**_BASE_RSI, "min_rr_bearish": 3.0, "stop_atr_multiplier_bearish": 2.0},
    "target_2R": {**_BASE_RSI, "min_rr_bearish": 2.0, "stop_atr_multiplier_bearish": 2.0},
    "target_1.5R": {**_BASE_RSI, "min_rr_bearish": 1.5, "stop_atr_multiplier_bearish": 2.0},
    "target_1R": {**_BASE_RSI, "min_rr_bearish": 1.0, "stop_atr_multiplier_bearish": 2.0},
    "tighter_stop_1.5xATR_3R": {**_BASE_RSI, "min_rr_bearish": 3.0, "stop_atr_multiplier_bearish": 1.5},
    "tighter_stop_1.5xATR_2R": {**_BASE_RSI, "min_rr_bearish": 2.0, "stop_atr_multiplier_bearish": 1.5},
    "tighter_stop_1xATR_1.5R": {**_BASE_RSI, "min_rr_bearish": 1.5, "stop_atr_multiplier_bearish": 1.0},
}


def _pooled_bearish_metrics(windows: list[dict]) -> dict:
    pooled = [o for w in windows for o in w.get("outcomes", []) if o.get("direction") == "bearish"]
    if not pooled:
        return {"n_trades": 0, "win_rate": None, "avg_rr": None, "sharpe": None}
    chrono = sorted(pooled, key=lambda o: o.get("exit_date") or o.get("signal_date") or "")
    equity_curve = _build_equity_curve(chrono)
    trade_returns = equity_curve.pct_change().dropna()
    sharpe = compute_sharpe(trade_returns, periods_per_year=_trades_per_year(chrono)) if len(chrono) > 1 else 0.0
    return {
        "n_trades": len(pooled),
        "win_rate": round(compute_win_rate(pooled), 4),
        "avg_rr": round(compute_avg_rr(pooled), 2),
        "sharpe": round(sharpe, 2),
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
            metrics = _pooled_bearish_metrics(windows)
            rows.append({"variant": variant_name, "sector": sector, **metrics})
            pooled_all_sectors.extend(
                o for w in windows for o in w.get("outcomes", []) if o.get("direction") == "bearish"
            )

        if pooled_all_sectors:
            chrono = sorted(pooled_all_sectors, key=lambda o: o.get("exit_date") or o.get("signal_date") or "")
            equity_curve = _build_equity_curve(chrono)
            trade_returns = equity_curve.pct_change().dropna()
            sharpe = compute_sharpe(trade_returns, periods_per_year=_trades_per_year(chrono)) if len(chrono) > 1 else 0.0
            rows.append({
                "variant": variant_name, "sector": "ALL (pooled)",
                "n_trades": len(pooled_all_sectors),
                "win_rate": round(compute_win_rate(pooled_all_sectors), 4),
                "avg_rr": round(compute_avg_rr(pooled_all_sectors), 2),
                "sharpe": round(sharpe, 2),
            })

    df = pd.DataFrame(rows)
    report_dir = Path("backtesting/reports")
    report_dir.mkdir(parents=True, exist_ok=True)
    df.to_csv(report_dir / "bearish_exit_sizing_sweep.csv", index=False)
    return df


def main() -> None:
    print("Sweeping bearish exit sizing (min_rr_bearish/stop_atr_multiplier_bearish) "
          "against real historical data, pooled across walk-forward windows, all 4 sectors...\n")
    df = run_sweep()
    pd.set_option("display.width", 160)
    print(df.to_string(index=False))
    print("\nSaved to backtesting/reports/bearish_exit_sizing_sweep.csv")

    pooled_only = df[df["sector"] == "ALL (pooled)"].sort_values("sharpe", ascending=False)
    if not pooled_only.empty:
        print("\n=== Pooled-across-sectors ranking (by Sharpe) ===\n")
        print(pooled_only.to_string(index=False))


if __name__ == "__main__":
    main()
