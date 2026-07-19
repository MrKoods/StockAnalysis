"""
Paper trading signal runner. Run post-close each session day to detect qualifying
signals (confidence >= 90) and log them to paper_trading/paper_trades.csv.

Records every layer's raw scores, regime state, and trade parameters so the paper
trading period produces a rich dataset for model calibration.

Does NOT enforce circuit breakers or position size limits — all qualifying signals
are logged regardless of portfolio state, giving an unfiltered view of model accuracy.

Discord alerts fire separately from the live model alerts (different embed format,
clearly labeled as paper trading).

Usage:
    python -m paper_trading.paper_runner
    python -m paper_trading.paper_runner --scan-type post_close
"""

import argparse
import csv
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

# Load .env before any imports that read environment variables
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from app_ui import db as app_db
from swing_model.indicator_pipeline import run_pipeline, load_config
from swing_model.sentiment_layer import compute_sentiment_score
from swing_model.news_layer import compute_news_score
from swing_model.scoring import compute_confidence_score
from shared.utils.risk_reward import compute_entry_zone, compute_stop_loss, compute_target
from shared.utils.regime_detection import get_regime_modifiers
from shared.utils.earnings_calendar import get_earnings_modifier
from shared.utils.seasonality import get_seasonality_modifier
from shared.utils.logger import get_logger
from shared.utils.discord_alerts import send_paper_signal_alert, send_near_miss_alert
from swing_model.trade_selector import rank_trade_structures
from shared.utils.regime_detection import REGIME_HIGH_VOL
from shared.utils.event_gate import (
    load_gate_state, save_gate_state, is_ticker_blocked, add_block,
    has_active_block_for_trigger, expire_blocks, is_thesis_opposed,
    SCOPE_SECTOR,
)

# Reuse all pipeline helpers from run_swing_model to avoid duplication
from swing_model.run_swing_model import (
    _fetch_market_context,
    _compute_regime_safe,
    _compute_macro_safe,
    _compute_rotation_safe,
    _compute_cross_ticker_safe,
    _fetch_stocktwits_safe,
    _fetch_sa_engagement_safe,
    _fetch_av_news_safe,
    _fetch_yahoo_news_safe,
    _fetch_finnhub_news_safe,
    _fetch_earnings_safe,
    get_model_version,
    _try_send_event_gate_alert,
    _try_send_event_gate_expired_alert,
    _write_event_gate_audit,
)

logger = get_logger(__name__)

PAPER_TRADES_CSV = Path("paper_trading/paper_trades.csv")
CONFIG_PATH = Path("config/swing_config.yaml")
CONFIDENCE_THRESHOLD = 90
NEAR_MISS_THRESHOLD = 80  # awareness-only Discord ping; never logged as a trade

# Maps a layer_scores.layer_name (app_ui/db.py) to the compute_confidence_score()
# result key it comes from — 5 scored categories + 6 modifiers, see App_UI_Scope.md §3.1/§5.
_LAYER_SCORE_FIELDS = {
    "technical": "technical_total",
    "market_positioning": "positioning_total",
    "sentiment": "sentiment_total",
    "news": "news_total",
    "fundamental": "fundamental_score",
    "regime": "regime_modifier",
    "sector_rotation": "sector_rotation_modifier",
    "earnings": "earnings_modifier",
    "cross_ticker": "cross_ticker_modifier",
    "seasonality": "seasonality_modifier",
    "macro_overlay": "macro_modifier",
}

_CSV_COLUMNS = [
    "signal_date", "ticker", "confidence",
    "technical_score", "positioning_score", "sentiment_score", "news_score", "fundamental_score",
    "regime", "vix_at_signal",
    "rsi_14", "rs_zscore", "mom_5d", "trend_intact",
    "entry_zone_lower", "entry_zone_upper", "entry_price", "stop_loss", "target", "rr_ratio",
    "news_article_count", "dominant_news_theme", "fundamental_data_quality",
    "structure_recommended", "ev_per_dollar",
    "event_gate_blocked", "event_gate_trigger",
    # Outcome fields — blank until paper_updater.py fills them in
    "outcome", "exit_date", "exit_price", "pnl_pct", "achieved_rr", "holding_days",
]


def _load_logged_keys() -> set[tuple[str, str]]:
    """Return set of (signal_date, ticker) pairs already in paper_trades.csv."""
    if not PAPER_TRADES_CSV.exists():
        return set()
    seen: set[tuple[str, str]] = set()
    try:
        with open(PAPER_TRADES_CSV, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                seen.add((row.get("signal_date", ""), row.get("ticker", "")))
    except Exception as exc:
        logger.warning(f"Could not read paper_trades.csv: {exc}")
    return seen


def _append_row(row: dict) -> None:
    """Append one signal row to paper_trades.csv, creating header on first write."""
    PAPER_TRADES_CSV.parent.mkdir(parents=True, exist_ok=True)
    write_header = not PAPER_TRADES_CSV.exists()
    with open(PAPER_TRADES_CSV, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=_CSV_COLUMNS, extrasaction="ignore")
        if write_header:
            writer.writeheader()
        writer.writerow(row)


# ---------------------------------------------------------------------------
# App UI persistence — writes alongside the existing CSV/Discord behavior,
# never in place of it. Every call is wrapped so a DB failure (locked file,
# disk full) never breaks a scan the way it would if this were load-bearing.
# See App_UI_Scope.md §4 — "wrap instead of consolidate."
# ---------------------------------------------------------------------------

def _read_config_snapshot() -> str:
    try:
        return CONFIG_PATH.read_text(encoding="utf-8")
    except Exception as exc:
        logger.warning(f"Could not read {CONFIG_PATH} for config_snapshot: {exc}")
        return ""


def _db_create_scan_run_safe(scan_type: str, config_snapshot: str) -> Optional[int]:
    try:
        return app_db.create_scan_run(scan_type, config_snapshot)
    except Exception as exc:
        logger.warning(f"app_ui DB: could not create scan_run — {exc}")
        return None


def _db_insert_ticker_result_safe(
    run_id: Optional[int],
    ticker: str,
    category: str,
    composite_score: float,
    trade_structure: Optional[str] = None,
    expected_value: Optional[float] = None,
    event_gate_blocked: bool = False,
    event_gate_trigger: Optional[str] = None,
) -> Optional[int]:
    if run_id is None:
        return None
    try:
        return app_db.insert_ticker_result(
            run_id, ticker, category, composite_score,
            trade_structure=trade_structure, expected_value=expected_value,
            event_gate_blocked=event_gate_blocked, event_gate_trigger=event_gate_trigger,
        )
    except Exception as exc:
        logger.warning(f"app_ui DB: could not insert ticker_result for {ticker} — {exc}")
        return None


def _db_insert_layer_scores_safe(result_id: Optional[int], score: dict) -> None:
    if result_id is None:
        return
    try:
        for layer_name, score_key in _LAYER_SCORE_FIELDS.items():
            app_db.insert_layer_score(result_id, layer_name, score.get(score_key))
    except Exception as exc:
        logger.warning(f"app_ui DB: could not insert layer_scores — {exc}")


def _db_insert_notification_safe(
    run_id: Optional[int],
    ticker: Optional[str],
    alert_type: str,
    payload: dict,
    discord_sent: bool,
) -> None:
    try:
        app_db.insert_notification(
            alert_type, "sent" if discord_sent else "failed",
            run_id=run_id, ticker=ticker, payload=payload,
        )
    except Exception as exc:
        logger.warning(f"app_ui DB: could not insert notification ({alert_type}) — {exc}")


def run_paper_scan(scan_type: str = "post_close") -> int:
    """
    Run the full swing model pipeline and log qualifying signals to paper_trades.csv.
    Returns number of new signals logged this session.
    """
    cfg = load_config()
    model_version = get_model_version()
    today_str = date.today().isoformat()
    already_logged = _load_logged_keys()

    # app_ui DB — one scan_runs row per invocation; every ticker_result and
    # notification below is tagged with this run_id. run_id is None if the DB
    # write itself failed, in which case the _db_*_safe helpers all no-op.
    run_id = _db_create_scan_run_safe(scan_type, _read_config_snapshot())

    # Event Severity Gate state — shared with run_swing_model.py's live scans
    # (same real-world tickers, same blocks). See event_gate.expire_blocks for
    # why blocks created in this run must be excluded from this run's expiry.
    gate_state = load_gate_state()
    blocks_created_this_scan: set[str] = set()

    watchlist: list[str] = cfg.get("watchlist", {}).get("tickers", ["NVDA", "AMD", "AVGO", "TSM", "MU", "ASML"])
    rr_cfg: dict = cfg.get("risk_reward", {})

    # --- Technical indicators (single batch yfinance fetch) ---
    indicators_by_ticker = run_pipeline(watchlist, scan_type=scan_type, cfg=cfg)

    # --- Shared market context ---
    mkt = _fetch_market_context(watchlist)
    vix_val = float(mkt["vix"]) if mkt["vix"] is not None else 15.0
    regime = _compute_regime_safe(mkt["vix"], mkt["smh_df"])
    regime_mod = get_regime_modifiers(regime, cfg).get("regime_modifier", 0.0)
    macro_mod = _compute_macro_safe(mkt["tnx_series"], mkt["dxy_series"], cfg).get("confidence_modifier", 0.0)
    rotation_mod = _compute_rotation_safe(mkt["smh_df"], mkt["spy_df"]).get("confidence_modifier", 0.0)
    seasonality_mod = get_seasonality_modifier(cfg=cfg).get("confidence_modifier", 0.0)
    cross_ticker = _compute_cross_ticker_safe(indicators_by_ticker, mkt["ticker_ohlcv"], cfg)

    signals_logged = 0

    for ticker in watchlist:
        try:
            indicators = indicators_by_ticker.get(ticker)
            if indicators is None:
                logger.debug(f"{ticker}: no indicators — skipped")
                continue

            if (today_str, ticker) in already_logged:
                logger.info(f"{ticker}: already logged today — skipped")
                continue

            # Sentiment — StockTwits crowd sentiment + Seeking Alpha engagement proxy
            stocktwits_messages = _fetch_stocktwits_safe(ticker)
            sa_engagement_items = _fetch_sa_engagement_safe(ticker)
            price_data = {
                "price_change_5d_pct": (
                    indicators.get("close", 1.0) / max(indicators.get("sma_20", 1.0), 0.01) - 1
                )
            }
            sentiment = compute_sentiment_score(stocktwits_messages, sa_engagement_items, ticker, price_data, cfg)

            # News
            av_articles = _fetch_av_news_safe(ticker)
            yahoo_articles = _fetch_yahoo_news_safe(ticker)
            finnhub_articles = _fetch_finnhub_news_safe(ticker)
            news = compute_news_score(av_articles, yahoo_articles, ticker, cfg, finnhub_articles=finnhub_articles)

            # Earnings + cross-ticker modifiers
            earnings_info = _fetch_earnings_safe(ticker)
            earnings_date = (earnings_info or {}).get("next_earnings_date")
            earnings_result = get_earnings_modifier(ticker, earnings_date, cfg=cfg)
            earnings_mod = earnings_result.get("confidence_modifier", 0.0)
            ct_mod = cross_ticker.get(ticker, {}).get("confidence_modifier", 0.0)

            # Fundamental + Positioning (fetched inside run_pipeline, cached in *_state.json)
            fundamental = indicators.get("_fundamental_full") or {}
            positioning = indicators.get("_positioning_full") or {}

            # Event Severity Gate — check for an existing block (from a prior
            # scan) before scoring. Full parity with run_swing_model.py: advisory
            # only, so the signal still surfaces on its own score merits, flagged
            # with event_gate_blocked/trigger for the paper trade log and alert.
            existing_gate_block = is_ticker_blocked(ticker, gate_state)
            event_gate_blocked = existing_gate_block is not None
            event_gate_trigger = existing_gate_block.get("trigger_match") if existing_gate_block else None

            # Full confidence score
            score = compute_confidence_score(
                technical=indicators,
                positioning=positioning,
                sentiment=sentiment,
                news=news,
                regime_modifier=regime_mod,
                sector_rotation_modifier=rotation_mod,
                earnings_modifier=earnings_mod,
                cross_ticker_modifier=ct_mod,
                seasonality_modifier=seasonality_mod,
                macro_modifier=macro_mod,
                cfg=cfg,
                regime=regime,
                fundamental=fundamental,
                event_gate_blocked=event_gate_blocked,
                event_gate_trigger=event_gate_trigger,
            )

            final_score = float(score.get("final_score", 0.0))
            direction = score.get("direction", "bullish")

            # Event Severity Gate — process this scan's critical news for this
            # ticker (may block it before it's even logged as a paper signal).
            # Sector-wide triggers block unconditionally; ticker triggers block
            # only when thesis-opposed. Mirrors run_swing_model.py exactly,
            # including updating this scan's own score dict in place so a
            # same-scan critical event can't slip through before its own block
            # is created (see run_swing_model.py for the full rationale).
            for event in news.get("critical_events", []):
                event_scope = event["scope"]
                trigger = event["trigger_match"]

                if event_scope == SCOPE_SECTOR:
                    if not has_active_block_for_trigger(gate_state, trigger, SCOPE_SECTOR):
                        gate_state = add_block(
                            gate_state, tickers=list(watchlist), scope=SCOPE_SECTOR,
                            trigger_headline=event["headline"], trigger_match=trigger,
                            source=event["source"], event_timestamp_utc=event["event_timestamp_utc"],
                        )
                        new_block = gate_state["blocks"][-1]
                        blocks_created_this_scan.add(new_block["id"])
                        gate_discord_sent = _try_send_event_gate_alert(new_block, model_version)
                        _db_insert_notification_safe(
                            run_id, None, "event_gate_triggered", new_block, gate_discord_sent,
                        )
                        _write_event_gate_audit(new_block, model_version, scan_type, triggered=True)
                        score["event_gate_blocked"] = True
                        score["event_gate_trigger"] = trigger
                else:
                    opposed = is_thesis_opposed(event.get("ner_sentiment"), direction)
                    if opposed and not is_ticker_blocked(ticker, gate_state):
                        gate_state = add_block(
                            gate_state, tickers=[ticker], scope=event_scope,
                            trigger_headline=event["headline"], trigger_match=trigger,
                            source=event["source"], event_timestamp_utc=event["event_timestamp_utc"],
                        )
                        new_block = gate_state["blocks"][-1]
                        blocks_created_this_scan.add(new_block["id"])
                        gate_discord_sent = _try_send_event_gate_alert(new_block, model_version)
                        _db_insert_notification_safe(
                            run_id, ticker, "event_gate_triggered", new_block, gate_discord_sent,
                        )
                        _write_event_gate_audit(new_block, model_version, scan_type, triggered=True)
                        score["event_gate_blocked"] = True
                        score["event_gate_trigger"] = trigger

            if score.get("event_gate_blocked"):
                logger.info(
                    f"{ticker}: ACTIVE EVENT (trigger='{score.get('event_gate_trigger')}') "
                    f"— signal still logged, flagged for review"
                )

            # Log every ticker's computed score regardless of qualification —
            # otherwise sub-threshold tickers leave no record of what they
            # actually scored, making it impossible to audit the scoring
            # layers on days with zero qualifying signals. Modifiers are
            # included since they're shared across the whole watchlist each
            # scan and are the natural explanation for a uniform day-over-day
            # move in every ticker's score at once.
            logger.info(
                f"{ticker}: SCORE {final_score:.1f}/100 "
                f"(technical={score.get('technical_total', 0.0):.1f}/40, "
                f"positioning={score.get('positioning_total', 0.0):.1f}/20, "
                f"sentiment={score.get('sentiment_total', 0.0):.1f}/15, "
                f"news={score.get('news_total', 0.0):.1f}/15, "
                f"fundamental={score.get('fundamental_score', 0.0):.1f}/10) "
                f"modifiers(regime={score.get('regime_modifier', 0.0):+.1f}, "
                f"macro={score.get('macro_modifier', 0.0):+.1f}, "
                f"sector_rotation={score.get('sector_rotation_modifier', 0.0):+.1f}, "
                f"earnings={score.get('earnings_modifier', 0.0):+.1f}, "
                f"cross_ticker={score.get('cross_ticker_modifier', 0.0):+.1f}, "
                f"seasonality={score.get('seasonality_modifier', 0.0):+.1f}, "
                f"total={score.get('total_modifier', 0.0):+.1f}) "
                f"direction={direction} "
                f"qualifies={'yes' if final_score >= CONFIDENCE_THRESHOLD else 'no'}"
            )

            # regime_modifier and sector_rotation_modifier are both derived
            # from the same underlying SMH price action (regime: SMH vs. its
            # own SMA trend; sector_rotation: SMH return vs. SPY) but summed
            # as if independent. When both are negative at once, it's one
            # real observation ("SMH is weak") being counted twice, not two
            # separate corroborating signals — worth knowing when reading a
            # heavily-penalized score, not something to silently auto-adjust.
            if score.get("regime_modifier", 0.0) < 0 and score.get("sector_rotation_modifier", 0.0) < 0:
                logger.info(
                    f"{ticker}: NOTE — regime ({score.get('regime_modifier', 0.0):+.1f}) and "
                    f"sector_rotation ({score.get('sector_rotation_modifier', 0.0):+.1f}) are both "
                    f"negative and both derived from SMH price action — likely the same underlying "
                    f"weakness counted twice, not two independent signals"
                )

            if final_score < CONFIDENCE_THRESHOLD:
                sub_threshold_category = (
                    app_db.CATEGORY_NEAR_MISS if final_score >= NEAR_MISS_THRESHOLD else app_db.CATEGORY_NO_SIGNAL
                )
                result_id = _db_insert_ticker_result_safe(
                    run_id, ticker, sub_threshold_category, final_score,
                    event_gate_blocked=bool(score.get("event_gate_blocked", False)),
                    event_gate_trigger=score.get("event_gate_trigger"),
                )
                _db_insert_layer_scores_safe(result_id, score)

                if final_score >= NEAR_MISS_THRESHOLD:
                    near_miss_payload = {
                        "ticker": ticker,
                        "confidence": final_score,
                        "direction": direction,
                        "regime": regime,
                        "technical_score": score.get("technical_total", 0.0),
                        "positioning_score": score.get("positioning_total", 0.0),
                        "sentiment_score": score.get("sentiment_total", 0.0),
                        "news_score": score.get("news_total", 0.0),
                        "fundamental_score": score.get("fundamental_score", 0.0),
                        "total_modifier": score.get("total_modifier", 0.0),
                    }
                    near_miss_sent = False
                    try:
                        near_miss_sent = send_near_miss_alert(near_miss_payload, model_version=model_version)
                    except Exception as exc:
                        logger.warning(f"{ticker}: near-miss Discord alert failed — {exc}")
                    _db_insert_notification_safe(
                        run_id, ticker, "near_miss", near_miss_payload, near_miss_sent,
                    )
                continue

            # Entry/stop/target
            close_px = float(indicators.get("close", 0.0))
            atr = float(indicators.get("atr_14", close_px * 0.02))
            breakout_level = float(indicators.get("rolling_high_20", close_px))

            entry_lower, entry_upper = compute_entry_zone(
                close_px, breakout_level, atr,
                rr_cfg.get("entry_zone_half_width_atr", 0.25),
            )
            entry_mid = (entry_lower + entry_upper) / 2.0
            stop_loss = compute_stop_loss(
                entry_lower, atr,
                stop_atr_multiplier=rr_cfg.get("stop_atr_multiplier", 2.0),
            )
            target_px = compute_target(entry_mid, stop_loss, min_rr=rr_cfg.get("min_rr_ratio", 3.0))
            risk = entry_mid - stop_loss
            rr_ratio = round((target_px - entry_mid) / risk, 2) if (target_px and risk > 0) else 0.0

            # Trade structure ranking
            structure_recommended = ""
            ev_per_dollar = ""
            try:
                force_defined_risk = earnings_result.get("force_defined_risk", False) or (regime == REGIME_HIGH_VOL)
                trade_result = rank_trade_structures(
                    {
                        "ticker": ticker,
                        "direction": direction,
                        "confidence": final_score,
                        "entry": entry_mid,
                        "entry_mid": entry_mid,
                        "stop_loss": stop_loss,
                        "target": target_px,
                        "atr_14": atr,
                        "force_defined_risk": force_defined_risk,
                    },
                    account_equity=15000.0,
                    options_approval_level=int(cfg.get("options_approval_level", 2)),
                    iv_percentile=50.0,
                    cfg=cfg,
                )
                ranked = trade_result.get("ranked_structures", [])
                if ranked:
                    best = ranked[0]
                    structure_recommended = best.get("name", "")
                    ev_per_dollar = f"{best.get('ev_per_dollar_risked', 0.0):.3f}"
            except Exception as exc:
                logger.warning(f"{ticker}: structure ranking failed — {exc}")

            qualified_category = (
                app_db.CATEGORY_TRADE_RECOMMENDED if structure_recommended else app_db.CATEGORY_PASSED_NO_TRADE
            )
            result_id = _db_insert_ticker_result_safe(
                run_id, ticker, qualified_category, final_score,
                trade_structure=structure_recommended or None,
                expected_value=float(ev_per_dollar) if ev_per_dollar else None,
                event_gate_blocked=bool(score.get("event_gate_blocked", False)),
                event_gate_trigger=score.get("event_gate_trigger"),
            )
            _db_insert_layer_scores_safe(result_id, score)

            news_count = len(av_articles) + len(yahoo_articles) + len(finnhub_articles)
            dominant_theme = str(news.get("dominant_theme", "")) if isinstance(news, dict) else ""

            row: dict = {
                "signal_date": today_str,
                "ticker": ticker,
                "confidence": f"{final_score:.1f}",
                "technical_score": f"{score.get('technical_total', 0.0):.1f}",
                "positioning_score": f"{score.get('positioning_total', 0.0):.1f}",
                "sentiment_score": f"{score.get('sentiment_total', 0.0):.1f}",
                "news_score": f"{score.get('news_total', 0.0):.1f}",
                "fundamental_score": f"{score.get('fundamental_score', 0.0):.1f}",
                "regime": regime,
                "vix_at_signal": f"{vix_val:.1f}",
                "rsi_14": f"{float(indicators.get('rsi_14', 0.0)):.1f}",
                "rs_zscore": f"{float(indicators.get('rs_zscore', 0.0)):.3f}",
                "mom_5d": f"{float(indicators.get('mom_5d', 0.0)):.4f}",
                "trend_intact": str(bool(indicators.get("trend_intact", False))),
                "entry_zone_lower": f"{entry_lower:.2f}",
                "entry_zone_upper": f"{entry_upper:.2f}",
                "entry_price": f"{entry_mid:.2f}",
                "stop_loss": f"{stop_loss:.2f}",
                "target": f"{target_px:.2f}" if target_px else "",
                "rr_ratio": f"{rr_ratio:.2f}",
                "news_article_count": str(news_count),
                "dominant_news_theme": dominant_theme,
                "fundamental_data_quality": str(score.get("fundamental_data_quality", "unavailable")),
                "structure_recommended": structure_recommended,
                "ev_per_dollar": ev_per_dollar,
                "event_gate_blocked": bool(score.get("event_gate_blocked", False)),
                "event_gate_trigger": score.get("event_gate_trigger", "") or "",
                # Outcome fields filled by paper_updater.py
                "outcome": "",
                "exit_date": "",
                "exit_price": "",
                "pnl_pct": "",
                "achieved_rr": "",
                "holding_days": "",
            }

            _append_row(row)
            signals_logged += 1
            logger.info(f"{ticker}: PAPER signal logged — confidence {final_score:.1f}")

            # Paper-specific Discord alert (separate from live model alert)
            paper_alert_payload = {
                **row,
                "entry_zone_lower": entry_lower,
                "entry_zone_upper": entry_upper,
                "stop_loss": stop_loss,
                "target": float(target_px) if target_px else 0.0,
                "rr_ratio": rr_ratio,
                "technical_score": score.get("technical_total", 0.0),
                "positioning_score": score.get("positioning_total", 0.0),
                "sentiment_score": score.get("sentiment_total", 0.0),
                "news_score": score.get("news_total", 0.0),
                "fundamental_score": score.get("fundamental_score", 0.0),
            }
            paper_alert_sent = False
            try:
                paper_alert_sent = send_paper_signal_alert(paper_alert_payload, model_version=model_version)
            except Exception as exc:
                logger.warning(f"{ticker}: paper Discord alert failed — {exc}")
            _db_insert_notification_safe(run_id, ticker, "trade", paper_alert_payload, paper_alert_sent)

        except Exception as exc:
            logger.error(f"{ticker}: paper_runner error — {exc}")

    # Event Severity Gate — expire blocks whose cooling-off condition is met,
    # same rule as run_swing_model.py: a post_close scan completing after the
    # block's event timestamp, excluding blocks created earlier in this run.
    newly_expired_blocks = expire_blocks(
        gate_state, scan_type, datetime.now(timezone.utc), exclude_ids=blocks_created_this_scan,
    )
    save_gate_state(gate_state)
    for expired_block in newly_expired_blocks:
        expired_discord_sent = _try_send_event_gate_expired_alert(expired_block, model_version)
        _db_insert_notification_safe(
            run_id, None, "event_gate_expired", expired_block, expired_discord_sent,
        )
        _write_event_gate_audit(expired_block, model_version, scan_type, triggered=False)

    logger.info(f"Paper scan complete — {signals_logged} new signals logged to {PAPER_TRADES_CSV}")
    return signals_logged


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Paper trading signal runner")
    parser.add_argument(
        "--scan-type",
        choices=["pre_market", "mid_session", "post_close"],
        default="post_close",
        help="Which scan window (default: post_close)",
    )
    args = parser.parse_args()
    count = run_paper_scan(scan_type=args.scan_type)
    print(f"Done — {count} paper signal(s) logged.")
    sys.exit(0)
