"""
SHARED: Tracks how a signal's conviction decays over time.
A breakout signal that hasn't triggered entry after 3 days is less actionable.
Signal decay is applied before each scan run to age queued candidates.
Decay schedule: no decay for 1 day; linear decay days 2-4; signal expires at day 5.
Also tracks win-rate feedback per signal type from signal_win_rates.json.
"""

import json
import math
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

_WIN_RATES_FILE = Path("data/processed/signal_win_rates.json")

# Days until a queued signal expires (no entry triggered)
SIGNAL_EXPIRY_DAYS = 5

# Minimum decay factor before signal is expired
MIN_DECAY_FACTOR = 0.0


def compute_signal_decay(
    signal_generated_at_utc: datetime,
    now_utc: Optional[datetime] = None,
    decay_style: str = "linear",
    expiry_days: int = SIGNAL_EXPIRY_DAYS,
) -> float:
    """
    Compute decay factor for a signal that hasn't yet triggered entry.

    decay_style:
    - 'linear': full strength day 0-1; linear decline days 1-5; 0 at day 5
    - 'exponential': exp decay with halflife of 2 days

    Returns multiplier in [0.0, 1.0].
    0.0 = signal expired; 1.0 = signal at full strength.
    """
    if now_utc is None:
        now_utc = datetime.now(timezone.utc)
    if signal_generated_at_utc.tzinfo is None:
        signal_generated_at_utc = signal_generated_at_utc.replace(tzinfo=timezone.utc)

    age_days = (now_utc - signal_generated_at_utc).total_seconds() / 86400.0

    if age_days >= expiry_days:
        return 0.0
    if age_days <= 1.0:
        return 1.0

    if decay_style == "exponential":
        halflife = expiry_days / 2.5
        return max(0.0, math.exp(-age_days / halflife))

    # Linear decay: from 1.0 at day 1 to 0.0 at day expiry_days
    return max(0.0, 1.0 - (age_days - 1.0) / (expiry_days - 1.0))


def apply_signal_decay_to_score(
    base_score: float,
    decay_factor: float,
    floor_score: float = 80.0,
) -> float:
    """
    Apply decay to a confidence score.
    Score decays toward floor_score (keeps directional conviction but loses urgency).
    final_score = floor_score + (base_score - floor_score) × decay_factor
    """
    if decay_factor >= 1.0:
        return base_score
    decayed = floor_score + (base_score - floor_score) * decay_factor
    return round(max(0.0, decayed), 2)


def is_signal_expired(
    signal_generated_at_utc: datetime,
    now_utc: Optional[datetime] = None,
    expiry_days: int = SIGNAL_EXPIRY_DAYS,
) -> bool:
    """Return True if the signal is too old to act on."""
    if now_utc is None:
        now_utc = datetime.now(timezone.utc)
    if signal_generated_at_utc.tzinfo is None:
        signal_generated_at_utc = signal_generated_at_utc.replace(tzinfo=timezone.utc)
    age_days = (now_utc - signal_generated_at_utc).total_seconds() / 86400.0
    return age_days >= expiry_days


def load_signal_win_rates() -> dict:
    """
    Load historical win rates per signal type from signal_win_rates.json.
    Used by the feedback loop (Phase 14) to adjust sub-signal weights.
    Returns empty dict if file not found.
    """
    if not _WIN_RATES_FILE.exists():
        return {}
    try:
        return json.loads(_WIN_RATES_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def update_signal_win_rate(
    signal_type: str,
    outcome: str,  # 'win' | 'loss' | 'scratch'
) -> None:
    """
    Immediate feedback loop update: log outcome for a signal type.
    Does NOT update live scoring weights — that happens in monthly calibration (Phase 14).
    """
    rates = load_signal_win_rates()
    if signal_type not in rates:
        rates[signal_type] = {"wins": 0, "losses": 0, "scratches": 0, "total": 0}

    rates[signal_type]["total"] += 1
    if outcome == "win":
        rates[signal_type]["wins"] += 1
    elif outcome == "loss":
        rates[signal_type]["losses"] += 1
    else:
        rates[signal_type]["scratches"] += 1

    _WIN_RATES_FILE.parent.mkdir(parents=True, exist_ok=True)
    _WIN_RATES_FILE.write_text(json.dumps(rates, indent=2))


def get_win_rate(signal_type: str) -> Optional[float]:
    """Return historical win rate for a signal type, or None if insufficient data."""
    rates = load_signal_win_rates()
    if signal_type not in rates:
        return None
    data = rates[signal_type]
    total = data.get("total", 0)
    if total < 10:  # Require minimum sample before trusting win rate
        return None
    return data["wins"] / total
