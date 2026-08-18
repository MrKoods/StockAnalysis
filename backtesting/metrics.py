"""
Win rate, R:R, drawdown, Sharpe -- confidence calibration, per-regime stats,
stress test results. All metrics computed on the test (out-of-sample) set only.
"""

import math
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
from scipy.stats import norm


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


def compute_max_drawdown_duration(equity_curve: pd.Series) -> int:
    """
    Longest stretch (in equity-curve steps — one per trade, since this
    project's equity curves are trade-indexed, not calendar-indexed) from a
    peak until a new equity high is reached. max_drawdown_pct alone doesn't
    say how long capital sat underwater — a portfolio flat for 8 months even
    at "only 12%" drawdown is a materially different risk profile than one
    that recovers in 3 weeks, and the two are indistinguishable from
    max_drawdown_pct alone.
    """
    if equity_curve.empty:
        return 0
    rolling_max = equity_curve.cummax()
    underwater = equity_curve < rolling_max
    max_duration = 0
    current_duration = 0
    for is_underwater in underwater:
        if is_underwater:
            current_duration += 1
            max_duration = max(max_duration, current_duration)
        else:
            current_duration = 0
    return max_duration


def compute_ulcer_index(equity_curve: pd.Series) -> float:
    """
    Ulcer Index (Martin, 1987) — root-mean-square of percentage drawdown
    across the whole equity curve, not just its single worst point. Combines
    depth and duration into one number: a drawdown that's both deep and
    long-lasting scores worse than one that's equally deep but brief, which
    max_drawdown_pct alone can't distinguish (see compute_max_drawdown_duration
    for the duration-only view). Returns a percentage (e.g. 8.2, not 0.082).
    """
    if equity_curve.empty:
        return 0.0
    rolling_max = equity_curve.cummax()
    drawdown_pct = (equity_curve - rolling_max) / rolling_max * 100
    return float((drawdown_pct.pow(2).mean()) ** 0.5)


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


def compute_sortino(returns: pd.Series, risk_free_rate: float = 0.05, periods_per_year: float = 252) -> float:
    """
    Annualized Sortino ratio — Sharpe's downside-only counterpart. This
    project's structures have deliberately asymmetric payoffs (long_strangle
    convex, credit spreads concave — see options_math.py), so a Sharpe-style
    denominator that penalizes upside variance exactly as much as downside
    variance is the wrong lens: it dings a strategy for the very upside swings
    that are the point of buying convexity. Sortino only penalizes returns
    below the risk-free rate, matching what "risk" actually means for capital
    at stake — the chance of losing it, not the chance of a bigger-than-usual win.

    Same periods_per_year caveat as compute_sharpe applies here.
    """
    if returns.empty:
        return 0.0
    period_rf = risk_free_rate / periods_per_year
    excess = returns - period_rf
    downside = excess[excess < 0]
    if len(downside) < 2:
        return 0.0
    downside_std = downside.std()
    if downside_std == 0 or math.isnan(downside_std):
        return 0.0
    return float((excess.mean() / downside_std) * math.sqrt(periods_per_year))


def compute_deflated_sharpe_ratio(
    sharpe_ratios: list[float],
    selected_sharpe: float,
    n_observations: int,
    skew: float = 0.0,
    kurtosis: float = 3.0,
) -> dict:
    """
    Deflated Sharpe Ratio (Bailey & Lopez de Prado, 2014). Answers: given that
    `selected_sharpe` was picked as the best of `len(sharpe_ratios)` independent
    trials (a sensitivity-analysis threshold sweep, an entry-filter variant
    sweep, ...), how much of that Sharpe is genuine edge versus what you'd
    expect from selection alone — trying N configurations and reporting the
    winner inflates the reported Sharpe purely from having N chances, even if
    every configuration has zero true edge.

    sharpe_ratios: the per-trial Sharpe estimate from every trial in the sweep
      (used to estimate the sampling variance of the Sharpe estimator across
      trials — a wide spread of Sharpes across otherwise-similar configs means
      more of any single Sharpe is noise, not signal).
    selected_sharpe: the Sharpe of the trial being reported (usually
      max(sharpe_ratios), but passed explicitly since the caller may select on
      a different criterion).
    n_observations: number of trade-level return observations the selected
      Sharpe was computed over — more observations means the same Sharpe is
      more likely to be real.
    skew / kurtosis: of the selected trial's per-trade return series. Default
      to a normal distribution's own moments (0, 3) when the caller doesn't
      have them handy — this makes the correction conservative-normal rather
      than silently wrong, not an assumption that trade returns really are
      normal (options-structure payoffs usually aren't — see the fix-5/6/7
      EV-normalization work for where that distinction actually matters).

    Returns:
      expected_max_sharpe_under_null: the Sharpe you'd expect to see just from
        taking the best of n_trials draws with zero true edge.
      deflated_sharpe: selected_sharpe - expected_max_sharpe_under_null — the
        edge left over after subtracting what pure trial-selection would give
        you for free.
      psr: P(true Sharpe > expected_max_sharpe_under_null) — the number to
        actually act on. psr < 0.95 means the "winning" configuration's edge
        over what this sweep would produce by chance isn't statistically
        convincing at the 95% level, i.e. don't trust the pick yet.
      n_trials, n_observations: echoed back for the caller to log/display.

    All fields are 0.0 when there's nothing to compute from (no trials or
    fewer than 2 observations).
    """
    n_trials = len(sharpe_ratios)
    if n_trials == 0 or n_observations < 2:
        return {
            "expected_max_sharpe_under_null": 0.0,
            "deflated_sharpe": 0.0,
            "psr": 0.0,
            "n_trials": n_trials,
            "n_observations": n_observations,
        }

    # Sampling variance of the Sharpe-ratio estimator across trials. With only
    # one trial there's no spread to estimate from, so fall back to the
    # analytic asymptotic variance of a single Sharpe estimate (Bailey &
    # Lopez de Prado, eq. 5) rather than a degenerate zero-variance case that
    # would silently report expected_max_sharpe_under_null == 0 regardless of
    # how many observations backed it.
    if n_trials > 1:
        var_sr = float(np.var(sharpe_ratios, ddof=1))
    else:
        var_sr = (1.0 + 0.5 * selected_sharpe ** 2) / max(n_observations - 1, 1)

    if var_sr <= 0 or n_trials <= 1:
        expected_max_sr = 0.0
    else:
        # Expected maximum of n_trials iid standard normal draws (Bailey &
        # Lopez de Prado, eq. 8), scaled by the estimated Sharpe std dev —
        # this is "how good would the best of N noisy, edge-free trials look
        # purely by luck."
        euler_mascheroni = 0.5772156649
        expected_max_sr = math.sqrt(var_sr) * (
            (1 - euler_mascheroni) * norm.ppf(1.0 - 1.0 / n_trials)
            + euler_mascheroni * norm.ppf(1.0 - 1.0 / (n_trials * math.e))
        )

    # Probabilistic Sharpe Ratio (Bailey & Lopez de Prado, eq. 1), benchmarked
    # against expected_max_sr instead of 0 — the higher-moment terms correct
    # for the selected trial's own return distribution not being normal.
    denom = math.sqrt(max(
        1e-12,
        1 - skew * selected_sharpe + ((kurtosis - 1) / 4.0) * selected_sharpe ** 2,
    ))
    psr = float(norm.cdf(
        (selected_sharpe - expected_max_sr) * math.sqrt(max(n_observations - 1, 1)) / denom
    ))

    return {
        "expected_max_sharpe_under_null": round(expected_max_sr, 4),
        "deflated_sharpe": round(selected_sharpe - expected_max_sr, 4),
        "psr": round(psr, 4),
        "n_trials": n_trials,
        "n_observations": n_observations,
    }


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
    report_path: Optional[Path] = None,
) -> pd.DataFrame:
    """
    Run backtest across 5 confidence thresholds (Clarification 3).
    For each threshold: qualifying trades, win rate, avg R:R, signal frequency, max consecutive losses.

    report_path: where to save the CSV — defaults to the real
    backtesting/reports/sensitivity_analysis.csv for real callers. Tests
    exercising this function with synthetic outcomes must pass a tmp_path
    override here — without one, a test run silently overwrote the real
    report with synthetic data (confirmed live: the checked-in report file
    matched test_no_deflated_sharpe_columns_when_nothing_qualifies' all-
    below-threshold synthetic outcomes exactly, dated to a test run, not a
    real backtest).

    `outcomes` should be the full unfiltered out-of-sample signal set (see
    backtest_engine._get_test_outcomes) — this function does the threshold
    filtering itself, once per threshold, rather than expecting pre-filtered input.

    Returns DataFrame with columns: threshold, qualifying_trades, win_rate, avg_rr,
    sharpe_ratio, signals_per_month, max_consec_losses, plus (once at least one
    threshold has a nonzero Sharpe) psr_best_threshold_vs_sweep and
    deflated_sharpe_best_threshold — see compute_deflated_sharpe_ratio's
    docstring. Saves to backtesting/reports/sensitivity_analysis.csv.
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
                "sharpe_ratio": 0.0,
                "signals_per_month": 0.0,
                "max_consec_losses": 0,
            })
            continue

        # Sharpe wasn't previously computed per threshold at all — this sweep
        # only reported win_rate/avg_rr, which says nothing about volatility
        # or path risk. Chronological order matters here for the same reason
        # backtest_engine.run_backtest() sorts before building its equity
        # curve: P&L realizes at exit, not at signal-generation order.
        qualifying_chrono = sorted(qualifying, key=lambda o: o.get("exit_date") or o.get("signal_date") or "")
        equity_curve = _build_equity_curve(qualifying_chrono)
        trade_returns = equity_curve.pct_change().dropna()
        sharpe = compute_sharpe(trade_returns, periods_per_year=_trades_per_year(qualifying_chrono))

        rows.append({
            "threshold": threshold,
            "qualifying_trades": len(qualifying),
            "win_rate": round(compute_win_rate(qualifying), 4),
            "avg_rr": round(compute_avg_rr(qualifying), 2),
            "sharpe_ratio": round(sharpe, 2),
            "signals_per_month": round(len(qualifying) / max(test_months, 1.0), 2),
            "max_consec_losses": compute_consecutive_losses(qualifying),
        })

    df = pd.DataFrame(rows)

    # Multiple-testing correction: this sweep tests len(thresholds) configurations
    # and an analyst reading this table will naturally gravitate to whichever
    # threshold has the best Sharpe — exactly the "best of N trials" selection
    # compute_deflated_sharpe_ratio exists to discount. Attach that check right
    # on the table instead of leaving it as a separate step someone has to
    # remember to run.
    if not df.empty and (df["sharpe_ratio"] != 0.0).any():
        best_idx = df["sharpe_ratio"].idxmax()
        best_row = df.loc[best_idx]
        dsr = compute_deflated_sharpe_ratio(
            sharpe_ratios=df["sharpe_ratio"].tolist(),
            selected_sharpe=float(best_row["sharpe_ratio"]),
            n_observations=int(best_row["qualifying_trades"]),
        )
        df["psr_best_threshold_vs_sweep"] = dsr["psr"]
        df["deflated_sharpe_best_threshold"] = dsr["deflated_sharpe"]

    out_path = report_path if report_path is not None else Path("backtesting/reports/sensitivity_analysis.csv")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_path, index=False)

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


# Round-trip (entry + exit) stock-level slippage estimate, in $/share — reuses
# the exact $0.02/share convention already established in
# shared/utils/options_math.py's adjust_ev_for_slippage default, rather than
# inventing a new, uncalibrated number. trade_selector.py already applies
# this same cost when ranking option structures; the backtest's simulated
# P&L previously didn't apply anything at all, making its Sharpe/expectancy
# numbers optimistic versus what real fills will actually produce.
_ROUND_TRIP_SLIPPAGE_PER_SHARE = 0.02 * 2


def _build_equity_curve(
    outcomes: list[dict],
    starting_equity: float = 15000.0,
    include_slippage: bool = True,
) -> pd.Series:
    """
    Build equity curve from ordered trade outcomes.

    include_slippage: when True (the default), subtracts
    _ROUND_TRIP_SLIPPAGE_PER_SHARE / entry_price from each trade's pnl_pct
    before compounding it into the curve. Pass False to reproduce the old
    frictionless behavior (e.g. to isolate some other change's effect in
    isolation from this one).
    """
    equity = starting_equity
    values = [equity]

    for o in outcomes:
        pnl_pct = float(o.get("pnl_pct", 0.0))
        risk_pct = 0.01  # Fixed 1% risk per trade
        risk_dollars = equity * risk_pct
        entry = o.get("entry_price", 1.0) or 1.0
        stop = o.get("stop", entry * 0.97) or entry * 0.97

        if include_slippage and entry > 0:
            pnl_pct -= _ROUND_TRIP_SLIPPAGE_PER_SHARE / entry

        # Normalize: pnl as fraction of risk
        risk_dist = abs(float(entry) - float(stop)) / float(entry) if float(entry) > 0 else 0.03
        dollar_pnl = risk_dollars * (pnl_pct / risk_dist) if risk_dist > 0 else risk_dollars * pnl_pct
        equity += dollar_pnl
        values.append(max(0.0, equity))

    if not values:
        return pd.Series([starting_equity])
    return pd.Series(values)


def build_portfolio_equity_curve(
    outcomes: list[dict],
    starting_equity: float = 15000.0,
    risk_pct: float = 0.01,
    include_slippage: bool = True,
) -> tuple[pd.Series, dict]:
    """
    Equity curve that accounts for concurrently open positions, unlike
    _build_equity_curve's strictly one-trade-at-a-time stepping.

    Why this matters: this project can hold several correlated same-sector
    positions at once (e.g. 4 semiconductor names simultaneously) — real
    portfolio drawdown when correlated bets go wrong together is worse than a
    serial "close one before opening the next" curve can ever show, since
    that curve structurally has at most one position's risk affecting it at
    any point. This walks entry/exit events in true chronological order:
    each position's risk_dollars is locked in at ITS OWN entry against
    whatever equity existed at that moment (not equity that reflects trades
    that hadn't closed yet), and multiple positions can have risk locked in
    simultaneously against the same starting equity — exactly the concurrent-
    exposure scenario a serial curve can't represent.

    Requires each outcome to have signal_date (entry) and exit_date; falls
    back to a same-day round trip (exit_date = signal_date) when exit_date
    is missing, rather than dropping the trade.

    Returns (equity_curve, stats) where stats has:
      max_concurrent_positions: the most positions open at any single point.
      max_concurrent_risk_pct: the largest fraction of starting equity ever
        committed across simultaneously-open positions at once — how much
        worse a single correlated adverse move could have been than the
        1%-per-trade figure alone suggests.
    """
    if not outcomes:
        return pd.Series([starting_equity]), {"max_concurrent_positions": 0, "max_concurrent_risk_pct": 0.0}

    events = []
    for o in outcomes:
        entry_date = o.get("signal_date")
        if entry_date is None:
            continue
        exit_date = o.get("exit_date") or entry_date
        # sort_key second field: entries (0) before exits (1) on the same
        # date, so a same-day round trip is sized before it's realized.
        events.append((pd.Timestamp(entry_date), 0, id(o), o))
        events.append((pd.Timestamp(exit_date), 1, id(o), o))
    events.sort(key=lambda e: (e[0], e[1]))

    equity = starting_equity
    values = [equity]
    committed_risk: dict[int, float] = {}
    open_count = 0
    max_concurrent_positions = 0
    max_concurrent_risk_pct = 0.0

    for _, _, obj_id, o in events:
        # Distinguish entry vs exit event unambiguously: an entry event for
        # this outcome hasn't been recorded in committed_risk yet.
        if obj_id not in committed_risk:
            risk_dollars = equity * risk_pct
            committed_risk[obj_id] = risk_dollars
            open_count += 1
            max_concurrent_positions = max(max_concurrent_positions, open_count)
            # Ratio against CURRENT equity at this point in time, not the
            # account's original starting balance — over a multi-year
            # compounding backtest, dividing a later peak's dollar figure by
            # a years-old starting_equity would overstate concurrent risk
            # purely from equity growth, not from anything about how many
            # positions were actually open relative to capital at the time.
            current_committed = sum(committed_risk.values())
            current_ratio = current_committed / equity if equity > 0 else 0.0
            max_concurrent_risk_pct = max(max_concurrent_risk_pct, current_ratio)
        else:
            risk_dollars = committed_risk.pop(obj_id)
            open_count -= 1
            pnl_pct = float(o.get("pnl_pct", 0.0))
            entry = o.get("entry_price", 1.0) or 1.0
            stop = o.get("stop", entry * 0.97) or entry * 0.97
            if include_slippage and entry > 0:
                pnl_pct -= _ROUND_TRIP_SLIPPAGE_PER_SHARE / entry
            risk_dist = abs(float(entry) - float(stop)) / float(entry) if float(entry) > 0 else 0.03
            dollar_pnl = risk_dollars * (pnl_pct / risk_dist) if risk_dist > 0 else risk_dollars * pnl_pct
            equity += dollar_pnl
            values.append(max(0.0, equity))

    stats = {
        "max_concurrent_positions": max_concurrent_positions,
        "max_concurrent_risk_pct": round(max_concurrent_risk_pct, 4),
    }
    return pd.Series(values), stats


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
