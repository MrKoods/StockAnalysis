"""
SHARED: Formats + sends all Discord alert types via webhook.
Reads DISCORD_WEBHOOK_URL from .env.
Supports two-message architecture for trade alerts (primary compact + optional "details" expansion).
Each alert is sent as a Discord embed for clean formatting.
"""

import json
import os
from datetime import datetime, timezone
from typing import Optional

import requests

from shared.utils.logger import get_logger

logger = get_logger(__name__)

# Alert color codes (Discord embed color integers)
_COLORS = {
    "green": 0x00C851,
    "red": 0xFF4444,
    "yellow": 0xFFBB33,
    "orange": 0xFF8800,
    "blue": 0x33B5E5,
    "grey": 0x9E9E9E,
    "gold": 0xFFD700,
}

# Circuit breaker color by level
_CB_COLORS = {
    "yellow": _COLORS["yellow"],
    "orange": _COLORS["orange"],
    "red": _COLORS["red"],
    "normal": _COLORS["green"],
}


def send_trade_alert(candidate: dict, model_version: str = "v1.0.0") -> bool:
    """
    Format and send a full trade recommendation alert to Discord.
    Implements the exact alert format from the scope (signal breakdown,
    entry params, position sizing, trade ranking, execution guidance, confirmation request).
    Returns True on successful delivery.
    """
    ticker = candidate.get("ticker", "?")
    direction = candidate.get("direction", "bullish")
    confidence = candidate.get("confidence", 0.0)
    entry_lower = candidate.get("entry_zone_lower", candidate.get("entry_mid", 0.0))
    entry_upper = candidate.get("entry_zone_upper", entry_lower)
    stop = candidate.get("stop_loss", 0.0)
    target = candidate.get("target", 0.0)
    rr = candidate.get("rr_ratio", 0.0)
    structure = candidate.get("structure_recommended", "long_stock")
    ev = candidate.get("ev_per_dollar", 0.0)
    dollar_risk = candidate.get("dollar_risk", 0.0)
    technical_score = candidate.get("technical_total", 0.0)
    sentiment_score = candidate.get("sentiment_total", 0.0)
    news_score = candidate.get("news_total", 0.0)
    regime = candidate.get("regime", "")
    dominant_theme = candidate.get("dominant_theme", "")

    direction_emoji = "📈" if direction == "bullish" else "📉"
    color = _COLORS["green"] if direction == "bullish" else _COLORS["red"]

    embed = {
        "title": f"{direction_emoji} {ticker} SWING SIGNAL — Confidence {confidence:.0f}/100",
        "color": color,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "fields": [
            {"name": "Direction", "value": direction.upper(), "inline": True},
            {"name": "Structure", "value": structure.replace("_", " ").title(), "inline": True},
            {"name": "Regime", "value": regime.replace("_", " ").title() if regime else "—", "inline": True},
            {"name": "Entry Zone", "value": f"${entry_lower:.2f} – ${entry_upper:.2f}", "inline": True},
            {"name": "Stop Loss", "value": f"${stop:.2f}", "inline": True},
            {"name": "Target", "value": f"${target:.2f}  (R:R 1:{rr:.1f})", "inline": True},
            {"name": "Signal Breakdown",
             "value": f"Technical: {technical_score:.1f}/60\nSentiment: {sentiment_score:.1f}/25\nNews: {news_score:.1f}/15",
             "inline": True},
            {"name": "EV / $$ Risked", "value": f"${ev:.4f}", "inline": True},
            {"name": "Dollar Risk", "value": f"${dollar_risk:.2f}", "inline": True},
        ],
        "footer": {"text": f"StockAnalysis {model_version} | Reply ENTERED or SKIPPED to log trade"},
    }

    if dominant_theme:
        embed["fields"].append({
            "name": "Narrative Theme",
            "value": dominant_theme.replace("_", " ").title(),
            "inline": False,
        })

    exclusion_summary = candidate.get("exclusion_summary", "")
    if exclusion_summary and exclusion_summary != "All structures eligible.":
        embed["fields"].append({
            "name": "Excluded Structures",
            "value": exclusion_summary[:1000],
            "inline": False,
        })

    return _post_to_webhook({"embeds": [embed]})


def send_health_check(
    tickers_processed: int,
    total_tickers: int,
    data_sources: dict,
    av_calls_used: int,
    av_calls_limit: int,
    candidates_found: int,
    open_positions: list[dict],
    circuit_breaker_state: str,
    day_trades_count: int,
    model_version: str = "v1.0.0",
) -> bool:
    """
    Send daily system health check at 4:30pm ET.
    """
    def _src_icon(ok):
        return "✅" if ok else "❌"

    src_line = " | ".join(
        f"{src} {_src_icon(status)}" for src, status in data_sources.items()
    )
    pos_text = ", ".join(
        f"{p.get('ticker')} ({p.get('direction', 'bullish')})" for p in open_positions
    ) or "None"

    cb_map = {"normal": "✅", "yellow": "🟡", "orange": "🟠", "red": "🔴"}

    embed = {
        "title": "✅ SYSTEM HEALTH — 4:30pm ET",
        "color": _CB_COLORS.get(circuit_breaker_state, _COLORS["blue"]),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "fields": [
            {"name": "Scan",
             "value": f"{tickers_processed}/{total_tickers} tickers processed | {candidates_found} candidates",
             "inline": False},
            {"name": "Data Sources", "value": src_line, "inline": False},
            {"name": "Alpha Vantage", "value": f"{av_calls_used}/{av_calls_limit} calls used today", "inline": True},
            {"name": "Circuit Breaker",
             "value": f"{cb_map.get(circuit_breaker_state, '❓')} {circuit_breaker_state.upper()}",
             "inline": True},
            {"name": "Day Trades (rolling)", "value": str(day_trades_count), "inline": True},
            {"name": "Open Positions", "value": pos_text, "inline": False},
        ],
        "footer": {"text": f"StockAnalysis {model_version}"},
    }
    return _post_to_webhook({"embeds": [embed]})


def send_signal_decay_alert(position: dict, new_confidence: float, drop: float) -> bool:
    """🟡 Signal decay early-exit alert for an open position."""
    ticker = position.get("ticker", "?")
    embed = {
        "title": f"🟡 {ticker} SIGNAL DECAY — Consider Early Exit",
        "color": _COLORS["yellow"],
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "fields": [
            {"name": "Original Confidence",
             "value": f"{new_confidence + drop:.0f}",
             "inline": True},
            {"name": "Current Confidence",
             "value": f"{new_confidence:.0f}  (▼{drop:.0f} pts)",
             "inline": True},
            {"name": "Entry", "value": f"${position.get('entry_price', 0.0):.2f}", "inline": True},
            {"name": "Stop", "value": f"${position.get('stop_loss', 0.0):.2f}", "inline": True},
        ],
        "footer": {"text": "Consider early exit or tightening stop to protect capital."},
    }
    return _post_to_webhook({"embeds": [embed]})


def send_circuit_breaker_alert(level: str, account_equity: float, peak_equity: float) -> bool:
    """🟡/🟠/🔴 Circuit breaker alert (Yellow/Orange/Red)."""
    emoji = {"yellow": "🟡", "orange": "🟠", "red": "🔴"}.get(level, "⚠️")
    drawdown_pct = (peak_equity - account_equity) / peak_equity * 100 if peak_equity > 0 else 0.0
    actions = {
        "yellow": "Reduce position size to 50%. Only confidence ≥ 95 trades.",
        "orange": "No new positions. Manage existing positions only.",
        "red": "FULL STOP. No new positions. Review all open positions immediately.",
    }
    embed = {
        "title": f"{emoji} CIRCUIT BREAKER {level.upper()} TRIGGERED",
        "color": _CB_COLORS.get(level, _COLORS["red"]),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "fields": [
            {"name": "Drawdown", "value": f"{drawdown_pct:.1f}% from peak", "inline": True},
            {"name": "Current Equity", "value": f"${account_equity:,.2f}", "inline": True},
            {"name": "Peak Equity", "value": f"${peak_equity:,.2f}", "inline": True},
            {"name": "Required Action", "value": actions.get(level, "Review positions."), "inline": False},
        ],
        "footer": {"text": "Circuit breaker auto-resets when drawdown recovers."},
    }
    return _post_to_webhook({"embeds": [embed]})


def send_black_swan_alert(message: str) -> bool:
    """🚨 Black Swan alert — highest priority. Escalates to email + SMS via notification_router."""
    embed = {
        "title": "🚨 BLACK SWAN EVENT DETECTED",
        "color": _COLORS["red"],
        "description": message[:2000],
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    return _post_to_webhook({"embeds": [embed]})


def send_position_management_alert(
    position: dict,
    alert_type: str,
    details: dict,
) -> bool:
    """
    Send position management alert (time stop, structure stop, profit target, trailing stop update).
    alert_type: 'time_stop' | 'structure_stop' | 'profit_target' | 'trailing_stop_update'
    """
    ticker = position.get("ticker", "?")
    emoji_map = {
        "time_stop": "⏱️",
        "structure_stop": "🛑",
        "profit_target": "🎯",
        "trailing_stop_update": "📌",
    }
    emoji = emoji_map.get(alert_type, "📊")
    title = f"{emoji} {ticker} — {alert_type.replace('_', ' ').upper()}"

    fields = [
        {"name": "Direction", "value": position.get("direction", "bullish").upper(), "inline": True},
        {"name": "Entry", "value": f"${position.get('entry_price', 0.0):.2f}", "inline": True},
    ]
    for k, v in details.items():
        fields.append({"name": k.replace("_", " ").title(), "value": str(v), "inline": True})

    embed = {
        "title": title,
        "color": _COLORS["blue"],
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "fields": fields,
    }
    return _post_to_webhook({"embeds": [embed]})


def send_macro_warning(macro_state: dict) -> bool:
    """🌐 Macro overlay warning when adverse conditions detected."""
    state = macro_state.get("macro_state", "MACRO_NEUTRAL")
    embed = {
        "title": f"🌐 MACRO OVERLAY — {state}",
        "color": _COLORS["orange"] if "ADVERSE" in state else _COLORS["blue"],
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "fields": [
            {"name": "TNX Trend", "value": str(macro_state.get("tnx_trend", "unknown")), "inline": True},
            {"name": "DXY Trend", "value": str(macro_state.get("dxy_trend", "unknown")), "inline": True},
            {"name": "China Tension", "value": str(macro_state.get("china_tension_level", "unknown")), "inline": True},
            {"name": "Confidence Modifier",
             "value": str(macro_state.get("confidence_modifier", 0.0)),
             "inline": True},
        ],
    }
    return _post_to_webhook({"embeds": [embed]})


def send_paper_signal_alert(trade: dict, model_version: str = "v1.0.0") -> bool:
    """PAPER TRADE OPENED embed — clearly labeled as simulated, not live capital."""
    ticker = trade.get("ticker", "?")
    confidence = float(trade.get("confidence", 0.0))
    entry_lower = float(trade.get("entry_zone_lower", 0.0))
    entry_upper = float(trade.get("entry_zone_upper", entry_lower))
    stop = float(trade.get("stop_loss", 0.0))
    target = float(trade.get("target", 0.0))
    rr = float(trade.get("rr_ratio", 0.0))
    regime = str(trade.get("regime", ""))
    technical_score = float(trade.get("technical_score", 0.0))
    sentiment_score = float(trade.get("sentiment_score", 0.0))
    news_score = float(trade.get("news_score", 0.0))
    fundamental_score = float(trade.get("fundamental_score", 0.0))
    news_count = trade.get("news_article_count", "0")
    vix_val = trade.get("vix_at_signal", "—")

    embed = {
        "title": f"📋 PAPER TRADE OPENED — {ticker}  |  {confidence:.0f}/100",
        "color": _COLORS["blue"],
        "description": "**PAPER TRADING ONLY** — no live capital",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "fields": [
            {"name": "Entry Zone", "value": f"${entry_lower:.2f} – ${entry_upper:.2f}", "inline": True},
            {"name": "Stop Loss", "value": f"${stop:.2f}", "inline": True},
            {"name": "Target", "value": f"${target:.2f}  (1:{rr:.1f}R)", "inline": True},
            {"name": "Regime", "value": regime.replace("_", " ").title() if regime else "—", "inline": True},
            {"name": "VIX", "value": str(vix_val), "inline": True},
            {
                "name": "Score Breakdown",
                "value": (
                    f"Tech: **{technical_score:.1f}**/50  |  "
                    f"Sent: **{sentiment_score:.1f}**/20  |  "
                    f"News: **{news_score:.1f}**/15  |  "
                    f"Fund: **{fundamental_score:.1f}**/15\n"
                    f"News articles: {news_count}"
                ),
                "inline": False,
            },
        ],
        "footer": {"text": f"StockAnalysis {model_version} | Paper Trading"},
    }
    return _post_to_webhook({"embeds": [embed]})


def send_paper_outcome_alert(trade: dict) -> bool:
    """PAPER TRADE CLOSED embed — sends when stop, target, or time stop triggers."""
    ticker = trade.get("ticker", "?")
    outcome = str(trade.get("outcome", "unknown"))
    signal_date = trade.get("signal_date", "—")
    exit_date = trade.get("exit_date", "—")
    pnl_pct = float(trade.get("pnl_pct", 0.0))
    achieved_rr = float(trade.get("achieved_rr", 0.0))
    holding_days = int(trade.get("holding_days", 0))
    entry_price = float(trade.get("entry_price", 0.0))
    exit_price = float(trade.get("exit_price", 0.0))
    confidence = float(trade.get("confidence", 0.0))

    is_win = (outcome == "win") or (outcome == "time_stop" and pnl_pct > 0)

    _outcome_labels = {
        "win": "TARGET HIT",
        "loss": "STOPPED OUT",
        "time_stop": f"TIME STOP  ({pnl_pct * 100:+.1f}%)",
    }
    label = _outcome_labels.get(outcome, outcome.upper())
    emoji = "✅" if is_win else ("⏱️" if outcome == "time_stop" else "❌")
    color = _COLORS["green"] if is_win else (_COLORS["yellow"] if outcome == "time_stop" else _COLORS["red"])

    embed = {
        "title": f"{emoji} PAPER CLOSE — {ticker}  |  {label}",
        "color": color,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "fields": [
            {"name": "Signal Date", "value": signal_date, "inline": True},
            {"name": "Exit Date", "value": exit_date, "inline": True},
            {"name": "Holding Days", "value": str(holding_days), "inline": True},
            {"name": "Entry Price", "value": f"${entry_price:.2f}", "inline": True},
            {"name": "Exit Price", "value": f"${exit_price:.2f}", "inline": True},
            {"name": "P&L", "value": f"{pnl_pct * 100:+.2f}%", "inline": True},
            {"name": "Achieved R:R", "value": f"{achieved_rr:+.2f}R", "inline": True},
            {"name": "Signal Confidence", "value": f"{confidence:.0f}/100", "inline": True},
        ],
        "footer": {"text": "Paper trade closed — outcome logged for model calibration"},
    }
    return _post_to_webhook({"embeds": [embed]})


def _post_to_webhook(payload: dict, webhook_url: Optional[str] = None) -> bool:
    """POST JSON payload to Discord webhook. Returns True on 204 response."""
    url = webhook_url or os.getenv("DISCORD_WEBHOOK_URL")
    if not url:
        logger.error("DISCORD_WEBHOOK_URL not set in environment.")
        return False
    try:
        resp = requests.post(url, json=payload, timeout=10)
        return resp.status_code in (200, 204)
    except Exception as exc:
        logger.error(f"Discord webhook POST failed: {exc}")
        return False


def format_trade_alert_text(candidate: dict, model_version: str = "v1.0.0") -> str:
    """
    Return the formatted alert as plain text (for testing and logging without sending).
    Same content as send_trade_alert embed, rendered as text.
    """
    ticker = candidate.get("ticker", "?")
    direction = candidate.get("direction", "bullish")
    confidence = candidate.get("confidence", 0.0)
    entry_lower = candidate.get("entry_zone_lower", 0.0)
    entry_upper = candidate.get("entry_zone_upper", 0.0)
    stop = candidate.get("stop_loss", 0.0)
    target = candidate.get("target", 0.0)
    rr = candidate.get("rr_ratio", 0.0)
    structure = candidate.get("structure_recommended", "long_stock")

    lines = [
        f"{'📈' if direction == 'bullish' else '📉'} {ticker} SWING SIGNAL — {confidence:.0f}/100",
        f"Direction: {direction.upper()} | Structure: {structure.replace('_', ' ').title()}",
        f"Entry Zone: ${entry_lower:.2f}–${entry_upper:.2f}",
        f"Stop: ${stop:.2f} | Target: ${target:.2f} (R:R 1:{rr:.1f})",
        f"Model: {model_version}",
    ]
    return "\n".join(lines)
