"""
Entry point — run daily to generate ranked swing recommendations.
Reads model version from CHANGELOG.md. Checks for missed scans.
Runs pre-market (~8:30am ET), mid-session (~12pm ET), post-close (~4:30pm ET).
Sends system health check at post-close regardless of whether candidates were found.
"""

import argparse
import csv
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional


from shared.utils.logger import get_logger, write_audit_entry
from swing_model.indicator_pipeline import run_pipeline, load_config
from swing_model.portfolio_manager import (
    load_position_state, save_position_state,
    update_circuit_breaker, can_open_new_position,
)
from shared.api_clients.market_data_client import (
    fetch_ohlcv_batch, fetch_vix_and_pct_change, fetch_treasury_yield, fetch_dxy,
    fetch_earnings_calendar,
)
from shared.utils.black_swan_detector import build_black_swan_alert
from swing_model.position_rescoring import rescore_open_positions
from shared.api_clients.sentiment_client import fetch_stocktwits, fetch_seeking_alpha_engagement
from shared.api_clients.news_client import fetch_news_alpha_vantage, fetch_news_yahoo, fetch_news_finnhub
from shared.api_clients.sec_edgar_client import fetch_recent_8k_filings, fetch_hyperscaler_capex_snippets
from shared.utils.regime_detection import classify_regime, get_regime_modifiers, REGIME_HIGH_VOL
from shared.utils.macro_overlay import (
    compute_macro_state,
    dampen_news_china_theme_if_macro_confirmed,
    save_macro_state,
)
from shared.utils.geopolitical_risk import apply_geopolitical_penalty
from shared.utils.sector_rotation import (
    compute_rotation_state, dampen_rotation_penalty_for_leader, get_rotation_modifier, ROTATION_NEUTRAL,
)
from shared.utils.earnings_calendar import get_earnings_modifier
from swing_model.cross_ticker_analysis import analyze_cross_ticker, get_cross_ticker_modifier_for_direction
from shared.utils.seasonality import get_seasonality_modifier
from shared.utils.risk_reward import compute_entry_zone, compute_stop_loss, compute_target, compute_rr_ratio
from swing_model.sentiment_layer import compute_sentiment_score, classify_dominant_sentiment
from swing_model.news_layer import compute_news_score, free_sources_flag_critical_event
from swing_model.scoring import compute_confidence_score, CONFIDENCE_THRESHOLD, determine_direction
from swing_model.feedback_loop import load_live_weights_if_calibrated
from swing_model.win_probability_calibration import load_calibration
from swing_model.trade_selector import rank_trade_structures
from shared.utils.position_sizer import compute_position_size, derive_sizing_inputs
from shared.utils.event_gate import (
    load_gate_state, save_gate_state, is_ticker_blocked, add_block,
    has_active_block_for_trigger, expire_blocks, is_thesis_opposed,
    SCOPE_SECTOR,
)
from shared.utils.sector_config import (
    get_active_sectors, get_all_tickers, get_ticker_sector_map, get_sector_tickers,
)
from shared.utils.scan_lock import acquire_scan_lock

logger = get_logger(__name__)

_RUN_SWING_MODEL_LOCK_DIR = Path("data/processed/scan_locks/run_swing_model")


def main(scan_type: str = "post_close") -> None:
    """
    Guarded by a file lock (shared.utils.scan_lock), same as
    paper_trading/paper_runner.py's run_paper_scan() — this entry point has
    the identical three-scan-type structure and per-sector OHLCV-fetch shape
    that caused the 2026-08-04 double-run incident the lock was built for
    (see scan_lock.py's module docstring), but the fix was only ever applied
    to paper_runner.py, leaving this one of two structurally identical entry
    points unprotected (Signal Integrity Audit finding G.2) — not exploitable
    while this isn't the scheduled path, but the same bug the moment it is.
    No-ops (returns immediately) if another instance already holds the lock
    for this scan_type.
    """
    # Distinct lock_dir from paper_runner.py's own acquire_scan_lock(scan_type)
    # call — these are two independent pipelines (this one drives live
    # Discord alerts + position_state.json, paper_runner.py drives
    # paper_trades.csv) that legitimately CAN run concurrently; sharing one
    # lock namespace would incorrectly serialize them against each other
    # instead of just guarding against two copies of THIS entry point.
    with acquire_scan_lock(scan_type, lock_dir=_RUN_SWING_MODEL_LOCK_DIR) as acquired:
        if not acquired:
            logger.warning(
                f"{scan_type}: another instance appears to already be running this scan_type — "
                "skipping this invocation rather than duplicating work and doubling up on the same "
                "rate-limited APIs (see shared/utils/scan_lock.py)."
            )
            return
        _main_locked(scan_type)


def _main_locked(scan_type: str = "post_close") -> None:
    """
    The actual scan body — see main() for the lock guard around this.

    Steps:
    1.  Load config + model version from CHANGELOG.md
    2.  Check for missed previous scan (audit_log.csv)
    3.  Load portfolio state (position_state.json)
    4.  Run indicator pipeline for all tickers in one batch call
    5.  Fetch shared market context (VIX, SMH, SPY, TNX, DXY)
    6.  Compute shared modifiers: regime, macro overlay, sector rotation, seasonality
    7.  Compute cross-ticker correlation analysis
    8.  Per-ticker: sentiment, news, earnings, positioning (incl. insider), full confidence score
    9.  Evaluate trade structures for candidates meeting threshold (>=90)
    10. Send Discord alerts (new candidates + management alerts)
    11. Write audit log entries
    12. Save updated portfolio state
    13. Send system health check (post-close only)
    """
    cfg = load_config()
    model_version = get_model_version()
    logger.info(f"Run started: {model_version} scan_type={scan_type}")

    # Step 2: Check for missed scan
    missed = check_for_missed_scan("data/logs/audit_log.csv", scan_type)
    if missed:
        logger.warning("Missed scan detected — sending Discord warning")
        _try_send_missed_scan_alert(model_version)

    # Step 3: Load portfolio state + update circuit breaker
    state = load_position_state()
    state = update_circuit_breaker(state, cfg)
    cb_state = state.get("circuit_breaker_state", "normal")

    if "_cb_state_changed" in state:
        _try_send_cb_alert(state["_cb_state_changed"], state["account_equity"], state["peak_equity"])
        del state["_cb_state_changed"]

    if cb_state == "red":
        logger.warning("RED circuit breaker active — no new signals")

    active_sectors = get_active_sectors(cfg)
    watchlist = get_all_tickers(cfg)
    ticker_sector_map = get_ticker_sector_map(cfg)

    # Event Severity Gate state — loaded once per scan; blocks_created_this_scan
    # tracks ids added during THIS run so expire_blocks() never self-expires a
    # block in the same scan that just created it (see event_gate.expire_blocks).
    gate_state = load_gate_state()
    blocks_created_this_scan: set[str] = set()

    # Step 4: Run indicator pipeline once per active sector (each sector's
    # relative-strength calc needs its OWN benchmark, e.g. banks vs. KRE, not
    # semis' SMH), then merge into one dict for the per-ticker loop below.
    indicators_by_ticker: dict = {}
    for sector_name, sector_cfg in active_sectors.items():
        sector_indicators = run_pipeline(
            sector_cfg.get("tickers", []),
            benchmark=sector_cfg.get("benchmark", "SMH"),
            scan_type=scan_type, cfg=cfg,
        )
        indicators_by_ticker.update(sector_indicators)

    # Step 5: Fetch shared market context data (separate 3-month window for
    # modifiers) — one batch fetch covering every active sector's benchmark.
    mkt = _fetch_market_context(cfg)

    # Black Swan check — advisory only (see black_swan_detector.py's module
    # docstring): flags an extreme benchmark-drop/VIX-spike condition with a
    # Discord alert and a note on this scan's output, same treatment as the
    # Event Severity Gate. It does not suspend or veto any signal. Per-sector
    # since 2026-08-23 — see _check_black_swan_per_sector's docstring.
    black_swan_results = _check_black_swan_per_sector(active_sectors, mkt, cfg)
    for sector_name, bs_result in black_swan_results.items():
        if bs_result.pop("_newly_triggered", False):
            open_positions_for_alert = [
                p for p in state.get("positions", [])
                if p.get("open", True) and ticker_sector_map.get(p.get("ticker", "")) == sector_name
            ]
            alert_msg = build_black_swan_alert(
                bs_result["trigger_type"], open_positions_for_alert,
                bs_result["smh_pct_change"], bs_result["vix_pct_change"],
            )
            _try_send_black_swan_alert(alert_msg)

    # Step 6: Compute regime/rotation/macro/seasonality modifiers PER SECTOR —
    # each sector can be in a different regime at the same time, and (see
    # macro_overlay._SECTORS_WITH_VALIDATED_MACRO_LOGIC / seasonality's
    # equivalent) the TNX/DXY/China rationale and the semiconductor demand
    # calendar are only validated for semiconductors, not universal — applying
    # them identically to every sector used to mean, e.g., "hawkish rates are
    # adverse" scoring regional bank tickers backwards (rate rises typically
    # widen bank margins) and "TSM/ASML currency exposure" logic applying to
    # Home Depot.
    regime_by_sector: dict[str, str] = {}
    regime_modifier_by_sector: dict[str, float] = {}
    rotation_state_by_sector: dict[str, str] = {}
    rotation_modifier_by_sector: dict[str, float] = {}
    for sector_name in active_sectors:
        bench_df = mkt["sector_benchmark_dfs"].get(sector_name)
        regime = _compute_regime_safe(mkt["vix"], bench_df)
        regime_by_sector[sector_name] = regime
        # Bullish-default values, kept for _rescore_and_alert_open_positions
        # (existing open positions, rescored below at their own stored
        # direction — out of scope for this change, see position_rescoring.py).
        # The per-ticker candidate-scoring loop below recomputes both modifiers
        # directly from regime/rotation_state once each ticker's real direction
        # is known, rather than reading these bullish-default values.
        regime_modifier_by_sector[sector_name] = get_regime_modifiers(regime, cfg).get("regime_modifier", 0.0)
        rotation_result = _compute_rotation_safe(bench_df, mkt["spy_df"], cfg=cfg)
        rotation_state_by_sector[sector_name] = rotation_result.get("rotation_state", ROTATION_NEUTRAL)
        rotation_modifier_by_sector[sector_name] = rotation_result.get("confidence_modifier", 0.0)

    # Sector-wide hyperscaler capex context (semiconductors' AMZN/MSFT/GOOGL/
    # META) — fetched once per scan, reused for every ticker in that sector.
    sector_context_filings = _compute_sector_context_filings(active_sectors)

    # China-tension keyword count — free (Yahoo, no API budget), scoped to the
    # semiconductor watchlist since that's the only sector this signal is
    # validated for. Previously hardcoded to 0 unconditionally (dead signal —
    # see CHANGELOG), which silently required BOTH TNX and DXY to be adverse
    # simultaneously to ever reach MACRO_ADVERSE, a materially higher bar than
    # the module's own 2-of-3 design.
    china_keyword_count = _compute_china_tension_count(cfg) if "semiconductors" in active_sectors else 0

    macro_state_by_sector: dict[str, dict] = {}
    macro_modifier_by_sector: dict[str, float] = {}
    for sector_name in active_sectors:
        bench_result = _compute_macro_safe(
            mkt["tnx_series"], mkt["dxy_series"], china_keyword_count, cfg, sector=sector_name
        )
        macro_state_by_sector[sector_name] = bench_result
        macro_modifier_by_sector[sector_name] = bench_result.get("confidence_modifier", 0.0)
    # Persist for observability (app UI, debugging) — computed fresh every run
    # regardless, this doesn't feed back into scoring itself. Best-effort: a
    # write failure here shouldn't abort the scan.
    try:
        save_macro_state({"by_sector": macro_state_by_sector})
    except Exception as exc:
        logger.warning(f"Failed to persist macro state — {exc}")

    seasonality_modifier_by_sector: dict[str, float] = {
        sector_name: get_seasonality_modifier(cfg=cfg, sector=sector_name).get("confidence_modifier", 0.0)
        for sector_name in active_sectors
    }

    # Global weights: non-None only once a real feedback-loop calibration has
    # passed holdout — see load_live_weights_if_calibrated's docstring. With
    # zero global calibrations run so far this is always None today.
    # Per-sector weights: sectors with enough historical data and a fit that
    # passed real holdout validation get their own weights instead of the
    # global default (see backtesting/sector_weight_calibration.py and
    # config's feedback_loop.sector_calibration_enabled kill switch) —
    # computed once per active sector, not per ticker, since it's the same
    # lookup for every ticker in that sector.
    # Each sector's lookup is direction-aware (bullish/bearish get independently
    # calibrated weights once enough bearish outcomes exist — see
    # backtesting/sector_weight_calibration.py); both are precomputed here since
    # a ticker's real direction isn't known until the per-ticker loop below.
    sector_calibration_enabled = bool(cfg.get("feedback_loop", {}).get("sector_calibration_enabled", True))
    live_weights_by_sector = {
        sector_name: {
            direction: load_live_weights_if_calibrated(
                sector=sector_name if sector_calibration_enabled else None, direction=direction
            )
            for direction in ("bullish", "bearish")
        }
        for sector_name in active_sectors
    }

    # Real backtest-derived (threshold -> win rate) points — see
    # win_probability_calibration.py's module docstring for why
    # confidence/100 alone was never a real probability. None when
    # data/processed/win_probability_calibration.json hasn't been generated
    # yet, in which case compute_confidence_score/rank_trade_structures both
    # fall back to the old uncalibrated behavior. paper_runner.py has loaded
    # this every scan since it existed; this entry point never did — live's
    # calibrated_win_probability was always the uncalibrated final_score/100,
    # and live's trade-structure ranking was always uncalibrated too, even
    # once a real calibration file existed (Signal Integrity Audit follow-up).
    win_probability_calibration = load_calibration()

    # Step 7: Cross-ticker analysis, run once per sector so "3+ tickers moving
    # together" and peer-average divergence are computed within each sector's
    # own ticker set, not pooled across unrelated sectors.
    cross_ticker_results: dict = {}
    for sector_name, sector_cfg in active_sectors.items():
        sector_tickers = sector_cfg.get("tickers", [])
        sector_indicators = {t: indicators_by_ticker[t] for t in sector_tickers if t in indicators_by_ticker}
        sector_ohlcv = {t: mkt["ticker_ohlcv"][t] for t in sector_tickers if t in mkt["ticker_ohlcv"]}
        cross_ticker_results.update(_compute_cross_ticker_safe(sector_indicators, sector_ohlcv, cfg))

    # Step 8-9: Per-ticker scoring and signal evaluation
    tickers_processed = 0
    candidates = []
    data_sources = {
        "yfinance": True, "StockTwits": False, "SeekingAlpha": False,
        "Alpha Vantage": True, "Finnhub": False, "SEC EDGAR": False,
    }

    for ticker in watchlist:
        try:
            indicators = indicators_by_ticker.get(ticker)
            if indicators is None:
                # This IS an actual yfinance/OHLCV data gap for this ticker (Step 4's
                # run_pipeline already tried and failed) — the correct place to flag
                # data_sources["yfinance"], unlike the broad except below which used
                # to set this for any unrelated failure further down the pipeline.
                data_sources["yfinance"] = False
                continue
            tickers_processed += 1

            # This ticker's sector — drives which regime/rotation/macro/
            # seasonality modifier applies and which sector's event-gate
            # trigger list is checked below.
            sector = ticker_sector_map.get(ticker)
            regime = regime_by_sector.get(sector, "choppy")
            macro_modifier_val = macro_modifier_by_sector.get(sector, 0.0)
            seasonality_modifier_val = seasonality_modifier_by_sector.get(sector, 0.0)

            # Sentiment layer — StockTwits crowd sentiment + Seeking Alpha engagement proxy.
            # StockTwits is fetched here (ahead of the rest of Sentiment/News/
            # Positioning scoring below) purely to classify dominant_sentiment —
            # direction must be known BEFORE those layers run, since their
            # bearish-mirrored sub-formulas (sentiment_layer.py's ratio/velocity,
            # news_layer.py's credibility/theme, positioning_layer.py's 5
            # sub-signals) need it as an input, not something computed after the
            # fact from their own already-bullish-scored output (see
            # scoring.py::determine_direction and compute_confidence_score's
            # direction_override param docstring).
            stocktwits_messages = _fetch_stocktwits_safe(ticker)
            if stocktwits_messages:
                data_sources["StockTwits"] = True
            dominant_sentiment = classify_dominant_sentiment(stocktwits_messages)["dominant_sentiment"]
            direction = determine_direction(indicators, {"dominant_sentiment": dominant_sentiment}, cfg)

            # macro_modifier_val/seasonality_modifier_val above were computed
            # once per sector (bullish-default) — flip sign for bearish now
            # that direction is known, equivalent to (and cheaper than)
            # recomputing per ticker with direction="bearish" (see Signal
            # Integrity Audit finding B.3).
            if direction == "bearish":
                macro_modifier_val = -macro_modifier_val
                seasonality_modifier_val = -seasonality_modifier_val

            regime_modifier_val = get_regime_modifiers(regime, cfg, direction=direction).get("regime_modifier", 0.0)
            rotation_modifier_val = dampen_rotation_penalty_for_leader(
                get_rotation_modifier(rotation_state_by_sector.get(sector, ROTATION_NEUTRAL), cfg, direction=direction),
                float(indicators.get("rs_zscore", 0.0)),
                direction=direction,
            )

            sa_engagement_items = _fetch_sa_engagement_safe(ticker)
            if sa_engagement_items:
                data_sources["SeekingAlpha"] = True
            price_data = {
                "price_change_5d_pct": (
                    indicators.get("close", 1.0) / max(indicators.get("sma_20", 1.0), 0.01) - 1
                )
            }
            sentiment = compute_sentiment_score(
                stocktwits_messages, sa_engagement_items, ticker, price_data, cfg, direction=direction
            )

            # News layer
            # Yahoo + Finnhub + Seeking Alpha are the primary sources, on every
            # scan — all free. Alpha Vantage is a confirmation tool, not a
            # routine per-ticker fetch: it's only called when one of the free
            # sources already flagged a critical event for this ticker, to
            # cross-reference it against an independent source immediately
            # rather than scoring on free-source data alone. This replaces the
            # old post-close-always/pre-market-conditional split — AV budget
            # is now spent on confirmed events, not spent unconditionally once
            # per ticker per day regardless of whether anything happened.
            sa_news_articles = [
                {**item, "source": "seekingalpha.com"} for item in sa_engagement_items
            ]
            yahoo_articles = _fetch_yahoo_news_safe(ticker)
            finnhub_articles = _fetch_finnhub_news_safe(ticker)
            if finnhub_articles:
                data_sources["Finnhub"] = True
            sec_edgar_filings = _fetch_sec_edgar_safe(ticker) + sector_context_filings.get(sector, [])
            if sec_edgar_filings:
                data_sources["SEC EDGAR"] = True
            free_source_articles = sa_news_articles + yahoo_articles + finnhub_articles + sec_edgar_filings
            fetch_av_now = free_sources_flag_critical_event(
                free_source_articles, ticker, cfg, sector=sector
            )
            av_articles = _fetch_av_news_safe(ticker) if fetch_av_now else []
            news = compute_news_score(
                av_articles, yahoo_articles, ticker, cfg, finnhub_articles=finnhub_articles,
                sector=sector, seeking_alpha_articles=sa_news_articles,
                sec_edgar_filings=sec_edgar_filings, direction=direction,
            )
            # China-tension double-count fix — see macro_overlay.py's
            # dampen_news_china_theme_if_macro_confirmed docstring.
            news = dampen_news_china_theme_if_macro_confirmed(
                news, macro_state_by_sector.get(sector, {}).get("china_tension_level", "normal")
            )

            # Earnings proximity modifier
            earnings_info = _fetch_earnings_safe(ticker)
            earnings_date = (earnings_info or {}).get("next_earnings_date")
            earnings_result = get_earnings_modifier(ticker, earnings_date, cfg=cfg)

            # Cross-ticker modifier for this specific ticker — direction-aware
            # (Signal Integrity Audit follow-up finding: analyze_cross_ticker
            # itself has no notion of trade direction; its own confidence_modifier
            # field always assumes bullish, so a bearish candidate needs the
            # swapped outperforming/underperforming mapping applied here).
            ct_modifier = get_cross_ticker_modifier_for_direction(
                cross_ticker_results.get(ticker, {}), direction, cfg
            )

            # Fundamental data (fetched weekly inside run_pipeline, cached in fundamental_state.json)
            fundamental = indicators.get("_fundamental_full") or {}

            # Market Positioning data (fetched daily inside run_pipeline, cached in positioning_state.json —
            # includes insider transactions, which are scored here instead of as a standalone modifier).
            # Both directions are pre-scored by indicator_pipeline.py (cheap — same
            # cached raw data); select the one matching this ticker's real direction.
            positioning = indicators.get(
                "_positioning_full_bearish" if direction == "bearish" else "_positioning_full"
            ) or {}

            # Event Severity Gate — check for an existing block (from a prior scan)
            # covering this ticker before scoring. Advisory only: the signal still
            # surfaces on its own score merits; event_gate_blocked/trigger are
            # attached below so the alert/audit trail can flag it for review.
            existing_gate_block = is_ticker_blocked(ticker, gate_state)
            event_gate_blocked = existing_gate_block is not None
            event_gate_trigger = existing_gate_block.get("trigger_match") if existing_gate_block else None

            # Full confidence score — all layers combined
            score = compute_confidence_score(
                technical=indicators,
                positioning=positioning,
                sentiment=sentiment,
                news=news,
                regime_modifier=regime_modifier_val,
                sector_rotation_modifier=rotation_modifier_val,
                earnings_modifier=earnings_result.get("confidence_modifier", 0.0),
                cross_ticker_modifier=ct_modifier,
                seasonality_modifier=seasonality_modifier_val,
                macro_modifier=macro_modifier_val,
                cfg=cfg,
                live_weights=live_weights_by_sector.get(sector, {}).get(direction),
                regime=regime,
                fundamental=fundamental,
                event_gate_blocked=event_gate_blocked,
                event_gate_trigger=event_gate_trigger,
                win_probability_calibration=win_probability_calibration,
                direction_override=direction,
            )

            final_score = float(score.get("final_score", 0.0))

            # Geopolitical risk penalty — TSM/ASML per config.geopolitical_risk_tickers.
            # Applied here, before structure ranking/threshold check, so every
            # downstream consumer (EV ranking, audit log, Discord alert,
            # qualification) sees the real, penalized score consistently.
            final_score, geo_note = apply_geopolitical_penalty(cfg, ticker, final_score)
            if geo_note:
                score["final_score"] = final_score

            # Event Severity Gate — process this scan's critical news: create new
            # blocks for thesis-opposed critical items (or unconditionally for
            # sector-wide triggers), log thesis-aligned items without blocking or
            # boosting, and fire an immediate alert if this ticker has an open
            # position (does not wait for the daily re-score).
            open_position = next(
                (p for p in state.get("positions", []) if p.get("open", True) and p.get("ticker") == ticker),
                None,
            )
            for event in news.get("critical_events", []):
                event_scope = event["scope"]
                trigger = event["trigger_match"]

                if event_scope == SCOPE_SECTOR:
                    if not has_active_block_for_trigger(gate_state, trigger, SCOPE_SECTOR):
                        gate_state = add_block(
                            gate_state, tickers=get_sector_tickers(cfg, sector), scope=SCOPE_SECTOR,
                            trigger_headline=event["headline"], trigger_match=trigger,
                            source=event["source"], event_timestamp_utc=event["event_timestamp_utc"],
                        )
                        new_block = gate_state["blocks"][-1]
                        blocks_created_this_scan.add(new_block["id"])
                        _try_send_event_gate_alert(new_block, model_version)
                        _write_event_gate_audit(new_block, model_version, scan_type, triggered=True)
                        # This ticker's score was computed before this loop ran — a
                        # sector-wide block discovered just now must still flag this
                        # scan's output, not only future ones.
                        score["event_gate_blocked"] = True
                        score["event_gate_trigger"] = trigger
                else:
                    opposed = is_thesis_opposed(event.get("ner_sentiment"), direction)
                    if opposed:
                        if not is_ticker_blocked(ticker, gate_state):
                            gate_state = add_block(
                                gate_state, tickers=[ticker], scope=event_scope,
                                trigger_headline=event["headline"], trigger_match=trigger,
                                source=event["source"], event_timestamp_utc=event["event_timestamp_utc"],
                            )
                            new_block = gate_state["blocks"][-1]
                            blocks_created_this_scan.add(new_block["id"])
                            _try_send_event_gate_alert(new_block, model_version)
                            _write_event_gate_audit(new_block, model_version, scan_type, triggered=True)
                            # Same reasoning as the sector-wide branch above — flag
                            # this scan's output, not just subsequent ones.
                            score["event_gate_blocked"] = True
                            score["event_gate_trigger"] = trigger
                    else:
                        logger.info(
                            f"{ticker}: critical news thesis-aligned "
                            f"({event.get('ner_sentiment')} vs {direction} thesis) — logged, "
                            f"no block, no boost. Trigger: '{trigger}'"
                        )

                if open_position is not None:
                    _handle_open_position_critical_event(open_position, event, model_version)

            # Trade structure evaluation (only for signals at or above threshold)
            entry_lower = entry_upper = stop_loss = target = None
            structure_recommended = ev_per_dollar = rr_ratio = None
            capital_required = structure_legs = structure_effective_days = structure_greeks_summary = None
            structure_max_loss = structure_max_gain = structure_strikes = structure_expiration_date = None
            alternative_structures = None
            greeks_filter_status = None
            risk_pct = 0.01
            dollar_risk = 0.0
            position_size = 0
            capital_deployed = 0.0
            notes = ""
            if score.get("event_gate_blocked"):
                notes = f"⚠️ ACTIVE EVENT ALERT — trigger: {score.get('event_gate_trigger')} — review before trading"
            ticker_bs_result = black_swan_results.get(sector)
            if ticker_bs_result and ticker_bs_result.get("black_swan_triggered"):
                bs_note = (
                    f"🚨 BLACK SWAN CONDITIONS ACTIVE ({ticker_bs_result.get('trigger_type')}) "
                    f"— advisory, review before trading"
                )
                notes = f"{notes} | {bs_note}" if notes else bs_note
            if geo_note:
                notes = f"{notes} | {geo_note}" if notes else geo_note

            if final_score >= CONFIDENCE_THRESHOLD:
                close_px = indicators.get("close", 0.0)
                atr = indicators.get("atr_14", close_px * 0.02)
                # Breakout (rolling high) anchors a bullish entry zone; breakdown
                # (rolling low) anchors a bearish one — see risk_reward.py's
                # module docstring for why bearish mirrors every formula here.
                level = indicators.get(
                    "rolling_low_20" if direction == "bearish" else "rolling_high_20", close_px
                )
                rr_cfg = cfg.get("risk_reward", {})

                entry_lower, entry_upper = compute_entry_zone(
                    close_px, level, atr,
                    rr_cfg.get("entry_zone_half_width_atr", 0.25),
                    direction=direction,
                )
                entry_mid = (entry_lower + entry_upper) / 2.0
                # high_volume_support/low_volume_area_above (bullish) and their
                # high_volume_resistance/low_volume_area_below mirrors (bearish)
                # come from the same volume-profile nodes technical_common.py
                # already computes for the volume_profile technical sub-signal —
                # anchoring both directions' stop/target to real support/
                # resistance instead of always falling back to the mechanical
                # ATR-multiple/min-R:R number (see risk_reward.py docstrings).
                stop_loss = compute_stop_loss(
                    entry_upper if direction == "bearish" else entry_lower, atr,
                    high_volume_support=indicators.get("high_volume_support"),
                    high_volume_resistance=indicators.get("high_volume_resistance"),
                    stop_atr_multiplier=rr_cfg.get("stop_atr_multiplier", 2.0),
                    direction=direction,
                )
                target = compute_target(
                    entry_mid, stop_loss,
                    low_volume_area_above=indicators.get("low_volume_area_above"),
                    low_volume_area_below=indicators.get("low_volume_area_below"),
                    min_rr=rr_cfg.get("min_rr_ratio", 3.0), direction=direction,
                )

                valid_setup = (
                    target and (target < entry_mid < stop_loss if direction == "bearish"
                                else target > entry_mid > stop_loss)
                )
                if valid_setup:
                    rr_ratio = compute_rr_ratio(entry_mid, stop_loss, target, direction=direction)
                    force_defined_risk = (
                        earnings_result.get("force_defined_risk", False)
                        or regime == REGIME_HIGH_VOL
                    )
                    try:
                        options_raw = positioning.get("_options_raw") or {}
                        trade_result = rank_trade_structures(
                            {
                                "ticker": ticker, "direction": direction,
                                "confidence": final_score, "entry": entry_mid,
                                "entry_mid": entry_mid, "stop_loss": stop_loss,
                                "target": target, "atr_14": atr,
                                "force_defined_risk": force_defined_risk,
                            },
                            account_equity=float(state.get("account_equity", 15000.0)),
                            options_approval_level=int(cfg.get("options_approval_level", 2)),
                            iv_percentile=options_raw.get("iv_percentile", 50.0),
                            option_chain=options_raw.get("chain"),
                            dte=options_raw.get("dte"),
                            atm_iv=options_raw.get("atm_iv"),
                            cfg=cfg,
                            win_probability_calibration=win_probability_calibration,
                        )
                        ranked = trade_result.get("ranked_structures", [])
                        # Surfaced in the Discord alert below so a human
                        # reviewing a recommendation can see when Filter 4
                        # (Greeks) didn't run at all this scan (chain fetch
                        # failed) — see paper_runner.py's matching comment
                        # (Signal Integrity Audit finding D.1).
                        greeks_filter_status = trade_result.get("greeks_filter_status")
                        if ranked:
                            # recommended=True, not ranked[0]: see paper_runner.py's
                            # matching comment — rank_trade_structures can prefer a
                            # lower-ranked options structure over a higher-ranked
                            # gap-risk-exposed stock structure, and reading ranked[0]
                            # directly here would silently disagree with what
                            # paper_runner.py actually traded on the same signal.
                            best = next((s for s in ranked if s.get("recommended")), ranked[0])
                            structure_recommended = best.get("name", "")
                            # ev_per_dollar_per_day, not the un-normalized ev_per_dollar_risked —
                            # trade_selector.py ranks (and picks ranked[0]) on the per-day metric,
                            # so persisting the un-normalized figure here would silently disagree
                            # with which structure was actually recommended and why (see
                            # paper_runner.py's matching comment/fix — this call site still had
                            # the stale field).
                            ev_per_dollar = best.get("ev_per_dollar_per_day", 0.0)
                            rr_ratio = best.get("rr_ratio", rr_ratio)
                            # See paper_runner.py's matching comment — these were
                            # already computed by rank_trade_structures() and
                            # previously discarded before reaching the Discord alert.
                            capital_required = best.get("capital_required")
                            structure_legs = best.get("legs")
                            structure_effective_days = best.get("effective_days")
                            greeks = best.get("greeks")
                            if greeks and greeks.get("net_greeks"):
                                g = greeks["net_greeks"]
                                structure_greeks_summary = (
                                    f"Δ{g.get('delta', 0.0):+.2f} "
                                    f"Γ{g.get('gamma', 0.0):+.3f} "
                                    f"Θ{g.get('theta', 0.0):+.3f} "
                                    f"V{g.get('vega', 0.0):+.3f}"
                                )

                            # See paper_runner.py's matching comment — real
                            # dollar max-loss/max-gain (None = genuinely
                            # unbounded, never fabricated) and the actual
                            # strikes/expiration this structure's EV was
                            # priced against.
                            max_loss_val = best.get("max_loss_dollars")
                            max_gain_val = best.get("max_gain_dollars")
                            structure_max_loss = f"{float(max_loss_val):.2f}" if max_loss_val is not None else None
                            structure_max_gain = f"{float(max_gain_val):.2f}" if max_gain_val is not None else None
                            strikes_dict = best.get("strikes") or {}
                            structure_strikes = ", ".join(f"{k}={v:.2f}" for k, v in strikes_dict.items()) or None
                            eff_days = best.get("effective_days")
                            structure_expiration_date = (
                                (datetime.now(timezone.utc) + timedelta(days=round(eff_days))).date().isoformat()
                                if eff_days is not None else None
                            )

                            # Real position sizing — this used to stop at a
                            # bare risk_pct (see the removed pre-ranking block
                            # this replaced), never turning into an actual
                            # dollar_risk/position_size/capital_deployed the
                            # way paper_runner.py's does; the live Discord
                            # alert's "Dollar Risk" field always showed $0.00.
                            # Real circuit-breaker/consecutive-loss state
                            # (unlike paper_runner.py's paper-trading-only
                            # "normal"/0) — compute_position_size applies both
                            # internally now instead of the caller pre-
                            # applying them to a raw get_risk_pct() figure.
                            position_type = best.get("position_type", "shares")
                            account_equity_val = float(state.get("account_equity", 15000.0))
                            max_capital_pct = float(cfg.get("position_sizing", {}).get("max_capital_pct", 0.05))
                            position_type, risk_per_unit, per_unit_cost = derive_sizing_inputs(
                                position_type, capital_required, entry_mid, stop_loss
                            )
                            sizing = compute_position_size(
                                confidence_score=final_score, account_equity=account_equity_val,
                                circuit_breaker_state=cb_state, capital_required=risk_per_unit,
                                max_capital_pct=max_capital_pct,
                                consecutive_losses=int(state.get("consecutive_losses", 0)),
                                cfg=cfg, per_unit_cost=per_unit_cost, position_type=position_type,
                            )
                            risk_pct = sizing["risk_pct"]
                            dollar_risk = sizing["dollar_risk"]
                            position_size = sizing["contracts_or_shares"]
                            capital_deployed = sizing["capital_deployed"]

                            # Alternatives — see paper_runner.py's matching
                            # comment. Full ranking already exists in-memory;
                            # only the winner ever reached the Discord alert
                            # before this.
                            alternatives = [s for s in ranked if s is not best][:2]
                            alternative_structures = " | ".join(
                                f"{alt.get('name', '')} (${alt.get('ev_per_dollar_per_day', 0.0):.5f}/day, "
                                f"${alt.get('capital_required', 0.0):.2f})"
                                for alt in alternatives
                            )
                    except Exception as exc:
                        logger.error(f"{ticker}: trade structure ranking failed — {exc}")

            signal_surfaced = final_score >= CONFIDENCE_THRESHOLD

            # Step 11: Write audit log entry for every scanned ticker
            write_audit_entry({
                "model_version": model_version,
                "scan_type": scan_type,
                "ticker": ticker,
                "technical_score": score.get("technical_total", 0.0),
                "positioning_score": score.get("positioning_total", 0.0),
                "sentiment_score": score.get("sentiment_total", 0.0),
                "news_score": score.get("news_total", 0.0),
                "base_score": score.get("base_score", 0.0),
                "regime_modifier": score.get("regime_modifier", 0.0),
                "sector_rotation_modifier": score.get("sector_rotation_modifier", 0.0),
                "earnings_modifier": score.get("earnings_modifier", 0.0),
                "cross_ticker_modifier": score.get("cross_ticker_modifier", 0.0),
                "seasonality_modifier": score.get("seasonality_modifier", 0.0),
                "macro_modifier": score.get("macro_modifier", 0.0),
                "final_score": final_score,
                "signal_surfaced": signal_surfaced,
                "direction": direction,
                "structure_recommended": structure_recommended or "",
                "ev_per_dollar": ev_per_dollar or "",
                "rr_ratio": rr_ratio or "",
                "entry_lower": entry_lower or "",
                "entry_upper": entry_upper or "",
                "stop_loss": stop_loss or "",
                "target": target or "",
                "notes": notes,
                "event_gate_blocked": score.get("event_gate_blocked", False),
                "event_gate_trigger": score.get("event_gate_trigger", "") or "",
            })

            if signal_surfaced and cb_state not in ("orange", "red"):
                allowed, reason = can_open_new_position(state, {
                    "ticker": ticker,
                    "direction": direction,
                    "confidence": final_score,
                    "risk_pct": risk_pct,
                }, cfg=cfg)
                if allowed:
                    candidate = {
                        **score,
                        "ticker": ticker, "confidence": final_score,
                        "entry_zone_lower": entry_lower, "entry_zone_upper": entry_upper,
                        "stop_loss": stop_loss, "target": target,
                        "structure_recommended": structure_recommended,
                        "ev_per_dollar": ev_per_dollar, "rr_ratio": rr_ratio,
                        "capital_required": capital_required,
                        "structure_legs": structure_legs,
                        "structure_effective_days": structure_effective_days,
                        "structure_greeks_summary": structure_greeks_summary,
                        "structure_max_loss": structure_max_loss,
                        "structure_max_gain": structure_max_gain,
                        "structure_strikes": structure_strikes,
                        "structure_expiration_date": structure_expiration_date,
                        "alternative_structures": alternative_structures,
                        "greeks_filter_status": greeks_filter_status,
                        "direction": direction, "risk_pct": risk_pct,
                        # dollar_risk was never populated here before v2.2.60 —
                        # the live Discord alert's "Dollar Risk" field always
                        # showed $0.00 (see send_trade_alert's dollar_risk
                        # field, which reads candidate.get("dollar_risk", 0.0)).
                        "dollar_risk": dollar_risk,
                        "position_size": position_size,
                        "capital_deployed": capital_deployed,
                        "notes": notes,
                    }
                    candidates.append(candidate)
                    _try_send_trade_alert(candidate, model_version)
                else:
                    logger.info(f"{ticker}: eligible score {final_score:.0f} but blocked — {reason}")

        except Exception as exc:
            logger.error(f"{ticker}: pipeline error — {exc}")
            # Always leave an audit_log.csv row for this ticker, even on failure —
            # previously an exception anywhere before the normal audit write above
            # (sentiment/news/scoring/event-gate all run before it) meant this
            # ticker silently had no row at all for this scan, with no record of
            # what happened. Also no longer blindly marks data_sources["yfinance"]
            # False here: this ticker's actual yfinance OHLCV fetch (run_pipeline's
            # Step 4, earlier) already succeeded by the time this block runs — an
            # exception here is in sentiment/news/scoring/event-gate code, not
            # yfinance, and mislabeling it that way pointed incident debugging at
            # the wrong subsystem.
            try:
                write_audit_entry({
                    "model_version": model_version,
                    "scan_type": scan_type,
                    "ticker": ticker,
                    "notes": f"pipeline_error: {exc}",
                })
            except Exception as audit_exc:
                logger.error(f"{ticker}: failed to write audit_log.csv error row — {audit_exc}")

    # Event Severity Gate — expire blocks whose cooling-off condition is met:
    # a post_close scan that completes after the block's event timestamp (a full
    # daily-bar update reflecting the event). Blocks created earlier in THIS scan
    # are excluded — cooling-off requires a scan that starts after the block
    # already existed, not the one that just created it moments ago.
    newly_expired_blocks = expire_blocks(
        gate_state, scan_type, datetime.now(timezone.utc), exclude_ids=blocks_created_this_scan,
    )
    save_gate_state(gate_state)
    for expired_block in newly_expired_blocks:
        _try_send_event_gate_expired_alert(expired_block, model_version)
        _write_event_gate_audit(expired_block, model_version, scan_type, triggered=False)

    # Signal decay — daily re-score of open positions (early exit / time stop /
    # trailing stop). Grouped by sector since rescore_open_positions() takes
    # one flat market_modifiers dict but different sectors can be in different
    # regimes at the same time (see Step 6's per-sector modifier comment
    # above). A no-op today while nothing populates state["positions"] live
    # (see handle_entry_confirmation's docstring), but wired correctly for
    # when it is.
    state["positions"] = _rescore_and_alert_open_positions(
        state, indicators_by_ticker, ticker_sector_map,
        regime_by_sector, regime_modifier_by_sector,
        seasonality_modifier_by_sector, macro_modifier_by_sector, cfg,
    )

    # Step 12: Save updated state
    state["last_scan_timestamp_utc"] = datetime.now(timezone.utc).isoformat()
    save_position_state(state)

    # Step 13: Health check (post_close only)
    if scan_type == "post_close":
        open_positions = [p for p in state.get("positions", []) if p.get("open", True)]
        av_count = _read_av_call_count()
        _try_send_health_check(
            tickers_processed=tickers_processed,
            total_tickers=len(watchlist),
            data_sources=data_sources,
            av_calls_used=av_count,
            av_calls_limit=20,
            candidates_found=len(candidates),
            open_positions=open_positions,
            circuit_breaker_state=cb_state,
            day_trades_count=len(state.get("day_trades_rolling_5d", [])),
            model_version=model_version,
        )

    logger.info(
        f"Scan complete — {tickers_processed}/{len(watchlist)} tickers, "
        f"{len(candidates)} candidates, cb={cb_state}"
    )


def check_for_missed_scan(audit_log_path: str, scan_type: str) -> bool:
    """
    Check audit_log.csv for expected timestamp of previous scan.
    Returns True if a scan was missed. Fires Discord warning if True.

    Logic: if no audit entry in the last 26 hours for scan_type, declare missed.
    26h window allows for daily scheduling jitter.
    """
    path = Path(audit_log_path)
    if not path.exists():
        return False  # First run — no previous scan to miss

    cutoff = datetime.now(timezone.utc) - timedelta(hours=26)
    try:
        with open(path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                ts_str = row.get("timestamp_utc", "")
                st = row.get("scan_type", "")
                if st != scan_type:
                    continue
                try:
                    ts = datetime.fromisoformat(ts_str)
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=timezone.utc)
                    if ts >= cutoff:
                        return False  # Found recent scan — not missed
                except (ValueError, TypeError):
                    continue
    except Exception as exc:
        logger.warning(f"Could not read audit log: {exc}")
        return False

    return True  # No recent scan found


def get_model_version(changelog_path: str = "CHANGELOG.md") -> str:
    """
    Extract current model version from CHANGELOG.md header.
    Tries UTF-8 first (CHANGELOG.md may contain emoji in alert-type descriptions);
    falls back to the platform default encoding for files written without an
    explicit encoding, so this stays robust regardless of who last saved the file.
    """
    path = Path(changelog_path)
    try:
        content = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        try:
            content = path.read_text()
        except Exception:
            return "v1.0.0"
    except Exception:
        return "v1.0.0"

    for line in content.splitlines():
        if line.startswith("## [v"):
            return line.split("[", 1)[1].split("]")[0]
    return "v1.0.0"


# ---------------------------------------------------------------------------
# Private alert senders — all gracefully no-op if Discord not configured
# ---------------------------------------------------------------------------

def _try_send_trade_alert(candidate: dict, model_version: str) -> None:
    try:
        from shared.utils.discord_alerts import send_trade_alert
        send_trade_alert(candidate, model_version=model_version)
    except Exception as exc:
        logger.error(f"Trade alert send failed: {exc}")


def _try_send_health_check(**kwargs) -> None:
    try:
        from shared.utils.discord_alerts import send_health_check
        send_health_check(**kwargs)
    except Exception as exc:
        logger.error(f"Health check send failed: {exc}")


def _try_send_event_gate_alert(block: dict, model_version: str) -> bool:
    """Returns True if the Discord send succeeded — callers may log this to the app UI's DB."""
    try:
        from shared.utils.discord_alerts import send_event_gate_triggered_alert
        return send_event_gate_triggered_alert(block, model_version=model_version)
    except Exception as exc:
        logger.error(f"Event gate triggered alert send failed: {exc}")
        return False


def _try_send_event_gate_expired_alert(block: dict, model_version: str) -> bool:
    """Returns True if the Discord send succeeded — callers may log this to the app UI's DB."""
    try:
        from shared.utils.discord_alerts import send_event_gate_expired_alert
        return send_event_gate_expired_alert(block, model_version=model_version)
    except Exception as exc:
        logger.error(f"Event gate expired alert send failed: {exc}")
        return False


def _rescore_and_alert_open_positions(
    state: dict,
    indicators_by_ticker: dict,
    ticker_sector_map: dict,
    regime_by_sector: dict,
    regime_modifier_by_sector: dict,
    seasonality_modifier_by_sector: dict,
    macro_modifier_by_sector: dict,
    cfg: dict,
) -> list:
    """
    Re-score every open position with this scan's fresh indicator data
    (swing_model.position_rescoring.rescore_open_positions) and alert on early
    exit / time stop / profit target. Positions are grouped by sector so
    each group gets its OWN sector's regime/seasonality/macro modifiers,
    since rescore_open_positions takes one flat market_modifiers dict per
    call but different sectors can be in different regimes simultaneously.

    Alerts only fire when management_action actually CHANGES from the
    position's last recorded action (tracked via "_last_management_action"
    on the position dict) — otherwise the same lingering condition would
    re-alert on every scan (up to 3x/day) instead of once per new event.

    Returns the full updated positions list (open positions replaced with
    their rescored dict; closed positions passed through unchanged).
    """
    positions = state.get("positions", [])
    open_positions = [p for p in positions if p.get("open", True)]
    if not open_positions:
        return positions

    by_sector: dict[str, list] = {}
    for pos in open_positions:
        sector = ticker_sector_map.get(pos.get("ticker", "")) or "_unknown"
        by_sector.setdefault(sector, []).append(pos)

    rescored_by_ticker: dict = {}
    for sector, sector_positions in by_sector.items():
        market_modifiers = {
            "regime": regime_by_sector.get(sector),
            "regime_modifier": regime_modifier_by_sector.get(sector, 0.0),
            "seasonality_modifier": seasonality_modifier_by_sector.get(sector, 0.0),
            "macro_modifier": macro_modifier_by_sector.get(sector, 0.0),
        }
        results = rescore_open_positions(
            sector_positions, indicators_by_ticker, cfg=cfg, market_modifiers=market_modifiers,
        )
        for result in results:
            rescored_by_ticker[result.get("ticker", "")] = result

    alert_types = {"early_exit", "time_stop", "profit_target"}
    updated = []
    for pos in positions:
        if not pos.get("open", True):
            updated.append(pos)
            continue
        result = rescored_by_ticker.get(pos.get("ticker", ""), pos)
        action = result.get("management_action", "hold")
        if action in alert_types and action != pos.get("_last_management_action"):
            _try_send_signal_decay_alert(result, action)
        result["_last_management_action"] = action
        updated.append(result)

    return updated


def _try_send_signal_decay_alert(position: dict, action: str) -> None:
    try:
        from shared.utils.discord_alerts import send_signal_decay_alert, send_position_management_alert
        if action == "early_exit":
            send_signal_decay_alert(
                position, position.get("current_confidence", 0.0), position.get("confidence_drop", 0.0),
            )
        else:
            details = {
                "current_price": position.get("close", ""),
                "days_held": position.get("days_held", ""),
                "pnl_pct_of_target": position.get("pnl_pct_of_target", ""),
                "trailing_stop": position.get("trailing_stop_current", ""),
            }
            send_position_management_alert(position, action, details)
    except Exception as exc:
        logger.error(f"Signal decay alert send failed: {exc}")


def _handle_open_position_critical_event(position: dict, event: dict, model_version: str) -> dict:
    """
    Fire an immediate critical alert for an open position hit by a critical news
    event — does not wait for the daily re-score, same treatment as a
    signal-decay early-exit flag. Routes through notification_router.py.
    Returns the routing result dict.
    """
    from shared.utils.notification_router import route_alert
    ticker = position.get("ticker", "?")
    message = (
        f"🚨 CRITICAL EVENT — {ticker} (OPEN POSITION) — {event.get('trigger_match', '')}: "
        f"{event.get('headline', '')[:200]}"
    )
    result = route_alert(message, alert_type="event_gate_critical")
    write_audit_entry({
        "model_version": model_version,
        "scan_type": "critical",
        "ticker": ticker,
        "notes": f"OPEN POSITION CRITICAL EVENT ALERT — trigger='{event.get('trigger_match')}'",
        "event_gate_blocked": False,
        "event_gate_trigger": event.get("trigger_match", ""),
        "signal_surfaced": False,
    })
    return result


def _write_event_gate_audit(block: dict, model_version: str, scan_type: str, triggered: bool) -> None:
    """Audit-log a gate trigger or expiry event (every gate action gets a row)."""
    note = (
        f"EVENT_GATE_TRIGGERED — scope={block.get('scope')} trigger='{block.get('trigger_match')}' "
        f"source='{block.get('source')}'"
        if triggered else
        f"EVENT_GATE_EXPIRED — trigger='{block.get('trigger_match')}'"
    )
    write_audit_entry({
        "model_version": model_version,
        "scan_type": scan_type,
        "ticker": ",".join(block.get("tickers", [])),
        "notes": note,
        "event_gate_blocked": triggered,
        "event_gate_trigger": block.get("trigger_match", ""),
        "signal_surfaced": False,
    })


def _try_send_cb_alert(cb_change: dict, equity: float, peak: float) -> None:
    try:
        from shared.utils.discord_alerts import send_circuit_breaker_alert
        send_circuit_breaker_alert(cb_change["to"], equity, peak)
    except Exception as exc:
        logger.error(f"CB alert send failed: {exc}")


def _try_send_black_swan_alert(message: str) -> None:
    try:
        from shared.utils.discord_alerts import send_black_swan_alert
        send_black_swan_alert(message)
    except Exception as exc:
        logger.error(f"Black Swan alert send failed: {exc}")


def _try_send_missed_scan_alert(model_version: str) -> None:
    try:
        from shared.utils.notification_router import route_alert
        route_alert(
            f"⚠️ Missed scan detected — {model_version} — check system health.",
            alert_type="missed_scan",
        )
    except Exception as exc:
        logger.error(f"Missed scan alert failed: {exc}")


def _read_av_call_count() -> int:
    """Read today's Alpha Vantage call count from av_call_count.json."""
    import json
    path = Path("data/processed/av_call_count.json")
    if not path.exists():
        return 0
    try:
        data = json.loads(path.read_text())
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if data.get("date") == today:
            return int(data.get("count", 0))
    except Exception:
        pass
    return 0


# ---------------------------------------------------------------------------
# Market context helpers
# ---------------------------------------------------------------------------

def _fetch_market_context(cfg: dict) -> dict:
    """
    Fetch all shared market-context data needed for modifier computation.

    Fetches EVERY active sector's benchmark (not just SMH) in the same batch
    call, since regime/rotation modifiers are computed per-sector — a bank
    ticker's regime must be classified against KRE, not the semiconductor
    sector's SMH.

    Returns dict with keys:
      vix                — float (or None if fetch failed)
      sector_benchmark_dfs — dict[sector_name, pd.DataFrame] OHLCV per active sector's benchmark
      spy_df              — pd.DataFrame OHLCV for SPY
      tnx_series          — pd.Series of TNX Close prices
      dxy_series          — pd.Series of DXY Close prices
      ticker_ohlcv        — dict[str, pd.DataFrame] for watchlist tickers only
    """
    import pandas as pd

    active_sectors = get_active_sectors(cfg)
    watchlist = get_all_tickers(cfg)
    benchmark_tickers = {s.get("benchmark") for s in active_sectors.values() if s.get("benchmark")}

    tickers_to_fetch = list(set(watchlist) | benchmark_tickers | {"SPY"})
    ohlcv_all = fetch_ohlcv_batch(tickers_to_fetch, period="3mo", interval="1d") or {}

    sector_benchmark_dfs = {
        name: ohlcv_all.get(s.get("benchmark")) for name, s in active_sectors.items()
    }
    spy_df = ohlcv_all.get("SPY")

    # One fetch, both values — see fetch_vix_and_pct_change's docstring
    # (2026-08-23 full model audit: this used to be 2 independent
    # yf.download("^VIX", ...) round trips every scan).
    vix = None
    vix_pct_change = None
    try:
        vix, vix_pct_change = fetch_vix_and_pct_change()
    except Exception as exc:
        logger.warning(f"VIX fetch failed — {exc}")

    tnx_series: Optional[pd.Series] = None
    try:
        tnx_df = fetch_treasury_yield(period="3mo")
        if tnx_df is not None and not tnx_df.empty:
            tnx_series = tnx_df["Close"]
    except Exception as exc:
        logger.warning(f"TNX fetch failed — {exc}")

    dxy_series: Optional[pd.Series] = None
    try:
        dxy_df = fetch_dxy(period="3mo")
        if dxy_df is not None and not dxy_df.empty:
            dxy_series = dxy_df["Close"]
    except Exception as exc:
        logger.warning(f"DXY fetch failed — {exc}")

    ticker_ohlcv = {t: ohlcv_all[t] for t in watchlist if t in ohlcv_all}

    return {
        "vix": vix,
        "vix_pct_change": vix_pct_change,
        "sector_benchmark_dfs": sector_benchmark_dfs,
        "spy_df": spy_df,
        "tnx_series": tnx_series,
        "dxy_series": dxy_series,
        "ticker_ohlcv": ticker_ohlcv,
    }


def _check_black_swan_per_sector(active_sectors: dict, mkt: dict, cfg: dict) -> dict[str, dict]:
    """
    Per-sector Black Swan check (2026-08-23, full model audit follow-up):
    each active sector's OWN benchmark (SMH/KRE/XLV/XLY) checked for a >7%
    drop, alongside the one shared VIX spike condition, with each sector's
    trigger/cooldown state tracked independently in black_swan_state.json.
    Previously this only ever watched SMH regardless of which sectors were
    actually active — a bank/healthcare/consumer-discretionary-specific
    crash could have happened with zero detection at all.

    Advisory only, same as before (see black_swan_detector.py's module
    docstring) — never blocks new signals. Shared between this module and
    paper_trading/paper_runner.py (which had NO black swan check wired in at
    all until this same audit pass — the pipeline actually running daily had
    no crash circuit breaker) so both watch the same real market consistently.

    Returns {sector_name: check_black_swan() result} for sectors with usable
    data this scan, with an extra "_newly_triggered" bool per entry the
    caller should pop and act on (build+send its own alert using its own
    open-positions view — deliberately left to the caller since live and
    paper track open positions in different, non-interchangeable stores).
    Persists per-sector state as a side effect; call once per scan.
    """
    from shared.utils.black_swan_detector import (
        check_black_swan, load_black_swan_state, save_black_swan_state,
    )
    from swing_model.portfolio_manager import update_black_swan_state

    results: dict[str, dict] = {}
    vix_pct_change = mkt.get("vix_pct_change")
    if vix_pct_change is None:
        return results

    bs_state = load_black_swan_state()
    for sector_name in active_sectors:
        bench_df = mkt.get("sector_benchmark_dfs", {}).get(sector_name)
        bench_pct_change = _compute_last_bar_pct_change(bench_df)
        if bench_pct_change is None:
            continue
        result = check_black_swan(
            smh_current_pct_change=bench_pct_change,
            vix_current_pct_change=vix_pct_change,
            cfg=cfg,
        )
        sector_state = update_black_swan_state(bs_state.get(sector_name, {}), result, cfg=cfg)
        result["_newly_triggered"] = sector_state.pop("_black_swan_newly_triggered", False)
        bs_state[sector_name] = sector_state
        results[sector_name] = result

    save_black_swan_state(bs_state)
    return results


def _compute_last_bar_pct_change(df) -> Optional[float]:
    """
    Most recent daily bar's close-over-close % change for a benchmark OHLCV
    DataFrame, used as the Black Swan check's SMH-move input. Same "latest
    available daily bar, not live streaming" caveat as fetch_vix_pct_change.
    Returns None if df is missing/too short rather than raising.
    """
    try:
        import pandas as pd
        if df is None or (isinstance(df, pd.DataFrame) and len(df) < 2):
            return None
        closes = df["Close"]
        prior, latest = float(closes.iloc[-2]), float(closes.iloc[-1])
        if prior == 0:
            return None
        return (latest - prior) / prior
    except Exception as exc:
        logger.warning(f"SMH % change computation failed — {exc}")
        return None


def _compute_regime_safe(
    vix: Optional[float],
    benchmark_df,
) -> str:
    """
    Classify market regime for one sector's benchmark; falls back to 'choppy'
    on any error. Called once per active sector (see main()) — `benchmark_df`
    is that sector's own benchmark OHLCV (SMH for semis, KRE for banks, etc.),
    not always SMH despite the underlying classify_regime() param name.

    A failed VIX fetch (vix is None) does NOT default to a calm reading (15.0) —
    that would fail open exactly when a data-provider outage coincides with real
    volatility, potentially skipping the REGIME_HIGH_VOL score cap / defined-risk
    brake. With no real VIX data, this fails conservative instead: REGIME_HIGH_VOL.
    """
    try:
        import pandas as pd
        if benchmark_df is None or (isinstance(benchmark_df, pd.DataFrame) and benchmark_df.empty):
            return "choppy"
        if vix is None:
            logger.warning("VIX unavailable — defaulting to REGIME_HIGH_VOL (fail conservative, not calm).")
            return REGIME_HIGH_VOL
        return classify_regime(vix=float(vix), smh_ohlcv=benchmark_df)
    except Exception as exc:
        logger.warning(f"Regime detection failed — {exc}. Defaulting to 'choppy'.")
        return "choppy"


def _compute_macro_safe(
    tnx_series,
    dxy_series,
    china_keyword_count_5d: int,
    cfg: dict,
    sector: Optional[str] = None,
) -> dict:
    """
    Compute one sector's macro overlay state; falls back to neutral
    (confidence_modifier=0.0) on error. See macro_overlay.compute_macro_state's
    `sector` param — this module's TNX/DXY/China rationale is only validated
    for the semiconductors sector, so any other sector resolves neutral
    regardless of the real TNX/DXY/China readings.
    """
    try:
        # Only bail early if BOTH series are missing — compute_macro_state's
        # own _period_pct_change already degrades a single None series to a
        # neutral reading for just that signal (tnx or dxy), computing the
        # other for real. The old `or` guard bailed to fully-neutral whenever
        # EITHER series was missing, discarding real signal the function was
        # already safe to compute — backtesting/simulation.py's inline
        # equivalent never had this over-conservative guard, so live/paper
        # was silently less accurate than the backtest in this one case
        # (Signal Integrity Audit follow-up finding).
        if tnx_series is None and dxy_series is None:
            return {"confidence_modifier": 0.0, "macro_state": "neutral"}
        return compute_macro_state(
            tnx_close=tnx_series,
            dxy_close=dxy_series,
            china_keyword_count_5d=china_keyword_count_5d,
            cfg=cfg,
            sector=sector,
        )
    except Exception as exc:
        logger.warning(f"Macro overlay failed — {exc}. Using neutral modifier.")
        return {"confidence_modifier": 0.0, "macro_state": "neutral"}


def _compute_china_tension_count(cfg: dict) -> int:
    """
    Count semiconductor-relevant China-tension keyword mentions in recent
    Yahoo Finance headlines for the semiconductor watchlist — free (no API
    budget cost), scoped to that sector's own tickers since that's the only
    sector macro_overlay's China-tension signal is validated for.

    Previously this was hardcoded to 0 everywhere (see CHANGELOG) — the
    config-declared china_keywords list and china_keyword_lookback_days
    setting existed but were never actually consumed. Best-effort: any fetch
    failure for a given ticker is skipped, not fatal to the count.
    """
    m_cfg = cfg.get("modifiers", {}).get("macro_overlay", {})
    keywords = [k.lower() for k in m_cfg.get("china_keywords", [])]
    if not keywords:
        return 0
    lookback_days = int(m_cfg.get("china_keyword_lookback_days", 5))
    cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)

    semi_tickers = get_sector_tickers(cfg, "semiconductors")
    seen_titles: set = set()
    count = 0
    for ticker in semi_tickers:
        for art in _fetch_yahoo_news_safe(ticker):
            title = (art.get("title") or "").strip()
            if not title or title in seen_titles:
                continue
            ts_str = art.get("timestamp_utc")
            if ts_str:
                try:
                    ts = datetime.fromisoformat(ts_str)
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=timezone.utc)
                    if ts < cutoff:
                        continue
                except (ValueError, TypeError):
                    pass  # unparseable timestamp — don't drop the article over it
            if any(kw in title.lower() for kw in keywords):
                seen_titles.add(title)
                count += 1
    return count


def _compute_rotation_safe(benchmark_df, spy_df, cfg: Optional[dict] = None) -> dict:
    """
    Compute one sector's rotation state (benchmark vs. SPY flow); falls back
    to neutral on error. Called once per active sector — `benchmark_df` is
    that sector's own benchmark, not always SMH despite the underlying
    compute_rotation_state() param names.

    cfg: threaded through to compute_rotation_state() so the config-driven
    inflow_boost/outflow_penalty recalibration (see that function's
    docstring) actually reaches live scoring — without it, this silently
    fell back to a hardcoded +5 inflow boost the project's own backtest
    calibration found was backwards (CHANGELOG v2.2.47).
    """
    try:
        import pandas as pd
        if benchmark_df is None or spy_df is None:
            return {"confidence_modifier": 0.0, "rotation_state": "neutral"}
        benchmark_close = benchmark_df["Close"] if isinstance(benchmark_df, pd.DataFrame) else benchmark_df
        spy_close = spy_df["Close"] if isinstance(spy_df, pd.DataFrame) else spy_df
        return compute_rotation_state(smh_close=benchmark_close, spy_close=spy_close, cfg=cfg)
    except Exception as exc:
        logger.warning(f"Sector rotation failed — {exc}. Using neutral modifier.")
        return {"confidence_modifier": 0.0, "rotation_state": "neutral"}


def _compute_cross_ticker_safe(
    indicators_by_ticker: dict,
    ticker_ohlcv: dict,
    cfg: dict,
) -> dict:
    """Run cross-ticker analysis; returns empty dict on error so per-ticker modifier defaults to 0."""
    try:
        return analyze_cross_ticker(
            ticker_scores=indicators_by_ticker,
            ohlcv_data=ticker_ohlcv,
            cfg=cfg,
        )
    except Exception as exc:
        logger.warning(f"Cross-ticker analysis failed — {exc}. Using zero modifiers.")
        return {}


# ---------------------------------------------------------------------------
# Per-ticker data fetchers — all return empty results on failure so the
# scoring pipeline can continue with neutral values.
# ---------------------------------------------------------------------------

def _fetch_stocktwits_safe(ticker: str) -> list[dict]:
    try:
        return fetch_stocktwits(ticker) or []
    except Exception as exc:
        logger.debug(f"{ticker}: StockTwits fetch skipped — {exc}")
        return []


def _fetch_sa_engagement_safe(ticker: str) -> list[dict]:
    try:
        return fetch_seeking_alpha_engagement(ticker) or []
    except Exception as exc:
        logger.debug(f"{ticker}: Seeking Alpha engagement fetch skipped — {exc}")
        return []


def _fetch_av_news_safe(ticker: str) -> list[dict]:
    try:
        return fetch_news_alpha_vantage(ticker) or []
    except Exception as exc:
        logger.warning(f"{ticker}: Alpha Vantage news fetch failed — {exc}")
        return []


def _fetch_yahoo_news_safe(ticker: str) -> list[dict]:
    try:
        return fetch_news_yahoo(ticker) or []
    except Exception as exc:
        logger.warning(f"{ticker}: Yahoo news fetch failed — {exc}")
        return []


def _fetch_finnhub_news_safe(ticker: str) -> list[dict]:
    try:
        return fetch_news_finnhub(ticker) or []
    except Exception as exc:
        logger.warning(f"{ticker}: Finnhub news fetch failed — {exc}")
        return []


def _fetch_sec_edgar_safe(ticker: str) -> list[dict]:
    try:
        return fetch_recent_8k_filings(ticker) or []
    except Exception as exc:
        logger.warning(f"{ticker}: SEC EDGAR 8-K fetch failed — {exc}")
        return []


def _fetch_hyperscaler_capex_safe(ticker: str) -> list[dict]:
    try:
        return fetch_hyperscaler_capex_snippets(ticker) or []
    except Exception as exc:
        logger.warning(f"{ticker}: hyperscaler capex snippet fetch failed — {exc}")
        return []


def _compute_sector_context_filings(active_sectors: dict) -> dict[str, list[dict]]:
    """
    Fetch each active sector's configured capex_context_tickers (e.g.
    semiconductors' AMZN/MSFT/GOOGL/META — see config/swing_config.yaml)
    ONCE per scan, not once per ticker, since every ticker in that sector
    shares the same context filings. Sectors with no capex_context_tickers
    configured are simply absent from the returned dict.
    """
    context_filings: dict[str, list[dict]] = {}
    for sector_name, sector_cfg in active_sectors.items():
        capex_tickers = sector_cfg.get("capex_context_tickers", [])
        if not capex_tickers:
            continue
        snippets: list[dict] = []
        for hs_ticker in capex_tickers:
            snippets.extend(_fetch_hyperscaler_capex_safe(hs_ticker))
        context_filings[sector_name] = snippets
    return context_filings


def _fetch_earnings_safe(ticker: str) -> Optional[dict]:
    try:
        return fetch_earnings_calendar(ticker)
    except Exception as exc:
        logger.warning(f"{ticker}: Earnings calendar fetch failed — {exc}")
        return None


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Swing model daily scan")
    parser.add_argument(
        "--scan-type",
        choices=["pre_market", "mid_session", "post_close"],
        default="post_close",
        help="Which scan window to run",
    )
    args = parser.parse_args()
    main(scan_type=args.scan_type)
