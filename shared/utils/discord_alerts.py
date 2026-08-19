"""
SHARED: Formats + sends all Discord alert types via webhook.
Reads DISCORD_WEBHOOK_URL from .env.
Supports two-message architecture for trade alerts (primary compact + optional "details" expansion).
Each alert is sent as a Discord embed for clean formatting.
"""

import os
from datetime import datetime, timezone
from typing import Optional

import requests

from shared.utils.logger import get_logger
from swing_model.scoring import CONFIDENCE_THRESHOLD

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


def _extract_score_breakdown(d: dict) -> dict:
    """
    Pull the five category scores + their (possibly calibration-reweighted)
    maxes from a score/candidate dict, tolerating both naming conventions
    this project uses for the same data: scoring.py's own
    compute_confidence_score() output uses "_total" suffixes
    (technical_total, sentiment_total, ...) — send_trade_alert's candidate
    dict is {**score, ...} straight from there. paper_runner.py's payloads
    (used by send_paper_signal_alert/send_near_miss_alert) instead remap to
    "_score" suffixes (technical_score, sentiment_score, ...) before handing
    off. Checking both, rather than each caller hardcoding one, means a
    caller passed the "other" dict shape gets the real score instead of a
    silently wrong 0.0 default — each of the three send_*_alert functions
    used to read only its own caller's convention.
    """
    def _get(total_key: str, score_key: str) -> float:
        if total_key in d:
            return float(d.get(total_key, 0.0))
        return float(d.get(score_key, 0.0))

    return {
        "technical_score": _get("technical_total", "technical_score"),
        "technical_max": float(d.get("technical_max", 40.0)),
        "positioning_score": _get("positioning_total", "positioning_score"),
        "sentiment_score": _get("sentiment_total", "sentiment_score"),
        "sentiment_max": float(d.get("sentiment_max", 15.0)),
        "news_score": _get("news_total", "news_score"),
        "news_max": float(d.get("news_max", 15.0)),
        "fundamental_score": float(d.get("fundamental_score", 0.0)),
    }


def _format_score_breakdown(d: dict, style: str = "bold") -> str:
    """
    Render the standard 5-category score breakdown used by
    send_trade_alert/send_paper_signal_alert/send_near_miss_alert — all
    three built the identical string by hand before this existed.

    style="bold": Discord bold markdown, one "|"-joined line (paper-signal /
    near-miss embeds). style="plain": no bold, one category per line
    (send_trade_alert's original "Signal Breakdown" field style).
    """
    s = _extract_score_breakdown(d)
    if style == "plain":
        return (
            f"Technical: {s['technical_score']:.1f}/{s['technical_max']:.0f}\n"
            f"Positioning: {s['positioning_score']:.1f}/20\n"
            f"Sentiment: {s['sentiment_score']:.1f}/{s['sentiment_max']:.0f}\n"
            f"News: {s['news_score']:.1f}/{s['news_max']:.0f}\n"
            f"Fundamental: {s['fundamental_score']:.1f}/10"
        )
    return (
        f"Tech: **{s['technical_score']:.1f}**/{s['technical_max']:.0f}  |  "
        f"Pos: **{s['positioning_score']:.1f}**/20  |  "
        f"Sent: **{s['sentiment_score']:.1f}**/{s['sentiment_max']:.0f}  |  "
        f"News: **{s['news_score']:.1f}**/{s['news_max']:.0f}  |  "
        f"Fund: **{s['fundamental_score']:.1f}**/10"
    )


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
    regime = candidate.get("regime", "")
    dominant_theme = candidate.get("dominant_theme", "")
    # See paper_runner.py/send_paper_signal_alert's matching comment — these
    # were already computed by rank_trade_structures() for this exact pick
    # and previously discarded before reaching this alert.
    capital_required = candidate.get("capital_required")
    structure_legs = candidate.get("structure_legs")
    structure_effective_days = candidate.get("structure_effective_days")
    structure_greeks_summary = candidate.get("structure_greeks_summary")
    structure_max_loss = candidate.get("structure_max_loss")
    structure_max_gain = candidate.get("structure_max_gain")
    structure_strikes = candidate.get("structure_strikes")
    structure_expiration_date = candidate.get("structure_expiration_date")
    alternative_structures = candidate.get("alternative_structures")

    direction_emoji = "📈" if direction == "bullish" else "📉"
    event_gate_blocked = bool(candidate.get("event_gate_blocked"))
    color = _COLORS["orange"] if event_gate_blocked else (
        _COLORS["green"] if direction == "bullish" else _COLORS["red"]
    )
    title_prefix = "⚠️ [ACTIVE EVENT] " if event_gate_blocked else ""

    embed = {
        "title": f"{title_prefix}{direction_emoji} {ticker} SWING SIGNAL — Confidence {confidence:.0f}/100",
        "color": color,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "fields": [
            {"name": "Direction", "value": direction.upper(), "inline": True},
            {"name": "Structure", "value": structure.replace("_", " ").title(), "inline": True},
            {"name": "Regime", "value": regime.replace("_", " ").title() if regime else "—", "inline": True},
            {"name": "Entry Zone", "value": f"${entry_lower:.2f} – ${entry_upper:.2f}", "inline": True},
            {"name": "Stop Loss", "value": f"${stop:.2f}", "inline": True},
            {"name": "Target", "value": f"${target:.2f}  (R:R 1:{rr:.1f})", "inline": True},
            {"name": "Signal Breakdown", "value": _format_score_breakdown(candidate, style="plain"), "inline": True},
            {"name": "EV / $$ Risked", "value": f"${ev:.4f}", "inline": True},
            {"name": "Dollar Risk", "value": f"${dollar_risk:.2f}", "inline": True},
        ],
        "footer": {"text": f"StockAnalysis {model_version} | Reply ENTERED or SKIPPED to log trade"},
    }

    econ_parts = []
    if capital_required is not None:
        try:
            econ_parts.append(f"Capital Required: ${float(capital_required):.2f}")
        except (TypeError, ValueError):
            pass
    if structure_legs:
        econ_parts.append(f"Legs: {structure_legs}")
    if structure_effective_days:
        econ_parts.append(f"Effective Days: {structure_effective_days}")
    if structure_expiration_date:
        econ_parts.append(f"Expiration: {structure_expiration_date}")
    if structure_max_loss:
        econ_parts.append(f"Max Loss: ${structure_max_loss}")
    if structure_max_gain:
        econ_parts.append(f"Max Gain: ${structure_max_gain}")
    elif structure_max_loss:
        econ_parts.append("Max Gain: unlimited")
    if econ_parts:
        embed["fields"].append({
            "name": "Structure Economics",
            "value": "  |  ".join(econ_parts),
            "inline": False,
        })
    if structure_strikes:
        embed["fields"].append({
            "name": "Strikes",
            "value": structure_strikes,
            "inline": False,
        })
    if structure_greeks_summary:
        embed["fields"].append({
            "name": "Net Greeks",
            "value": structure_greeks_summary,
            "inline": False,
        })
    if alternative_structures:
        embed["fields"].append({
            "name": "Alternatives",
            "value": str(alternative_structures)[:1000],
            "inline": False,
        })

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

    if event_gate_blocked:
        embed["fields"].append({
            "name": "⚠️ Active Event — Review Before Trading",
            "value": (
                f"Trigger: {candidate.get('event_gate_trigger', 'unknown')}\n"
                f"This signal still qualifies on score alone, but a critical news "
                f"event is active for this ticker. Use your own judgment."
            ),
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


def send_calibration_alert(result: dict) -> bool:
    """
    🟡 Feedback-loop calibration pass needs human attention — either it failed
    its out-of-sample holdout check (weights unchanged) or it passed but a
    weight moved >5pp, which this project's own rule requires a version bump
    + re-backtest for before it can be applied (see
    swing_model.feedback_loop.run_calibration/model_versioning.check_backtest_required).
    Matches feedback_loop.py's own module docstring intent ("if failing:
    Discord alert + keep old weights"), not previously implemented anywhere.
    """
    status = result.get("status", "unknown")
    needs_version = bool(result.get("needs_version_increment"))

    if status == "pass" and needs_version:
        title = "🟡 CALIBRATION PASSED — Version Bump Required Before Applying"
        footer = "Weight change exceeds 5pp. Bump model version + re-backtest before applying (see CHANGELOG.md rule)."
    else:
        title = "🟡 CALIBRATION FAILED HOLDOUT — Weights Unchanged"
        footer = "New weights did not beat the current weights on held-out trades. Kept existing weights."

    current = result.get("current_weights", {})
    new = result.get("new_weights", {})
    embed = {
        "title": title,
        "color": _COLORS["yellow"],
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "fields": [
            {"name": "Status", "value": status, "inline": True},
            {"name": "Train / Holdout", "value": f"{result.get('train_count', '?')} / {result.get('holdout_count', '?')}", "inline": True},
            {"name": "Holdout score (old → new)",
             "value": f"{result.get('holdout_win_rate_old', 0.0):.3f} → {result.get('holdout_win_rate_new', 0.0):.3f}",
             "inline": True},
            {"name": "Current weights", "value": str(current) or "n/a", "inline": False},
            {"name": "Proposed weights", "value": str(new) or "n/a", "inline": False},
        ],
        "footer": {"text": footer},
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
    """🚨 Black Swan alert — highest priority. Discord is the only delivery
    channel (see notification_router.py's own docstring — email/SMS were
    removed project-wide in v2.2.1); this used to claim an email/SMS escalation
    that was never actually implemented."""
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


def send_event_gate_triggered_alert(
    block: dict,
    open_positions_affected: Optional[list[dict]] = None,
    model_version: str = "v1.0.0",
) -> bool:
    """
    🚨 EVENT_GATE_TRIGGERED — critical, thesis-opposed news has vetoed new signal
    surfacing for one ticker (ticker scope) or the entire watchlist (sector scope).
    """
    tickers = block.get("tickers", [])
    scope = block.get("scope", "ticker")
    open_positions_affected = open_positions_affected or []

    # The embed's own "timestamp" field (rendered by Discord as "X ago") only
    # reflects when we detected/posted this — not when the underlying news
    # actually happened. Detection only runs when a scan fires (pre-market/
    # mid-session/post-close), so a story that breaks between scans can sit
    # undetected for hours before it's caught and posted here looking
    # deceptively "fresh." Surface the real article time and the resulting
    # lag explicitly so that's never hidden.
    event_ts_str = block.get("event_timestamp_utc")
    detected_lag_value = "—"
    if event_ts_str:
        try:
            event_dt = datetime.fromisoformat(event_ts_str)
            lag = datetime.now(timezone.utc) - event_dt
            hours = lag.total_seconds() / 3600
            detected_lag_value = f"{hours:.1f} hr" if hours >= 1 else f"{lag.total_seconds() / 60:.0f} min"
        except ValueError:
            pass

    embed = {
        "title": f"🚨 EVENT SEVERITY GATE TRIGGERED — {scope.upper()} BLOCK",
        "color": _COLORS["red"],
        "description": block.get("trigger_headline", "")[:2000],
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "fields": [
            {"name": "Blocked Tickers", "value": ", ".join(tickers) or "—", "inline": False},
            {"name": "Trigger Match", "value": block.get("trigger_match", "—"), "inline": True},
            {"name": "Source", "value": block.get("source", "—"), "inline": True},
            {"name": "Expiry Condition", "value": block.get("expiry_condition", "next_post_close_scan"), "inline": True},
            {"name": "Actual Event Time", "value": event_ts_str or "unknown", "inline": True},
            {"name": "Detection Lag", "value": detected_lag_value, "inline": True},
            {
                "name": "Open Positions Affected",
                "value": ", ".join(p.get("ticker", "?") for p in open_positions_affected) or "None",
                "inline": False,
            },
        ],
        "footer": {"text": f"StockAnalysis {model_version} | New signals suppressed until cooling-off completes"},
    }
    return _post_to_webhook({"embeds": [embed]})


def send_event_gate_expired_alert(block: dict, model_version: str = "v1.0.0") -> bool:
    """ℹ️ EVENT_GATE_EXPIRED — cooling-off complete (a post-close scan ran after the
    event); the ticker(s) surface normally again on the next qualifying score."""
    tickers = block.get("tickers", [])
    embed = {
        "title": f"ℹ️ EVENT GATE EXPIRED — {', '.join(tickers) or '—'}",
        "color": _COLORS["grey"],
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "fields": [
            {"name": "Trigger Match", "value": block.get("trigger_match", "—"), "inline": True},
            {"name": "Scope", "value": block.get("scope", "—"), "inline": True},
            {"name": "Blocked Since", "value": block.get("created_at_utc", "—"), "inline": True},
        ],
        "footer": {"text": f"StockAnalysis {model_version} | Post-close scan completed after event — normal scoring resumed"},
    }
    return _post_to_webhook({"embeds": [embed]})


def send_paper_signal_alert(trade: dict, model_version: str = "v1.0.0") -> bool:
    """
    PAPER TRADE PENDING embed — sent when a signal is logged, before price has
    necessarily traded into its entry zone. entry_zone_lower/upper is a
    breakout/breakdown trigger (see risk_reward.compute_entry_zone), often
    anchored above/below the current close — this is a conditional order, not
    a filled position. paper_updater.py's send_paper_fill_alert is the
    "actually opened" counterpart, sent once price confirms the fill.
    """
    ticker = trade.get("ticker", "?")
    confidence = float(trade.get("confidence", 0.0))
    entry_lower = float(trade.get("entry_zone_lower", 0.0))
    entry_upper = float(trade.get("entry_zone_upper", entry_lower))
    stop = float(trade.get("stop_loss", 0.0))
    target = float(trade.get("target", 0.0))
    rr = float(trade.get("rr_ratio", 0.0))
    regime = str(trade.get("regime", ""))
    news_count = trade.get("news_article_count", "0")
    vix_val = trade.get("vix_at_signal", "—")
    event_gate_blocked = bool(trade.get("event_gate_blocked"))
    title_prefix = "⚠️ [ACTIVE EVENT] " if event_gate_blocked else ""

    # Structure/position fields: previously computed and persisted to
    # paper_trades.csv but never surfaced here, so a Discord alert could only
    # ever say a signal fired and what it scored — not what trade it actually
    # became, or whether it became a real trade at all (a 0-size row looked
    # identical here to a fully-deployed one). structure_recommended/
    # position_type/position_size/capital_deployed/sizing_note are all
    # already on the row dict paper_runner.py passes in — see its
    # sizing_note comment for why that field exists at all.
    structure = str(trade.get("structure_recommended", "") or "")
    position_type = str(trade.get("position_type", "") or "")
    position_size = trade.get("position_size", "0")
    capital_deployed = float(trade.get("capital_deployed", 0.0) or 0.0)
    sizing_note = str(trade.get("sizing_note", "") or "")
    # capital_required/legs/effective_days/greeks: computed by
    # rank_trade_structures() for the winning structure but previously
    # dropped before reaching this alert — see paper_runner.py's row dict
    # comment for where these are extracted.
    capital_required_raw = trade.get("capital_required", "")
    structure_legs = str(trade.get("structure_legs", "") or "")
    structure_effective_days = str(trade.get("structure_effective_days", "") or "")
    structure_greeks_summary = str(trade.get("structure_greeks_summary", "") or "")
    # max_loss/max_gain/strikes/expiration_date/alternatives: same pattern,
    # computed by rank_trade_structures()/resolve_structure_economics() and
    # previously dropped before reaching this alert.
    structure_max_loss = str(trade.get("structure_max_loss", "") or "")
    structure_max_gain = str(trade.get("structure_max_gain", "") or "")
    structure_strikes = str(trade.get("structure_strikes", "") or "")
    structure_expiration_date = str(trade.get("structure_expiration_date", "") or "")
    alternative_structures = str(trade.get("alternative_structures", "") or "")
    unit = "options contract" if position_type == "options" else "share"
    try:
        size_int = int(float(position_size))
    except (TypeError, ValueError):
        size_int = 0
    position_value = f"{size_int} {unit}{'s' if size_int != 1 else ''}" if position_type else "—"

    embed = {
        "title": f"{title_prefix}⏳ PAPER TRADE PENDING — {ticker}  |  {confidence:.0f}/100",
        "color": _COLORS["orange"] if event_gate_blocked else _COLORS["blue"],
        "description": "**PAPER TRADING ONLY** — no live capital. Conditional order — opens once price trades into the entry zone below.",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "fields": [
            {"name": "Entry Zone (trigger)", "value": f"${entry_lower:.2f} – ${entry_upper:.2f}", "inline": True},
            {"name": "Stop Loss", "value": f"${stop:.2f}", "inline": True},
            {"name": "Target", "value": f"${target:.2f}  (1:{rr:.1f}R)", "inline": True},
            {"name": "Trade Structure", "value": structure.replace("_", " ").title() if structure else "—", "inline": True},
            {"name": "Position", "value": position_value, "inline": True},
            {"name": "Capital Deployed", "value": f"${capital_deployed:.2f}", "inline": True},
            {"name": "Regime", "value": regime.replace("_", " ").title() if regime else "—", "inline": True},
            {"name": "VIX", "value": str(vix_val), "inline": True},
            {
                "name": "Score Breakdown",
                "value": f"{_format_score_breakdown(trade, style='bold')}\nNews articles: {news_count}",
                "inline": False,
            },
        ],
        "footer": {"text": f"StockAnalysis {model_version} | Paper Trading"},
    }

    # Structure economics rank_trade_structures() already computed for this
    # exact pick — capital_required is the structure's own theoretical risk
    # (distinct from capital_deployed above, the post-sizing actual amount);
    # legs/effective_days/Greeks previously never left trade_selector.py.
    if structure:
        try:
            capital_required_val = float(capital_required_raw) if capital_required_raw else None
        except (TypeError, ValueError):
            capital_required_val = None
        econ_parts = []
        if capital_required_val is not None:
            econ_parts.append(f"Capital Required: ${capital_required_val:.2f}")
        if structure_legs:
            econ_parts.append(f"Legs: {structure_legs}")
        if structure_effective_days:
            econ_parts.append(f"Effective Days: {structure_effective_days}")
        if structure_expiration_date:
            econ_parts.append(f"Expiration: {structure_expiration_date}")
        if structure_max_loss:
            econ_parts.append(f"Max Loss: ${structure_max_loss}")
        if structure_max_gain:
            econ_parts.append(f"Max Gain: ${structure_max_gain}")
        elif structure_max_loss:
            # Max loss populated but max gain absent means genuinely
            # unbounded (never fabricated — see resolve_structure_economics'
            # own per-branch comments in options_math.py), worth saying
            # explicitly rather than just omitting the field silently.
            econ_parts.append("Max Gain: unlimited")
        if econ_parts:
            embed["fields"].append({
                "name": "Structure Economics",
                "value": "  |  ".join(econ_parts),
                "inline": False,
            })
        if structure_strikes:
            embed["fields"].append({
                "name": "Strikes",
                "value": structure_strikes,
                "inline": False,
            })
        if structure_greeks_summary:
            embed["fields"].append({
                "name": "Net Greeks",
                "value": structure_greeks_summary,
                "inline": False,
            })
        if alternative_structures:
            embed["fields"].append({
                "name": "Alternatives",
                "value": alternative_structures[:1000],
                "inline": False,
            })

    if sizing_note:
        embed["fields"].append({
            "name": "⚠️ Sizing Note" if size_int == 0 else "Sizing Note",
            "value": sizing_note[:1000],
            "inline": False,
        })

    if event_gate_blocked:
        embed["fields"].append({
            "name": "⚠️ Active Event — Review Before Trading",
            "value": (
                f"Trigger: {trade.get('event_gate_trigger', 'unknown')}\n"
                f"This signal still qualifies on score alone, but a critical news "
                f"event is active for this ticker. Use your own judgment."
            ),
            "inline": False,
        })

    return _post_to_webhook({"embeds": [embed]})


def send_paper_fill_alert(trade: dict, fill_price: float, fill_date: str) -> bool:
    """
    PAPER TRADE OPENED embed — the send_paper_signal_alert "pending" order's
    counterpart, sent once paper_updater.py's _find_fill confirms price
    actually traded into the entry zone. Sent exactly once per trade, at the
    pending → filled transition (caller only invokes this the first time
    trade["fill_date"] gets set — see paper_updater.py).
    """
    ticker = trade.get("ticker", "?")
    signal_date = trade.get("signal_date", "—")
    stop = float(trade.get("stop_loss", 0.0))
    target = float(trade.get("target", 0.0))
    rr = float(trade.get("rr_ratio", 0.0))
    confidence = float(trade.get("confidence", 0.0))
    position_type = str(trade.get("position_type", "") or "")
    position_size = trade.get("position_size", "0")
    capital_deployed = float(trade.get("capital_deployed", 0.0) or 0.0)
    unit = "options contract" if position_type == "options" else "share"
    try:
        size_int = int(float(position_size))
    except (TypeError, ValueError):
        size_int = 0
    position_value = f"{size_int} {unit}{'s' if size_int != 1 else ''}" if position_type else "—"

    embed = {
        "title": f"✅ PAPER TRADE OPENED — {ticker}  |  {confidence:.0f}/100",
        "color": _COLORS["green"],
        "description": "**PAPER TRADING ONLY** — no live capital. Entry zone reached — stop/target tracking is now active.",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "fields": [
            {"name": "Signal Date", "value": signal_date, "inline": True},
            {"name": "Fill Date", "value": fill_date, "inline": True},
            {"name": "Fill Price", "value": f"${fill_price:.2f}", "inline": True},
            {"name": "Stop Loss", "value": f"${stop:.2f}", "inline": True},
            {"name": "Target", "value": f"${target:.2f}  (1:{rr:.1f}R)", "inline": True},
            {"name": "Position", "value": position_value, "inline": True},
            {"name": "Capital Deployed", "value": f"${capital_deployed:.2f}", "inline": True},
        ],
        "footer": {"text": "Order filled — position now open"},
    }
    return _post_to_webhook({"embeds": [embed]})


def send_near_miss_alert(candidate: dict, model_version: str = "v1.0.0") -> bool:
    """
    Lower-priority awareness ping for a ticker that scored close to but below
    CONFIDENCE_THRESHOLD — NOT a trade signal, no entry/stop/target (those
    are never computed for sub-threshold tickers). Deliberately low-key
    styling (grey, no "SIGNAL"/"TRADE" language) so it can't be mistaken for
    an actual recommendation or dilute the weight of a real one.
    """
    ticker = candidate.get("ticker", "?")
    confidence = float(candidate.get("confidence", 0.0))
    direction = str(candidate.get("direction", "bullish"))
    regime = str(candidate.get("regime", ""))
    total_modifier = float(candidate.get("total_modifier", 0.0))

    embed = {
        "title": f"👀 Near miss — {ticker} — {confidence:.0f}/100 (needs {CONFIDENCE_THRESHOLD:.0f})",
        "color": _COLORS["grey"],
        "description": "Not a trade signal — awareness only, below threshold",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "fields": [
            {"name": "Direction", "value": direction.title(), "inline": True},
            {"name": "Regime", "value": regime.replace("_", " ").title() if regime else "—", "inline": True},
            {"name": "Modifiers (total)", "value": f"{total_modifier:+.1f}", "inline": True},
            {
                "name": "Score Breakdown",
                "value": _format_score_breakdown(candidate, style="bold"),
                "inline": False,
            },
        ],
        "footer": {"text": f"StockAnalysis {model_version} | Near-Miss — Not a Trade Signal"},
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


def send_paper_expired_alert(trade: dict) -> bool:
    """
    PAPER SIGNAL EXPIRED embed — sends when a breakout/breakdown entry order's
    zone is never reached within paper_updater.FILL_WINDOW_DAYS. Deliberately
    separate from send_paper_outcome_alert: no P&L or R:R ever accrued here
    (no capital was at risk), so labeling it a "STOPPED OUT" close would be
    reporting a loss that never actually happened.
    """
    ticker = trade.get("ticker", "?")
    signal_date = trade.get("signal_date", "—")
    exit_date = trade.get("exit_date", "—")
    entry_zone_lower = trade.get("entry_zone_lower", "")
    entry_zone_upper = trade.get("entry_zone_upper", "")
    confidence = float(trade.get("confidence", 0.0))

    embed = {
        "title": f"⌛ PAPER SIGNAL EXPIRED — {ticker}",
        "color": _COLORS["grey"],
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "fields": [
            {"name": "Signal Date", "value": signal_date, "inline": True},
            {"name": "Expired Date", "value": exit_date, "inline": True},
            {"name": "Entry Zone", "value": f"${entry_zone_lower}-${entry_zone_upper}", "inline": True},
            {"name": "Signal Confidence", "value": f"{confidence:.0f}/100", "inline": True},
        ],
        "footer": {"text": "Entry zone never reached — order never filled, no capital at risk"},
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
        # The webhook token lives in the URL path itself (not a header), and
        # requests' connection/timeout errors often embed the full URL — redact
        # before logging so a network failure doesn't write the live webhook to disk.
        logger.error(f"Discord webhook POST failed: {str(exc).replace(url, '***REDACTED_WEBHOOK***')}")
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
    capital_required = candidate.get("capital_required")
    structure_legs = candidate.get("structure_legs")
    structure_effective_days = candidate.get("structure_effective_days")
    structure_greeks_summary = candidate.get("structure_greeks_summary")
    structure_max_loss = candidate.get("structure_max_loss")
    structure_max_gain = candidate.get("structure_max_gain")
    structure_strikes = candidate.get("structure_strikes")
    structure_expiration_date = candidate.get("structure_expiration_date")
    alternative_structures = candidate.get("alternative_structures")

    lines = [
        f"{'📈' if direction == 'bullish' else '📉'} {ticker} SWING SIGNAL — {confidence:.0f}/100",
        f"Direction: {direction.upper()} | Structure: {structure.replace('_', ' ').title()}",
        f"Entry Zone: ${entry_lower:.2f}–${entry_upper:.2f}",
        f"Stop: ${stop:.2f} | Target: ${target:.2f} (R:R 1:{rr:.1f})",
    ]
    econ_parts = []
    if capital_required is not None:
        try:
            econ_parts.append(f"Capital Required: ${float(capital_required):.2f}")
        except (TypeError, ValueError):
            pass
    if structure_legs:
        econ_parts.append(f"Legs: {structure_legs}")
    if structure_effective_days:
        econ_parts.append(f"Effective Days: {structure_effective_days}")
    if structure_expiration_date:
        econ_parts.append(f"Expiration: {structure_expiration_date}")
    if structure_max_loss:
        econ_parts.append(f"Max Loss: ${structure_max_loss}")
    if structure_max_gain:
        econ_parts.append(f"Max Gain: ${structure_max_gain}")
    elif structure_max_loss:
        econ_parts.append("Max Gain: unlimited")
    if econ_parts:
        lines.append(" | ".join(econ_parts))
    if structure_strikes:
        lines.append(f"Strikes: {structure_strikes}")
    if structure_greeks_summary:
        lines.append(f"Net Greeks: {structure_greeks_summary}")
    if alternative_structures:
        lines.append(f"Alternatives: {alternative_structures}")
    lines.append(f"Model: {model_version}")
    return "\n".join(lines)
