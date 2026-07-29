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


def compute_macro_state(
    tnx_close: pd.Series,
    dxy_close: pd.Series,
    china_keyword_count_5d: int,
    cfg: Optional[dict] = None,
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

    Returns dict:
    {
        macro_state, tnx_trend, dxy_trend, china_tension_level,
        tnx_20d_pct, dxy_20d_pct,
        adverse_signal_count: int,
        confidence_modifier: float,  # -10 to +3
        computed_at_utc: str,
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

    modifier = get_macro_modifier(macro_state, cfg)

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


def get_macro_modifier(macro_state: str, cfg: Optional[dict] = None) -> float:
    """
    Map macro_state to confidence modifier.
    Bounds per spec: -10 to +3.
    """
    if cfg is None:
        cfg = {}
    m_cfg = cfg.get("modifiers", {}).get("macro_overlay", {})
    if macro_state == MACRO_ADVERSE:
        return float(m_cfg.get("adverse_penalty", -10))
    if macro_state == MACRO_FAVORABLE:
        return float(m_cfg.get("favorable_boost", 3))
    return 0.0
