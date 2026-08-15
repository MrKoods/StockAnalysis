"""
Forward-testing win rate, R:R, and EV vs. theoretical.
Pass/fail criteria for Phase 13 go-live decision.

Pass criteria (v2.2.19 — mirrors the backtest gate's v2.2.17 change): rather than
a flat win-rate/R:R pair, "passed" requires the bootstrapped 95% CI lower bound on
per-trade R-expectancy to clear min_expectancy_r, alongside slippage and minimum-
duration floors. win_rate/avg_rr are still computed and returned for continuity
with existing reports/dashboards — they no longer gate pass/fail directly, for the
same reason the backtest gate changed: a flat percentage pair can't distinguish a
real edge from a small sample that got lucky, which matters even more here since
qualifying paper trades (score >= CONFIDENCE_THRESHOLD) accumulate far slower than backtest replay.

data_status ("evaluated" vs. "insufficient_trades"): below _MIN_TRADES_FOR_MEANINGFUL_READ
closed trades, overall_pass still reports False (safe default, unchanged) but the
failure reason is reported as a data-volume problem, not an expectancy failure — at
n=0 the CI lower bound is trivially 0.0, which without this distinction reads
identically to "the edge genuinely isn't there." This matters concretely here: as of
this change, real paper trading has logged 215 scans over 9 days and never once
reached the 90-point qualifying threshold (see paper_trading/score_distribution_diagnostic.py),
so n_trades has been 0 the entire time — this gate would otherwise report "failing"
indefinitely with no way to tell that apart from a real failure.
"""

import csv
from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd

from backtesting.metrics import bootstrap_expectancy_ci, compute_r_multiples

_PAPER_TRADES_CSV = Path("paper_trading/paper_trades.csv")


_PASS_CRITERIA = {
    "min_expectancy_r": 0.3,
    "max_slippage_excess_pct": 0.10,
    "min_trading_days": 60,
}

# Below this many closed trades, a CI-lower-bound failure is a sample-size
# artifact, not a real "the edge isn't there" signal — at n=0 the CI lower
# bound is trivially 0.0, indistinguishable from a genuine failure without
# this distinction.
#
# Raised from 15 to 30 (2026-08-15): 15 was chosen to match
# feedback_loop.run_calibration()'s own minimum (holdout_count=5 + 10) on the
# theory that both gates should agree on "enough data to have an opinion" —
# but that number was never checked against what evaluate_paper_trading_pass()
# below actually requires (bootstrapped 95% CI lower bound on per-trade
# R-expectancy >= min_expectancy_r, default 0.3R). Simulated a model
# performing exactly to the current backtest's own spec (62.3% win rate,
# 2.13 avg R:R) through bootstrap_expectancy_ci at increasing n (300 trials
# each): at n=15, mean CI-lower is only ~0.10R and a genuinely-good model
# reads as "insufficient/failing" ~71% of the time — the gate it's supposed
# to unlock can't be passed by the system it's calibrated against. Pass rate
# only crosses 50% around n=30 (mean CI-lower ~0.34R) and keeps climbing
# through n=50 (~80%). 30 is a middle ground, not a fully reliable read —
# picked over a higher, more statistically comfortable value (40-50) to keep
# the real-world wait reasonable (~26 days at the observed ~1.17 funded
# signals/day, vs. ~34-43 days) while still being meaningfully more honest
# than 15. feedback_loop.py's own trigger is deliberately left at 15 — unlike
# this gate, an early/imprecise calibration attempt there just wastes one
# cheap run_calibration() call that returns "insufficient_data" (see that
# function's own docstring), not a decision anyone acts on.
_MIN_TRADES_FOR_MEANINGFUL_READ = 30


def evaluate_paper_trading_pass(
    trade_outcomes: list[dict],
    fill_log: list[dict],
    trading_days_elapsed: int,
    min_expectancy_r: float = _PASS_CRITERIA["min_expectancy_r"],
) -> dict:
    """
    Evaluate whether paper trading has passed the Phase 13 go-live criteria.

    Returns dict:
    {
        overall_pass: bool,
        win_rate: float,
        avg_rr: float,
        expectancy_r_mean: float,
        expectancy_r_ci_lower: float,
        expectancy_r_ci_upper: float,
        expectancy_pass: bool,
        avg_slippage_excess: float,
        slippage_pass: bool,
        trading_days_elapsed: int,
        duration_pass: bool,
        failures: list[str],
    }
    """
    failures = []

    # Win rate / avg R:R (winners only) — reported for continuity, no longer gate
    # overall_pass directly.
    wins = sum(1 for o in trade_outcomes if o.get("outcome") == "win")
    win_rate = wins / len(trade_outcomes) if trade_outcomes else 0.0
    rr_values = [float(o.get("achieved_rr", 0.0)) for o in trade_outcomes if o.get("outcome") == "win"]
    avg_rr = sum(rr_values) / len(rr_values) if rr_values else 0.0

    # Expectancy CI — the actual gate. compute_r_multiples pulls achieved_rr from
    # every outcome (wins and losses), not just winners, since expectancy needs
    # the full win/loss distribution, not just how much winners capture.
    expectancy_ci = bootstrap_expectancy_ci(compute_r_multiples(trade_outcomes))
    n_trades = expectancy_ci["n_trades"]
    data_status = "evaluated" if n_trades >= _MIN_TRADES_FOR_MEANINGFUL_READ else "insufficient_trades"
    expectancy_pass = expectancy_ci["ci_lower"] >= min_expectancy_r
    if not expectancy_pass:
        if data_status == "insufficient_trades":
            # At low n, "ci_lower < min_expectancy_r" is a sample-size artifact
            # (n=0 always gives ci_lower=0.0), not evidence the edge is failing —
            # report it as what it is rather than implying a real expectancy miss.
            failures.append(
                f"insufficient_trade_data_{n_trades}_below_{_MIN_TRADES_FOR_MEANINGFUL_READ}"
            )
        else:
            failures.append(
                f"expectancy_ci_lower_{expectancy_ci['ci_lower']:.3f}R_below_{min_expectancy_r}R"
                f"_({n_trades}_trades)"
            )

    # Slippage
    slippage_excess = _compute_slippage_excess(fill_log)
    slippage_pass = slippage_excess <= _PASS_CRITERIA["max_slippage_excess_pct"]
    if not slippage_pass:
        failures.append(f"slippage_excess_{slippage_excess:.1%}_above_10pct")

    # Duration
    duration_pass = trading_days_elapsed >= _PASS_CRITERIA["min_trading_days"]
    if not duration_pass:
        failures.append(f"only_{trading_days_elapsed}_trading_days_need_60")

    overall_pass = expectancy_pass and slippage_pass and duration_pass

    return {
        "overall_pass": overall_pass,
        "data_status": data_status,
        "win_rate": round(win_rate, 4),
        "avg_rr": round(avg_rr, 2),
        "expectancy_r_mean": round(expectancy_ci["mean_r"], 3),
        "expectancy_r_ci_lower": round(expectancy_ci["ci_lower"], 3),
        "expectancy_r_ci_upper": round(expectancy_ci["ci_upper"], 3),
        "expectancy_pass": expectancy_pass,
        "avg_slippage_excess": round(slippage_excess, 4),
        "slippage_pass": slippage_pass,
        "trading_days_elapsed": trading_days_elapsed,
        "duration_pass": duration_pass,
        "failures": failures,
    }


def _is_funded(row: dict) -> bool:
    """True if this row actually deployed capital (position_size > 0) rather
    than qualifying but sizing to 0 (e.g. its best structure cost more than
    the confidence tier's risk budget allowed — see trade_selector.py's
    recommended-selection priority chain). A qualifying-but-unaffordable call
    is real signal-accuracy data (see compute_signal_accuracy) but shouldn't
    count the same as a real, capital-deployed trade when deciding whether
    this strategy is fit to trade real money."""
    try:
        return float(row.get("position_size", 0) or 0) > 0
    except (TypeError, ValueError):
        return False


def _load_paper_trades_rows(csv_path: Optional[Path] = None) -> tuple[list[dict], int]:
    """Shared CSV read + trading_days_elapsed calc for both the funded-only
    go-live gate (load_paper_trade_gate_inputs) and the unfiltered signal-
    accuracy view (compute_signal_accuracy) — keeps the two from silently
    disagreeing on file-reading or duration logic."""
    path = csv_path or _PAPER_TRADES_CSV
    if not path.exists():
        return [], 0

    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    signal_dates = []
    for r in rows:
        try:
            signal_dates.append(datetime.strptime(r["signal_date"], "%Y-%m-%d"))
        except (KeyError, ValueError, TypeError):
            continue

    trading_days_elapsed = 0
    if signal_dates:
        earliest = min(signal_dates)
        trading_days_elapsed = len(pd.bdate_range(start=earliest, end=datetime.now()))

    return rows, trading_days_elapsed


def load_paper_trade_gate_inputs(csv_path: Optional[Path] = None) -> dict:
    """
    Read paper_trading/paper_trades.csv (written by paper_trading/paper_updater.py
    — the system that's actually been running) and shape it as
    evaluate_paper_trading_pass()'s three positional inputs. This is
    deliberately NOT data/logs/trade_outcomes.csv (swing_model/feedback_loop.py's
    file, fed by swing_model/portfolio_manager.py) — that path belongs to the
    live/manual-Discord-confirmation flow, which has never been used since no
    model version has gone live; paper trading has its own separate, already-
    populated schema and is where real data has actually been accumulating.

    Returns {trade_outcomes, fill_log, trading_days_elapsed}:
      trade_outcomes: closed AND funded rows only (outcome/achieved_rr are
        already named exactly what evaluate_paper_trading_pass expects — no
        field mapping needed, unlike the calibration side's technical_score->
        technical, see feedback_loop.load_calibration_outcomes_from_paper_trades).
        Funded-only as of the same change that added compute_signal_accuracy:
        a signal that qualified but sized to 0 (couldn't afford any structure
        at this account size) previously counted toward this go-live gate's
        win_rate/expectancy the same as a real, capital-deployed trade —
        blending "is the model's call accurate" with "is this strategy
        profitable to actually run at $15k" into one number. Use
        compute_signal_accuracy() for the former; this stays scoped to the
        latter, which is what the go-live decision is actually about.
      fill_log: always [] — paper trades fill at exact simulated entry/stop/
        target prices; there's no real slippage to compare against until real
        capital is used, so slippage_pass trivially stays True rather than
        fabricating a comparison.
      trading_days_elapsed: trading days between the earliest logged
        signal_date (open or closed) and today — this floor is about how long
        the system has been running, not how many trades happen to have closed.
        Computed from every row regardless of funding, same as before.
    """
    rows, trading_days_elapsed = _load_paper_trades_rows(csv_path)
    trade_outcomes = [
        r for r in rows
        if r.get("outcome") and r.get("outcome") != "expired" and _is_funded(r)
    ]

    return {
        "trade_outcomes": trade_outcomes,
        "fill_log": [],
        "trading_days_elapsed": trading_days_elapsed,
    }


def compute_signal_accuracy(csv_path: Optional[Path] = None) -> dict:
    """
    Model-accuracy view: every closed signal, funded or not — answers "is the
    model's call correct" independent of whether the account could actually
    afford to act on it. Deliberately separate from load_paper_trade_gate_inputs
    (which now filters to funded trades only, for the go-live decision) — a
    signal that correctly predicted direction but sized to 0 because its
    structure cost more than the confidence tier's risk budget allowed is
    real evidence about the model, even though no capital was ever at risk.

    Returns {total_closed, funded_count, unfunded_count, win_rate_all,
    win_rate_funded, win_rate_unfunded} — reporting all three win rates side
    by side (not just the blended one) surfaces whether affordability itself
    correlates with signal quality, not just what the numbers are.
    """
    rows, _ = _load_paper_trades_rows(csv_path)
    # "expired" rows (entry zone never reached — see paper_updater.py's fill
    # confirmation) never had a directional call resolve either way, so they
    # don't belong in a model-accuracy view any more than an open trade does.
    closed = [r for r in rows if r.get("outcome") and r.get("outcome") != "expired"]
    funded = [r for r in closed if _is_funded(r)]
    unfunded = [r for r in closed if not _is_funded(r)]

    def _win_rate(outcomes: list[dict]) -> float:
        if not outcomes:
            return 0.0
        return round(sum(1 for o in outcomes if o.get("outcome") == "win") / len(outcomes), 4)

    return {
        "total_closed": len(closed),
        "funded_count": len(funded),
        "unfunded_count": len(unfunded),
        "win_rate_all": _win_rate(closed),
        "win_rate_funded": _win_rate(funded),
        "win_rate_unfunded": _win_rate(unfunded),
    }


def compute_forward_ev_accuracy(
    outcomes: list[dict],
) -> float:
    """
    Compare actual trade outcomes against theoretical EV from alert time.
    Returns ratio of actual_avg_pnl / theoretical_ev (1.0 = perfect calibration).
    """
    if not outcomes:
        return 0.0

    actual_pnls = [float(o.get("pnl_pct", 0.0)) for o in outcomes]
    theoretical_evs = [float(o.get("theoretical_ev", 0.0)) for o in outcomes]

    actual_avg = sum(actual_pnls) / len(actual_pnls) if actual_pnls else 0.0
    theoretical_avg = sum(theoretical_evs) / len(theoretical_evs) if theoretical_evs else 0.0

    if theoretical_avg == 0:
        return 0.0
    return round(actual_avg / theoretical_avg, 4)


def _compute_slippage_excess(fill_log: list[dict]) -> float:
    """
    Compute how much actual slippage exceeded the modeled slippage estimate.
    Returns excess as a fraction (0.0 = on-model, 0.15 = 15% worse than modeled).
    """
    if not fill_log:
        return 0.0

    actual_slippages = [abs(float(f.get("slippage_pct", 0.0))) for f in fill_log]
    modeled_slippages = [abs(float(f.get("modeled_slippage_pct", 0.005))) for f in fill_log]

    avg_actual = sum(actual_slippages) / len(actual_slippages)
    avg_modeled = sum(modeled_slippages) / len(modeled_slippages)

    if avg_modeled <= 0:
        return 0.0

    excess = (avg_actual - avg_modeled) / avg_modeled
    return max(0.0, excess)
