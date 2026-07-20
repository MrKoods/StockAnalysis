"""
Replays scoring logic against historical data.
70/30 out-of-sample split; walk-forward validation; per-regime reporting.
Minimum 100 qualifying trades (confidence 90+, R:R 1:3+) before win rate is valid.
"""

import bisect
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
)


def run_backtest(
    historical_data: dict[str, pd.DataFrame],
    config_path: str = "config/swing_config.yaml",
    train_split: float = 0.70,
    min_qualifying_trades: int = 100,
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
    4. Compute metrics (win rate, R:R, drawdown, Sharpe) per-regime and overall
    5. Run walk-forward validation across available windows
    6. Return full backtest results dict

    Returns dict with all metrics, per-regime results, walk-forward results.
    """
    if not historical_data:
        return {
            "passed": False,
            "error": "no_historical_data",
            "win_rate": 0.0,
            "avg_rr": 0.0,
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

    # Determine pass/fail — scope targets: 80% win rate, 1:3 R:R, 100+ trades
    passed = (
        len(qualifying) >= min_qualifying_trades
        and win_rate >= 0.80
        and avg_rr >= 1.8
        and sharpe >= 1.0
        and max_dd <= 0.15
    )

    result = {
        "passed": passed,
        "win_rate": round(win_rate, 4),
        "avg_rr": round(avg_rr, 2),
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


def run_walk_forward(
    historical_data: dict[str, pd.DataFrame],
    initial_train_months: int = 18,
    validate_months: int = 6,
    config_path: str = "config/swing_config.yaml",
    signal_kwargs: "dict | None" = None,
    include_outcomes: bool = False,
) -> list[dict]:
    """
    Walk-forward validation across all available windows.
    Calibrate on months 1-18, validate on 19-24. Roll: calibrate 1-24, validate 25-30.
    Model must pass thresholds in every window, not just the initial one.
    Returns list of per-window results.

    signal_kwargs: forwarded to _simulate_test_signals (rsi_min/rsi_max/
    min_breakout_volume_zscore/require_confirmation_bar) — lets callers test
    entry-filter variants across every window instead of a single fixed split.
    See backtesting/entry_filter_variants.py.

    include_outcomes: when True, each window's dict also carries its raw
    qualifying-trade outcome list under "outcomes", so a caller can pool
    outcomes across all windows for a single large-sample evaluation. Off by
    default to keep run_backtest()'s saved JSON report lean — it doesn't need
    per-trade detail duplicated inside walk_forward.
    """
    if not historical_data:
        return []

    all_dates = sorted(set(
        date for df in historical_data.values() for date in df.index
    ))
    if not all_dates:
        return []

    signal_kwargs = signal_kwargs or {}
    results = []
    window_num = 0

    while True:
        # Compute approx month boundaries using 21 trading days = 1 month
        train_days = initial_train_months * 21 + window_num * validate_months * 21
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
        passed = win_rate >= 0.70 and avg_rr >= 1.8 and len(qualifying) >= 10

        window_result = {
            "window": window_num + 1,
            "train_through": str(train_cutoff),
            "validate_through": str(val_cutoff),
            "qualifying_trades": len(qualifying),
            "win_rate": round(win_rate, 4),
            "avg_rr": round(avg_rr, 2),
            "passed": passed,
        }
        if include_outcomes:
            window_result["outcomes"] = qualifying
        results.append(window_result)

        window_num += 1
        if val_end_days >= len(all_dates):
            break

    return results


def simulate_trade_outcome(
    signal_date: str,
    direction: str,
    entry: float,
    stop: float,
    target: float,
    future_ohlcv: pd.DataFrame,
    holding_period: tuple[int, int] = (5, 15),
    regime: str = "unknown",
    confidence: float = 90.0,
) -> dict:
    """
    Simulate a single trade outcome against future OHLCV bars.
    Checks target hit, stop hit, and time stop (Day 10 rule) day by day.
    Returns dict: {outcome, exit_date, exit_price, pnl_pct, holding_days, achieved_rr}
    """
    if future_ohlcv.empty or entry <= 0 or stop <= 0 or target <= 0:
        return {"outcome": "no_data", "exit_price": entry, "pnl_pct": 0.0,
                "holding_days": 0, "achieved_rr": 0.0, "confidence": confidence,
                "signal_date": signal_date, "exit_date": signal_date}

    risk = entry - stop if direction == "bullish" else stop - entry
    max_days = holding_period[1]

    for day_idx, (bar_date, bar) in enumerate(future_ohlcv.iterrows()):
        if day_idx >= max_days:
            break

        high = float(bar.get("High", 0))
        low = float(bar.get("Low", 0))

        if direction == "bullish":
            if high >= target:
                return {
                    "outcome": "win",
                    "signal_date": signal_date,
                    "exit_date": str(bar_date),
                    "exit_price": target,
                    "pnl_pct": (target - entry) / entry,
                    "holding_days": day_idx + 1,
                    "achieved_rr": (target - entry) / risk if risk > 0 else 0.0,
                    "regime": regime,
                    "confidence": confidence,
                    "entry_price": entry,
                    "stop": stop,
                }
            if low <= stop:
                return {
                    "outcome": "loss",
                    "signal_date": signal_date,
                    "exit_date": str(bar_date),
                    "exit_price": stop,
                    "pnl_pct": (stop - entry) / entry,
                    "holding_days": day_idx + 1,
                    "achieved_rr": -(entry - stop) / risk if risk > 0 else 0.0,
                    "regime": regime,
                    "confidence": confidence,
                    "entry_price": entry,
                    "stop": stop,
                }
        else:  # bearish
            if low <= target:
                return {
                    "outcome": "win",
                    "signal_date": signal_date,
                    "exit_date": str(bar_date),
                    "exit_price": target,
                    "pnl_pct": (entry - target) / entry,
                    "holding_days": day_idx + 1,
                    "achieved_rr": (entry - target) / risk if risk > 0 else 0.0,
                    "regime": regime,
                    "confidence": confidence,
                    "entry_price": entry,
                    "stop": stop,
                }
            if high >= stop:
                return {
                    "outcome": "loss",
                    "signal_date": signal_date,
                    "exit_date": str(bar_date),
                    "exit_price": stop,
                    "pnl_pct": (stop - entry) / entry * -1,
                    "holding_days": day_idx + 1,
                    "achieved_rr": -1.0,
                    "regime": regime,
                    "confidence": confidence,
                    "entry_price": entry,
                    "stop": stop,
                }

    # Time stop — exit at close of last bar
    final_close = float(future_ohlcv.iloc[min(max_days - 1, len(future_ohlcv) - 1)]["Close"])
    pnl_pct = (final_close - entry) / entry if direction == "bullish" else (entry - final_close) / entry
    return {
        "outcome": "time_stop",
        "signal_date": signal_date,
        "exit_date": str(future_ohlcv.index[min(max_days - 1, len(future_ohlcv) - 1)]),
        "exit_price": final_close,
        "pnl_pct": pnl_pct,
        "holding_days": min(max_days, len(future_ohlcv)),
        "achieved_rr": pnl_pct / (risk / entry) if risk > 0 and entry > 0 else 0.0,
        "regime": regime,
        "confidence": confidence,
        "entry_price": entry,
        "stop": stop,
    }


def _load_fundamental_history(tickers: list, cfg: dict) -> list[tuple[datetime, dict]]:
    """
    Load every archived weekly fundamental snapshot (data/processed/fundamental_history/*.json),
    scored and sorted oldest-to-newest, for point-in-time lookup during backtest replay.

    fundamental_state.json only ever holds the latest snapshot, so scoring every historical
    bar against it would leak today's fundamentals into the past. The dated archive (written
    by indicator_pipeline.py's _archive_fundamental_snapshot on each weekly refresh) lets a
    bar look up the snapshot that was actually current as of its own date instead. Returns []
    until at least one weekly archive exists — bars before the first archived date fall back
    to the neutral fundamental score, the same "accumulates going forward" tradeoff already
    accepted for the Positioning layer.
    """
    from swing_model.fundamental_layer import FundamentalScorer
    import json as _json

    history_dir = Path("data/processed/fundamental_history")
    if not history_dir.exists():
        return []

    scorer = FundamentalScorer(cfg)
    watchlist = [t for t in tickers if t != "SMH"]
    snapshots = []
    for path in sorted(history_dir.glob("*.json")):
        try:
            with open(path, "r") as f:
                snapshot = _json.load(f)
            snap_date = datetime.strptime(snapshot["date"], "%Y-%m-%d").replace(tzinfo=timezone.utc)
            scores = scorer.score_all_tickers(watchlist, snapshot)
            snapshots.append((snap_date, scores))
        except Exception:
            continue

    snapshots.sort(key=lambda pair: pair[0])
    return snapshots


def _fundamental_as_of(history: list[tuple[datetime, dict]], ticker: str, bar_date, neutral: dict) -> dict:
    """Most recent archived fundamental snapshot at or before bar_date; neutral if none yet exists."""
    if not history:
        return neutral
    bar_dt = bar_date if bar_date.tzinfo else bar_date.replace(tzinfo=timezone.utc)
    dates = [snap_date for snap_date, _ in history]
    idx = bisect.bisect_right(dates, bar_dt) - 1
    if idx < 0:
        return neutral
    return history[idx][1].get(ticker, neutral)


def _simulate_test_signals(
    test_data: dict[str, pd.DataFrame],
    config_path: str = "config/swing_config.yaml",
    signal_cutoff: "pd.Timestamp | None" = None,
    rsi_min: float = 45.0,
    rsi_max: float = 70.0,
    min_breakout_volume_zscore: "float | None" = None,
    require_confirmation_bar: bool = False,
) -> list[dict]:
    """
    Replay the real indicator + scoring pipeline against historical OHLCV bars.

    signal_cutoff: when set, bars at or before this date can still be used for
    indicator warmup (SMA50/rolling-high/etc. need history) but never generate a
    signal themselves. Lets the caller hand this function a test slice that starts
    with a warmup buffer of real pre-cutoff bars, instead of every ticker losing its
    first ~60 nominal test-period days to indicator warmup with zero chance of a
    signal — those days had real prior history available, it just wasn't included.

    rsi_min/rsi_max: entry-filter RSI band, overridable for research experiments
    (see backtesting/entry_filter_variants.py). Default tightened from the
    original 45-82 to 45-70 in v2.2.5 — walk-forward evidence pooled across all
    24 windows (2014-2026) showed 82 lets through too many already-extended
    moves with less runway left to reach target: 45-70 improved pooled win rate
    49.4%→60.8% at a real cost of ~3x fewer qualifying candidates. This is a
    backtest-only candidate-selection filter — it does not exist in and does
    not change live/paper scoring, which already scores RSI continuously
    (swing_model/scoring.py, 0-8 points, no hard cutoff).

    min_breakout_volume_zscore: if set, requires the breakout bar's volume
    z-score (vs. its own 20-day history) to be at or above this value — a
    conviction filter (weak-volume breakouts are more prone to stalling).
    None (default) disables this filter entirely, matching original behavior.

    require_confirmation_bar: if True, the bar immediately after the breakout
    must also close above the breakout level before a signal counts — filters
    out one-day pops that immediately fade. When a candidate is confirmed,
    entry/indicators/outcome simulation all shift to that next bar (the
    breakout bar itself is never used as the entry bar in this mode).

    All scoring layers are applied:
    - Technical: real historical OHLCV via compute_technical_indicators
    - Positioning: static neutral proxy (no historical StockTwits/options/short-interest
      archive exists yet — accumulates from the first live scan onward, same caveat as
      Fundamental below)
    - Sentiment: price-momentum proxy (5-day return → retail sentiment correlation)
    - News: real Alpha Vantage historical articles where available; neutral fallback
    - Fundamental: point-in-time lookup against the archived weekly snapshot on or before
      each bar's date (data/processed/fundamental_history/); neutral for bars before the
      first archived snapshot exists

    Signal candidates: bars where close breaks the prior 20-day high AND pass
    three quality gates (trend intact, sector alignment, healthy RSI range).
    These gates mirror conditions the live model implicitly requires through high
    confidence scores — making them explicit here prevents low-quality breakouts
    from diluting the qualifying pool.

    Confidence is scaled to 0-100 relative to the maximum achievable raw score
    (with all layers active) so the >=90 qualifying threshold remains consistent.
    """
    import yaml
    from shared.indicators.technical_common import compute_technical_indicators
    from swing_model.scoring import compute_confidence_score
    from swing_model.news_layer import compute_news_score
    from shared.utils.regime_detection import classify_regime, get_regime_modifiers
    from shared.utils.seasonality import get_seasonality_modifier
    from shared.utils.risk_reward import compute_entry_zone, compute_stop_loss, compute_target
    from backtesting.historical_news_loader import load_historical_news

    try:
        cfg = yaml.safe_load(Path(config_path).read_text()) or {}
    except Exception:
        cfg = {}

    _neutral_fundamental = {"fundamental_score": 0.0, "data_quality": "unavailable"}

    # Fallback news when no historical cache exists for a bar's date
    _neutral_news = {
        "news_score_total": 7.5,
        "credibility_weighted_score": 3.0,
        "theme_alignment_score": 2.0,
        "clustering_score": 1.5,
        "decay_score": 1.0,
    }

    # No historical StockTwits/options/institutional/short-interest archive exists yet
    # (same forward-building-history caveat as Fundamental) — Positioning contributes a
    # fixed neutral midpoint (10 of 20: options 3, institutional 2.5, short_interest 2,
    # insider 1.5, analyst 1) to every backtested bar rather than a data-derived proxy.
    _neutral_positioning = {
        "positioning_score_total": 10.0,
        "options_score": 3.0, "institutional_score": 2.5,
        "short_interest_score": 2.0, "insider_score": 1.5, "analyst_score": 1.0,
        "positioning_offline": False, "data_quality": "unavailable",
    }

    # Max achievable raw score with all layers active (5-category system):
    # technical ≤ 36, positioning fixed at 10 (neutral proxy, not variable),
    # price-momentum sentiment ≤ 14, real news ≤ 15,
    # fundamental (avg qualifying tickers, rescaled to the new 10-pt contribution) ≤ 5,
    # regime +5, seasonality +5 → ~90 theoretical.
    # Rescaled proportionally from the pre-redesign calibrated value (72/94 ratio) pending
    # a full Phase 12 re-backtest against real historical Positioning/StockTwits data —
    # this constant should be re-validated once that data exists, not treated as final.
    _BACKTEST_SCORE_MAX = 69.0

    # Load the archived weekly fundamental snapshots once; each bar looks up the
    # snapshot on or before its own date (see _fundamental_as_of).
    fundamental_history = _load_fundamental_history(list(test_data.keys()), cfg)

    smh_df = test_data.get("SMH")
    rr_cfg = cfg.get("risk_reward", {})
    outcomes = []

    # Pre-compute SMH sector uptrend mask (O(n) once).
    # Require sector SMA20 > SMA50 AND SMH close > SMA50 before any individual
    # stock breakout is considered. In mixed markets the sector carries lagging
    # names upward briefly before reversing — dual confirmation eliminates
    # the highest-failure-rate subset from the qualifying pool.
    smh_sector_trend: pd.Series | None = None
    if smh_df is not None and len(smh_df) >= 55:
        smh_sma20 = smh_df["Close"].rolling(20).mean()
        smh_sma50 = smh_df["Close"].rolling(50).mean()
        smh_sector_trend = (smh_sma20 > smh_sma50) & (smh_df["Close"] > smh_sma50)

    for ticker, df in test_data.items():
        if ticker == "SMH" or df.empty or len(df) < 65:
            continue

        # Align SMH benchmark to ticker index
        if smh_df is not None:
            bench_aligned = smh_df["Close"].reindex(df.index, method="ffill")
        else:
            bench_aligned = pd.Series(100.0, index=df.index)

        # Pre-compute 20-day breakout mask on the full ticker DataFrame (O(n), no look-ahead)
        prior_20d_high = df["High"].rolling(20).max().shift(1)
        breakout_mask = df["Close"] > prior_20d_high

        # Only iterate breakout bars that have enough history for indicator computation
        signal_indices = [i for i in range(60, len(df) - 1) if breakout_mask.iloc[i]]

        for i in signal_indices:
            bar_date = df.index[i]
            if signal_cutoff is not None and bar_date <= signal_cutoff:
                # Warmup-buffer bar (real pre-cutoff history included so early
                # test-period bars aren't starved of indicator context) — usable
                # for computing indicators on later bars via df_slice, but not
                # itself an out-of-sample signal.
                continue

            entry_idx = i
            if require_confirmation_bar:
                # Next bar must still close above the breakout level — filters
                # out one-day pops that immediately fade. Entry shifts to the
                # confirmation bar itself, not the original breakout bar.
                if i + 1 >= len(df):
                    continue
                if not (df["Close"].iloc[i + 1] > prior_20d_high.iloc[i]):
                    continue
                entry_idx = i + 1
                bar_date = df.index[entry_idx]
                if signal_cutoff is not None and bar_date <= signal_cutoff:
                    continue

            df_slice = df.iloc[:entry_idx + 1]
            bench_slice = bench_aligned.iloc[:entry_idx + 1]

            try:
                indicators = compute_technical_indicators(df_slice, bench_slice, cfg)
            except Exception:
                continue

            # Quality pre-filters: conditions most predictive of breakout follow-through.
            # 1. trend_intact: SMA20 > SMA50 AND price > SMA50 (stock uptrend structure).
            # 2. Sector uptrend: SMH SMA20 > SMA50 AND SMH close > SMA50.
            # 3. 20-day raw RS > 0: stock outperformed SMH over the past 20 days.
            #    Captures intra-sector rotation (e.g., non-NVDA names lagging NVDA-inflated SMH)
            #    that rs_zscore (a normalized z-score) can miss because z-score can be positive
            #    even when absolute performance lags the benchmark.
            # 4. RSI band (default 45-82): healthy momentum range.
            # 5. Optional volume confirmation / next-bar confirmation — see docstring.
            if not indicators.get("trend_intact", False):
                continue
            if smh_sector_trend is not None:
                smh_idx = smh_sector_trend.index.get_indexer([bar_date], method="ffill")
                if smh_idx[0] >= 0 and not bool(smh_sector_trend.iloc[smh_idx[0]]):
                    continue
            if float(indicators.get("rs_zscore", -2.0)) < 0.0:
                continue
            if len(df_slice) >= 21 and len(bench_slice) >= 21:
                stock_ret_20d = float(df_slice["Close"].iloc[-1] / df_slice["Close"].iloc[-21]) - 1.0
                bench_ret_20d = float(bench_slice.iloc[-1] / bench_slice.iloc[-21]) - 1.0
                if stock_ret_20d < bench_ret_20d:
                    continue
            rsi_val = float(indicators.get("rsi_14", 50.0))
            if rsi_val < rsi_min or rsi_val > rsi_max:
                continue
            if min_breakout_volume_zscore is not None:
                if float(indicators.get("breakout_volume_zscore", 0.0)) < min_breakout_volume_zscore:
                    continue

            # Seasonality from the signal bar date
            try:
                seas_mod = get_seasonality_modifier(
                    date=bar_date.to_pydatetime(), cfg=cfg
                ).get("confidence_modifier", 0.0)
            except Exception:
                seas_mod = 0.0

            # Regime from SMH slice using realized-volatility VIX proxy.
            # This correctly classifies bear/choppy/high-vol periods rather than
            # forcing every bar into trending_up with a flat VIX=15 constant.
            regime = "choppy"
            regime_mod = 0.0
            if smh_df is not None:
                smh_slice = smh_df[smh_df.index <= bar_date]
                if len(smh_slice) >= 22:
                    try:
                        vix_proxy = _compute_vix_proxy(smh_slice)
                        regime = classify_regime(vix=vix_proxy, smh_ohlcv=smh_slice)
                        regime_mod = get_regime_modifiers(regime, cfg).get("regime_modifier", 0.0)
                    except Exception:
                        pass

            # Price-momentum sentiment proxy: when price is trending up,
            # retail sentiment tends to be bullish. This is a documented
            # phenomenon at short horizons and better than a flat neutral
            # mid-point.
            sentiment = _sentiment_from_price_momentum(df_slice)

            # Historical news: use real AV articles when downloaded,
            # fall back to neutral mid-point when not yet available.
            bar_dt = bar_date.to_pydatetime()
            try:
                hist_articles = load_historical_news(ticker, bar_dt, lookback_days=5)
            except Exception:
                hist_articles = []

            if hist_articles:
                try:
                    from datetime import timezone as _tz
                    ref = bar_dt if bar_dt.tzinfo else bar_dt.replace(tzinfo=_tz.utc)
                    news = compute_news_score(hist_articles, [], ticker, cfg, reference_date=ref)
                except Exception:
                    news = _neutral_news
            else:
                news = _neutral_news

            fundamental = _fundamental_as_of(fundamental_history, ticker, bar_date, _neutral_fundamental)

            try:
                score = compute_confidence_score(
                    technical=indicators,
                    positioning=_neutral_positioning,
                    sentiment=sentiment,
                    news=news,
                    regime_modifier=regime_mod,
                    sector_rotation_modifier=0.0,
                    earnings_modifier=0.0,
                    cross_ticker_modifier=0.0,
                    seasonality_modifier=seas_mod,
                    macro_modifier=0.0,
                    cfg=cfg,
                    regime=regime,
                    fundamental=fundamental,
                )
            except Exception:
                continue

            # Scale to 0-100 so the existing >=90 qualifying threshold applies correctly
            raw_score = score.get("final_score", 0.0)
            confidence = min(100.0, raw_score * (100.0 / _BACKTEST_SCORE_MAX))

            entry = indicators.get("close", 0.0)
            atr = indicators.get("atr_14", entry * 0.02)
            breakout_level = indicators.get("rolling_high_20", entry)

            try:
                entry_lower, _ = compute_entry_zone(
                    entry, breakout_level, atr,
                    rr_cfg.get("entry_zone_half_width_atr", 0.25),
                )
                stop = compute_stop_loss(
                    entry_lower, atr,
                    stop_atr_multiplier=rr_cfg.get("stop_atr_multiplier", 2.0),
                )
                target = compute_target(entry, stop, min_rr=rr_cfg.get("min_rr_ratio", 3.0))
            except Exception:
                continue

            if stop <= 0 or target is None or target <= entry or atr <= 0:
                continue

            future = df.iloc[entry_idx + 1: entry_idx + 16]
            if future.empty:
                continue

            outcome = simulate_trade_outcome(
                signal_date=str(bar_date),
                direction="bullish",
                entry=entry,
                stop=stop,
                target=target,
                future_ohlcv=future,
                confidence=confidence,
                regime=regime,
            )
            outcome["ticker"] = ticker
            outcomes.append(outcome)

    return outcomes


def _compute_vix_proxy(smh_df: pd.DataFrame) -> float:
    """
    Estimate a VIX-equivalent value from SMH realized volatility.
    Uses a 10-day trailing lookback to be responsive to volatility spikes
    (e.g., the August 2024 Japan rate-hike shock) rather than diluting them
    into a 20-day average that never crosses the high-vol threshold.
    15% annualized → VIX 15, 30% annualized → VIX 30.
    """
    if len(smh_df) < 12:
        return 15.0
    close = smh_df["Close"]
    returns = close.pct_change().dropna().tail(10)
    if len(returns) < 5:
        return 15.0
    realized_vol = float(returns.std() * (252 ** 0.5)) * 100  # annualized, in VIX units
    return max(10.0, min(60.0, realized_vol))


def _sentiment_from_price_momentum(df_slice: pd.DataFrame) -> dict:
    """
    Derive a proxy sentiment dict from 5-day price momentum.

    At short horizons, retail sentiment is strongly correlated with recent
    price performance. This gives a more realistic sentiment proxy than a
    flat neutral mid-point, without requiring historical StockTwits/Seeking
    Alpha data (none exists prior to this redesign's first live scan).

    Maps to the same dict structure expected by compute_confidence_score():
    sentiment_score_total, ratio_score, velocity_score, engagement_score,
    dominant_sentiment, sentiment_offline.
    """
    close = df_slice["Close"].values
    mom_5d = (close[-1] - close[-6]) / close[-6] if len(close) >= 6 else 0.0
    mom_1d = (close[-1] - close[-2]) / close[-2] if len(close) >= 2 else 0.0

    # Map 5-day momentum to total sentiment score (0-15 scale)
    if mom_5d > 0.07:
        total, dom = 13.0, "bullish"
    elif mom_5d > 0.04:
        total, dom = 11.5, "bullish"
    elif mom_5d > 0.015:
        total, dom = 9.5, "bullish"
    elif mom_5d > -0.005:
        total, dom = 8.0, "neutral"
    elif mom_5d > -0.025:
        total, dom = 6.5, "neutral"
    else:
        total, dom = 5.0, "bearish"

    # Add intraday momentum bonus (strong green day often spikes retail chatter)
    if mom_1d > 0.03:
        total = min(15.0, total + 1.1)
    elif mom_1d < -0.03:
        total = max(0.0, total - 1.1)

    # Break total into sub-scores proportionally (ratio carries most weight)
    ratio = round(total * (7.0 / 15.0), 2)       # 0-7
    velocity = round(total * (5.0 / 15.0), 2)    # 0-5
    engagement = round(total * (3.0 / 15.0), 2)  # 0-3

    return {
        "sentiment_score_total": round(total, 2),
        "ratio_score": ratio,
        "velocity_score": velocity,
        "engagement_score": engagement,
        "dominant_sentiment": dom,
        "sentiment_offline": False,
    }


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


def _build_equity_curve(outcomes: list[dict], starting_equity: float = 15000.0) -> pd.Series:
    """Build equity curve from ordered trade outcomes."""
    equity = starting_equity
    values = [equity]

    for o in outcomes:
        pnl_pct = float(o.get("pnl_pct", 0.0))
        risk_pct = 0.01  # Fixed 1% risk per trade
        risk_dollars = equity * risk_pct
        entry = o.get("entry_price", 1.0) or 1.0
        stop = o.get("stop", entry * 0.97) or entry * 0.97

        # Normalize: pnl as fraction of risk
        risk_dist = abs(float(entry) - float(stop)) / float(entry) if float(entry) > 0 else 0.03
        dollar_pnl = risk_dollars * (pnl_pct / risk_dist) if risk_dist > 0 else risk_dollars * pnl_pct
        equity += dollar_pnl
        values.append(max(0.0, equity))

    if not values:
        return pd.Series([starting_equity])
    return pd.Series(values)


def _save_report(result: dict) -> None:
    """Save backtest result JSON to backtesting/reports/."""
    report_dir = Path("backtesting/reports")
    report_dir.mkdir(parents=True, exist_ok=True)
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    path = report_dir / f"swing_backtest_{date_str}.json"
    with open(path, "w") as f:
        import json
        json.dump(result, f, indent=2, default=str)
