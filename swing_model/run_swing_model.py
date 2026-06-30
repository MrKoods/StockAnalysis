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

logger = get_logger(__name__)


def main(scan_type: str = "post_close") -> None:
    """
    Main entry point for a single scan run.

    Steps:
    1. Load config + model version from CHANGELOG.md
    2. Check for missed previous scan (audit_log.csv)
    3. Load portfolio state (position_state.json)
    4. Run data validation + indicator pipeline for all tickers
    5. Run sentiment + news layers
    6. Run macro overlay + regime detection
    7. Score each ticker
    8. Evaluate trade structures for candidates meeting threshold
    9. Re-score open positions (signal decay)
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

    # If cb changed, fire Discord alert
    if "_cb_state_changed" in state:
        _try_send_cb_alert(state["_cb_state_changed"], state["account_equity"], state["peak_equity"])
        del state["_cb_state_changed"]

    if cb_state == "red":
        logger.warning("RED circuit breaker active — no new signals")

    # Step 4-9: Pipeline run for each ticker
    tickers_processed = 0
    candidates = []
    watchlist = cfg.get("watchlist", ["NVDA", "AMD", "AVGO", "TSM", "MU", "ASML"])
    data_sources = {"yfinance": True, "StockTwits": True, "Reddit": True, "Alpha Vantage": True}

    for ticker in watchlist:
        try:
            result = run_pipeline(ticker, cfg=cfg)
            if result is None:
                continue
            tickers_processed += 1

            score_data = result.get("score", {})
            final_score = float(score_data.get("final_score", 0.0))

            write_audit_entry({
                "model_version": model_version,
                "scan_type": scan_type,
                "ticker": ticker,
                "technical_score": score_data.get("technical_total", 0.0),
                "sentiment_score": score_data.get("sentiment_total", 0.0),
                "news_score": score_data.get("news_total", 0.0),
                "base_score": score_data.get("base_score", 0.0),
                "regime_modifier": score_data.get("regime_modifier", 0.0),
                "sector_rotation_modifier": score_data.get("sector_rotation_modifier", 0.0),
                "earnings_modifier": score_data.get("earnings_modifier", 0.0),
                "cross_ticker_modifier": score_data.get("cross_ticker_modifier", 0.0),
                "insider_modifier": score_data.get("insider_modifier", 0.0),
                "seasonality_modifier": score_data.get("seasonality_modifier", 0.0),
                "macro_modifier": score_data.get("macro_modifier", 0.0),
                "final_score": final_score,
                "signal_surfaced": final_score >= 90,
                "direction": result.get("direction", ""),
                "structure_recommended": result.get("structure_recommended", ""),
                "ev_per_dollar": result.get("ev_per_dollar", ""),
                "rr_ratio": result.get("rr_ratio", ""),
                "entry_lower": result.get("entry_zone_lower", ""),
                "entry_upper": result.get("entry_zone_upper", ""),
                "stop_loss": result.get("stop_loss", ""),
                "target": result.get("target", ""),
                "notes": result.get("notes", ""),
            })

            if final_score >= 90 and cb_state not in ("orange", "red"):
                allowed, reason = can_open_new_position(state, {
                    "ticker": ticker,
                    "direction": result.get("direction", "bullish"),
                    "confidence": final_score,
                    "risk_pct": result.get("risk_pct", 0.01),
                })
                if allowed:
                    candidate = {**result, **score_data, "ticker": ticker, "confidence": final_score}
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
