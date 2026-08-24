"""
Replays scoring logic against historical data.
70/30 out-of-sample split; walk-forward validation; per-regime reporting.
Minimum 100 qualifying trades (confidence >= CONFIDENCE_THRESHOLD, R:R 1:3+) before win rate is valid.

Qualifying-confidence fix (2026-08-22, full model audit, v2.2.75): the
qualifying filter below used to hardcode `confidence >= 90`, a relic of the
original scoring design. Live's real gate (swing_model/scoring.py
CONFIDENCE_THRESHOLD) was cut to 70 in v2.2.46 after 750 real logged scans
never once exceeded 79.84 — so this backtest had been validating a signal
population the live/paper pipeline can structurally never produce, silently
drifting out of sync with the live threshold it exists to test. Now imports
CONFIDENCE_THRESHOLD directly so the two can't drift apart again.

Rescale re-derivation (2026-08-23, v2.2.76): the fix above didn't by itself
revisit simulation.py's raw-score-to-confidence rescale, which was calibrated
against the old 90 target — see that module's `_RAW_TO_LIVE_RESCALE_FACTOR`
docstring for the empirical re-derivation (backtesting/
raw_score_calibration_diagnostic.py) that replaced it.

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

Walk-forward pooled gate (2026-08-23): "passed" also requires the SAME
expectancy-CI/Sharpe/drawdown/trade-count bar to clear on qualifying trades
pooled across every walk-forward window, not just the single fixed 70/30
split. Added after finding the single-split "passed" had been true only
because the fixed test period happens to sit inside the 2 (of 6) windows
that looked favorable — see CHANGELOG.md v2.2.83 for the full incident.

Orchestration only — the historical replay/simulation engine lives in
simulation.py, walk-forward windowing in walk_forward.py, and pure metrics
(win rate, R:R, drawdown, Sharpe, equity curve, expectancy CI) in metrics.py.
`run_walk_forward` and `simulate_trade_outcome` are re-exported here for
backward compatibility with existing callers (entry_filter_variants.py,
tests/test_phase12_backtest.py).
"""

from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import pandas as pd

from backtesting.metrics import (
    compute_win_rate,
    compute_avg_rr,
    compute_max_drawdown,
    compute_max_drawdown_duration,
    compute_ulcer_index,
    compute_sharpe,
    compute_sortino,
    per_regime_metrics,
    compute_consecutive_losses,
    compute_r_multiples,
    bootstrap_expectancy_ci,
    _trades_per_year,
    _build_equity_curve,
    build_portfolio_equity_curve,
)
from backtesting.simulation import _simulate_test_signals, simulate_trade_outcome  # noqa: F401 (simulate_trade_outcome re-exported for tests/test_phase12_backtest.py)
from backtesting.walk_forward import run_walk_forward
from swing_model.scoring import CONFIDENCE_THRESHOLD


def _backtesting_cfg(config_path: str) -> dict:
    """Load config/swing_config.yaml's `backtesting` section (Tier B batch 2,
    2026-08-19) — used to resolve train_split/min_qualifying_trades defaults
    when the caller doesn't pass an explicit override."""
    from swing_model.indicator_pipeline import load_config
    return load_config(config_path).get("backtesting", {})

# Referenced by name at call time in _save_report (not baked into a default arg
# value, which Python evaluates once at import time) so tests/conftest.py's
# autouse fixture can monkeypatch this and keep run_backtest() smoke tests from
# writing real-looking (but synthetic, all-zero) report files into the actual
# backtesting/reports/ directory under today's real date.
_REPORTS_DIR = Path("backtesting/reports")


def _compute_metrics_bundle(qualifying: list[dict], starting_equity: float = 15000.0) -> dict:
    """
    Full metrics bundle for one population of qualifying trade outcomes: win
    rate, avg R:R, per-regime breakdown, bootstrapped expectancy CI, serial
    equity curve (max drawdown/duration/ulcer index/Sharpe/Sortino),
    portfolio-level equity curve (concurrent-position Sharpe/drawdown/max
    concurrent positions & risk), and max consecutive losses.

    Shared by run_backtest() (single-sector/pooled case) and
    run_multi_sector_backtest() (both its pooled-across-sectors call and its
    per-sector loop) — all three need the identical metric set computed the
    identical way, just on different trade populations; this used to be
    ~30 lines of copy-pasted code at each of the three call sites, which had
    to be kept in sync by hand (the v2.2.56 per-sector-must-also-pass rule
    already had to be added in two places before this existed).

    Callers that don't need the full bundle (e.g. the per-sector loop only
    reports win_rate/sharpe/max_dd/expectancy_ci) just read the subset of
    keys they want — computing the rest is cheap (all pure in-memory/pandas
    work on an already-small trade list, no I/O).
    """
    win_rate = compute_win_rate(qualifying)
    avg_rr = compute_avg_rr(qualifying)
    regime_metrics = per_regime_metrics(qualifying)
    expectancy_ci = bootstrap_expectancy_ci(compute_r_multiples(qualifying))

    # Build equity curve — trades must be in calendar order (chronological by exit
    # date, when P&L actually realizes), not the ticker-by-ticker order they were
    # generated in, or the curve/drawdown/Sharpe would replay history out of sequence.
    qualifying_chrono = sorted(qualifying, key=lambda o: o.get("exit_date") or o.get("signal_date") or "")
    equity_curve = _build_equity_curve(qualifying_chrono, starting_equity=starting_equity)
    max_dd = compute_max_drawdown(equity_curve)
    max_dd_duration = compute_max_drawdown_duration(equity_curve)
    ulcer_index = compute_ulcer_index(equity_curve)
    trade_returns = equity_curve.pct_change().dropna()
    # Each step in trade_returns is one trade, not one calendar day — annualize
    # using the actual observed trade frequency rather than assuming sqrt(252).
    sharpe = compute_sharpe(trade_returns, periods_per_year=_trades_per_year(qualifying_chrono))
    sortino = compute_sortino(trade_returns, periods_per_year=_trades_per_year(qualifying_chrono))

    # Portfolio-level view: concurrently open positions realistically compound
    # risk together (a correlated adverse move hits several open positions at
    # once), which the serial curve above — one trade fully closed before the
    # next affects the curve — structurally can't represent. Reported
    # alongside, not in place of, the serial figures above.
    portfolio_curve, portfolio_stats = build_portfolio_equity_curve(qualifying_chrono, starting_equity=starting_equity)
    portfolio_max_dd = compute_max_drawdown(portfolio_curve)
    portfolio_returns = portfolio_curve.pct_change().dropna()
    portfolio_sharpe = compute_sharpe(portfolio_returns, periods_per_year=_trades_per_year(qualifying_chrono))

    # Chronological order, not generation order (ticker-by-ticker) — a
    # streak is a path-dependent statistic, same reasoning as the equity
    # curve above (2026-07-19 fix). Using `qualifying` here instead of
    # `qualifying_chrono` was the same bug surviving in one more metric.
    max_consec_losses = compute_consecutive_losses(qualifying_chrono)

    return {
        "win_rate": win_rate,
        "avg_rr": avg_rr,
        "regime_metrics": regime_metrics,
        "expectancy_ci": expectancy_ci,
        "qualifying_chrono": qualifying_chrono,
        "max_dd": max_dd,
        "max_dd_duration": max_dd_duration,
        "ulcer_index": ulcer_index,
        "sharpe": sharpe,
        "sortino": sortino,
        "portfolio_sharpe": portfolio_sharpe,
        "portfolio_max_dd": portfolio_max_dd,
        "portfolio_stats": portfolio_stats,
        "max_consec_losses": max_consec_losses,
    }


def run_backtest(
    historical_data: dict[str, pd.DataFrame],
    config_path: str = "config/swing_config.yaml",
    train_split: Optional[float] = None,
    min_qualifying_trades: Optional[int] = None,
    min_expectancy_r: float = 0.3,
) -> dict:
    """
    Replay the full scoring + trade selection pipeline against historical OHLCV data.

    Steps:
    1. Split data into train (70%) and test (30%) sets
    2. Identify all qualifying signals (confidence >= CONFIDENCE_THRESHOLD, R:R >= 1:3) in test set —
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
    # train_split/min_qualifying_trades: explicit override, else config.backtesting
    # (defaults 0.70/100) — Tier B batch 2 (2026-08-19).
    if min_qualifying_trades is None:
        min_qualifying_trades = int(_backtesting_cfg(config_path).get("min_qualifying_trades", 100))
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
            "sortino_ratio": 0.0,
            "max_drawdown_pct": 0.0,
            "max_drawdown_duration_trades": 0,
            "ulcer_index": 0.0,
            "portfolio_sharpe_ratio": 0.0,
            "portfolio_max_drawdown_pct": 0.0,
            "max_concurrent_positions": 0,
            "max_concurrent_risk_pct": 0.0,
            "qualifying_trades": 0,
            "per_regime": {},
            "walk_forward": [],
            "walk_forward_pooled_passed": False,
            "walk_forward_pooled_qualifying_trades": 0,
            "walk_forward_pooled_expectancy_r_ci_lower": 0.0,
            "walk_forward_pooled_sharpe": 0.0,
            "walk_forward_pooled_max_drawdown_pct": 0.0,
        }

    # Step 1-4: Split into train/test and simulate signals in the test period.
    # (Full indicator pipeline requires live data; in backtest we use simplified proxy signals)
    all_outcomes, _test_months, all_dates, train_cutoff = _get_test_outcomes(
        historical_data, config_path, train_split
    )
    if not all_dates:
        return {"passed": False, "error": "no_dates", "win_rate": 0.0}
    qualifying = [o for o in all_outcomes if float(o.get("confidence", 0)) >= CONFIDENCE_THRESHOLD]

    # Step 5: Metrics
    m = _compute_metrics_bundle(qualifying, starting_equity=15000.0)

    # Step 6: Walk-forward
    wf_results = run_walk_forward(historical_data, include_outcomes=True)

    # Pooled walk-forward check (2026-08-23, full model audit follow-up):
    # previously wf_results was computed and attached to the report but never
    # gated "passed" — a single 70/30 split can pass by construction whenever
    # the fixed test period happens to land in a favorable stretch, which is
    # exactly what was happening here (the test period starts 2022-06-09,
    # sitting entirely inside the only 2 walk-forward windows that "passed"
    # under the confidence-threshold bug fixed the same day this was added —
    # see CHANGELOG v2.2.83). A per-window majority vote would be a weak fix
    # in its own right (6 windows is too few data points for a binary
    # pass/fail vote per window to mean much, and most windows don't clear
    # min_trades_for_verdict at all). Pooling every window's qualifying
    # outcomes into one larger sample and running the SAME metrics bundle the
    # single-slice check already uses is more statistically honest — it's the
    # exact approach entry_filter_variants.py already established for testing
    # entry-filter candidates without overfitting to one fixed slice, just
    # applied to the go-live gate itself instead of a research tool.
    wf_pooled_outcomes: list[dict] = []
    for w in wf_results:
        wf_pooled_outcomes.extend(w.pop("outcomes", []))
    wf_m = _compute_metrics_bundle(wf_pooled_outcomes, starting_equity=15000.0)
    walk_forward_pooled_passed = (
        len(wf_pooled_outcomes) >= min_qualifying_trades
        and wf_m["expectancy_ci"]["ci_lower"] >= min_expectancy_r
        and wf_m["sharpe"] >= 1.0
        and wf_m["max_dd"] <= 0.15
    )

    # Determine pass/fail (v2.2.17): trade count + expectancy CI lower bound +
    # Sharpe + drawdown. win_rate/avg_rr no longer gate "passed" directly — see
    # module docstring for why the old flat pair was replaced. Sortino/Ulcer/
    # drawdown-duration are reported but don't gate "passed" — the existing
    # Sharpe/drawdown floors are what this project's go-live decision has
    # actually been validated against; adding new gates on new metrics is a
    # deliberate bar-raising decision, not something to fold in silently.
    # walk_forward_pooled_passed added 2026-08-23 — see the comment above.
    passed = (
        len(qualifying) >= min_qualifying_trades
        and m["expectancy_ci"]["ci_lower"] >= min_expectancy_r
        and m["sharpe"] >= 1.0
        and m["max_dd"] <= 0.15
        and walk_forward_pooled_passed
    )

    result = {
        "passed": passed,
        "win_rate": round(m["win_rate"], 4),
        "avg_rr": round(m["avg_rr"], 2),
        "expectancy_r_mean": round(m["expectancy_ci"]["mean_r"], 3),
        "expectancy_r_ci_lower": round(m["expectancy_ci"]["ci_lower"], 3),
        "expectancy_r_ci_upper": round(m["expectancy_ci"]["ci_upper"], 3),
        "sharpe_ratio": round(m["sharpe"], 2),
        "sortino_ratio": round(m["sortino"], 2),
        "max_drawdown_pct": round(m["max_dd"], 4),
        "max_drawdown_duration_trades": m["max_dd_duration"],
        "ulcer_index": round(m["ulcer_index"], 4),
        "portfolio_sharpe_ratio": round(m["portfolio_sharpe"], 2),
        "portfolio_max_drawdown_pct": round(m["portfolio_max_dd"], 4),
        "max_concurrent_positions": m["portfolio_stats"]["max_concurrent_positions"],
        "max_concurrent_risk_pct": m["portfolio_stats"]["max_concurrent_risk_pct"],
        "qualifying_trades": len(qualifying),
        "total_signals": len(all_outcomes),
        "max_consecutive_losses": m["max_consec_losses"],
        "per_regime": m["regime_metrics"],
        "walk_forward": wf_results,
        "walk_forward_pooled_passed": walk_forward_pooled_passed,
        "walk_forward_pooled_qualifying_trades": len(wf_pooled_outcomes),
        "walk_forward_pooled_expectancy_r_ci_lower": round(wf_m["expectancy_ci"]["ci_lower"], 3),
        "walk_forward_pooled_sharpe": round(wf_m["sharpe"], 2),
        "walk_forward_pooled_max_drawdown_pct": round(wf_m["max_dd"], 4),
        "train_period": str(all_dates[0]) if all_dates else "",
        "test_period": str(train_cutoff) if train_cutoff else "",
    }

    # Save report
    _save_report(result)
    return result


# Sector -> (historical data directory, sector benchmark ticker). The live model
# trades all three sectors (config/swing_config.yaml watchlist.sectors); until now
# run_backtest() only ever validated the semiconductors sector (data/historical/,
# 6 tickers) — regional_banks and healthcare have had a matching historical dataset
# sitting in data/historical_banks/ and data/historical_healthcare/ (gitignored
# research data, same 2013-2026 date range) that was never wired into the backtest.
_SECTOR_DATASETS = {
    "semiconductors": ("data/historical", "SMH"),
    "regional_banks": ("data/historical_banks", "KRE"),
    "healthcare": ("data/historical_healthcare", "XLV"),
    "consumer_discretionary": ("data/historical_consumer_discretionary", "XLY"),
}


def run_multi_sector_backtest(
    sector_historical_data: dict[str, dict[str, pd.DataFrame]],
    config_path: str = "config/swing_config.yaml",
    train_split: Optional[float] = None,
    min_qualifying_trades: Optional[int] = None,
    min_expectancy_r: float = 0.3,
) -> dict:
    """
    Same replay + metrics pipeline as run_backtest(), but run once per sector
    (each against its own benchmark — SMH/KRE/XLV) and the resulting out-of-sample
    signal sets pooled into one combined qualifying-trade population before
    computing win rate/R:R/Sharpe/drawdown/expectancy. A stock's technical setup
    is only ever compared against its own sector's benchmark (mixing sectors into
    one _simulate_test_signals() call would benchmark bank tickers against SMH,
    which is meaningless) — this is why pooling happens at the outcome level, not
    the raw OHLCV level.

    sector_historical_data: {sector_name: {ticker: OHLCV_df}} — each inner dict
    must include that sector's benchmark ticker (see _SECTOR_DATASETS) alongside
    its tradeable tickers, same shape run_backtest() expects for a single sector.

    Does not run walk-forward validation (per-sector walk-forward pooling is a
    separate, larger change) — this covers the same headline 70/30 single-slice
    metric every other backtest result in this project is compared against.

    "passed" (2026-08-15, see CHANGELOG v2.2.56): requires every individual
    sector to also clear the Sharpe/expectancy/drawdown bars on its own data,
    not just the pooled aggregate. Found via backtesting/architecture_diagnostic.py:
    a strong sector can single-handedly carry a "passed" pooled read while 3 of
    4 sectors fail those same bars on their own (semiconductors Sharpe 4.16 vs.
    regional_banks/healthcare/consumer_discretionary all under 0.7) — the pooled
    number alone would have said "go" while real capital in 3 of the 4 sectors
    would have been trading on an edge that isn't actually there. This doesn't
    change any sector's weighting or scoring — it only changes what "passed"
    is honest about. A sector with zero qualifying trades correctly fails here
    too: bootstrap_expectancy_ci's own convention returns ci_lower=0.0 for an
    empty sample, which can't clear min_expectancy_r.

    Returns the same result dict shape as run_backtest(), plus "per_sector" (the
    qualifying trade count per sector, unchanged) and "per_sector_metrics" (each
    sector's own win_rate/sharpe/expectancy_r_ci_lower/max_drawdown_pct/passed).
    """
    # train_split/min_qualifying_trades: explicit override, else config.backtesting
    # (defaults 0.70/100) — Tier B batch 2 (2026-08-19).
    if min_qualifying_trades is None:
        min_qualifying_trades = int(_backtesting_cfg(config_path).get("min_qualifying_trades", 100))
    all_outcomes: list[dict] = []
    per_sector_counts: dict[str, int] = {}
    per_sector_outcomes: dict[str, list[dict]] = {}
    earliest_date = None
    train_cutoff_label = ""

    for sector, historical_data in sector_historical_data.items():
        if not historical_data:
            continue
        _, benchmark = _SECTOR_DATASETS.get(sector, (None, "SMH"))
        outcomes, _months, dates, train_cutoff = _get_test_outcomes(
            historical_data, config_path, train_split, benchmark_ticker=benchmark
        )
        per_sector_counts[sector] = len(outcomes)
        per_sector_outcomes[sector] = outcomes
        all_outcomes.extend(outcomes)
        if dates and (earliest_date is None or dates[0] < earliest_date):
            earliest_date = dates[0]
        if train_cutoff is not None:
            train_cutoff_label = str(train_cutoff)

    if not all_outcomes:
        return {"passed": False, "error": "no_dates", "win_rate": 0.0, "per_sector": per_sector_counts}

    per_sector_metrics: dict[str, dict] = {}
    for sector, outcomes in per_sector_outcomes.items():
        sector_qualifying = [o for o in outcomes if float(o.get("confidence", 0)) >= CONFIDENCE_THRESHOLD]
        sm = _compute_metrics_bundle(sector_qualifying, starting_equity=15000.0)
        sector_passed = (
            sm["expectancy_ci"]["ci_lower"] >= min_expectancy_r
            and sm["sharpe"] >= 1.0
            and sm["max_dd"] <= 0.15
        )
        per_sector_metrics[sector] = {
            "n_qualifying": len(sector_qualifying),
            "win_rate": round(sm["win_rate"], 4),
            "expectancy_r_ci_lower": round(sm["expectancy_ci"]["ci_lower"], 3),
            "sharpe_ratio": round(sm["sharpe"], 2),
            "max_drawdown_pct": round(sm["max_dd"], 4),
            "passed": sector_passed,
        }

    qualifying = [o for o in all_outcomes if float(o.get("confidence", 0)) >= CONFIDENCE_THRESHOLD]

    # Especially relevant here vs. the single-sector run_backtest(): this
    # pools outcomes across all 3 sectors, so concurrent positions can now
    # span sectors too — exactly what live trading actually does.
    m = _compute_metrics_bundle(qualifying, starting_equity=15000.0)

    pooled_passed = (
        len(qualifying) >= min_qualifying_trades
        and m["expectancy_ci"]["ci_lower"] >= min_expectancy_r
        and m["sharpe"] >= 1.0
        and m["max_dd"] <= 0.15
    )
    passed = pooled_passed and all(sm["passed"] for sm in per_sector_metrics.values())

    result = {
        "passed": passed,
        "pooled_passed": pooled_passed,
        "win_rate": round(m["win_rate"], 4),
        "avg_rr": round(m["avg_rr"], 2),
        "expectancy_r_mean": round(m["expectancy_ci"]["mean_r"], 3),
        "expectancy_r_ci_lower": round(m["expectancy_ci"]["ci_lower"], 3),
        "expectancy_r_ci_upper": round(m["expectancy_ci"]["ci_upper"], 3),
        "sharpe_ratio": round(m["sharpe"], 2),
        "sortino_ratio": round(m["sortino"], 2),
        "max_drawdown_pct": round(m["max_dd"], 4),
        "max_drawdown_duration_trades": m["max_dd_duration"],
        "ulcer_index": round(m["ulcer_index"], 4),
        "portfolio_sharpe_ratio": round(m["portfolio_sharpe"], 2),
        "portfolio_max_drawdown_pct": round(m["portfolio_max_dd"], 4),
        "max_concurrent_positions": m["portfolio_stats"]["max_concurrent_positions"],
        "max_concurrent_risk_pct": m["portfolio_stats"]["max_concurrent_risk_pct"],
        "qualifying_trades": len(qualifying),
        "total_signals": len(all_outcomes),
        "max_consecutive_losses": m["max_consec_losses"],
        "per_regime": m["regime_metrics"],
        "per_sector": per_sector_counts,
        "per_sector_metrics": per_sector_metrics,
        "train_period": str(earliest_date) if earliest_date else "",
        "test_period": train_cutoff_label,
    }
    return result


def _get_test_outcomes(
    historical_data: dict[str, pd.DataFrame],
    config_path: str = "config/swing_config.yaml",
    train_split: Optional[float] = None,
    benchmark_ticker: str = "SMH",
) -> tuple[list[dict], float, list, "pd.Timestamp | None"]:
    """
    Split historical_data into train/test (70/30 by default) and simulate every
    out-of-sample breakout signal in the test period, unfiltered by confidence.

    Shared by run_backtest() (which filters to >=CONFIDENCE_THRESHOLD) and run_sensitivity_analysis()
    (which filters at several thresholds) so both operate on the exact same
    out-of-sample signal set instead of two independently-computed splits that
    could silently drift apart.

    train_split: explicit override, else read from config.backtesting.train_split
    (default 0.70) — Tier B batch 2 (2026-08-19).

    Returns (all_outcomes, test_period_months, all_dates, train_cutoff).
    """
    if train_split is None:
        train_split = float(_backtesting_cfg(config_path).get("train_split", 0.70))
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

    all_outcomes = _simulate_test_signals(
        test_data, config_path, signal_cutoff=train_cutoff, benchmark_ticker=benchmark_ticker
    )

    test_months = max(1.0, (all_dates[-1] - train_cutoff).days / 30.44)

    return all_outcomes, test_months, all_dates, train_cutoff


def _save_report(result: dict) -> None:
    """Save backtest result JSON to _REPORTS_DIR (backtesting/reports/ by default)."""
    report_dir = _REPORTS_DIR
    report_dir.mkdir(parents=True, exist_ok=True)
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    path = report_dir / f"swing_backtest_{date_str}.json"
    with open(path, "w", encoding="utf-8") as f:
        import json
        json.dump(result, f, indent=2, default=str)
