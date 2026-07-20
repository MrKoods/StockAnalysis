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
from backtesting.metrics import compute_win_rate, compute_avg_rr, compute_consecutive_losses
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
}


def run_variant_comparison(historical_data: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """
    Run every variant in VARIANTS across all walk-forward windows, pool each
    variant's qualifying trades, and return a comparison DataFrame.
    """
    rows = []

    for name, signal_kwargs in VARIANTS.items():
        logger.info(f"Running variant: {name} ({signal_kwargs})")
        windows = run_walk_forward(historical_data, signal_kwargs=signal_kwargs, include_outcomes=True)

        pooled = [o for w in windows for o in w.get("outcomes", [])]
        windows_with_trades = [w for w in windows if w["qualifying_trades"] > 0]
        windows_passed = sum(1 for w in windows if w["passed"])

        rows.append({
            "variant": name,
            "pooled_trades": len(pooled),
            "pooled_win_rate": round(compute_win_rate(pooled), 4),
            "pooled_avg_rr": round(compute_avg_rr(pooled), 2),
            "pooled_max_consec_losses": compute_consecutive_losses(pooled),
            "windows_with_any_trades": len(windows_with_trades),
            "windows_passed": windows_passed,
            "total_windows": len(windows),
        })

    df = pd.DataFrame(rows)

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
