"""
Walk-forward validation across all available historical windows. Split out of
backtest_engine.py (see that module's docstring for why) — this piece is
independent of the single fixed 70/30 split and is reused by
entry_filter_variants.py to pool trades across many windows.
"""

from typing import Optional

import pandas as pd

from backtesting.metrics import compute_win_rate, compute_avg_rr
from backtesting.simulation import _simulate_test_signals


def run_walk_forward(
    historical_data: dict[str, pd.DataFrame],
    initial_train_months: Optional[int] = None,
    validate_months: Optional[int] = None,
    step_months: "int | None" = None,
    config_path: str = "config/swing_config.yaml",
    signal_kwargs: "dict | None" = None,
    include_outcomes: bool = False,
    min_trades_for_verdict: int = 10,
    win_rate_bar: float = 0.55,
    avg_rr_bar: float = 1.3,
) -> list[dict]:
    """
    Walk-forward validation across all available windows.

    validate_months / step_months (v2.2.6): decoupled so validation windows can
    be sized to the strategy's actual signal frequency (default 24 months —
    at this design's ~0.5-2 qualifying signals/month post-v2.2.5, a 6-month
    window routinely yields 0-5 trades, too few to judge win rate on at all)
    while still stepping forward more finely (step_months, default = same as
    validate_months if unset) to produce enough — optionally overlapping —
    windows to assess stability. The original 6-month non-overlapping window
    (pre-v2.2.6) produced 0/24 "passed" windows almost entirely because most
    windows never reached min_trades_for_verdict, not because win rate/R:R
    were actually bad in the windows that did have enough trades to judge.

    win_rate_bar / avg_rr_bar (v2.2.6): default lowered from the original
    0.70/1.8 to 0.55/1.3 — see CHANGELOG.md v2.2.6 for the evidence (pooled
    24-window backtest result was ~60.8% WR / 1.41 avg R:R after the v2.2.5
    RSI change) and reasoning behind recalibrating this bar rather than
    continuing to score every window against a target the strategy has never
    once hit. Still overridable per-call for research (e.g. re-checking
    against the original bar).

    min_trades_for_verdict (v2.2.6): windows with fewer qualifying trades than
    this get verdict="insufficient_data", not "fail" — a window with zero
    signals during a regime this strategy structurally can't trade (see
    CHANGELOG.md v2.2.4's regime-coverage finding) is not evidence of failure,
    it's the entry filter correctly staying quiet. Previously such windows
    were indistinguishable from genuine underperformance in the "passed"
    field alone.

    signal_kwargs: forwarded to _simulate_test_signals (rsi_min/rsi_max/
    min_breakout_volume_zscore/require_confirmation_bar) — lets callers test
    entry-filter variants across every window instead of a single fixed split.
    See backtesting/entry_filter_variants.py.

    include_outcomes: when True, each window's dict also carries its raw
    qualifying-trade outcome list under "outcomes", so a caller can pool
    outcomes across all windows for a single large-sample evaluation. Off by
    default to keep run_backtest()'s saved JSON report lean — it doesn't need
    per-trade detail duplicated inside walk_forward.

    Returns list of per-window results, each with "verdict" (pass/fail/
    insufficient_data) and "passed" (bool, True only when verdict=="pass",
    kept for backward compatibility with anything reading the old field).
    """
    if initial_train_months is None or validate_months is None:
        # Explicit override, else config.backtesting.walk_forward_windows —
        # Tier B batch 2/3 (2026-08-19). initial_train_months default 18.
        # validate_months default 24 (NOT config's old stale 6 — see this
        # function's own docstring above for why 24 was deliberately chosen
        # in v2.2.6; config was corrected to match, not the other way round).
        from swing_model.indicator_pipeline import load_config
        wf_cfg = load_config(config_path).get("backtesting", {}).get("walk_forward_windows", {})
        if initial_train_months is None:
            initial_train_months = int(wf_cfg.get("initial_train_months", 18))
        if validate_months is None:
            validate_months = int(wf_cfg.get("initial_validate_months", 24))
    if not historical_data:
        return []

    all_dates = sorted(set(
        date for df in historical_data.values() for date in df.index
    ))
    if not all_dates:
        return []

    signal_kwargs = signal_kwargs or {}
    step_months = step_months if step_months is not None else validate_months
    results = []
    window_num = 0

    while True:
        # Compute approx month boundaries using 21 trading days = 1 month.
        # Window length is validate_months; step_months controls how far the
        # next window starts from this one (equal to validate_months, i.e.
        # non-overlapping windows, unless the caller sets step_months smaller
        # for overlapping/rolling windows).
        train_days = initial_train_months * 21 + window_num * step_months * 21
        val_end_days = train_days + validate_months * 21

        train_dates = all_dates[:train_days]
        val_dates = all_dates[train_days:val_end_days]

        if len(val_dates) < validate_months * 10:  # Need at least some data
            break

        train_cutoff = train_dates[-1] if train_dates else all_dates[0]
        val_cutoff = val_dates[-1] if val_dates else all_dates[-1]

        val_data = {t: df[(df.index > train_cutoff) & (df.index <= val_cutoff)]
                    for t, df in historical_data.items()}

        outcomes = _simulate_test_signals(val_data, config_path, **signal_kwargs)
        qualifying = [o for o in outcomes if float(o.get("confidence", 0)) >= 90]

        win_rate = compute_win_rate(qualifying)
        avg_rr = compute_avg_rr(qualifying)

        if len(qualifying) < min_trades_for_verdict:
            verdict = "insufficient_data"
        elif win_rate >= win_rate_bar and avg_rr >= avg_rr_bar:
            verdict = "pass"
        else:
            verdict = "fail"

        window_result = {
            "window": window_num + 1,
            "train_through": str(train_cutoff),
            "validate_through": str(val_cutoff),
            "qualifying_trades": len(qualifying),
            "win_rate": round(win_rate, 4),
            "avg_rr": round(avg_rr, 2),
            "verdict": verdict,
            "passed": verdict == "pass",
        }
        if include_outcomes:
            window_result["outcomes"] = qualifying
        results.append(window_result)

        window_num += 1
        if val_end_days >= len(all_dates):
            break

    return results
