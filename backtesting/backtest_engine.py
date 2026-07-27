"""
Replays scoring logic against historical data.
70/30 out-of-sample split; walk-forward validation; per-regime reporting.
Minimum 100 qualifying trades (confidence 90+, R:R 1:3+) before win rate is valid.

Go-live gate (v2.2.17): pass/fail no longer rests on a flat 80% win rate / 1.8
avg R:R pair. That combination implied ~1.24R expectancy per trade — far above
anything ever observed even in the best historical windows — and said nothing
about sample-size confidence (a small sample hitting 80%/1.8 by chance looks
identical to a large one that's actually reliable). The gate now requires the
bootstrapped 95% CI lower bound on per-trade R-expectancy to clear
min_expectancy_r, alongside the existing trade-count/Sharpe/drawdown floors.
win_rate/avg_rr are still computed and reported for continuity with existing
dashboards, they just no longer gate "passed" on their own. See CHANGELOG.md
v2.2.17 and Project_Scope.md's go-live criteria section for the full rationale.

Orchestration only — the historical replay/simulation engine lives in
simulation.py, walk-forward windowing in walk_forward.py, and pure metrics
(win rate, R:R, drawdown, Sharpe, equity curve, expectancy CI) in metrics.py.
`run_walk_forward` and `simulate_trade_outcome` are re-exported here for
backward compatibility with existing callers (entry_filter_variants.py,
tests/test_phase12_backtest.py).
"""

from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from backtesting.metrics import (
    compute_win_rate,
    compute_avg_rr,
    compute_max_drawdown,
    compute_sharpe,
    per_regime_metrics,
    compute_consecutive_losses,
    compute_r_multiples,
    bootstrap_expectancy_ci,
    _trades_per_year,
    _build_equity_curve,
)
from backtesting.simulation import _simulate_test_signals, simulate_trade_outcome  # noqa: F401 (simulate_trade_outcome re-exported for tests/test_phase12_backtest.py)
from backtesting.walk_forward import run_walk_forward

# Referenced by name at call time in _save_report (not baked into a default arg
# value, which Python evaluates once at import time) so tests/conftest.py's
# autouse fixture can monkeypatch this and keep run_backtest() smoke tests from
# writing real-looking (but synthetic, all-zero) report files into the actual
# backtesting/reports/ directory under today's real date.
_REPORTS_DIR = Path("backtesting/reports")


def run_backtest(
    historical_data: dict[str, pd.DataFrame],
    config_path: str = "config/swing_config.yaml",
    train_split: float = 0.70,
    min_qualifying_trades: int = 100,
    min_expectancy_r: float = 0.3,
) -> dict:
    """
    Replay the full scoring + trade selection pipeline against historical OHLCV data.

    Steps:
    1. Split data into train (70%) and test (30%) sets
    2. Identify all qualifying signals (confidence >= 90, R:R >= 1:3) in test set —
       NOTE: the train split is currently only used to hold out test data; no weight
       calibration runs against it here. Live weight calibration (technical/sentiment/
       news rebalancing from real trade outcomes) is a separate, opt-in mechanism —
       see swing_model/feedback_loop.py run_calibration() and scoring.py's
       live_weights parameter — not part of this backtest.
    3. Simulate trade outcomes (entry at alert price, exit at target/stop/time stop)
    4. Compute metrics (win rate, R:R, drawdown, Sharpe, expectancy CI) per-regime and overall
    5. Run walk-forward validation across available windows
    6. Return full backtest results dict

    min_expectancy_r: the bootstrapped 95% CI lower bound on per-trade R-expectancy
    must clear this to pass (see module docstring for why this replaced the flat
    80% win rate / 1.8 avg R:R pair). Default 0.3R — a meaningfully positive,
    statistically-defensible edge, not a number this design has ever hit yet;
    this is a deliberately less permissive change vs. the old pair for a sample
    size in the 100-200 trade range, not a loosened bar.

    Returns dict with all metrics (including expectancy_r_mean/ci_lower/ci_upper),
    per-regime results, walk-forward results.
    """
    if not historical_data:
        return {
            "passed": False,
            "error": "no_historical_data",
            "win_rate": 0.0,
            "avg_rr": 0.0,
            "expectancy_r_mean": 0.0,
            "expectancy_r_ci_lower": 0.0,
            "expectancy_r_ci_upper": 0.0,
            "sharpe_ratio": 0.0,
            "max_drawdown_pct": 0.0,
            "qualifying_trades": 0,
            "per_regime": {},
            "walk_forward": [],
        }

    # Step 1-4: Split into train/test and simulate signals in the test period.
    # (Full indicator pipeline requires live data; in backtest we use simplified proxy signals)
    all_outcomes, _test_months, all_dates, train_cutoff = _get_test_outcomes(
        historical_data, config_path, train_split
    )
    if not all_dates:
        return {"passed": False, "error": "no_dates", "win_rate": 0.0}
    qualifying = [o for o in all_outcomes if float(o.get("confidence", 0)) >= 90]

    # Step 5: Metrics
    win_rate = compute_win_rate(qualifying)
    avg_rr = compute_avg_rr(qualifying)
    regime_metrics = per_regime_metrics(qualifying)
    expectancy_ci = bootstrap_expectancy_ci(compute_r_multiples(qualifying))

    # Build equity curve — trades must be in calendar order (chronological by exit
    # date, when P&L actually realizes), not the ticker-by-ticker order they were
    # generated in, or the curve/drawdown/Sharpe would replay history out of sequence.
    qualifying_chrono = sorted(qualifying, key=lambda o: o.get("exit_date") or o.get("signal_date") or "")
    equity_curve = _build_equity_curve(qualifying_chrono, starting_equity=15000.0)
    max_dd = compute_max_drawdown(equity_curve)
    trade_returns = equity_curve.pct_change().dropna()
    # Each step in trade_returns is one trade, not one calendar day — annualize
    # using the actual observed trade frequency rather than assuming sqrt(252).
    sharpe = compute_sharpe(trade_returns, periods_per_year=_trades_per_year(qualifying_chrono))

    max_consec_losses = compute_consecutive_losses(qualifying)

    # Step 6: Walk-forward
    wf_results = run_walk_forward(historical_data)

    # Determine pass/fail (v2.2.17): trade count + expectancy CI lower bound +
    # Sharpe + drawdown. win_rate/avg_rr no longer gate "passed" directly — see
    # module docstring for why the old flat pair was replaced.
    passed = (
        len(qualifying) >= min_qualifying_trades
        and expectancy_ci["ci_lower"] >= min_expectancy_r
        and sharpe >= 1.0
        and max_dd <= 0.15
    )

    result = {
        "passed": passed,
        "win_rate": round(win_rate, 4),
        "avg_rr": round(avg_rr, 2),
        "expectancy_r_mean": round(expectancy_ci["mean_r"], 3),
        "expectancy_r_ci_lower": round(expectancy_ci["ci_lower"], 3),
        "expectancy_r_ci_upper": round(expectancy_ci["ci_upper"], 3),
        "sharpe_ratio": round(sharpe, 2),
        "max_drawdown_pct": round(max_dd, 4),
        "qualifying_trades": len(qualifying),
        "total_signals": len(all_outcomes),
        "max_consecutive_losses": max_consec_losses,
        "per_regime": regime_metrics,
        "walk_forward": wf_results,
        "train_period": str(all_dates[0]) if all_dates else "",
        "test_period": str(train_cutoff) if train_cutoff else "",
    }

    # Save report
    _save_report(result)
    return result


def _get_test_outcomes(
    historical_data: dict[str, pd.DataFrame],
    config_path: str = "config/swing_config.yaml",
    train_split: float = 0.70,
) -> tuple[list[dict], float, list, "pd.Timestamp | None"]:
    """
    Split historical_data into train/test (70/30 by default) and simulate every
    out-of-sample breakout signal in the test period, unfiltered by confidence.

    Shared by run_backtest() (which filters to >=90) and run_sensitivity_analysis()
    (which filters at several thresholds) so both operate on the exact same
    out-of-sample signal set instead of two independently-computed splits that
    could silently drift apart.

    Returns (all_outcomes, test_period_months, all_dates, train_cutoff).
    """
    if not historical_data:
        return [], 0.0, [], None

    all_dates = sorted(set(
        date for df in historical_data.values() for date in df.index
    ))
    if not all_dates:
        return [], 0.0, [], None

    split_idx = int(len(all_dates) * train_split)
    train_cutoff = all_dates[split_idx] if split_idx < len(all_dates) else all_dates[-1]

    # Split each ticker's DataFrame, keeping a warmup buffer of real pre-cutoff
    # bars (matches _simulate_test_signals' len(df)>=65 / range(60,...) indicator
    # warmup requirement) so the first ~60 nominal test-period days aren't wasted
    # on indicator warmup with zero chance of producing a signal — that history
    # exists for free just before train_cutoff. signal_cutoff below ensures none
    # of those buffer bars are themselves treated as an out-of-sample signal.
    _WARMUP_BARS = 65
    test_data = {}
    for t, df in historical_data.items():
        if df.empty:
            test_data[t] = df
            continue
        pos = df.index.searchsorted(train_cutoff, side="right")
        test_data[t] = df.iloc[max(0, pos - _WARMUP_BARS):]

    all_outcomes = _simulate_test_signals(test_data, config_path, signal_cutoff=train_cutoff)

    test_months = max(1.0, (all_dates[-1] - train_cutoff).days / 30.44)

    return all_outcomes, test_months, all_dates, train_cutoff


def _save_report(result: dict) -> None:
    """Save backtest result JSON to _REPORTS_DIR (backtesting/reports/ by default)."""
    report_dir = _REPORTS_DIR
    report_dir.mkdir(parents=True, exist_ok=True)
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    path = report_dir / f"swing_backtest_{date_str}.json"
    with open(path, "w") as f:
        import json
        json.dump(result, f, indent=2, default=str)
