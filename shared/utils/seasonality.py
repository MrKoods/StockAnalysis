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


def get_seasonality_modifier(
    date: Optional[datetime] = None,
    cfg: Optional[dict] = None,
) -> dict:
    """
    Return semiconductor seasonality confidence modifier for given date.

    Returns dict:
    {
        month: int, quarter: int,
        seasonality_state: str,  # 'strong', 'neutral', 'weak'
        confidence_modifier: float,  # -5 to +5
        rationale: str,
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
    modifier = max(-5.0, min(5.0, float(raw)))

    if modifier >= 2.0:
        state = "strong"
    elif modifier <= -2.0:
        state = "weak"
    else:
        state = "neutral"

    return {
        "month": month,
        "quarter": quarter,
        "seasonality_state": state,
        "confidence_modifier": modifier,
        "rationale": _MONTH_RATIONALE.get(month, f"Q{quarter} semiconductor pattern"),
    }


# Default semiconductor seasonality profile (calibrated via Phase 12 backtesting).
# Values are confidence score point adjustments. Range clamped to [-5, +5] per spec.
_DEFAULT_MONTHLY: dict[str, float] = {
    "1":  2.0,   # Jan: new budgets, inventory restocking
    "2":  0.0,   # Feb: neutral
    "3":  1.0,   # Mar: Q1-end demand
    "4": -2.0,   # Apr: post-Q1 soft demand
    "5": -3.0,   # May: historically weak
    "6": -1.0,   # Jun: mid-year recovery beginning
    "7":  1.0,   # Jul: Q3 setup, new product cycle begins
    "8":  2.0,   # Aug: pre-Q3 earnings order build
    "9":  0.0,   # Sep: mixed (back-to-school done, data center unclear)
    "10": 3.0,   # Oct: Q4 strength begins
    "11": 4.0,   # Nov: peak Q4 seasonality
    "12": 5.0,   # Dec: strongest — year-end builds, Q1 pre-buy
}

_DEFAULT_QUARTERLY: dict[str, float] = {
    "Q1":  1.0,
    "Q2": -2.0,
    "Q3":  1.0,
    "Q4":  4.0,
}

_MONTH_RATIONALE: dict[int, str] = {
    1:  "New fiscal budgets released; semiconductor restocking demand",
    2:  "Neutral — post-CES inventory settle",
    3:  "Q1 end-of-quarter demand pull",
    4:  "Post-Q1 soft patch — historically weakest for semis",
    5:  "May weakness; guidance-season uncertainty",
    6:  "Mid-year recovery begins; early data center orders",
    7:  "Q3 setup; new product cycle order flow begins",
    8:  "Pre-earnings build; NVDA/AMD cycle ordering",
    9:  "Mixed; back-to-school cycle winding down",
    10: "Q4 strength begins; holiday supply chain procurement",
    11: "Peak Q4 semiconductor demand",
    12: "Year-end builds + Q1 pre-buy front-loading",
}
