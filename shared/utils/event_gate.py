"""
SHARED: Event Severity Gate — advisory flag for critical news in the pipeline.

This is not a sixth scoring category — it exists because News's normal
15-point additive score can be mathematically outvoted by four slower-moving
layers (Technical/Positioning/Sentiment on daily-to-quarterly cadence,
Fundamental weekly) that haven't reacted yet to a severe breaking event.
Classification is keyword + source based and fully driven by
config/swing_config.yaml['event_severity_gate'] — never hardcoded in Python.

Advisory only: a candidate with an active block still surfaces on its own
score merits — event_gate_blocked/event_gate_trigger are attached so the
caller can flag it, never used to suppress or alter the score.

Block state persists in data/processed/event_gate_state.json until the next
full post-close scan completes after the event timestamp (cooling-off).
"""

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from shared.utils.logger import get_logger
from shared.utils.source_credibility import score_news_outlet

logger = get_logger(__name__)

_STATE_FILE = Path("data/processed/event_gate_state.json")

SEVERITY_NORMAL = "normal"
SEVERITY_CRITICAL = "critical"
SCOPE_TICKER = "ticker"
SCOPE_SECTOR = "sector"


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

def classify_severity(headline: str, source: Optional[str] = None, cfg: Optional[dict] = None) -> dict:
    """
    Classify a single news headline's severity per the event_severity_gate config.

    Case-insensitive substring matching against post-NER headline text only
    (require_headline_match). Sector-wide triggers block regardless of source
    credibility; ticker triggers do too, EXCEPT that any match (sector or
    ticker) from a source below min_source_credibility is downgraded back to
    "normal" and logged as a WARNING instead of gating — UNLESS the source is
    one of the configured principal_sources, which are always critical.

    Returns: {severity, scope, trigger_match, source_credibility, principal_source}
    """
    cfg = cfg or {}
    gate_cfg = cfg.get("event_severity_gate", {})
    credibility = score_news_outlet(source or "")
    result = {
        "severity": SEVERITY_NORMAL,
        "scope": None,
        "trigger_match": None,
        "source_credibility": credibility,
        "principal_source": False,
    }

    matched = _find_trigger_match(headline, gate_cfg)
    if not matched:
        return result

    if not gate_cfg.get("enabled", True):
        # Full pass-through when disabled — never gates, but still observable.
        logger.warning(
            f"event_severity_gate disabled — would have classified as critical "
            f"({matched['scope']}, trigger='{matched['trigger_match']}'). Headline: {headline[:160]}"
        )
        return result

    principal_sources = [s.lower() for s in gate_cfg.get("principal_sources", [])]
    is_principal = bool(source) and any(p in source.lower() for p in principal_sources)
    result["principal_source"] = is_principal

    min_cred = float(gate_cfg.get("min_source_credibility", 0.5))
    if not is_principal and credibility < min_cred:
        logger.warning(
            f"Trigger match '{matched['trigger_match']}' ({matched['scope']}) from low-credibility "
            f"source '{source}' (credibility={credibility:.2f} < {min_cred}) — logged, not gated. "
            f"Headline: {headline[:160]}"
        )
        return result

    result["severity"] = SEVERITY_CRITICAL
    result["scope"] = matched["scope"]
    result["trigger_match"] = matched["trigger_match"]
    return result


def _find_trigger_match(headline: str, gate_cfg: dict) -> Optional[dict]:
    """Sector-wide triggers checked first — a sector-wide match always wins scope."""
    headline_lower = (headline or "").lower()
    for trigger in gate_cfg.get("sector_wide_triggers", []):
        if trigger.lower() in headline_lower:
            return {"scope": SCOPE_SECTOR, "trigger_match": trigger}
    for trigger in gate_cfg.get("ticker_triggers", []):
        if trigger.lower() in headline_lower:
            return {"scope": SCOPE_TICKER, "trigger_match": trigger}
    return None


def is_thesis_opposed(ner_sentiment: Optional[str], candidate_direction: str) -> bool:
    """
    Does a critical item's NER-attributed sentiment oppose the candidate's direction?

    Bearish news opposes a bullish thesis (and vice versa) — that's flagged.
    Bearish news on an already-bearish thesis is *confirming*, not opposing — the
    gate is asymmetric by design (flag only; chasing shock headlines that agree
    with your thesis is how you buy the top of a gap, so it is never boosted either).
    Neutral/unknown NER attribution defaults to opposed: a false flag costs the
    user a moment's extra scrutiny, a false pass means no warning on a real gap-down risk.
    """
    sentiment = (ner_sentiment or "neutral").lower()
    if sentiment == "bullish":
        return candidate_direction == "bearish"
    if sentiment == "bearish":
        return candidate_direction == "bullish"
    return True


# ---------------------------------------------------------------------------
# Block state persistence — data/processed/event_gate_state.json
# ---------------------------------------------------------------------------

def load_gate_state() -> dict:
    """Load event_gate_state.json, auto-repairing malformed/stale content."""
    from shared.utils.data_validator import validate_event_gate_state

    if not _STATE_FILE.exists():
        return {"blocks": []}
    try:
        raw = json.loads(_STATE_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError) as exc:
        logger.warning(f"event_gate_state.json unreadable ({exc}) — repairing to empty state.")
        return {"blocks": []}
    return validate_event_gate_state(raw)


def save_gate_state(state: dict) -> None:
    """Persist block state to data/processed/event_gate_state.json."""
    _STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    _STATE_FILE.write_text(json.dumps(state, indent=2, default=str), encoding="utf-8")


def is_ticker_blocked(ticker: str, state: dict) -> Optional[dict]:
    """Return the active block dict covering `ticker` (sector-wide or ticker-specific), or None."""
    for block in state.get("blocks", []):
        if block.get("expired"):
            continue
        if block.get("scope") == SCOPE_SECTOR:
            return block
        if ticker in block.get("tickers", []):
            return block
    return None


def has_active_block_for_trigger(state: dict, trigger_match: str, scope: str) -> bool:
    """Avoid re-adding a duplicate block for the same still-active trigger."""
    for block in state.get("blocks", []):
        if not block.get("expired") and block.get("trigger_match") == trigger_match and block.get("scope") == scope:
            return True
    return False


def add_block(
    state: dict,
    tickers: list[str],
    scope: str,
    trigger_headline: str,
    trigger_match: str,
    source: str,
    event_timestamp_utc: str,
) -> dict:
    """
    Append a new active block to state (caller must save_gate_state()).
    Returns the updated state; the new block is state["blocks"][-1].
    """
    block = {
        "id": str(uuid.uuid4()),
        "tickers": list(tickers),
        "scope": scope,
        "trigger_headline": (trigger_headline or "")[:500],
        "trigger_match": trigger_match,
        "source": source,
        "event_timestamp_utc": event_timestamp_utc,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "expiry_condition": "next_post_close_scan",
        "expired": False,
        "expired_at_utc": None,
    }
    state.setdefault("blocks", []).append(block)
    logger.warning(
        f"EVENT GATE TRIGGERED — scope={scope} tickers={tickers} trigger='{trigger_match}' source='{source}'"
    )
    return state


def expire_blocks(
    state: dict,
    scan_type: str,
    scan_completed_at_utc: Optional[datetime] = None,
    exclude_ids: Optional[set[str]] = None,
) -> list[dict]:
    """
    Expire blocks whose cooling-off condition is met: a post_close scan has
    completed with a timestamp after the block's event_timestamp_utc.

    exclude_ids skips blocks created during THIS SAME scan run — the cooling-off
    requires the system to see one full daily-bar update reflecting the event,
    which means a scan that starts *after* the block already exists, not the
    scan that just created it moments ago.

    Returns the list of newly-expired block dicts (for EVENT_GATE_EXPIRED alerts).
    """
    if scan_type != "post_close":
        return []
    exclude_ids = exclude_ids or set()
    completed_at = scan_completed_at_utc or datetime.now(timezone.utc)
    newly_expired = []
    for block in state.get("blocks", []):
        if block.get("expired") or block.get("id") in exclude_ids:
            continue
        event_ts = _parse_iso(block.get("event_timestamp_utc"))
        if event_ts is not None and completed_at > event_ts:
            block["expired"] = True
            block["expired_at_utc"] = datetime.now(timezone.utc).isoformat()
            newly_expired.append(block)
    return newly_expired


def _parse_iso(ts: Optional[str]) -> Optional[datetime]:
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None
