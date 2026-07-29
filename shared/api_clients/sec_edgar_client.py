"""
SHARED: Wraps SEC EDGAR's public company-filings feed for recent 8-K filings.

No API key required — SEC EDGAR is free and public, but SEC's fair-access
policy requires a descriptive User-Agent identifying the requester. Set
SEC_EDGAR_USER_AGENT in .env to "YourApp your-email@example.com"; falls back
to a generic identifier if unset (works, but SEC recommends a real contact).

An 8-K is a company's own legally-required disclosure of a material event
(executive departure, delisting notice, restructuring, etc.) — filed directly
with the regulator, not reported through a third party, so it's about as
authoritative as a News source can get (scored 1.0 credibility, see
shared/utils/source_credibility.py). Folded into the News layer's article
pool the same way Yahoo/Finnhub/Seeking Alpha are: a plain per-ticker fetch
returning the same article shape, no separate scoring path.

Response shape verified directly against the live endpoint (2026-07-29):
GET https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}&type=8-K&output=atom
returns an Atom feed where each <entry>'s <summary> already contains
human-readable "Item X.XX: <description>" text (e.g. "Item 5.02: Departure of
Directors or Certain Officers...") — that description is what actually makes
an 8-K useful to the keyword-based event severity gate, unlike the generic
"8-K - Current report" <title>, which never varies.
"""

import os
import re
import time
from datetime import datetime, timezone
from typing import Optional
from xml.etree import ElementTree as ET

import requests

from shared.utils.logger import get_logger

logger = get_logger(__name__)

_TICKER_MAP_URL = "https://www.sec.gov/files/company_tickers.json"
_BROWSE_EDGAR_URL = "https://www.sec.gov/cgi-bin/browse-edgar"
_BACKOFF_DELAYS = [30, 60, 120]
_ATOM_NS = {"atom": "http://www.w3.org/2005/Atom"}

# Module-level cache: SEC's ticker->CIK map is ~800KB and changes rarely, so
# fetching it once per process (not once per ticker per scan) is enough.
_ticker_cik_cache: Optional[dict] = None


def _user_agent() -> str:
    return os.environ.get(
        "SEC_EDGAR_USER_AGENT",
        "StockAnalysis-SwingModel research@stockanalysis.local",
    )


def _get_with_backoff(url: str, params: Optional[dict] = None, retries: int = 3) -> Optional[requests.Response]:
    """GET with exponential backoff (30s -> 60s -> 120s). Returns the raw Response or None."""
    for attempt in range(retries):
        try:
            resp = requests.get(url, params=params, timeout=15, headers={"User-Agent": _user_agent()})
            resp.raise_for_status()
            return resp
        except Exception as exc:
            if attempt < len(_BACKOFF_DELAYS):
                logger.warning(f"[sec_edgar] Request failed (attempt {attempt + 1}): {exc}. Retry in {_BACKOFF_DELAYS[attempt]}s.")
                time.sleep(_BACKOFF_DELAYS[attempt])
    logger.error(f"[sec_edgar] All retries exhausted for {url}")
    return None


def _load_ticker_cik_map() -> dict:
    """
    Fetch and cache SEC's ticker -> CIK mapping for the lifetime of this process.
    Returns {ticker: 10-digit zero-padded CIK string}. Empty dict on failure.
    """
    global _ticker_cik_cache
    if _ticker_cik_cache is not None:
        return _ticker_cik_cache

    resp = _get_with_backoff(_TICKER_MAP_URL)
    if resp is None:
        _ticker_cik_cache = {}
        return _ticker_cik_cache

    try:
        raw = resp.json()
    except ValueError as exc:
        logger.error(f"[sec_edgar] Ticker map response wasn't JSON: {exc}")
        _ticker_cik_cache = {}
        return _ticker_cik_cache

    mapping = {}
    for entry in raw.values():
        ticker = str(entry.get("ticker", "")).upper()
        cik = entry.get("cik_str")
        if ticker and cik is not None:
            mapping[ticker] = str(cik).zfill(10)
    _ticker_cik_cache = mapping
    return mapping


def _extract_item_descriptions(summary_text: Optional[str]) -> str:
    """
    Pull human-readable "Item X.XX: <description>" lines out of EDGAR's
    <summary> field (HTML-ish text like " <b>Filed:</b> ... <br>Item 5.02:
    Departure of Directors...<br>Item 9.01: ..."), dropping the boilerplate
    Filed/AccNo/Size prefix line. Returns segments joined with "; ", or ""
    if none matched.
    """
    if not summary_text:
        return ""
    segments = re.split(r"<br\s*/?>", summary_text, flags=re.IGNORECASE)
    items = []
    for seg in segments:
        clean = re.sub(r"<[^>]+>", "", seg).strip()
        if clean.lower().startswith("item "):
            items.append(clean)
    return "; ".join(items)


def fetch_recent_8k_filings(ticker: str, limit: int = 10) -> list[dict]:
    """
    Fetch recent 8-K filings for `ticker` from SEC EDGAR.

    Returns list of dicts (same shape as fetch_news_yahoo/fetch_news_finnhub):
    {article_id, timestamp_utc, title, url, source, source_domain,
     overall_sentiment_score, overall_sentiment_label, ticker_sentiment}
    No pre-computed sentiment — NER applied downstream like the other free
    sources. Title always embeds the ticker symbol (e.g. "NVDA 8-K: Item
    5.02: ...") so is_ticker_relevant() matches it even when the item
    description alone doesn't name the company.
    Returns [] if the ticker's CIK can't be resolved or the feed is unavailable.
    """
    cik_map = _load_ticker_cik_map()
    cik = cik_map.get(ticker.upper())
    if not cik:
        logger.warning(f"[sec_edgar] No CIK found for {ticker} — skipping 8-K fetch.")
        return []

    params = {
        "action": "getcompany",
        "CIK": cik,
        "type": "8-K",
        "dateb": "",
        "owner": "include",
        "count": limit,
        "output": "atom",
    }
    resp = _get_with_backoff(_BROWSE_EDGAR_URL, params=params)
    if resp is None:
        return []

    try:
        root = ET.fromstring(resp.content)
    except ET.ParseError as exc:
        logger.error(f"[sec_edgar] Failed to parse Atom feed for {ticker}: {exc}")
        return []

    articles = []
    for entry in root.findall("atom:entry", _ATOM_NS):
        summary_el = entry.find("atom:summary", _ATOM_NS)
        updated_el = entry.find("atom:updated", _ATOM_NS)
        link_el = entry.find("atom:link", _ATOM_NS)

        item_desc = _extract_item_descriptions(summary_el.text if summary_el is not None else None)
        title = f"{ticker} 8-K: {item_desc}" if item_desc else f"{ticker} 8-K filing"
        link = link_el.get("href") if link_el is not None else ""

        ts_raw = updated_el.text if updated_el is not None else None
        try:
            ts = datetime.fromisoformat(ts_raw) if ts_raw else datetime.now(timezone.utc)
            ts = ts.astimezone(timezone.utc) if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
        except ValueError:
            ts = datetime.now(timezone.utc)

        articles.append({
            "article_id": link or f"{cik}-{ts.isoformat()}",
            "timestamp_utc": ts.isoformat(),
            "title": title,
            "url": link,
            "source": "SEC EDGAR",
            "source_domain": "sec.gov",
            "overall_sentiment_score": None,
            "overall_sentiment_label": None,
            "ticker_sentiment": [],
        })

    logger.info(f"SEC EDGAR: fetched {len(articles)} 8-K filing(s) for {ticker}.")
    return articles
