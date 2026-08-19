"""
SHARED: Monthly and quarterly semiconductor seasonal modifiers (-5 to +5).
Modifiers reflect historical semiconductor sector patterns:
  - Q4 (Oct-Dec): strong demand pull-forward for PC/server builds → positive
  - Q2 (Apr-Jun): typically weak post-Q1 restock → slightly negative
  - Jan/Jul: new-quarter setup months → slight positive
Modifiers are read from swing_config.yaml so they can be tuned without code changes.
"""

from datetime import datetime, timezone
from typing import Optional


# This profile is a semiconductor-specific demand calendar (PC/server build
# cycles, NVDA/AMD product-cycle ordering — see _MONTH_RATIONALE below), not
# a universal market seasonality curve. Previously applied identically to
# every active sector (regional_banks, healthcare, consumer_discretionary
# too) since get_seasonality_modifier was called once per scan with no
# sector context. Consumer discretionary in particular has its own,
# different, well-known seasonality (holiday retail) this profile doesn't
# capture — applying the semiconductor curve there is actively misleading,
# not just imprecise. Restricted to the one sector it was built for; neutral
# for the others until sector-appropriate seasonality is built and validated.
_SECTORS_WITH_VALIDATED_SEASONALITY = {"semiconductors"}


def get_seasonality_modifier(
    date: Optional[datetime] = None,
    cfg: Optional[dict] = None,
    sector: Optional[str] = None,
    direction: str = "bullish",
) -> dict:
    """
    Return semiconductor seasonality confidence modifier for given date.

    sector: which sector this call is scoring for. When supplied and NOT in
    _SECTORS_WITH_VALIDATED_SEASONALITY, month/quarter/rationale are still
    returned for observability but confidence_modifier is forced to 0.0 and
    seasonality_state to 'neutral' — this profile's specific rationale isn't
    validated for that sector. None (the default) preserves the original
    sector-agnostic behavior.

    direction: "bullish" (default) or "bearish". The monthly/quarterly table
    is calibrated against bullish breakout outcomes (see the 2026-08-15
    sign-flip note on _DEFAULT_MONTHLY below and config's matching comment);
    for a bearish candidate the same seasonal read should confirm/oppose the
    short thesis in the opposite direction, so the modifier's sign is
    flipped — same pattern as regime_detection.get_regime_modifiers and
    macro_overlay.get_macro_modifier. seasonality_state (strong/weak/neutral)
    is left describing the underlying calendar reading, not re-labeled per
    direction.

    Returns dict:
    {
        month: int, quarter: int,
        seasonality_state: str,  # 'strong', 'neutral', 'weak'
        confidence_modifier: float,  # -5 to +5, sign-flipped for bearish
        rationale: str,
        sector_scoped: bool,  # True when this sector's modifier was neutralized
    }
    """
    if date is None:
        date = datetime.now(timezone.utc)
    if cfg is None:
        cfg = {}

    month = date.month
    quarter = (month - 1) // 3 + 1

    seasonal_cfg = cfg.get("modifiers", {}).get("seasonality", {})
    monthly = seasonal_cfg.get("monthly_modifiers", _DEFAULT_MONTHLY)
    quarterly = seasonal_cfg.get("quarterly_adjustments", _DEFAULT_QUARTERLY)

    # Monthly modifier takes precedence over quarterly. yaml.safe_load() parses
    # swing_config.yaml's unquoted numeric keys (e.g. `8: 0`) as int, not str — a
    # str(month) lookup against that real, int-keyed dict always misses and falls
    # through to the quarterly default. Try int first (matches real YAML parsing),
    # then str (hand-authored quoted configs, programmatic callers, _DEFAULT_MONTHLY
    # itself which is str-keyed), before falling through to quarterly.
    quarter_key = f"Q{quarter}"
    if month in monthly:
        raw = monthly[month]
    elif str(month) in monthly:
        raw = monthly[str(month)]
    else:
        raw = quarterly.get(quarter_key, 0.0)

    sector_scoped = sector is not None and sector not in _SECTORS_WITH_VALIDATED_SEASONALITY
    calendar_modifier = 0.0 if sector_scoped else max(-5.0, min(5.0, float(raw)))

    if sector_scoped:
        state = "neutral"
    elif calendar_modifier >= 2.0:
        state = "strong"
    elif calendar_modifier <= -2.0:
        state = "weak"
    else:
        state = "neutral"

    # Sign-flipped for bearish AFTER state is derived — state describes the
    # underlying calendar reading, not the direction-adjusted contribution.
    modifier = -calendar_modifier if direction == "bearish" else calendar_modifier

    return {
        "month": month,
        "quarter": quarter,
        "seasonality_state": state,
        "confidence_modifier": modifier,
        "rationale": _MONTH_RATIONALE.get(month, f"Q{quarter} semiconductor pattern"),
        "sector_scoped": sector_scoped,
    }


# Default semiconductor seasonality profile — only used when no cfg (or no
# cfg.modifiers.seasonality.monthly_modifiers key) is supplied; every real
# scan always has that key, so config/swing_config.yaml's table is what's
# actually live. Kept in sync with it by hand (see that file's comment for
# the 2026-08-15 sign-flip rationale and the real measured numbers) so a
# programmatic caller without cfg doesn't fall back to the old, backwards
# direction. Values are confidence score point adjustments, clamped [-5, +5].
_DEFAULT_MONTHLY: dict[str, float] = {
    "1":  5.0,
    "2":  5.0,
    "3":  0.0,
    "4": -2.0,
    "5":  0.0,
    "6":  0.0,
    "7":  0.0,
    "8":  0.0,
    "9":  2.0,
    "10": -3.0,
    "11": -5.0,
    "12": -5.0,
}

_DEFAULT_QUARTERLY: dict[str, float] = {
    "Q1":  1.0,
    "Q2": -2.0,
    "Q3":  1.0,
    "Q4": -4.0,
}

# Rationale text intentionally doesn't repeat the old month-specific demand
# narratives ("Q4 strength begins", "post-Q1 soft patch", etc.) — those
# stories were written to match the ORIGINAL (wrong-signed) table and aren't
# separately verified against real data; carrying them forward re-signed
# would just be a different set of unverified stories. This states what's
# actually known: the sign is empirically derived, not the specific
# mechanism, per config/swing_config.yaml's 2026-08-15 comment.
_MONTH_RATIONALE: dict[int, str] = {
    1:  "Historically favorable entry month for semiconductor breakouts (empirically re-derived 2026-08-15 — see CHANGELOG)",
    2:  "Historically favorable entry month for semiconductor breakouts (empirically re-derived 2026-08-15 — see CHANGELOG)",
    3:  "No significant seasonal tilt measured",
    4:  "Historically weaker entry month for semiconductor breakouts (empirically re-derived 2026-08-15 — see CHANGELOG)",
    5:  "No significant seasonal tilt measured",
    6:  "No significant seasonal tilt measured",
    7:  "No significant seasonal tilt measured",
    8:  "No significant seasonal tilt measured",
    9:  "Historically favorable entry month for semiconductor breakouts (empirically re-derived 2026-08-15 — see CHANGELOG)",
    10: "Historically weaker entry month for semiconductor breakouts (empirically re-derived 2026-08-15 — see CHANGELOG)",
    11: "Historically weaker entry month for semiconductor breakouts (empirically re-derived 2026-08-15 — see CHANGELOG)",
    12: "Historically weaker entry month for semiconductor breakouts (empirically re-derived 2026-08-15 — see CHANGELOG)",
}
