"""
Answers two open design questions from the 2026-08-15 whole-model audit
(CHANGELOG v2.2.55) with real historical data instead of waiting on live
paper-trading history to accumulate:

1. Does the shared 40/20/15/15/10 category weighting actually perform the
   same across all 4 sectors, or is one sector's result propping up (or
   hiding) another's in the pooled numbers run_multi_sector_backtest()
   reports? (per_sector_breakdown)

2. Would gating on Technical — requiring a minimum technical_total before a
   signal can qualify at all, instead of letting other categories/modifiers
   buy up a mediocre setup — actually improve win rate/expectancy, or just
   shrink the trade count for no real benefit? (technical_gate_sweep)

Both are read-only research against existing historical data
(data/historical*/) — no scoring/config changes, same pattern as
modifier_calibration_diagnostic.py and threshold_optimization_analysis.py.

Usage: python -m backtesting.architecture_diagnostic
"""

import pandas as pd

from backtesting.backtest_engine import _get_test_outcomes, _SECTOR_DATASETS
from backtesting.metrics import (
    compute_win_rate,
    compute_avg_rr,
    compute_r_multiples,
    bootstrap_expectancy_ci,
    compute_sharpe,
    compute_max_drawdown,
    _build_equity_curve,
    _trades_per_year,
)
from backtesting.run_backtest import load_historical_data
from swing_model.scoring import TECHNICAL_MAX, CONFIDENCE_THRESHOLD
from shared.utils.logger import get_logger

logger = get_logger(__name__)

# 2026-08-23: was hardcoded 90.0 with a comment claiming it "matches
# run_backtest()'s own qualifying bar" — true when written, silently false
# since v2.2.46 lowered the real threshold to 70 (backtest_engine.py's own
# copy wasn't fixed until v2.2.75, and this file's copy was missed then too).
# Every per-sector Sharpe/win-rate number this tool has ever produced —
# including the "3 of 4 sectors fail independently" finding — was computed
# against the wrong population. Now imports the real constant so the two
# can't drift apart again.
_CONFIDENCE_THRESHOLD_BACKTEST = CONFIDENCE_THRESHOLD


def collect_per_sector_outcomes(config_path: str = "config/swing_config.yaml") -> dict[str, list[dict]]:
    """Same replay as modifier_calibration_diagnostic.collect_pooled_outcomes,
    but keeps each sector's out-of-sample outcomes separate instead of
    flattening them — needed to compute per-sector metrics rather than one
    pooled number that a dominant sector's sample size can hide behind."""
    per_sector: dict[str, list[dict]] = {}
    for sector, (data_dir, benchmark) in _SECTOR_DATASETS.items():
        historical_data = load_historical_data(data_dir)
        if not historical_data:
            logger.warning(f"{sector}: no historical data in {data_dir}, skipping")
            continue
        outcomes, _months, _dates, _cutoff = _get_test_outcomes(
            historical_data, config_path, train_split=0.70, benchmark_ticker=benchmark,
        )
        per_sector[sector] = outcomes
    return per_sector


def _metrics_row(label: str, outcomes: list[dict]) -> dict:
    qualifying = [o for o in outcomes if float(o.get("confidence", 0)) >= _CONFIDENCE_THRESHOLD_BACKTEST]
    if not qualifying:
        return {
            "label": label, "n_signals": len(outcomes), "n_qualifying": 0,
            "win_rate": None, "avg_rr": None, "expectancy_r_ci_lower": None,
            "sharpe": None, "max_drawdown_pct": None,
        }
    win_rate = compute_win_rate(qualifying)
    avg_rr = compute_avg_rr(qualifying)
    expectancy_ci = bootstrap_expectancy_ci(compute_r_multiples(qualifying))
    chrono = sorted(qualifying, key=lambda o: o.get("exit_date") or o.get("signal_date") or "")
    equity_curve = _build_equity_curve(chrono, starting_equity=15000.0)
    sharpe = compute_sharpe(equity_curve.pct_change().dropna(), periods_per_year=_trades_per_year(chrono))
    max_dd = compute_max_drawdown(equity_curve)
    return {
        "label": label,
        "n_signals": len(outcomes),
        "n_qualifying": len(qualifying),
        "win_rate": round(win_rate, 4),
        "avg_rr": round(avg_rr, 2),
        "expectancy_r_ci_lower": round(expectancy_ci["ci_lower"], 3),
        "sharpe": round(sharpe, 2),
        "max_drawdown_pct": round(max_dd, 4),
    }


def per_sector_breakdown(per_sector: dict[str, list[dict]]) -> pd.DataFrame:
    """
    Question 1: does the shared category weighting hold up per sector, or is
    the pooled read (what run_multi_sector_backtest() currently reports)
    hiding a sector that's actually failing underneath one that's carrying it?
    """
    rows = [_metrics_row(sector, outcomes) for sector, outcomes in per_sector.items()]
    all_outcomes = [o for outcomes in per_sector.values() for o in outcomes]
    rows.append(_metrics_row("ALL (pooled, current reported number)", all_outcomes))
    return pd.DataFrame(rows)


def technical_gate_sweep(all_outcomes: list[dict]) -> pd.DataFrame:
    """
    Question 2: does requiring a Technical floor before a signal can qualify
    — instead of the current fully-additive scoring, where weak Technical can
    be bought up to the qualifying bar by Positioning/Sentiment/News/
    Fundamental/modifiers — actually improve win rate/expectancy, or just
    shrink the sample for no benefit? Sweeps the floor as a percentage of
    TECHNICAL_MAX (40) applied ON TOP OF the existing qualifying bar
    (CONFIDENCE_THRESHOLD), not a replacement for it.
    """
    rows = []
    for floor_pct in (0.0, 0.40, 0.50, 0.60, 0.70):
        floor_pts = floor_pct * TECHNICAL_MAX
        gated = [o for o in all_outcomes if float(o.get("technical_total", 0.0)) >= floor_pts]
        label = f"technical >= {floor_pct:.0%} of max ({floor_pts:.0f}/{TECHNICAL_MAX} pts)"
        rows.append(_metrics_row(label, gated))
    return pd.DataFrame(rows)


def main() -> None:
    print("Loading historical data and replaying signals for all 4 sectors "
          "(this mirrors run_backtest()'s own replay, ~15-20s per sector)...")
    per_sector = collect_per_sector_outcomes()
    if not per_sector:
        print("No historical outcomes across any sector — nothing to measure.")
        return

    all_outcomes = [o for outcomes in per_sector.values() for o in outcomes]

    print("\n=== Question 1: does the shared 40/20/15/15/10 weighting hold up per sector? ===\n")
    df1 = per_sector_breakdown(per_sector)
    print(df1.to_string(index=False))

    print("\n=== Question 2: would gating on Technical improve results, or just shrink the sample? ===\n")
    df2 = technical_gate_sweep(all_outcomes)
    print(df2.to_string(index=False))

    from pathlib import Path
    report_dir = Path("backtesting/reports")
    report_dir.mkdir(parents=True, exist_ok=True)
    df1.to_csv(report_dir / "per_sector_diagnostic.csv", index=False)
    df2.to_csv(report_dir / "technical_gate_diagnostic.csv", index=False)
    print(f"\nSaved to {report_dir / 'per_sector_diagnostic.csv'} and {report_dir / 'technical_gate_diagnostic.csv'}")


if __name__ == "__main__":
    main()
