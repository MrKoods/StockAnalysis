"""
Historical replay engine: turns raw OHLCV bars into simulated trade outcomes by
running the real indicator + scoring pipeline against the past. Split out of
backtest_engine.py (which now only orchestrates train/test split, metrics, and
reporting) since this is where nearly every backtest-methodology bug has been
found and fixed (Sharpe periodicity, equity-curve ordering, fundamental
point-in-time leakage) — a single ~950-line file mixing simulation with
orchestration made those harder to isolate than they needed to be.
"""

import bisect
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd


def simulate_trade_outcome(
    signal_date: str,
    direction: str,
    entry: float,
    stop: float,
    target: float,
    future_ohlcv: pd.DataFrame,
    holding_period: tuple[int, int] = (1, 15),
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
                    "achieved_rr": -(stop - entry) / risk if risk > 0 else 0.0,
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


def _load_fundamental_history(tickers: list, cfg: dict, benchmark_ticker: str = "SMH") -> list[tuple[datetime, dict]]:
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
    watchlist = [t for t in tickers if t != benchmark_ticker]
    snapshots = []
    for path in sorted(history_dir.glob("*.json")):
        try:
            with open(path, "r", encoding="utf-8") as f:
                snapshot = _json.load(f)
            snap_date = datetime.strptime(snapshot["date"], "%Y-%m-%d").replace(tzinfo=timezone.utc)
            scores = scorer.score_all_tickers(watchlist, snapshot)
            snapshots.append((snap_date, scores))
        except Exception:
            continue

    snapshots.sort(key=lambda pair: pair[0])
    return snapshots


def _load_macro_series(macro_dir: str = "data/historical_macro") -> tuple:
    """
    Load cached historical TNX (10-yr Treasury yield) and DXY (USD index)
    close-price series for backtest-time macro_overlay computation. Returns
    (tnx_series, dxy_series); either is None if its CSV isn't present.
    compute_macro_state() degrades to a neutral read when a series is None,
    the same "accumulates going forward"/graceful-degradation pattern already
    used for Positioning and Fundamental. Research data, not part of the live
    watchlist — see CHANGELOG.md v2.2.7 for why this exists.
    """
    macro_path = Path(macro_dir)
    tnx = dxy = None
    for fname, attr in (("TNX.csv", "tnx"), ("DXY.csv", "dxy")):
        path = macro_path / fname
        if not path.exists():
            continue
        try:
            df = pd.read_csv(path, parse_dates=["Date"], index_col="Date")
            df.index = pd.to_datetime(df.index, utc=True)
            series = pd.to_numeric(df["Close"], errors="coerce").dropna()
            if attr == "tnx":
                tnx = series
            else:
                dxy = series
        except Exception:
            continue
    return tnx, dxy


def _load_spy_series(spy_path: str = "data/historical_market/SPY.csv") -> "pd.Series | None":
    """
    Load cached SPY close-price history for backtest-time sector_rotation
    computation. Returns None if the CSV isn't present — the sector_rotation
    block below degrades to a neutral modifier, same pattern as
    _load_macro_series. SPY is the fixed cross-sector benchmark shared by all
    3 backtested sectors, so it lives outside any one sector's own
    data/historical*/ directory. Research data, not part of the live
    watchlist — mirrors data/historical_macro/ (see v2.2.7).
    """
    path = Path(spy_path)
    if not path.exists():
        return None
    try:
        df = pd.read_csv(path, parse_dates=["Date"], index_col="Date")
        df.index = pd.to_datetime(df.index, utc=True)
        return pd.to_numeric(df["Close"], errors="coerce").dropna()
    except Exception:
        return None


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
    rsi_max: float = 82.0,
    rsi_min_bearish: float = 18.0,
    rsi_max_bearish: float = 55.0,
    min_breakout_volume_zscore: "float | None" = None,
    require_confirmation_bar: bool = False,
    benchmark_ticker: str = "SMH",
    min_rr_bearish: "float | None" = None,
    stop_atr_multiplier_bearish: "float | None" = None,
    bearish_entry_style: str = "continuation",
    bounce_fade_lookback: int = 10,
    bounce_fade_min_bounce_atr: float = 1.0,
    bounce_fade_rsi_min: float = 45.0,
    bounce_fade_rsi_max: float = 65.0,
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
    (see backtesting/entry_filter_variants.py). v2.2.5 (2026-07-19) tightened this
    from 45-82 to 45-70 on walk-forward evidence that was valid for the scoring
    formula at the time. v2.2.29 (2026-08-01) re-tested both bands under the current
    5-category formula and found the 45-70 tightening's benefit had evaporated —
    reverted to 45-82. Re-confirmed again here (2026-08-01) against both the
    semis-only test AND the newly-wired 3-sector pooled test
    (run_multi_sector_backtest): 82 beats 70 on every axis that matters — trade
    count (108 vs 28 semis-only, 266 vs 91 pooled), Sharpe (2.81 vs 1.16 semis-only,
    3.10 vs 2.29 pooled), and go-live-gate pass/fail (82 passes both slices, 70
    fails both). Do not revert to 70 without a similarly direct A/B result — a
    plausible-sounding rationale is not sufficient given this parameter's history
    of being flipped back and forth without being re-validated each time. This is a
    backtest-only candidate-selection filter — it does not exist in and does
    not change live/paper scoring, which already scores RSI continuously
    (swing_model/scoring.py, 0-8 points, no hard cutoff).

    benchmark_ticker: the sector benchmark to compare tickers against (SMH for
    semiconductors, KRE for regional banks, XLV for healthcare) — must be a key
    in test_data. Excluded from the candidate loop itself.

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

    Signal candidates: bars where close breaks the prior 20-day high (bullish)
    or falls below the prior 20-day low (bearish), AND pass three quality gates
    mirrored per direction (trend/downtrend intact, sector alignment, healthy
    RSI range — oversold band for bearish, rsi_min_bearish/rsi_max_bearish).
    These gates mirror conditions the live model implicitly requires through high
    confidence scores — making them explicit here prevents low-quality breakouts/
    breakdowns from diluting the qualifying pool.

    rsi_min_bearish/rsi_max_bearish: bearish counterpart to rsi_min/rsi_max —
    starts as a direct mirror of the bullish band (100 - 82 = 18, 100 - 45 =
    55) pending its own backtest re-validation the same way the bullish band's
    boundaries were themselves re-tested rather than assumed (see rsi_min/
    rsi_max's own history above). CHANGELOG v2.2.58's initial backtest found
    this band alone doesn't explain the bearish path's underperformance
    (raising the floor 18->35 improved win rate 32%->43% but Sharpe stayed
    deeply negative throughout) — see min_rr_bearish below for the hypothesis
    tested next.

    min_rr_bearish/stop_atr_multiplier_bearish: bearish-specific overrides for
    risk_reward.py's min_rr_ratio/stop_atr_multiplier (both None by default,
    falling back to the same config values bullish uses — rr_cfg's
    min_rr_ratio/stop_atr_multiplier, currently 3.0/2.0 for both directions
    identically). Research hypothesis (CHANGELOG v2.2.58 follow-up): a
    breakdown may not continue down far/fast enough within the 15-day holding
    period to reach an ATR-sized 3R target the way a breakout continues up —
    bearish trades' avg R:R sat at 0.7-1.3 against the 3R target with a large
    time_stop share, consistent with the target being oversized for what the
    downside move actually delivers in this holding window, not with the
    entry filter being wrong. Overridable per-call for exactly this research,
    same pattern as rsi_min/rsi_max.

    bearish_entry_style: "continuation" (default, unchanged behavior) shorts
    the breakdown bar itself, mirroring the bullish breakout entry exactly.
    "capitulation_fade" is a research alternative (CHANGELOG v2.2.59's working
    theory): the continuation mirror enters right after a breakdown, near
    where a relief bounce/short-squeeze is likeliest — the opposite of the
    bullish case, where entering a fresh breakout while RSI is still healthy
    (not yet stretched) is the point. capitulation_fade instead waits for the
    bounce that follows a breakdown and shorts its exhaustion — still inside
    an intact downtrend — once RSI recovers into a neutral band and rolls
    back over (see shared/indicators/technical_common.py's
    bounce_fade_setup()). The bounce_fade_* params tune that detection and
    only apply when bearish_entry_style == "capitulation_fade"; bullish
    candidate generation is completely unaffected either way.

    Confidence is scaled to 0-100 relative to the maximum achievable raw score
    (with all layers active) so the >=90 qualifying threshold remains consistent.
    """
    import yaml
    from shared.indicators.technical_common import compute_technical_indicators, bounce_fade_setup
    # Aliased: this function already has local variables named `atr`/`rsi_val`
    # per-candidate below (the current bar's scalar ATR/RSI reading) — importing
    # the technical_common series functions under their own names would make
    # Python treat them as local throughout this whole function (assigned
    # later in the loop) and raise UnboundLocalError the first time they're
    # called, before ever reaching that later assignment.
    from shared.indicators.technical_common import rsi as _rsi_series
    from shared.indicators.technical_common import atr as _atr_series
    from shared.indicators.technical_common import sma as _sma_series
    from swing_model.scoring import compute_confidence_score
    from swing_model.news_layer import compute_news_score
    from shared.utils.regime_detection import classify_regime, get_regime_modifiers
    from shared.utils.seasonality import get_seasonality_modifier
    from shared.utils.risk_reward import compute_entry_zone, compute_stop_loss, compute_target
    from shared.utils.macro_overlay import compute_macro_state
    from shared.utils.sector_rotation import (
        compute_rotation_state, dampen_rotation_penalty_for_leader, get_rotation_modifier,
    )
    from swing_model.cross_ticker_analysis import analyze_cross_ticker
    from backtesting.historical_news_loader import load_historical_news

    try:
        cfg = yaml.safe_load(Path(config_path).read_text(encoding="utf-8")) or {}
    except Exception:
        cfg = {}

    # get_seasonality_modifier/compute_macro_state both restrict their real
    # adverse/favorable logic to the semiconductor sector they were built and
    # validated for (see each module's _SECTORS_WITH_VALIDATED_* set) — every
    # other live/paper call site already passes a sector for exactly this
    # reason. This function's calls below previously passed none at all, so
    # the backtest applied the semiconductor-specific seasonality calendar
    # and TNX/DXY rate rationale to regional-bank/healthcare/consumer-
    # discretionary bars too whenever this ran against those datasets —
    # contaminating any pooled-sector calibration read of whether either
    # modifier's real logic (not its neutral-elsewhere fallback) is correct.
    _BENCHMARK_TO_SECTOR = {
        "SMH": "semiconductors", "KRE": "regional_banks",
        "XLV": "healthcare", "XLY": "consumer_discretionary",
    }
    sector = _BENCHMARK_TO_SECTOR.get(benchmark_ticker)

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
    fundamental_history = _load_fundamental_history(list(test_data.keys()), cfg, benchmark_ticker=benchmark_ticker)

    # Load cached TNX/DXY series once for point-in-time macro_overlay computation
    # (v2.2.7 — previously hardcoded to macro_modifier=0.0 always; see CHANGELOG).
    # China tension defaults to 0 (no historical news-keyword archive covers the
    # full backtest window) — neutral-when-unavailable, same as News/Fundamental.
    tnx_series, dxy_series = _load_macro_series()

    # Load cached SPY series once for point-in-time sector_rotation computation
    # (v2.2.X — previously hardcoded to sector_rotation_modifier=0.0 always,
    # see modifier_calibration_diagnostic.py's former _NEVER_EXERCISED_IN_BACKTEST).
    spy_close_series = _load_spy_series()

    smh_df = test_data.get(benchmark_ticker)
    rr_cfg = cfg.get("risk_reward", {})
    outcomes = []

    # Pre-compute SMH sector uptrend/downtrend masks (O(n) once).
    # Require sector SMA20 > SMA50 AND SMH close > SMA50 before any individual
    # stock breakout is considered (mirror: SMA20 < SMA50 AND close < SMA50 for
    # a breakdown). In mixed markets the sector carries lagging names upward
    # (or downward) briefly before reversing — dual confirmation eliminates
    # the highest-failure-rate subset from the qualifying pool.
    smh_sector_trend: pd.Series | None = None
    smh_sector_downtrend: pd.Series | None = None
    if smh_df is not None and len(smh_df) >= 55:
        smh_sma20 = smh_df["Close"].rolling(20).mean()
        smh_sma50 = smh_df["Close"].rolling(50).mean()
        smh_sector_trend = (smh_sma20 > smh_sma50) & (smh_df["Close"] > smh_sma50)
        smh_sector_downtrend = (smh_sma20 < smh_sma50) & (smh_df["Close"] < smh_sma50)

    # Pre-compute trend_intact/breakout_confirmed for every sector ticker
    # (O(n) once per ticker, vectorized) — feeds cross_ticker_modifier below.
    # Cheap reuse of the same rolling-window primitives already used for the
    # breakout/breakdown masks above, not a full compute_technical_indicators()
    # call per candidate bar (which would be the expensive way to get this).
    _sector_trend_intact: dict[str, pd.Series] = {}
    _sector_breakout_confirmed: dict[str, pd.Series] = {}
    for _t, _d in test_data.items():
        if _t == benchmark_ticker or _d.empty or len(_d) < 55:
            continue
        _t_sma20 = _d["Close"].rolling(20).mean()
        _t_sma50 = _d["Close"].rolling(50).mean()
        _sector_trend_intact[_t] = (_t_sma20 > _t_sma50) & (_d["Close"] > _t_sma50)
        _sector_breakout_confirmed[_t] = _d["Close"] > _d["High"].rolling(20).max().shift(1)

    for ticker, df in test_data.items():
        if ticker == benchmark_ticker or df.empty or len(df) < 65:
            continue

        # Align SMH benchmark to ticker index
        if smh_df is not None:
            bench_aligned = smh_df["Close"].reindex(df.index, method="ffill")
        else:
            bench_aligned = pd.Series(100.0, index=df.index)

        # Pre-compute 20-day breakout/breakdown masks on the full ticker DataFrame (O(n), no look-ahead)
        prior_20d_high = df["High"].rolling(20).max().shift(1)
        prior_20d_low = df["Low"].rolling(20).min().shift(1)
        breakout_mask = df["Close"] > prior_20d_high
        breakdown_mask = df["Close"] < prior_20d_low

        # capitulation_fade candidate generation: a completely different bar
        # selection from the continuation mirror above (breakdown_mask itself
        # is still needed either way — bounce_fade_setup uses it to find the
        # breakdown a bounce is fading, and the "continuation" branch below
        # uses it directly). See bearish_entry_style's docstring above.
        fade_result = None
        if bearish_entry_style == "capitulation_fade":
            tech_cfg = cfg.get("technical", {})
            rsi_full = _rsi_series(df["Close"], period=tech_cfg.get("rsi_period", 14))
            atr_full = _atr_series(df["High"], df["Low"], df["Close"], period=tech_cfg.get("atr_period", 14))
            sma20_full = _sma_series(df["Close"], tech_cfg.get("ma_short", 20))
            sma50_full = _sma_series(df["Close"], tech_cfg.get("ma_long", 50))
            downtrend_full = (sma20_full < sma50_full) & (df["Close"] < sma50_full)
            fade_result = bounce_fade_setup(
                df["High"], df["Low"], df["Close"], breakdown_mask, downtrend_full,
                rsi_full, atr_full,
                lookback=bounce_fade_lookback, min_bounce_atr=bounce_fade_min_bounce_atr,
                rsi_recovery_min=bounce_fade_rsi_min, rsi_recovery_max=bounce_fade_rsi_max,
            )
            bearish_candidate_mask = fade_result["fade_signal"]
        else:
            bearish_candidate_mask = breakdown_mask

        # Only iterate breakout/breakdown bars that have enough history for indicator
        # computation. Bearish candidates are tagged alongside bullish ones and run
        # through the same per-bar pipeline below with mirrored quality gates/
        # entry-stop-target math — see determine_direction()'s docstring for why the
        # live/paper kill switch (enable_bearish_signals) doesn't gate backtesting:
        # generating a real bearish outcome archive here is what a future calibration
        # pass needs to validate the bearish path at all.
        signal_indices = (
            [(i, "bullish") for i in range(60, len(df) - 1) if breakout_mask.iloc[i]]
            + [(i, "bearish") for i in range(60, len(df) - 1) if bearish_candidate_mask.iloc[i]]
        )
        signal_indices.sort(key=lambda pair: pair[0])

        for i, direction in signal_indices:
            is_bearish = direction == "bearish"
            is_fade_candidate = is_bearish and fade_result is not None
            level_mask = prior_20d_low if is_bearish else prior_20d_high
            bar_date = df.index[i]
            if signal_cutoff is not None and bar_date <= signal_cutoff:
                # Warmup-buffer bar (real pre-cutoff history included so early
                # test-period bars aren't starved of indicator context) — usable
                # for computing indicators on later bars via df_slice, but not
                # itself an out-of-sample signal.
                continue

            entry_idx = i
            # require_confirmation_bar's "next bar still beyond the breakout/
            # breakdown level" check is meaningless for a capitulation_fade
            # candidate (there's no fresh breakdown level at this bar — the
            # breakdown it's fading already happened up to bounce_fade_lookback
            # bars ago) — skip it for fade candidates rather than applying a
            # mismatched check.
            if require_confirmation_bar and not (is_bearish and fade_result is not None):
                # Next bar must still close beyond the breakout/breakdown level —
                # filters out one-day pops/drops that immediately fade. Entry
                # shifts to the confirmation bar itself, not the original bar.
                if i + 1 >= len(df):
                    continue
                next_close = df["Close"].iloc[i + 1]
                level = level_mask.iloc[i]
                confirmed = (next_close < level) if is_bearish else (next_close > level)
                if not confirmed:
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

            # Quality pre-filters: conditions most predictive of breakout/breakdown
            # follow-through, mirrored per direction.
            # 1. trend_intact/downtrend_intact: SMA20/SMA50/price structure.
            # 2. Sector alignment: SMH must be in the same trend as the candidate.
            # 3. 20-day raw RS: stock outperformed (bullish) / underperformed
            #    (bearish) SMH over the past 20 days. Captures intra-sector rotation
            #    that rs_zscore (a normalized z-score) can miss because z-score can
            #    disagree in sign with absolute performance vs. the benchmark.
            # 4. RSI band (bullish 45-82 default, bearish rsi_min_bearish/
            #    rsi_max_bearish default 18-55): healthy momentum range per direction.
            # 5. Optional volume confirmation / next-bar confirmation — see docstring.
            if is_bearish:
                if not indicators.get("downtrend_intact", False):
                    continue
                if smh_sector_downtrend is not None:
                    smh_idx = smh_sector_downtrend.index.get_indexer([bar_date], method="ffill")
                    if smh_idx[0] >= 0 and not bool(smh_sector_downtrend.iloc[smh_idx[0]]):
                        continue
                if float(indicators.get("rs_zscore", 2.0)) > 0.0:
                    continue
                if len(df_slice) >= 21 and len(bench_slice) >= 21:
                    stock_ret_20d = float(df_slice["Close"].iloc[-1] / df_slice["Close"].iloc[-21]) - 1.0
                    bench_ret_20d = float(bench_slice.iloc[-1] / bench_slice.iloc[-21]) - 1.0
                    if stock_ret_20d > bench_ret_20d:
                        continue  # stock outperformed the benchmark -> not a bearish-confirming underperformer
                # rsi_min_bearish/rsi_max_bearish is an oversold-entry band
                # calibrated for the continuation style (short the breakdown
                # while still falling). A fade candidate's RSI is, by
                # construction, already recovered into bounce_fade_rsi_min/max
                # (see bounce_fade_setup) — applying the oversold band here
                # too would reject every fade candidate (its recovered RSI
                # exceeds rsi_max_bearish), checking the wrong thing entirely.
                if not is_fade_candidate:
                    rsi_val = float(indicators.get("rsi_14", 50.0))
                    if rsi_val < rsi_min_bearish or rsi_val > rsi_max_bearish:
                        continue
            else:
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
                    date=bar_date.to_pydatetime(), cfg=cfg, sector=sector
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
                        regime_mod = get_regime_modifiers(regime, cfg, direction=direction).get("regime_modifier", 0.0)
                    except Exception:
                        pass

            # Macro overlay: real TNX (rate direction) / DXY (USD strength) state,
            # computed point-in-time as of bar_date so later history can't leak
            # backward. china_keyword_count_5d fixed at 0 (no historical news-
            # keyword archive covers the full backtest window) — neutral when
            # unavailable, same pattern as News/Fundamental elsewhere here.
            macro_mod = 0.0
            macro_state_label = "unavailable"
            if tnx_series is not None or dxy_series is not None:
                try:
                    tnx_slice = tnx_series[tnx_series.index <= bar_date] if tnx_series is not None else None
                    dxy_slice = dxy_series[dxy_series.index <= bar_date] if dxy_series is not None else None
                    macro_result = compute_macro_state(
                        tnx_slice, dxy_slice, china_keyword_count_5d=0, cfg=cfg, sector=sector
                    )
                    macro_mod = macro_result.get("confidence_modifier", 0.0)
                    macro_state_label = macro_result.get("macro_state", "neutral")
                except Exception:
                    macro_mod = 0.0
                    macro_state_label = "unavailable"

            # Sector rotation: real sector-benchmark-vs-SPY relative-flow state,
            # computed point-in-time as of bar_date so later history can't leak
            # backward. Leader dampening (dampen_rotation_penalty_for_leader)
            # softens the penalty for tickers with strong relative strength vs.
            # their own history, matching the live pipeline (run_swing_model.py).
            rotation_mod = 0.0
            rotation_state_label = "unavailable"
            if smh_df is not None and spy_close_series is not None:
                try:
                    spy_slice = spy_close_series[spy_close_series.index <= bar_date]
                    rotation_result = compute_rotation_state(
                        smh_close=smh_slice["Close"], spy_close=spy_slice, cfg=cfg
                    )
                    rotation_state_label = rotation_result.get("rotation_state", "neutral")
                    rotation_mod = dampen_rotation_penalty_for_leader(
                        get_rotation_modifier(rotation_state_label, cfg, direction=direction),
                        float(indicators.get("rs_zscore", 0.0)),
                        direction=direction,
                    )
                except Exception:
                    rotation_mod = 0.0
                    rotation_state_label = "unavailable"

            # Cross-ticker: real sector-peer trend/breakout state + 5-day
            # returns as of bar_date (point-in-time, no lookahead — every
            # peer's OHLCV is sliced to <= bar_date before analyze_cross_ticker
            # ever sees it). Uses the sector-wide trend_intact/breakout_confirmed
            # masks pre-computed once above (_sector_trend_intact/
            # _sector_breakout_confirmed) rather than a full
            # compute_technical_indicators() call per sibling per bar.
            # earnings_modifier has no equivalent fix — see its own comment
            # at the compute_confidence_score() call below for why.
            cross_ticker_mod = 0.0
            if len(_sector_trend_intact) > 1:
                try:
                    ticker_scores: dict[str, dict] = {}
                    ohlcv_data: dict[str, pd.DataFrame] = {}
                    for peer, peer_df in test_data.items():
                        if peer == benchmark_ticker or peer not in _sector_trend_intact:
                            continue
                        peer_idx = peer_df.index.get_indexer([bar_date], method="ffill")
                        if peer_idx[0] < 0:
                            continue
                        ohlcv_data[peer] = peer_df.iloc[:peer_idx[0] + 1]
                        ticker_scores[peer] = {
                            "trend_intact": bool(_sector_trend_intact[peer].iloc[peer_idx[0]]),
                            "breakout_confirmed": bool(_sector_breakout_confirmed[peer].iloc[peer_idx[0]]),
                        }
                    cross_result = analyze_cross_ticker(ticker_scores, ohlcv_data, cfg=cfg)
                    cross_ticker_mod = cross_result.get(ticker, {}).get("confidence_modifier", 0.0)
                except Exception:
                    cross_ticker_mod = 0.0

            # Price-momentum sentiment proxy: when price is trending up,
            # retail sentiment tends to be bullish. This is a documented
            # phenomenon at short horizons and better than a flat neutral
            # mid-point.
            sentiment = _sentiment_from_price_momentum(df_slice, direction=direction)

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
                    news = compute_news_score(hist_articles, [], ticker, cfg, reference_date=ref, direction=direction)
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
                    sector_rotation_modifier=rotation_mod,
                    # earnings_modifier stays hardcoded 0.0 — unlike macro/
                    # rotation/cross_ticker above, there is no historical
                    # earnings-date archive anywhere in this repo, and
                    # yfinance's live calendar only returns the *next
                    # upcoming* earnings date, which can't be used point-in-
                    # time for a bar in the past without leaking future
                    # information. Wiring this in for real needs a genuine
                    # historical earnings-date archive built first (the same
                    # kind of prerequisite data/historical_macro/TNX.csv/
                    # DXY.csv was for macro_overlay) — a known, honest gap,
                    # not an oversight.
                    earnings_modifier=0.0,
                    cross_ticker_modifier=cross_ticker_mod,
                    seasonality_modifier=seas_mod,
                    macro_modifier=macro_mod,
                    cfg=cfg,
                    regime=regime,
                    fundamental=fundamental,
                    direction_override=direction,
                )
            except Exception:
                continue

            # Scale to 0-100 so the existing >=90 qualifying threshold applies correctly
            raw_score = score.get("final_score", 0.0)
            confidence = min(100.0, raw_score * (100.0 / _BACKTEST_SCORE_MAX))

            entry = indicators.get("close", 0.0)
            atr = indicators.get("atr_14", entry * 0.02)
            # A fade candidate has no fresh breakdown level at this bar (the
            # breakdown it's fading already happened up to bounce_fade_lookback
            # bars ago) — anchor the entry zone on the close itself rather than
            # rolling_low_20, which would incorrectly reference a stale level.
            level = entry if is_fade_candidate else indicators.get(
                "rolling_low_20" if is_bearish else "rolling_high_20", entry
            )
            # The fade's own bounce swing-high/post-breakdown-low (already
            # computed by bounce_fade_setup) are more precise resistance/target
            # references than the generic volume-profile nodes indicators.get()
            # would otherwise supply — reuses compute_stop_loss/compute_target's
            # existing high_volume_resistance/low_volume_area_below params (see
            # risk_reward.py; same mechanism B1's volume-profile wiring uses).
            fade_resistance = fade_target = None
            if is_fade_candidate:
                fade_resistance = fade_result["swing_high_since_breakdown"].iloc[entry_idx]
                fade_target = fade_result["post_breakdown_low"].iloc[entry_idx]

            try:
                effective_stop_atr_mult = (
                    stop_atr_multiplier_bearish
                    if (is_bearish and stop_atr_multiplier_bearish is not None)
                    else rr_cfg.get("stop_atr_multiplier", 2.0)
                )
                effective_min_rr = (
                    min_rr_bearish
                    if (is_bearish and min_rr_bearish is not None)
                    else rr_cfg.get("min_rr_ratio", 3.0)
                )
                entry_lower, entry_upper = compute_entry_zone(
                    entry, level, atr,
                    rr_cfg.get("entry_zone_half_width_atr", 0.25),
                    direction=direction,
                )
                stop = compute_stop_loss(
                    entry_upper if is_bearish else entry_lower, atr,
                    high_volume_support=indicators.get("high_volume_support"),
                    high_volume_resistance=(
                        fade_resistance if is_fade_candidate else indicators.get("high_volume_resistance")
                    ),
                    stop_atr_multiplier=effective_stop_atr_mult,
                    direction=direction,
                )
                target = compute_target(
                    entry, stop,
                    low_volume_area_above=indicators.get("low_volume_area_above"),
                    low_volume_area_below=(
                        fade_target if is_fade_candidate else indicators.get("low_volume_area_below")
                    ),
                    min_rr=effective_min_rr,
                    direction=direction,
                )
            except Exception:
                continue

            if stop <= 0 or target is None or atr <= 0:
                continue
            if is_bearish and target >= entry:
                continue
            if not is_bearish and target <= entry:
                continue

            future = df.iloc[entry_idx + 1: entry_idx + 16]
            if future.empty:
                continue

            outcome = simulate_trade_outcome(
                signal_date=str(bar_date),
                direction=direction,
                entry=entry,
                stop=stop,
                target=target,
                future_ohlcv=future,
                confidence=confidence,
                regime=regime,
            )
            outcome["ticker"] = ticker
            outcome["sector"] = sector
            outcome["direction"] = direction
            outcome["macro_state"] = macro_state_label
            outcome["rotation_state"] = rotation_state_label
            # Numeric modifier values actually used for this bar's score, not
            # just the categorical regime/macro_state/rotation_state labels —
            # needed to measure whether each modifier's real-world outcome
            # correlation matches the magnitude config/swing_config.yaml's
            # modifiers block assigns it (see
            # backtesting/modifier_calibration_diagnostic.py). earnings isn't
            # included since it's still hardcoded to 0.0 above (see that call
            # site's comment) and carries no information here. cross_ticker
            # is now real (wired in above) and included.
            outcome["regime_modifier"] = regime_mod
            outcome["seasonality_modifier"] = seas_mod
            outcome["macro_modifier"] = macro_mod
            outcome["sector_rotation_modifier"] = rotation_mod
            outcome["cross_ticker_modifier"] = cross_ticker_mod
            # Category sub-totals — needed by feedback_loop._fit_logistic_weights'
            # regression (technical/sentiment/news weight calibration) to have
            # anything to fit against; previously only the blended confidence
            # score survived past this point, discarding the components.
            outcome["technical_total"] = score.get("technical_total", 0.0)
            outcome["sentiment_total"] = score.get("sentiment_total", 0.0)
            outcome["news_total"] = score.get("news_total", 0.0)
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


def _sentiment_from_price_momentum(df_slice: pd.DataFrame, direction: str = "bullish") -> dict:
    """
    Derive a proxy sentiment dict from 5-day price momentum.

    At short horizons, retail sentiment is strongly correlated with recent
    price performance. This gives a more realistic sentiment proxy than a
    flat neutral mid-point, without requiring historical StockTwits/Seeking
    Alpha data (none exists prior to this redesign's first live scan).

    Maps to the same dict structure expected by compute_confidence_score():
    sentiment_score_total, ratio_score, velocity_score, engagement_score,
    dominant_sentiment, sentiment_offline.

    direction: sentiment_score_total (and the sub-scores derived from it)
    reflect how strongly momentum CONFIRMS this candidate's own direction —
    symmetric 3-tier/neutral/3-tier ladder either way (previously 3 bullish
    tiers / 2 neutral / 1 bearish tier, skewed toward reading momentum as
    confirming a bullish candidate regardless of what was actually being
    evaluated). dominant_sentiment stays direction-agnostic — it reports
    real momentum direction (bullish/neutral/bearish), not candidate-relative.
    """
    close = df_slice["Close"].values
    mom_5d = (close[-1] - close[-6]) / close[-6] if len(close) >= 6 else 0.0
    mom_1d = (close[-1] - close[-2]) / close[-2] if len(close) >= 2 else 0.0

    if mom_5d > 0.015:
        dom = "bullish"
    elif mom_5d < -0.015:
        dom = "bearish"
    else:
        dom = "neutral"

    # Confirmation-relative momentum: positive = confirms this candidate's
    # own direction, negative = opposes it. Flipping the sign for "bearish"
    # is what makes the tier ladder below symmetric per-direction instead of
    # always reading raw upward momentum as the confirming case.
    sign = -1.0 if direction == "bearish" else 1.0
    signed_mom_5d = sign * mom_5d
    signed_mom_1d = sign * mom_1d

    # Map confirmation-relative 5-day momentum to total sentiment score (0-15
    # scale) — symmetric 3 confirming tiers / 1 neutral / 3 opposing tiers.
    if signed_mom_5d > 0.07:
        total = 14.0
    elif signed_mom_5d > 0.04:
        total = 12.0
    elif signed_mom_5d > 0.015:
        total = 10.0
    elif signed_mom_5d > -0.015:
        total = 7.5
    elif signed_mom_5d > -0.04:
        total = 5.0
    elif signed_mom_5d > -0.07:
        total = 3.0
    else:
        total = 1.0

    # Add intraday momentum bonus (a strong confirming day often spikes retail chatter)
    if signed_mom_1d > 0.03:
        total = min(15.0, total + 1.1)
    elif signed_mom_1d < -0.03:
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
