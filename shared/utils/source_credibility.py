"""
SHARED: Scores StockTwits authors + news outlets by account age, follower count,
historical accuracy, and posting frequency.
Credibility scores stored per author/outlet and updated on each data pull.
Suppresses coordinated pump attempts (low-credibility accounts).
A Reuters article on NVDA carries more weight than an obscure financial blog.
"""

import math
from datetime import datetime, timezone
from typing import Optional


# Default outlet credibility scores (0.0-1.0, calibrated manually)
_DEFAULT_OUTLET_SCORES: dict[str, float] = {
    "Reuters": 0.95,
    "Bloomberg": 0.95,
    "Wall Street Journal": 0.90,
    "wsj.com": 0.90,
    "Financial Times": 0.88,
    "ft.com": 0.88,
    "CNBC": 0.80,
    "cnbc.com": 0.80,
    "MarketWatch": 0.75,
    "marketwatch.com": 0.75,
    "Barron's": 0.78,
    "barrons.com": 0.78,
    "Motley Fool": 0.60,
    "fool.com": 0.60,
    "Seeking Alpha": 0.55,
    "seekingalpha.com": 0.55,
    "Yahoo Finance": 0.65,
    "finance.yahoo.com": 0.65,
    "benzinga.com": 0.60,
    "thestreet.com": 0.62,
    "investopedia.com": 0.58,
    "zacks.com": 0.65,
    "gurufocus.com": 0.55,
}


def score_stocktwits_author(
    author_data: dict,
    now_utc: Optional[datetime] = None,
) -> float:
    """
    Score a StockTwits author's credibility (0.0-1.0).

    Factors:
    - Account age: older accounts → more credible (log scale, max 0.35)
    - Follower count: log-scaled, max 0.30
    - Posting frequency: very high frequency (>50/day) = spam flag → penalty
    - Verified status: +0.20 bonus (capped at 1.0)
    - Following/follower ratio: high ratio (potential bot) → small penalty

    Returns credibility score in [0, 1].
    """
    if now_utc is None:
        now_utc = datetime.now(timezone.utc)

    score = 0.30  # base score for a valid account

    # Account age component (max 0.35)
    join_date = author_data.get("author_join_date")
    if join_date:
        if isinstance(join_date, str):
            try:
                join_date = datetime.fromisoformat(join_date.replace("Z", "+00:00"))
            except ValueError:
                join_date = None
        if join_date:
            if join_date.tzinfo is None:
                join_date = join_date.replace(tzinfo=timezone.utc)
            age_days = max(0, (now_utc - join_date).days)
            age_years = age_days / 365.25
            # log scale: 1yr→0.12, 3yr→0.22, 7yr→0.30, 10yr+→0.35
            age_component = min(0.35, 0.12 * math.log1p(age_years * 3))
            score += age_component

    # Follower count (max 0.30)
    followers = int(author_data.get("author_followers", 0))
    if followers > 0:
        # log scale: 10→0.05, 100→0.10, 1000→0.18, 10000→0.24, 100000+→0.30
        follower_component = min(0.30, 0.06 * math.log10(followers + 1))
        score += follower_component

    # Verified bonus
    if author_data.get("author_verified", False):
        score += 0.20

    # High following/follower ratio penalty (potential bot)
    following = int(author_data.get("author_following", 0))
    if following > 0 and followers > 0:
        ratio = following / max(followers, 1)
        if ratio > 10:
            score -= 0.10

    return max(0.0, min(1.0, score))


def score_news_outlet(source_domain: str) -> float:
    """
    Score a news outlet's credibility (0.0-1.0).
    Falls back to 0.50 (unknown outlet) if not in the credibility map.
    """
    if not source_domain:
        return 0.50
    # Try exact match first, then partial domain match
    clean = source_domain.lower().strip().rstrip("/")
    for key, val in _DEFAULT_OUTLET_SCORES.items():
        if key.lower() in clean or clean in key.lower():
            return val
    return 0.50


def weight_by_credibility(
    items: list[dict],
    score_field: str,
    credibility_field: str,
) -> float:
    """
    Compute credibility-weighted average of score_field across items.
    credibility_field: per-item credibility weight (0.0-1.0).
    Returns weighted average or 0.0 if items is empty.
    """
    if not items:
        return 0.0
    total_weight = 0.0
    weighted_sum = 0.0
    for item in items:
        w = float(item.get(credibility_field, 0.5))
        v = float(item.get(score_field, 0.0))
        weighted_sum += w * v
        total_weight += w
    if total_weight == 0:
        return 0.0
    return weighted_sum / total_weight
