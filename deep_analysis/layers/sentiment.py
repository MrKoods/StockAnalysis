"""
Deep sentiment view — StockTwits crowd lean, message volume and velocity,
tagged-message quality, Seeking Alpha editorial engagement, and whether the
crowd confirms or diverges from recent price action.

Feeds: sentiment_client.fetch_stocktwits + fetch_seeking_alpha_engagement
(both RapidAPI). This layer stays the thinnest of the six — a real depth
upgrade needs a licensed sentiment feed or options-implied positioning
(see CHANGELOG v3.0.0).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from shared.utils.logger import get_logger
from shared.api_clients.sentiment_client import fetch_seeking_alpha_engagement, fetch_stocktwits

logger = get_logger(__name__)


def _parse(ts: str) -> Optional[datetime]:
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError, AttributeError):
        return None


def _stocktwits_view(messages: list[dict]) -> dict:
    now = datetime.now(timezone.utc)
    tagged = [m for m in messages if m.get("sentiment") in ("bullish", "bearish")]
    bull = sum(1 for m in tagged if m["sentiment"] == "bullish")
    bear = len(tagged) - bull
    d1 = sum(1 for m in messages if (p := _parse(m.get("timestamp_utc", ""))) and p >= now - timedelta(days=1))
    d3 = sum(1 for m in messages if (p := _parse(m.get("timestamp_utc", ""))) and p >= now - timedelta(days=3))
    oldest = min((p for m in messages if (p := _parse(m.get("timestamp_utc", "")))), default=None)
    span_days = (now - oldest).total_seconds() / 86400 if oldest else None
    return {
        "message_count": len(messages),
        "tagged_count": len(tagged),
        "bullish_tagged": bull,
        "bearish_tagged": bear,
        "bull_bear_ratio": round(bull / bear, 2) if bear else (None if not bull else float("inf")),
        "messages_last_24h": d1,
        "messages_last_3d": d3,
        "feed_span_days": round(span_days, 1) if span_days else None,
        "avg_likes": round(sum(m.get("likes", 0) or 0 for m in messages) / len(messages), 1) if messages else None,
    }


def _divergence(st: dict, price_change_5d_pct: Optional[float]) -> Optional[str]:
    if price_change_5d_pct is None or st.get("tagged_count", 0) < 8:
        return None
    ratio = st.get("bull_bear_ratio")
    if ratio is None:
        return None
    crowd_bull = ratio > 1.3
    crowd_bear = ratio < 0.77
    if crowd_bull and price_change_5d_pct < -0.03:
        return "crowd bullish while price fell >3% over 5 sessions (bearish divergence)"
    if crowd_bear and price_change_5d_pct > 0.03:
        return "crowd bearish while price rose >3% over 5 sessions (bullish divergence)"
    if crowd_bull and price_change_5d_pct > 0.03:
        return "crowd and price both up (confirmation)"
    if crowd_bear and price_change_5d_pct < -0.03:
        return "crowd and price both down (confirmation)"
    return "no clear divergence"


def _observations(st: dict, sa: dict, divergence: Optional[str]) -> list[str]:
    obs: list[str] = []
    if st.get("message_count"):
        obs.append(f"StockTwits: {st['message_count']} recent messages ({st.get('tagged_count')} sentiment-tagged), "
                   f"{st.get('bullish_tagged')} bullish / {st.get('bearish_tagged')} bearish "
                   f"(ratio {st.get('bull_bear_ratio')}).")
        if st.get("feed_span_days"):
            obs.append(f"Those messages span {st['feed_span_days']} days "
                       f"({st.get('messages_last_24h')} in the last 24h, {st.get('messages_last_3d')} in 3 days) "
                       "— a read on how actively the name is being discussed.")
    else:
        obs.append("StockTwits returned no recent messages — crowd sentiment unavailable for this name.")
    if sa.get("item_count"):
        obs.append(f"Seeking Alpha: {sa['item_count']} recent editorial items, "
                   f"{sa.get('total_comments')} total comments (avg {sa.get('avg_comments')}/item).")
    if divergence:
        obs.append(f"Sentiment vs price: {divergence}.")
    return obs


def analyze_sentiment(
    ticker: str, *, price_change_5d_pct: Optional[float] = None,
) -> dict:
    """Deep sentiment view for `ticker`. `price_change_5d_pct` enables the divergence read."""
    try:
        messages = fetch_stocktwits(ticker, limit=30) or []
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"{ticker}: StockTwits failed — {exc}")
        messages = []
    try:
        sa_items = fetch_seeking_alpha_engagement(ticker, limit=10) or []
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"{ticker}: SA engagement failed — {exc}")
        sa_items = []

    st = _stocktwits_view(messages)
    total_comments = sum(i.get("comment_count", 0) or 0 for i in sa_items)
    sa = {
        "item_count": len(sa_items),
        "total_comments": total_comments,
        "avg_comments": round(total_comments / len(sa_items), 1) if sa_items else None,
        "recent_titles": [i.get("title", "") for i in sa_items[:5]],
    }
    divergence = _divergence(st, price_change_5d_pct)

    dq = "complete" if (st["message_count"] >= 15 and sa["item_count"]) else \
         "partial" if (st["message_count"] or sa["item_count"]) else "unavailable"

    return {
        "summary": {
            "stocktwits_messages": st["message_count"],
            "bull_bear_ratio": st["bull_bear_ratio"],
            "messages_last_3d": st["messages_last_3d"],
            "sa_engagement_items": sa["item_count"],
            "sentiment_vs_price": divergence,
        },
        "detail": {"stocktwits": st, "seeking_alpha": sa, "divergence": divergence},
        "observations": _observations(st, sa, divergence),
        "data_quality": dq,
    }
