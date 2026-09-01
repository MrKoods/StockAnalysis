"""
Deep news & events view — the concrete headlines and filings, grouped by
theme, on a recency timeline, with Alpha Vantage's per-ticker sentiment
aggregated and SEC 8-K item types decoded.

Feeds: Yahoo (yfinance), Finnhub /company-news, Alpha Vantage NEWS_SENTIMENT,
SEC EDGAR 8-K filings, Seeking Alpha editorial items.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from shared.utils.logger import get_logger
from shared.api_clients.news_client import (
    fetch_news_alpha_vantage,
    fetch_news_finnhub,
    fetch_news_yahoo,
)
from shared.api_clients.sec_edgar_client import fetch_recent_8k_filings
from shared.api_clients.sentiment_client import fetch_seeking_alpha_engagement
from shared.utils.ner_extractor import is_ticker_relevant

logger = get_logger(__name__)

# Theme -> keyword set. Order matters; first match wins per headline. Includes
# SEC 8-K item phrasings so filings classify sensibly alongside press headlines.
_THEMES = {
    "earnings / guidance": [
        "earnings", "eps", "revenue", "guidance", "beat", "miss", "outlook", "forecast",
        "quarterly results", "results of operations", "item 2.02",
    ],
    "analyst action": [
        "upgrade", "downgrade", "price target", "initiates coverage", "reiterates",
        "raised to", "cut to", "buy rating", "sell rating", "overweight", "underweight",
    ],
    "M&A / capital": [
        "acquire", "acquisition", "merger", "buyback", "repurchase", "dividend", "stake",
        "spinoff", "public offering", "raises $", "material definitive agreement",
        "item 1.01", "item 2.03", "direct financial obligation", "notes offering",
    ],
    "management / governance": [
        "ceo", "cfo", "resign", "appoint", "step down", "departure of directors",
        "election of directors", "appointment of certain officers", "item 5.02",
        "item 5.07", "vote of security holders",
    ],
    "regulation / legal": [
        "lawsuit", "antitrust", "doj", "ftc", "investigation", "subpoena", "fine",
        "settlement", "regulatory", "regulator", "tariff", "export control", "sanction", "ban on",
    ],
    "products / partnerships": [
        "launch", "unveil", "partnership", "deal with", "contract", "customer win",
        "supply agreement", "chip", "gpu", "data center", "ai model", "product",
    ],
    "macro / sector": ["fed ", "interest rates", "inflation", "recession", "sector rotation", "demand", "supply chain"],
}


def _parse(ts) -> Optional[datetime]:
    if isinstance(ts, datetime):
        return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def _normalize(articles: list[dict], source: str) -> list[dict]:
    out = []
    for a in articles or []:
        out.append({
            "title": (a.get("title") or a.get("headline") or "").strip(),
            "source": source,
            "publisher": a.get("publisher") or a.get("source") or source,
            "timestamp_utc": (_parse(a.get("timestamp_utc") or a.get("datetime")) or datetime.now(timezone.utc)).isoformat(),
            "url": a.get("url") or a.get("link") or "",
            "av_sentiment_score": a.get("overall_sentiment_score"),
            "ticker_sentiment": a.get("ticker_sentiment") or [],
        })
    return [a for a in out if a["title"]]


def _theme_of(title: str) -> str:
    t = title.lower()
    for theme, kws in _THEMES.items():
        if any(k in t for k in kws):
            return theme
    return "other"


def _av_sentiment(av_articles: list[dict], ticker: str) -> dict:
    scores = []
    for a in av_articles:
        for ts in a.get("ticker_sentiment", []):
            if ts.get("ticker", "").upper() == ticker.upper():
                try:
                    scores.append((float(ts.get("sentiment_score", 0)), float(ts.get("relevance_score", 0))))
                except (TypeError, ValueError):
                    pass
    if not scores:
        return {"article_count": 0}
    wsum = sum(rel for _, rel in scores) or len(scores)
    weighted = sum(s * rel for s, rel in scores) / wsum
    return {
        "article_count": len(scores),
        "weighted_sentiment": round(weighted, 3),
        "label": (
            "bullish" if weighted > 0.15 else "bearish" if weighted < -0.15 else "neutral"
        ),
    }


def _observations(d: dict) -> list[str]:
    obs: list[str] = []
    tl = d.get("timeline", {})
    obs.append(f"{d.get('total_headlines', 0)} headlines/filings in the window "
               f"({tl.get('last_3d', 0)} in the last 3 days, {tl.get('last_7d', 0)} in 7, "
               f"{tl.get('last_30d', 0)} in 30).")
    themes = d.get("themes", {})
    if themes:
        ranked = sorted(themes.items(), key=lambda kv: -len(kv[1]))
        obs.append("Themes: " + "; ".join(f"{name} ({len(items)})" for name, items in ranked[:5]) + ".")
        for name, items in ranked[:3]:
            obs.append(f"  [{name}] e.g. \"{items[0]['title']}\" ({items[0]['publisher']}, "
                       f"{items[0]['timestamp_utc'][:10]}).")
    av = d.get("av_sentiment", {})
    if av.get("article_count"):
        obs.append(f"Alpha Vantage per-ticker sentiment: {av['label']} "
                   f"(weighted {av['weighted_sentiment']} across {av['article_count']} scored articles).")
    filings = d.get("sec_8k", [])
    if filings:
        obs.append(f"{len(filings)} recent 8-K/6-K filing(s): "
                   + "; ".join(f"{f.get('filed', '?')} {f.get('title', '')}" for f in filings[:4]) + ".")
    if d.get("off_topic_headlines_dropped"):
        obs.append(f"({d['off_topic_headlines_dropped']} generic sector/market headlines were filtered "
                   "out as not referencing this company.)")
    if d.get("clusters"):
        for c in d["clusters"]:
            obs.append(f"Cluster: {c['count']} '{c['theme']}' items within {c['span_days']}d — possible catalyst.")
    return obs


def analyze_news(ticker: str, sector: Optional[str] = None) -> dict:
    """Deep news & events view for `ticker`."""
    def _try(fn, *a, **k):
        try:
            return fn(*a, **k) or []
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"{ticker}: {fn.__name__} failed — {exc}")
            return []

    def _relevant(articles):
        """Drop generic sector/market headlines that don't reference this company."""
        kept = [a for a in articles if is_ticker_relevant(a["title"], ticker)]
        return kept, len(articles) - len(kept)

    yahoo, yahoo_dropped = _relevant(_normalize(_try(fetch_news_yahoo, ticker), "yahoo"))
    finnhub, finnhub_dropped = _relevant(_normalize(_try(fetch_news_finnhub, ticker), "finnhub"))
    av_raw = _try(fetch_news_alpha_vantage, ticker)
    av, av_dropped = _relevant(_normalize(av_raw, "alpha_vantage"))
    # SA engagement is already a ticker-scoped editorial feed; 8-K titles embed
    # the symbol. Both are kept without the relevance gate.
    sa = _normalize(
        [{"title": i.get("title"), "timestamp_utc": i.get("timestamp_utc")} for i in _try(fetch_seeking_alpha_engagement, ticker)],
        "seeking_alpha",
    )
    filings_raw = _try(fetch_recent_8k_filings, ticker)
    filings = _normalize(filings_raw, "sec_8k")
    off_topic_dropped = yahoo_dropped + finnhub_dropped + av_dropped

    # De-dupe headlines by lowercased title
    seen, merged = set(), []
    for a in yahoo + finnhub + av + sa + filings:
        key = a["title"].lower()[:120]
        if key in seen:
            continue
        seen.add(key)
        merged.append(a)
    merged.sort(key=lambda a: a["timestamp_utc"], reverse=True)

    now = datetime.now(timezone.utc)
    def _within(days):
        return sum(1 for a in merged if (p := _parse(a["timestamp_utc"])) and p >= now - timedelta(days=days))

    themes: dict[str, list] = {}
    for a in merged:
        themes.setdefault(_theme_of(a["title"]), []).append(a)

    # Clusters: >=3 items on one theme within 5 days
    clusters = []
    for name, items in themes.items():
        if name == "other" or len(items) < 3:
            continue
        ts = sorted(_parse(i["timestamp_utc"]) for i in items if _parse(i["timestamp_utc"]))
        if ts and (ts[-1] - ts[0]).days <= 5:
            clusters.append({"theme": name, "count": len(items), "span_days": (ts[-1] - ts[0]).days})

    # 8-K titles come through as "NVDA 8-K: Item 5.02: Departure of Directors ..."
    sec_8k = [{"title": f["title"], "filed": f["timestamp_utc"][:10], "url": f["url"]} for f in filings]

    detail = {
        "total_headlines": len(merged),
        "off_topic_headlines_dropped": off_topic_dropped,
        "source_counts": {"yahoo": len(yahoo), "finnhub": len(finnhub), "alpha_vantage": len(av),
                          "seeking_alpha": len(sa), "sec_8k": len(filings)},
        "timeline": {"last_3d": _within(3), "last_7d": _within(7), "last_30d": _within(30)},
        "themes": {k: [{"title": i["title"], "publisher": i["publisher"], "timestamp_utc": i["timestamp_utc"],
                        "url": i["url"]} for i in v[:8]] for k, v in themes.items()},
        "av_sentiment": _av_sentiment(av_raw, ticker),
        "sec_8k": sec_8k,
        "clusters": clusters,
        "headlines": [{"title": a["title"], "publisher": a["publisher"], "source": a["source"],
                       "timestamp_utc": a["timestamp_utc"]} for a in merged[:40]],
    }

    dq = "complete" if len(merged) >= 8 else "partial" if merged else "unavailable"

    return {
        "summary": {
            "total_headlines": len(merged),
            "headlines_last_7d": detail["timeline"]["last_7d"],
            "top_theme": max(themes, key=lambda k: len(themes[k])) if themes else None,
            "av_sentiment_label": detail["av_sentiment"].get("label"),
            "recent_8k_count": len(filings),
        },
        "detail": detail,
        "observations": _observations(detail),
        "data_quality": dq,
    }
