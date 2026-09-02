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

def classify_severity(
    headline: str,
    source: Optional[str] = None,
    cfg: Optional[dict] = None,
    sector: Optional[str] = None,
) -> dict:
    """
    Classify a single news headline's severity per the event_severity_gate config.

    Case-insensitive substring matching against post-NER headline text only
    (require_headline_match). Sector-wide triggers block regardless of source
    credibility; ticker triggers do too, EXCEPT that any match (sector or
    ticker) from a source below min_source_credibility is downgraded back to
    "normal" and logged as a WARNING instead of gating — UNLESS the source is
    one of the configured principal_sources, which are always critical.

    `sector`: which sector's `event_severity_gate.sector_triggers` list to check
    against (see config/swing_config.yaml). None checks every active sector's
    list unioned — a defensive default for callers that haven't been migrated
    to pass a sector; every real call site should pass one after v2.2.8.

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

    matched = _find_trigger_match(headline, gate_cfg, sector)
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


def _find_trigger_match(headline: str, gate_cfg: dict, sector: Optional[str] = None) -> Optional[dict]:
    """
    Sector-wide triggers checked first — a sector-wide match always wins scope.

    `sector_triggers` is a dict keyed by sector name (config/swing_config.yaml).
    When `sector` is given, only that sector's trigger list is checked — a
    chip-ban headline must not match while scoring a bank ticker, and vice
    versa. When `sector` is None (unmigrated caller), every active sector's
    list is unioned as a defensive fallback.

    Ticker triggers only (not sector triggers — those describe macro/market
    events, not one company's own PR, so this ambiguity doesn't arise there):
    a match is suppressed when the headline also contains one of
    advisory_context_exclusions — the company publishing advisory/security/
    marketing content that happens to contain the trigger word, not being the
    subject of it. Observed live: KEY's "fraud" ticker trigger re-fired 6+
    times between 2026-07-23 and 2026-08-24 on KeyBank's own fraud-prevention
    marketing copy ("...How Businesses Can Help Prevent Fraud", "Launches
    Check Fraud Tool...", "...Fraud Prevention Tips"), never once a real
    fraud allegation about KEY itself; separately, AMD's "fraud" trigger
    fired on "Real-Time Fraud Detection at Machine Speed: Aerospike Debuts
    Agentic AI Stack with Google Gemini and AMD EPYC Processors" — AMD is a
    component vendor mentioned in a different company's product story, not
    the subject of the fraud keyword at all. A genuine allegation (e.g.
    UNH's "Lawsuit Alleges Medicare Fraud") contains none of these exclusion
    phrases and still matches normally.
    """
    headline_lower = (headline or "").lower()
    sector_triggers_cfg = gate_cfg.get("sector_triggers", {})
    if sector is not None:
        candidate_triggers = sector_triggers_cfg.get(sector, [])
    else:
        candidate_triggers = [t for triggers in sector_triggers_cfg.values() for t in triggers]
    for trigger in candidate_triggers:
        if trigger.lower() in headline_lower:
            return {"scope": SCOPE_SECTOR, "trigger_match": trigger}

    advisory_exclusions = [p.lower() for p in gate_cfg.get("advisory_context_exclusions", [])]
    for trigger in gate_cfg.get("ticker_triggers", []):
        if trigger.lower() in headline_lower:
            if any(phrase in headline_lower for phrase in advisory_exclusions):
                continue
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


def is_ticker_blocked(ticker: str, state: dict, direction: Optional[str] = None) -> Optional[dict]:
    """
    Return the active block dict covering `ticker` (sector-wide or ticker-specific), or None.

    Membership is decided purely by `block["tickers"]` — add_block() always
    populates it with the actual covered tickers regardless of scope (the full
    sector's ticker list for SCOPE_SECTOR, a single ticker for SCOPE_TICKER).
    `scope` is metadata about why the block was created, not which tickers it
    covers. A prior version of this function short-circuited on
    `scope == SCOPE_SECTOR` without checking membership at all, which was
    harmless with one sector (a sector-wide block always covered the whole,
    single-sector watchlist) but would incorrectly block every ticker in every
    sector once a second sector exists.

    direction: the candidate's own current thesis direction ("bullish"/
    "bearish"). When supplied and the block has a stored `ner_sentiment`
    (added when the block was created — see add_block()), membership alone
    isn't enough: the block only counts as blocking THIS ticker if the news
    actually opposes ITS OWN direction (is_thesis_opposed), same rule
    ticker-scope blocks already required before they were even created.
    Sector-wide blocks previously skipped this check entirely — every ticker
    in the sector was flagged regardless of its own direction, including one
    whose thesis the news would, if anything, confirm rather than oppose
    (2026-09 finding: a bearish-flavored sector headline flagged a bullish-
    thesis ticker it never should have agreed with in the first place, and
    would have flagged an already-bearish ticker for news that actually
    supports it). None (the default) or a block with no stored ner_sentiment
    (older state, or a ticker-scope caller doing a dedup check — see
    run_swing_model.py/paper_runner.py's own is_ticker_blocked() call before
    creating a new ticker-scope block) preserves the old unconditional-
    membership behavior.
    """
    for block in state.get("blocks", []):
        if block.get("expired"):
            continue
        if ticker not in block.get("tickers", []):
            continue
        ner_sentiment = block.get("ner_sentiment")
        if direction is not None and ner_sentiment is not None and not is_thesis_opposed(ner_sentiment, direction):
            continue
        return block
    return None


def has_active_block_for_trigger(state: dict, trigger_match: str, scope: str) -> bool:
    """Avoid re-adding a duplicate block for the same still-active trigger."""
    for block in state.get("blocks", []):
        if not block.get("expired") and block.get("trigger_match") == trigger_match and block.get("scope") == scope:
            return True
    return False


def critical_alert_key(ticker: str, event: dict) -> str:
    """
    Stable identity for one (open position, critical news event) pair.

    trigger_match + event_timestamp_utc, not the headline: the same underlying
    event reaches us through several vendors with slightly different headline
    text, and re-alerting once per vendor phrasing is exactly the noise this
    key exists to collapse.
    """
    return "|".join([
        ticker,
        str(event.get("trigger_match", "")),
        str(event.get("event_timestamp_utc", "")),
    ])


def was_critical_alert_sent(state: dict, ticker: str, event: dict) -> bool:
    """
    Has an open-position critical alert already fired for this ticker/event?

    A critical news item stays in the feed for days, and the open-position
    alert used to fire unconditionally — once per matching event, per scan,
    with three scans a day. MU generated ~9 identical "tariff" alerts a day
    across 2026-08-24/25 (and did it for a position sized to 0 units, so
    there was nothing to act on either). Alert fatigue on a safety channel is
    a real failure mode: the fix is to alert on the transition, matching the
    `action != pos["_last_management_action"]` guard the signal-decay alert
    beside it already uses.
    """
    return critical_alert_key(ticker, event) in state.get("critical_alerts_sent", {})


def record_critical_alert(state: dict, ticker: str, event: dict) -> dict:
    """
    Mark this ticker/event pair as alerted (caller must save_gate_state()).

    Stored as {key: sent_at_utc} — the timestamp is what
    validate_event_gate_state() prunes on, so the map can't grow without
    bound across the life of the state file.
    """
    state.setdefault("critical_alerts_sent", {})[critical_alert_key(ticker, event)] = (
        datetime.now(timezone.utc).isoformat()
    )
    return state


def add_block(
    state: dict,
    tickers: list[str],
    scope: str,
    trigger_headline: str,
    trigger_match: str,
    source: str,
    event_timestamp_utc: str,
    ner_sentiment: Optional[str] = None,
) -> dict:
    """
    Append a new active block to state (caller must save_gate_state()).
    Returns the updated state; the new block is state["blocks"][-1].

    ner_sentiment: the triggering headline's NER-attributed sentiment
    ("bullish"/"bearish"/None), stored so is_ticker_blocked() can later
    re-check it against each covered ticker's OWN direction (see that
    function's docstring) — mainly relevant for a SCOPE_SECTOR block, which
    covers tickers that can each be scored in either direction. None (the
    default) keeps every covered ticker unconditionally blocked, same as
    before this parameter existed.
    """
    block = {
        "id": str(uuid.uuid4()),
        "tickers": list(tickers),
        "scope": scope,
        "trigger_headline": (trigger_headline or "")[:500],
        "trigger_match": trigger_match,
        "source": source,
        "event_timestamp_utc": event_timestamp_utc,
        "ner_sentiment": ner_sentiment,
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
