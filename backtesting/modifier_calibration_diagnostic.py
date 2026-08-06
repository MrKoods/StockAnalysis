"""
Measures whether the 6 scoring modifiers' magnitudes (config/swing_config.yaml
modifiers block) are actually backed by real outcome evidence. Only
seasonality.monthly_modifiers carries a comment claiming Phase-12 backtest
calibration; regime, sector_rotation, earnings, cross_ticker, and
macro_overlay's bounds are hand-set round numbers with no such lineage.

Three of the six (sector_rotation_modifier, earnings_modifier,
cross_ticker_modifier) are hardcoded to 0.0 in backtesting/simulation.py's
replay (no historical sector-benchmark-aligned rotation signal, earnings
calendar, or cross-ticker joint data covering the full backtest window) —
this diagnostic can say nothing about those three; it reports that
explicitly rather than silently omitting them. The other three (regime,
seasonality, macro) DO vary during replay, so this measures each one's real
bucket-level win rate/avg R against its own configured point swing.

Usage: python -m backtesting.modifier_calibration_diagnostic
"""

from typing import Optional

import pandas as pd

from backtesting.backtest_engine import _get_test_outcomes, _SECTOR_DATASETS
from backtesting.metrics import compute_win_rate, compute_avg_rr
from backtesting.run_backtest import load_historical_data
from shared.utils.logger import get_logger

logger = get_logger(__name__)

# The 3 modifiers backtesting/simulation.py always hardcodes to 0.0 — no
# historical data path exists yet to exercise them, so no amount of outcome
# analysis on backtest replay can say anything about their calibration.
_NEVER_EXERCISED_IN_BACKTEST = ("sector_rotation_modifier", "earnings_modifier", "cross_ticker_modifier")

# The 3 that do vary during replay, per simulation.py's own outcome fields.
_EXERCISED_MODIFIERS = ("regime_modifier", "seasonality_modifier", "macro_modifier")


def collect_pooled_outcomes(config_path: str = "config/swing_config.yaml") -> list[dict]:
    """Same pooling as fit_win_probability_calibration.py — every sector's
    out-of-sample outcomes, unfiltered by confidence threshold."""
    pooled: list[dict] = []
    for sector, (data_dir, benchmark) in _SECTOR_DATASETS.items():
        historical_data = load_historical_data(data_dir)
        if not historical_data:
            logger.warning(f"{sector}: no historical data in {data_dir}, skipping")
            continue
        outcomes, _months, _dates, _cutoff = _get_test_outcomes(
            historical_data, config_path, train_split=0.70, benchmark_ticker=benchmark,
        )
        pooled.extend(outcomes)
    return pooled


def bucket_outcomes_by_modifier_sign(outcomes: list[dict], modifier_key: str) -> pd.DataFrame:
    """
    Splits outcomes into negative / zero / positive buckets by `modifier_key`'s
    value on each outcome, reporting win_rate/avg_rr/trade_count per bucket.
    The question this answers: does a negative modifier bucket actually show
    worse real outcomes than the zero or positive buckets, and is the *size*
    of that gap consistent with the modifier's configured point swing — or is
    the modifier's real predictive power much smaller (or larger, or absent)
    than its point allocation implies?
    """
    rows = []
    for label, predicate in (
        ("negative", lambda v: v < 0),
        ("zero", lambda v: v == 0),
        ("positive", lambda v: v > 0),
    ):
        bucket = [o for o in outcomes if modifier_key in o and predicate(float(o[modifier_key]))]
        rows.append({
            "modifier": modifier_key,
            "bucket": label,
            "n_trades": len(bucket),
            "win_rate": round(compute_win_rate(bucket), 4) if bucket else None,
            "avg_rr": round(compute_avg_rr(bucket), 2) if bucket else None,
        })
    return pd.DataFrame(rows)


def main() -> None:
    outcomes = collect_pooled_outcomes()
    if not outcomes:
        print("No historical outcomes across any sector — nothing to measure.")
        return

    print(f"\n=== Modifier calibration diagnostic — {len(outcomes)} pooled out-of-sample outcomes ===\n")

    print(
        f"NOT MEASURABLE from backtest data: {', '.join(_NEVER_EXERCISED_IN_BACKTEST)} — "
        "backtesting/simulation.py hardcodes these to 0.0 during replay (no historical "
        "sector-rotation-vs-benchmark alignment, earnings calendar, or cross-ticker joint "
        "data covering the full backtest window exists yet). Their config-file magnitudes "
        "are unvalidated by ANY data source, not just uncalibrated by one.\n"
    )

    report_rows = []
    for modifier_key in _EXERCISED_MODIFIERS:
        df = bucket_outcomes_by_modifier_sign(outcomes, modifier_key)
        print(f"--- {modifier_key} ---")
        print(df.to_string(index=False))
        neg = df[df["bucket"] == "negative"]
        pos = df[df["bucket"] == "positive"]
        if not neg.empty and not pos.empty and neg.iloc[0]["win_rate"] is not None and pos.iloc[0]["win_rate"] is not None:
            gap = pos.iloc[0]["win_rate"] - neg.iloc[0]["win_rate"]
            direction = "consistent with" if gap > 0 else "INVERTED from"
            print(f"  positive-minus-negative win-rate gap: {gap:+.4f} ({direction} the modifier's intended direction)\n")
        else:
            print()
        report_rows.append(df)

    if report_rows:
        combined = pd.concat(report_rows, ignore_index=True)
        from pathlib import Path
        report_dir = Path("backtesting/reports")
        report_dir.mkdir(parents=True, exist_ok=True)
        combined.to_csv(report_dir / "modifier_calibration_diagnostic.csv", index=False)
        print("Saved to backtesting/reports/modifier_calibration_diagnostic.csv")


if __name__ == "__main__":
    main()
