"""
Compares candidate entry-filter changes against the current baseline by pooling
qualifying trades across all 24 walk-forward windows (2014-2026), instead of
tuning against the single fixed 70/30 test-set split.

Why pooling instead of the fixed split: hand-tuning parameters by repeatedly
re-running against one fixed holdout is exactly the overfitting the 70/30 split
exists to prevent (see CHANGELOG.md v2.2.4). Walk-forward windows are each
validated independently and never used for calibration (run_backtest() only
uses the train split to hold out test data, no weight calibration runs on it),
so pooling their qualifying trades reconstructs a much larger, still-honest
out-of-sample sample than any single slice.

Each variant here is motivated by the diagnostic finding that qualifying-trade
losses take 5-9 days to resolve (not 1-2), and 41% of qualifying trades stall
around 0.88R when the 15-day time stop hits — a signal-conviction pattern, not
a fast-false-breakout pattern. See CHANGELOG.md for the full write-up.
"""

from pathlib import Path

import pandas as pd

from backtesting.backtest_engine import run_walk_forward
from backtesting.metrics import (
    compute_win_rate,
    compute_avg_rr,
    compute_consecutive_losses,
    compute_sharpe,
    compute_deflated_sharpe_ratio,
    _build_equity_curve,
    _trades_per_year,
)
from backtesting.run_backtest import load_historical_data
from shared.utils.logger import get_logger

logger = get_logger(__name__)

VARIANTS = {
    # Pinned explicitly to the pre-v2.2.5/v2.2.6 originals, not {} — since
    # _simulate_test_signals' own defaults have changed twice now (v2.2.5:
    # rsi_max 82->70, v2.2.6: require_confirmation_bar False->True), an
    # empty dict here would silently stop meaning "original baseline" the
    # moment either default next changes.
    "original_baseline_45_82": {"rsi_min": 45.0, "rsi_max": 82.0, "require_confirmation_bar": False},
    "rsi_tightened_45_70_only": {"rsi_min": 45.0, "rsi_max": 70.0, "require_confirmation_bar": False},
    "volume_confirmed_0.5z": {"min_breakout_volume_zscore": 0.5, "require_confirmation_bar": False},
    "current_default_confirmation_bar": {},
    "rsi_tightened_plus_volume": {"rsi_min": 45.0, "rsi_max": 70.0, "min_breakout_volume_zscore": 0.5, "require_confirmation_bar": False},
    # Isolate RSI band alone against today's current live default (confirmation
    # bar required) — original_baseline_45_82 above changes RSI AND drops the
    # confirmation-bar requirement at once, confounding which change did what.
    "rsi_82_confirmation_bar_true": {"rsi_min": 45.0, "rsi_max": 82.0},
    "rsi_75_confirmation_bar_true": {"rsi_min": 45.0, "rsi_max": 75.0},
}


def run_variant_comparison(historical_data: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """
    Run every variant in VARIANTS across all walk-forward windows, pool each
    variant's qualifying trades, and return a comparison DataFrame.

    Includes pooled_sharpe per variant and a deflated-Sharpe/PSR check
    (compute_deflated_sharpe_ratio) against whichever variant has the best
    pooled Sharpe — testing len(VARIANTS) configurations and reporting the
    winner without correcting for having tried that many is the same
    multiple-testing trap run_sensitivity_analysis's threshold sweep has,
    just with filter variants as the trials instead of thresholds.
    """
    rows = []

    for name, signal_kwargs in VARIANTS.items():
        logger.info(f"Running variant: {name} ({signal_kwargs})")
        windows = run_walk_forward(historical_data, signal_kwargs=signal_kwargs, include_outcomes=True)

        pooled = [o for w in windows for o in w.get("outcomes", [])]
        windows_with_trades = [w for w in windows if w["qualifying_trades"] > 0]
        windows_passed = sum(1 for w in windows if w["passed"])

        pooled_chrono = sorted(pooled, key=lambda o: o.get("exit_date") or o.get("signal_date") or "")
        equity_curve = _build_equity_curve(pooled_chrono)
        trade_returns = equity_curve.pct_change().dropna()
        sharpe = compute_sharpe(trade_returns, periods_per_year=_trades_per_year(pooled_chrono)) if pooled_chrono else 0.0

        rows.append({
            "variant": name,
            "pooled_trades": len(pooled),
            "pooled_win_rate": round(compute_win_rate(pooled), 4),
            "pooled_avg_rr": round(compute_avg_rr(pooled), 2),
            "pooled_sharpe": round(sharpe, 2),
            "pooled_max_consec_losses": compute_consecutive_losses(pooled),
            "windows_with_any_trades": len(windows_with_trades),
            "windows_passed": windows_passed,
            "total_windows": len(windows),
        })

    df = pd.DataFrame(rows)

    if not df.empty and (df["pooled_sharpe"] != 0.0).any():
        best_idx = df["pooled_sharpe"].idxmax()
        best_row = df.loc[best_idx]
        dsr = compute_deflated_sharpe_ratio(
            sharpe_ratios=df["pooled_sharpe"].tolist(),
            selected_sharpe=float(best_row["pooled_sharpe"]),
            n_observations=int(best_row["pooled_trades"]),
        )
        df["psr_best_variant_vs_sweep"] = dsr["psr"]
        df["deflated_sharpe_best_variant"] = dsr["deflated_sharpe"]

    report_dir = Path("backtesting/reports")
    report_dir.mkdir(parents=True, exist_ok=True)
    df.to_csv(report_dir / "entry_filter_variants.csv", index=False)

    return df


def main() -> None:
    historical_data = load_historical_data("data/historical")
    if not historical_data:
        logger.error("No historical data loaded. Place {ticker}.csv files in data/historical/")
        return

    df = run_variant_comparison(historical_data)
    print("\nEntry Filter Variant Comparison (pooled across 24 walk-forward windows):\n")
    print(df.to_string(index=False))
    print("\nSaved to backtesting/reports/entry_filter_variants.csv")


if __name__ == "__main__":
    main()
