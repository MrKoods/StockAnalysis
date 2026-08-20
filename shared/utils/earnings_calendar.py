"""
SHARED: Fetches upcoming earnings dates via yfinance.
Outputs days-to-earnings + confidence penalty + structure override flag.
Earnings-aware adjustments:
  - Within 5 trading days: penalty up to -20; structure → defined-risk spreads
  - On earnings day itself: no new trade recommendations for that ticker
  - Within 3 days after earnings (IV settling): tentative restore
"""

from datetime import datetime, timezone
from typing import Optional


def get_earnings_modifier(
    ticker: str,
    earnings_date: Optional[datetime],
    today: Optional[datetime] = None,
    cfg: Optional[dict] = None,
) -> dict:
    """
    Compute earnings proximity modifier and structure override flag.

    Returns dict:
    {
        days_to_earnings: int or None,
        confidence_modifier: float,   # 0 to -20
        force_defined_risk: bool,     # True if within 5 days
        no_new_trades: bool,          # True on earnings day itself
        post_earnings_settling: bool, # True within 3 days after earnings
    }
    """
    if today is None:
        today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

    if cfg is None:
        cfg = {}
    e_cfg = cfg.get("modifiers", {}).get("earnings", {})

    if earnings_date is None:
        return {
            "days_to_earnings": None,
            "confidence_modifier": 0.0,
            "force_defined_risk": False,
            "no_new_trades": False,
            "post_earnings_settling": False,
        }

    # Normalize earnings_date to UTC midnight
    if earnings_date.tzinfo is None:
        earnings_date = earnings_date.replace(tzinfo=timezone.utc)
    earnings_day = earnings_date.replace(hour=0, minute=0, second=0, microsecond=0)

    days = int((earnings_day - today).days)

    no_new_trades = days == 0
    post_settling = -3 <= days < 0  # within 3 days after earnings

    if days == 0:
        modifier = float(e_cfg.get("within_5_days_penalty", -20))
        force_defined_risk = True
    elif 1 <= days <= 5:
        modifier = float(e_cfg.get("within_5_days_penalty", -20))
        force_defined_risk = True
    elif 6 <= days <= 18:
        modifier = float(e_cfg.get("within_6_to_18_days_penalty", -5))
        force_defined_risk = False
    elif post_settling:
        # "Tentative restore," not an immediate full reset: the day after a
        # report still carries IV-crush/gap risk and estimates are still
        # being revised — post_settling used to be computed and returned
        # here but never actually changed the modifier, silently falling
        # through to the same 0.0 as 19+ days out (a full overnight cliff
        # from -20 to 0, despite the module docstring promising a gradual
        # "tentative restore"). Same caution magnitude as the 6-18-day
        # pre-earnings tier, not the near-earnings max.
        modifier = float(e_cfg.get("post_earnings_settling_penalty", -5))
        force_defined_risk = False
    else:
        modifier = float(e_cfg.get("beyond_18_days", 0))
        force_defined_risk = False

    # Clamp to config.modifier_bounds.earnings_proximity (default -20/0) —
    # Tier B batch 3 (2026-08-19): now reads from config instead of a bare
    # hardcoded [-20, 0], previously unenforced against a retuned penalty.
    bounds = cfg.get("modifier_bounds", {}).get("earnings_proximity", {})
    lo = float(bounds.get("min", -20.0))
    hi = float(bounds.get("max", 0.0))
    modifier = max(lo, min(hi, modifier))

    return {
        "days_to_earnings": days,
        "confidence_modifier": modifier,
        "force_defined_risk": force_defined_risk,
        "no_new_trades": no_new_trades,
        "post_earnings_settling": post_settling,
    }


def fetch_next_earnings_date(ticker: str) -> Optional[datetime]:
    """
    Fetch next earnings date from yfinance calendar.
    Returns UTC datetime or None if unavailable.
    """
    from shared.api_clients.market_data_client import fetch_earnings_calendar
    cal = fetch_earnings_calendar(ticker)
    if cal is None:
        return None
    return cal.get("next_earnings_date")
