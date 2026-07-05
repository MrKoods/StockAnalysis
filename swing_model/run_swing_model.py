"""
Entry point — run daily to generate ranked swing recommendations.
Reads model version from CHANGELOG.md. Checks for missed scans.
Runs pre-market (~8:30am ET), mid-session (~12pm ET), post-close (~4:30pm ET).
Sends system health check at post-close regardless of whether candidates were found.
"""

import argparse
import csv
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

import yaml

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
from shared.api_clients.sentiment_client import fetch_stocktwits, fetch_reddit
from shared.api_clients.news_client import fetch_news_alpha_vantage, fetch_news_yahoo
from shared.utils.regime_detection import classify_regime, get_regime_modifiers, REGIME_HIGH_VOL
from shared.utils.macro_overlay import compute_macro_state
from shared.utils.sector_rotation import compute_rotation_state
from shared.utils.earnings_calendar import get_earnings_modifier
from swing_model.cross_ticker_analysis import analyze_cross_ticker
from shared.utils.seasonality import get_seasonality_modifier
from shared.utils.insider_tracker import get_insider_signal
from shared.utils.risk_reward import compute_entry_zone, compute_stop_loss, compute_target
from swing_model.sentiment_layer import compute_sentiment_score
from swing_model.news_layer import compute_news_score
from swing_model.scoring import compute_confidence_score
from swing_model.trade_selector import rank_trade_structures
from shared.utils.position_sizer import get_risk_pct

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
    8.  Per-ticker: sentiment, news, earnings, insider, full confidence score
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

    watchlist = cfg.get("watchlist", {}).get("tickers", ["NVDA", "AMD", "AVGO", "TSM", "MU", "ASML"])

    # Step 4: Run indicator pipeline for ALL tickers in a single batch fetch
    indicators_by_ticker = run_pipeline(watchlist, scan_type=scan_type, cfg=cfg)

    # Step 5: Fetch shared market context data (separate 3-month window for modifiers)
    mkt = _fetch_market_context(watchlist)

    # Step 6: Compute shared modifiers — computed once and applied to every ticker
    regime = _compute_regime_safe(mkt["vix"], mkt["smh_df"])
    regime_modifier_val = get_regime_modifiers(regime, cfg).get("regime_modifier", 0.0)
    macro_modifier_val = _compute_macro_safe(mkt["tnx_series"], mkt["dxy_series"], cfg).get("confidence_modifier", 0.0)
    rotation_modifier_val = _compute_rotation_safe(mkt["smh_df"], mkt["spy_df"]).get("confidence_modifier", 0.0)
    seasonality_modifier_val = get_seasonality_modifier(cfg=cfg).get("confidence_modifier", 0.0)

    # Step 7: Cross-ticker analysis
    cross_ticker_results = _compute_cross_ticker_safe(indicators_by_ticker, mkt["ticker_ohlcv"], cfg)

    # Step 8-9: Per-ticker scoring and signal evaluation
    tickers_processed = 0
    candidates = []
    data_sources = {"yfinance": True, "StockTwits": False, "Reddit": False, "Alpha Vantage": True}

    for ticker in watchlist:
        try:
            indicators = indicators_by_ticker.get(ticker)
            if indicators is None:
                continue
            tickers_processed += 1

            # Sentiment layer
            st_posts = _fetch_stocktwits_safe(ticker)
            reddit_posts = _fetch_reddit_safe(ticker)
            if st_posts:
                data_sources["StockTwits"] = True
            if reddit_posts:
                data_sources["Reddit"] = True
            price_data = {
                "price_change_5d_pct": (
                    indicators.get("close", 1.0) / max(indicators.get("sma_20", 1.0), 0.01) - 1
                )
            }
            sentiment = compute_sentiment_score(st_posts, reddit_posts, ticker, price_data, cfg)

            # News layer
            av_articles = _fetch_av_news_safe(ticker)
            yahoo_articles = _fetch_yahoo_news_safe(ticker)
            news = compute_news_score(av_articles, yahoo_articles, ticker, cfg)

            # Earnings proximity modifier
            earnings_info = _fetch_earnings_safe(ticker)
            earnings_date = (earnings_info or {}).get("next_earnings_date")
            earnings_result = get_earnings_modifier(ticker, earnings_date, cfg=cfg)

            # Insider signal
            insider_result = _get_insider_safe(ticker)

            # Cross-ticker modifier for this specific ticker
            ct_modifier = cross_ticker_results.get(ticker, {}).get("confidence_modifier", 0.0)

            # Fundamental data (fetched weekly inside run_pipeline, cached in fundamental_state.json)
            fundamental = indicators.get("_fundamental_full") or {}

            # Full confidence score — all layers combined
            score = compute_confidence_score(
                technical=indicators,
                sentiment=sentiment,
                news=news,
                regime_modifier=regime_modifier_val,
                sector_rotation_modifier=rotation_modifier_val,
                earnings_modifier=earnings_result.get("confidence_modifier", 0.0),
                cross_ticker_modifier=ct_modifier,
                insider_modifier=insider_result.get("confidence_modifier", 0.0),
                seasonality_modifier=seasonality_modifier_val,
                macro_modifier=macro_modifier_val,
                cfg=cfg,
                regime=regime,
                fundamental=fundamental,
            )

            final_score = float(score.get("final_score", 0.0))
            direction = score.get("direction", "bullish")

            # Trade structure evaluation (only for signals at or above threshold)
            entry_lower = entry_upper = stop_loss = target = None
            structure_recommended = ev_per_dollar = rr_ratio = None
            risk_pct = 0.01
            notes = ""

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
                            iv_percentile=50.0,
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
                    notes = f"Geopolitical risk ticker ({cfg.get('geopolitical_penalty', -5)} confidence penalty applied)"

            # Step 11: Write audit log entry for every scanned ticker
            write_audit_entry({
                "model_version": model_version,
                "scan_type": scan_type,
                "ticker": ticker,
                "technical_score": score.get("technical_total", 0.0),
                "sentiment_score": score.get("sentiment_total", 0.0),
                "news_score": score.get("news_total", 0.0),
                "base_score": score.get("base_score", 0.0),
                "regime_modifier": score.get("regime_modifier", 0.0),
                "sector_rotation_modifier": score.get("sector_rotation_modifier", 0.0),
                "earnings_modifier": score.get("earnings_modifier", 0.0),
                "cross_ticker_modifier": score.get("cross_ticker_modifier", 0.0),
                "insider_modifier": score.get("insider_modifier", 0.0),
                "seasonality_modifier": score.get("seasonality_modifier", 0.0),
                "macro_modifier": score.get("macro_modifier", 0.0),
                "final_score": final_score,
                "signal_surfaced": final_score >= 90,
                "direction": direction,
                "structure_recommended": structure_recommended or "",
                "ev_per_dollar": ev_per_dollar or "",
                "rr_ratio": rr_ratio or "",
                "entry_lower": entry_lower or "",
                "entry_upper": entry_upper or "",
                "stop_loss": stop_loss or "",
                "target": target or "",
                "notes": notes,
            })

            if final_score >= 90 and cb_state not in ("orange", "red"):
                allowed, reason = can_open_new_position(state, {
                    "ticker": ticker,
                    "direction": direction,
                    "confidence": final_score,
                    "risk_pct": risk_pct,
                })
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
            data_sources["yfinance"] = False

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
    """Extract current model version from CHANGELOG.md header."""
    try:
        content = Path(changelog_path).read_text()
        for line in content.splitlines():
            if line.startswith("## [v"):
                return line.split("]")[0].strip("## [")
    except Exception:
        pass
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


def _try_send_cb_alert(cb_change: dict, equity: float, peak: float) -> None:
    try:
        from shared.utils.discord_alerts import send_circuit_breaker_alert
        send_circuit_breaker_alert(cb_change["to"], equity, peak)
    except Exception as exc:
        logger.error(f"CB alert send failed: {exc}")


def _try_send_missed_scan_alert(model_version: str) -> None:
    try:
        from shared.utils.notification_router import route_alert, classify_alert_priority
        priority = classify_alert_priority("missed_scan")
        route_alert(
            f"⚠️ Missed scan detected — {model_version} — check system health.",
            alert_type="missed_scan",
            priority=priority,
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

def _fetch_market_context(watchlist: list[str]) -> dict:
    """
    Fetch all shared market-context data needed for modifier computation.

    Returns dict with keys:
      vix          — float (or None if fetch failed)
      smh_df       — pd.DataFrame OHLCV for SMH
      spy_df       — pd.DataFrame OHLCV for SPY
      tnx_series   — pd.Series of TNX Close prices
      dxy_series   — pd.Series of DXY Close prices
      ticker_ohlcv — dict[str, pd.DataFrame] for watchlist tickers only
    """
    import pandas as pd

    tickers_to_fetch = list(set(watchlist) | {"SMH", "SPY"})
    ohlcv_all = fetch_ohlcv_batch(tickers_to_fetch, period="3mo", interval="1d") or {}

    smh_df = ohlcv_all.get("SMH")
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
        "smh_df": smh_df,
        "spy_df": spy_df,
        "tnx_series": tnx_series,
        "dxy_series": dxy_series,
        "ticker_ohlcv": ticker_ohlcv,
    }


def _compute_regime_safe(
    vix: Optional[float],
    smh_df,
) -> str:
    """Classify market regime; falls back to 'choppy' on any error."""
    try:
        import pandas as pd
        if smh_df is None or (isinstance(smh_df, pd.DataFrame) and smh_df.empty):
            return "choppy"
        vix_val = float(vix) if vix is not None else 15.0
        return classify_regime(vix=vix_val, smh_ohlcv=smh_df)
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
        import pandas as pd
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


def _compute_rotation_safe(smh_df, spy_df) -> dict:
    """Compute sector rotation state; falls back to neutral on error."""
    try:
        import pandas as pd
        if smh_df is None or spy_df is None:
            return {"confidence_modifier": 0.0, "rotation_state": "neutral"}
        smh_close = smh_df["Close"] if isinstance(smh_df, pd.DataFrame) else smh_df
        spy_close = spy_df["Close"] if isinstance(spy_df, pd.DataFrame) else spy_df
        return compute_rotation_state(smh_close=smh_close, spy_close=spy_close)
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
        logger.warning(f"{ticker}: StockTwits fetch failed — {exc}")
        return []


def _fetch_reddit_safe(ticker: str) -> list[dict]:
    try:
        return fetch_reddit(ticker) or []
    except Exception as exc:
        logger.debug(f"{ticker}: Reddit fetch skipped — {exc}")
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


def _fetch_earnings_safe(ticker: str) -> Optional[dict]:
    try:
        return fetch_earnings_calendar(ticker)
    except Exception as exc:
        logger.warning(f"{ticker}: Earnings calendar fetch failed — {exc}")
        return None


def _get_insider_safe(ticker: str) -> dict:
    try:
        result = get_insider_signal(ticker)
        return result if isinstance(result, dict) else {"confidence_modifier": 0.0}
    except Exception as exc:
        logger.warning(f"{ticker}: Insider signal fetch failed — {exc}")
        return {"confidence_modifier": 0.0}


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
