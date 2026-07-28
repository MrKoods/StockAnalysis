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
    fetch_ohlcv_batch, fetch_vix, fetch_treasury_yield, fetch_dxy,
    fetch_earnings_calendar,
)
from shared.api_clients.sentiment_client import fetch_stocktwits, fetch_seeking_alpha_engagement
from shared.api_clients.news_client import fetch_news_alpha_vantage, fetch_news_yahoo, fetch_news_finnhub
from shared.utils.regime_detection import classify_regime, get_regime_modifiers, REGIME_HIGH_VOL
from shared.utils.macro_overlay import compute_macro_state, save_macro_state
from shared.utils.sector_rotation import compute_rotation_state
from shared.utils.earnings_calendar import get_earnings_modifier
from swing_model.cross_ticker_analysis import analyze_cross_ticker
from shared.utils.seasonality import get_seasonality_modifier
from shared.utils.risk_reward import compute_entry_zone, compute_stop_loss, compute_target
from swing_model.sentiment_layer import compute_sentiment_score
from swing_model.news_layer import compute_news_score, free_sources_flag_critical_event
from swing_model.scoring import compute_confidence_score
from swing_model.feedback_loop import load_live_weights_if_calibrated
from swing_model.trade_selector import rank_trade_structures
from shared.utils.position_sizer import get_risk_pct
from shared.utils.event_gate import (
    load_gate_state, save_gate_state, is_ticker_blocked, add_block,
    has_active_block_for_trigger, expire_blocks, is_thesis_opposed,
    SCOPE_SECTOR,
)
from shared.utils.sector_config import (
    get_active_sectors, get_all_tickers, get_ticker_sector_map, get_sector_tickers,
)

logger = get_logger(__name__)


def main(scan_type: str = "post_close") -> None:
    """
    Main entry point for a single scan run.

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

    # Step 6: Compute regime/rotation modifiers PER SECTOR (each sector can be
    # in a different regime at the same time) — macro overlay and seasonality
    # stay global, since TNX/DXY and the calendar aren't sector-specific.
    regime_by_sector: dict[str, str] = {}
    regime_modifier_by_sector: dict[str, float] = {}
    rotation_modifier_by_sector: dict[str, float] = {}
    for sector_name in active_sectors:
        bench_df = mkt["sector_benchmark_dfs"].get(sector_name)
        regime = _compute_regime_safe(mkt["vix"], bench_df)
        regime_by_sector[sector_name] = regime
        regime_modifier_by_sector[sector_name] = get_regime_modifiers(regime, cfg).get("regime_modifier", 0.0)
        rotation_modifier_by_sector[sector_name] = _compute_rotation_safe(
            bench_df, mkt["spy_df"]
        ).get("confidence_modifier", 0.0)

    macro_state_result = _compute_macro_safe(mkt["tnx_series"], mkt["dxy_series"], cfg)
    macro_modifier_val = macro_state_result.get("confidence_modifier", 0.0)
    # Persist for observability (app UI, debugging) — computed fresh every run
    # regardless, this doesn't feed back into scoring itself. Best-effort: a
    # write failure here shouldn't abort the scan.
    try:
        save_macro_state(macro_state_result)
    except Exception as exc:
        logger.warning(f"Failed to persist macro state — {exc}")
    seasonality_modifier_val = get_seasonality_modifier(cfg=cfg).get("confidence_modifier", 0.0)

    # Only non-None once a real feedback-loop calibration has passed holdout —
    # see load_live_weights_if_calibrated's docstring. With zero calibrations
    # run so far this is always None today, so compute_confidence_score's
    # live_weights branch stays a no-op; computed once here rather than per
    # ticker since it's the same value for the whole scan.
    live_weights_calibrated = load_live_weights_if_calibrated()

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
        "Alpha Vantage": True, "Finnhub": False,
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

            # This ticker's sector — drives which regime/rotation modifier applies
            # and which sector's event-gate trigger list is checked below.
            sector = ticker_sector_map.get(ticker)
            regime = regime_by_sector.get(sector, "choppy")
            regime_modifier_val = regime_modifier_by_sector.get(sector, 0.0)
            rotation_modifier_val = rotation_modifier_by_sector.get(sector, 0.0)

            # Sentiment layer — StockTwits crowd sentiment + Seeking Alpha engagement proxy
            stocktwits_messages = _fetch_stocktwits_safe(ticker)
            if stocktwits_messages:
                data_sources["StockTwits"] = True
            sa_engagement_items = _fetch_sa_engagement_safe(ticker)
            if sa_engagement_items:
                data_sources["SeekingAlpha"] = True
            price_data = {
                "price_change_5d_pct": (
                    indicators.get("close", 1.0) / max(indicators.get("sma_20", 1.0), 0.01) - 1
                )
            }
            sentiment = compute_sentiment_score(stocktwits_messages, sa_engagement_items, ticker, price_data, cfg)

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
            free_source_articles = sa_news_articles + yahoo_articles + finnhub_articles
            fetch_av_now = free_sources_flag_critical_event(
                free_source_articles, ticker, cfg, sector=sector
            )
            av_articles = _fetch_av_news_safe(ticker) if fetch_av_now else []
            news = compute_news_score(
                av_articles, yahoo_articles, ticker, cfg, finnhub_articles=finnhub_articles,
                sector=sector, seeking_alpha_articles=sa_news_articles,
            )

            # Earnings proximity modifier
            earnings_info = _fetch_earnings_safe(ticker)
            earnings_date = (earnings_info or {}).get("next_earnings_date")
            earnings_result = get_earnings_modifier(ticker, earnings_date, cfg=cfg)

            # Cross-ticker modifier for this specific ticker
            ct_modifier = cross_ticker_results.get(ticker, {}).get("confidence_modifier", 0.0)

            # Fundamental data (fetched weekly inside run_pipeline, cached in fundamental_state.json)
            fundamental = indicators.get("_fundamental_full") or {}

            # Market Positioning data (fetched daily inside run_pipeline, cached in positioning_state.json —
            # includes insider transactions, which are scored here instead of as a standalone modifier)
            positioning = indicators.get("_positioning_full") or {}

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
                live_weights=live_weights_calibrated,
                regime=regime,
                fundamental=fundamental,
                event_gate_blocked=event_gate_blocked,
                event_gate_trigger=event_gate_trigger,
            )

            final_score = float(score.get("final_score", 0.0))
            direction = score.get("direction", "bullish")

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
            risk_pct = 0.01
            notes = ""
            if score.get("event_gate_blocked"):
                notes = f"⚠️ ACTIVE EVENT ALERT — trigger: {score.get('event_gate_trigger')} — review before trading"

            if final_score >= 90:
                close_px = indicators.get("close", 0.0)
                atr = indicators.get("atr_14", close_px * 0.02)
                breakout_level = indicators.get("rolling_high_20", close_px)
                rr_cfg = cfg.get("risk_reward", {})

                entry_lower, entry_upper = compute_entry_zone(
                    close_px, breakout_level, atr,
                    rr_cfg.get("entry_zone_half_width_atr", 0.25),
                )
                entry_mid = (entry_lower + entry_upper) / 2.0
                stop_loss = compute_stop_loss(
                    entry_lower, atr,
                    stop_atr_multiplier=rr_cfg.get("stop_atr_multiplier", 2.0),
                )
                target = compute_target(entry_mid, stop_loss, min_rr=rr_cfg.get("min_rr_ratio", 3.0))

                if target and target > entry_mid > stop_loss:
                    rr_ratio = round((target - entry_mid) / (entry_mid - stop_loss), 2)
                    risk_pct = get_risk_pct(final_score)
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
                            cfg=cfg,
                        )
                        ranked = trade_result.get("ranked_structures", [])
                        if ranked:
                            best = ranked[0]
                            structure_recommended = best.get("name", "")
                            ev_per_dollar = best.get("ev_per_dollar_risked", 0.0)
                            rr_ratio = best.get("rr_ratio", rr_ratio)
                    except Exception as exc:
                        logger.error(f"{ticker}: trade structure ranking failed — {exc}")

                if ticker in cfg.get("geopolitical_risk_tickers", []):
                    geo_note = f"Geopolitical risk ticker ({cfg.get('geopolitical_penalty', -5)} confidence penalty applied)"
                    notes = f"{notes} | {geo_note}" if notes else geo_note

            signal_surfaced = final_score >= 90

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
                        "direction": direction, "risk_pct": risk_pct,
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
            except Exception:
                pass

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
        with open(path, newline="") as f:
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

    vix = None
    try:
        vix = fetch_vix()
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
        "sector_benchmark_dfs": sector_benchmark_dfs,
        "spy_df": spy_df,
        "tnx_series": tnx_series,
        "dxy_series": dxy_series,
        "ticker_ohlcv": ticker_ohlcv,
    }


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
    cfg: dict,
) -> dict:
    """
    Compute macro overlay; falls back to neutral (confidence_modifier=0.0) on error.
    china_keyword_count_5d is passed as 0 — China keyword counting requires news data
    that isn't yet parsed at this stage of the pipeline.
    """
    try:
        if tnx_series is None or dxy_series is None:
            return {"confidence_modifier": 0.0, "macro_state": "neutral"}
        return compute_macro_state(
            tnx_close=tnx_series,
            dxy_close=dxy_series,
            china_keyword_count_5d=0,
            cfg=cfg,
        )
    except Exception as exc:
        logger.warning(f"Macro overlay failed — {exc}. Using neutral modifier.")
        return {"confidence_modifier": 0.0, "macro_state": "neutral"}


def _compute_rotation_safe(benchmark_df, spy_df) -> dict:
    """
    Compute one sector's rotation state (benchmark vs. SPY flow); falls back
    to neutral on error. Called once per active sector — `benchmark_df` is
    that sector's own benchmark, not always SMH despite the underlying
    compute_rotation_state() param names.
    """
    try:
        import pandas as pd
        if benchmark_df is None or spy_df is None:
            return {"confidence_modifier": 0.0, "rotation_state": "neutral"}
        benchmark_close = benchmark_df["Close"] if isinstance(benchmark_df, pd.DataFrame) else benchmark_df
        spy_close = spy_df["Close"] if isinstance(spy_df, pd.DataFrame) else spy_df
        return compute_rotation_state(smh_close=benchmark_close, spy_close=spy_close)
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
