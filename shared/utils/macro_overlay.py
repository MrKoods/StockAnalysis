"""
SHARED: Monitors Fed rate direction (^TNX proxy), USD strength (DXY),
and China trade policy signals (news keyword frequency).
Outputs macro state (favorable/neutral/adverse), recomputed fresh every scan
by run_swing_model.py/paper_runner.py (see _compute_macro_safe) and fed
directly into compute_confidence_score() as macro_modifier — this module's
own state is not read back from disk for scoring. save_macro_state()/
load_macro_state() persist data/processed/macro_state.json purely for
observability (so the current macro state is visible without recomputing);
nothing in the scoring path reads this file.

Free proxy sources (per Clarification 2):
  Fed direction: ^TNX 20-day trend (3%+ rise = hawkish = adverse)
  USD strength:  DX-Y.NYB 20-day trend (rising = adverse for TSM/ASML)
  China policy:  keyword frequency from news_client.py output
"""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import pandas as pd


MACRO_FAVORABLE = "favorable"
MACRO_NEUTRAL = "neutral"
MACRO_ADVERSE = "adverse"

_MACRO_STATE_FILE = Path("data/processed/macro_state.json")

# This module's TNX/DXY/China rationale is semiconductor-specific, not
# universal: "hawkish rates hurt growth/tech" doesn't hold for regional
# banks, where rising rates typically widen net interest margin and are
# often a net positive, not adverse. "Strong USD hurts TSM/ASML" is
# explicitly about foreign-ADR currency exposure — meaningless for
# domestically-focused names like HD/TGT or a regional bank. Previously
# this logic was applied identically to every active sector (semiconductors,
# regional_banks, healthcare, consumer_discretionary) since compute_macro_state
# was called once per scan with no sector context at all. Restricting it to
# the one sector it was actually designed and reasoned about avoids
# introducing a wrong-direction bias for sectors with different (and not yet
# modeled) rate/FX sensitivity — neutral is the honest answer until sector-
# specific macro logic is built and validated for them.
_SECTORS_WITH_VALIDATED_MACRO_LOGIC = {"semiconductors"}


def compute_macro_state(
    tnx_close: pd.Series,
    dxy_close: pd.Series,
    china_keyword_count_5d: int,
    cfg: Optional[dict] = None,
    sector: Optional[str] = None,
    direction: str = "bullish",
) -> dict:
    """
    Compute current macro overlay state from three free proxy signals.

    Signal logic:
    1. TNX (10-yr treasury yield): 20-day % change > +3% → hawkish → adverse
       20-day % change < -3% → dovish → favorable for growth/tech
    2. DXY (USD Index): 20-day % change > +2% → strong USD → adverse (TSM/ASML impact)
       < -2% → weak USD → favorable
    3. China tension: keyword count > threshold → adverse for TSM/ASML/NVDA export risk

    Aggregation: score adverse signals — 2+ adverse → adverse; 0 adverse → favorable;
    1 adverse → neutral (unless it's China tension alone = neutral)

    sector: which sector this call is scoring for. When supplied and NOT in
    _SECTORS_WITH_VALIDATED_MACRO_LOGIC, the trend readings (tnx_trend/
    dxy_trend/china_tension_level) are still computed and returned for
    observability, but they don't drive macro_state/confidence_modifier —
    both are forced to neutral/0.0, since this module's specific adverse/
    favorable rationale isn't validated for that sector. None (the default)
    preserves the original sector-agnostic behavior — every existing caller
    that doesn't pass a sector gets the same result as before.

    direction: "bullish" (default) or "bearish". Adverse macro conditions
    (hawkish rates, strong USD, China tension) penalize a bullish thesis but
    should CONFIRM a bearish one — same reasoning as
    regime_detection.get_regime_modifiers's directional sign flip. The
    modifier's sign is flipped for bearish; macro_state/adverse_signal_count
    themselves (categorical, not directional) are left unchanged so
    diagnostics/logging still read "adverse macro conditions" regardless of
    which direction that ends up favoring in confidence_modifier.

    Returns dict:
    {
        macro_state, tnx_trend, dxy_trend, china_tension_level,
        tnx_20d_pct, dxy_20d_pct,
        adverse_signal_count: int,
        confidence_modifier: float,  # -10 to +3 (bullish) / -3 to +10 (bearish)
        computed_at_utc: str,
        sector_scoped: bool,  # True when this sector's logic was neutralized
    }
    """
    if cfg is None:
        cfg = {}
    m_cfg = cfg.get("modifiers", {}).get("macro_overlay", {})

    tnx_window = int(m_cfg.get("tnx_lookback_days", 20))
    dxy_window = int(m_cfg.get("dxy_lookback_days", 20))
    tnx_adverse_pct = float(m_cfg.get("tnx_adverse_threshold_pct", 0.03))
    tnx_favorable_pct = float(m_cfg.get("tnx_favorable_threshold_pct", -0.03))
    dxy_adverse_pct = float(m_cfg.get("dxy_adverse_threshold_pct", 0.02))
    dxy_favorable_pct = float(m_cfg.get("dxy_favorable_threshold_pct", -0.02))
    china_adverse_count = int(m_cfg.get("china_keyword_adverse_threshold", 5))

    # 1. TNX trend
    tnx_pct = _period_pct_change(tnx_close, tnx_window)
    if tnx_pct is None or pd.isna(tnx_pct):
        tnx_trend = "neutral"
        tnx_adverse = False
    elif tnx_pct > tnx_adverse_pct:
        tnx_trend = "rising"
        tnx_adverse = True
    elif tnx_pct < tnx_favorable_pct:
        tnx_trend = "falling"
        tnx_adverse = False
    else:
        tnx_trend = "neutral"
        tnx_adverse = False

    # 2. DXY trend
    dxy_pct = _period_pct_change(dxy_close, dxy_window)
    if dxy_pct is None or pd.isna(dxy_pct):
        dxy_trend = "neutral"
        dxy_adverse = False
    elif dxy_pct > dxy_adverse_pct:
        dxy_trend = "rising"
        dxy_adverse = True
    elif dxy_pct < dxy_favorable_pct:
        dxy_trend = "falling"
        dxy_adverse = False
    else:
        dxy_trend = "neutral"
        dxy_adverse = False

    # 3. China tension
    china_high = china_keyword_count_5d >= china_adverse_count
    china_tension_level = "high" if china_high else "normal"
    china_adverse = china_high

    sector_scoped = sector is not None and sector not in _SECTORS_WITH_VALIDATED_MACRO_LOGIC

    if sector_scoped:
        # Trend readings above are still real and returned for observability,
        # but this sector's macro state/modifier stay neutral — see
        # _SECTORS_WITH_VALIDATED_MACRO_LOGIC's module-level comment.
        adverse_count = 0
        macro_state = MACRO_NEUTRAL
        modifier = 0.0
    else:
        adverse_count = sum([tnx_adverse, dxy_adverse, china_adverse])
        favorable_count = sum([
            tnx_trend == "falling",
            dxy_trend == "falling",
            not china_adverse,
        ])

        if adverse_count >= 2:
            macro_state = MACRO_ADVERSE
        elif adverse_count == 0 and favorable_count >= 2:
            macro_state = MACRO_FAVORABLE
        else:
            macro_state = MACRO_NEUTRAL

        modifier = get_macro_modifier(macro_state, cfg, direction=direction)

    return {
        "macro_state": macro_state,
        "tnx_trend": tnx_trend,
        "dxy_trend": dxy_trend,
        "china_tension_level": china_tension_level,
        "tnx_20d_pct": float(tnx_pct) if tnx_pct is not None else None,
        "dxy_20d_pct": float(dxy_pct) if dxy_pct is not None else None,
        "adverse_signal_count": adverse_count,
        "confidence_modifier": modifier,
        "computed_at_utc": datetime.now(timezone.utc).isoformat(),
        "sector_scoped": sector_scoped,
    }


def _period_pct_change(series: pd.Series, window: int) -> Optional[float]:
    """Compute percentage change over last `window` bars. Returns None if insufficient data."""
    if series is None or len(series) < window + 1:
        return None
    past = float(series.iloc[-(window + 1)])
    current = float(series.iloc[-1])
    if past == 0:
        return None
    return (current - past) / past


def load_macro_state() -> dict:
    """Load last computed macro state from data/processed/macro_state.json."""
    if _MACRO_STATE_FILE.exists():
        return json.loads(_MACRO_STATE_FILE.read_text(encoding="utf-8"))
    return {"macro_state": MACRO_NEUTRAL, "confidence_modifier": 0.0}


def save_macro_state(state: dict) -> None:
    """Persist macro state to data/processed/macro_state.json."""
    _MACRO_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    _MACRO_STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")


def get_macro_modifier(macro_state: str, cfg: Optional[dict] = None, direction: str = "bullish") -> float:
    """
    Map macro_state to confidence modifier.
    Bounds per spec: -10 to +3 (bullish); sign-flipped (-3 to +10) for bearish
    — adverse macro conditions confirm a bearish thesis instead of opposing it.
    """
    if cfg is None:
        cfg = {}
    m_cfg = cfg.get("modifiers", {}).get("macro_overlay", {})
    if macro_state == MACRO_ADVERSE:
        raw = float(m_cfg.get("adverse_penalty", -10))
    elif macro_state == MACRO_FAVORABLE:
        raw = float(m_cfg.get("favorable_boost", 3))
    else:
        return 0.0
    return -raw if direction == "bearish" else raw
