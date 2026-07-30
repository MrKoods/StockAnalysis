"""
SHARED: Wraps SEC EDGAR's public company-filings feed for recent 8-K filings,
plus a hyperscaler capex-context signal for the semiconductor sector.

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

fetch_hyperscaler_capex_snippets() goes one level deeper for a specific need:
the atom <summary> is only ever the generic Item-code boilerplate above — it
never contains actual company commentary, so it can't detect a real capex
change. The real number/commentary lives in the filing's attached press
release (Exhibit 99.x — SEC's near-universal naming convention includes
"ex99" in the filename), which requires fetching the filing's own index.json
and then the exhibit document itself. Verified against AMZN's Q1 2026
earnings 8-K: the atom <summary> for that filing has zero capex-related
text, while the actual exhibit mentions "$59.3 billion in purchases of
property and equipment" (Amazon's capex line item) and real AI-infrastructure
commentary. Returns short text snippets around capex-context terms as
article-shaped dicts so the Event Severity Gate's existing keyword matching
(config/swing_config.yaml event_severity_gate.sector_triggers.semiconductors)
can classify a real capex cut for real, instead of matching against
boilerplate that never varies.
"""

import hashlib
import html
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

# Items where earnings/operational commentary (and so capex commentary)
# actually shows up: 2.02 (results of operations), 7.01 (Reg FD — often an
# investor-update press release), 8.01 (other events — catch-all, used for
# major infrastructure announcements too).
_EARNINGS_RELATED_ITEMS = ("2.02", "7.01", "8.01")

# Amazon's cash-flow-statement phrasing ("purchases of property and
# equipment") is deliberately included alongside the more generic terms —
# different filers use different GAAP line-item language for the same thing.
_CAPEX_CONTEXT_TERMS = [
    "purchases of property and equipment",
    "capital expenditures",
    "capital expenditure",
    "capex",
    "infrastructure investment",
    "data center",
    "AI infrastructure",
]

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


def _parse_atom_timestamp(ts_raw: Optional[str]) -> datetime:
    """Parse an Atom <updated> value (e.g. "2026-07-02T09:23:16-04:00") to UTC."""
    try:
        ts = datetime.fromisoformat(ts_raw) if ts_raw else datetime.now(timezone.utc)
        return ts.astimezone(timezone.utc) if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
    except ValueError:
        return datetime.now(timezone.utc)


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
        ts = _parse_atom_timestamp(updated_el.text if updated_el is not None else None)

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


def _fetch_filing_entries(cik: str, limit: int) -> list[dict]:
    """
    Fetch the raw Atom entry data (item codes, filing index URL, timestamp)
    for a CIK's recent 8-Ks — a lighter-weight sibling of fetch_recent_8k_filings
    that returns fields needed to locate exhibit documents, not article dicts.
    """
    params = {
        "action": "getcompany", "CIK": cik, "type": "8-K", "dateb": "",
        "owner": "include", "count": limit, "output": "atom",
    }
    resp = _get_with_backoff(_BROWSE_EDGAR_URL, params=params)
    if resp is None:
        return []

    try:
        root = ET.fromstring(resp.content)
    except ET.ParseError as exc:
        logger.error(f"[sec_edgar] Failed to parse Atom feed: {exc}")
        return []

    entries = []
    for entry in root.findall("atom:entry", _ATOM_NS):
        content_el = entry.find("atom:content", _ATOM_NS)
        updated_el = entry.find("atom:updated", _ATOM_NS)
        if content_el is None:
            continue
        items_desc_el = content_el.find("atom:items-desc", _ATOM_NS)
        filing_href_el = content_el.find("atom:filing-href", _ATOM_NS)
        entries.append({
            "items_desc": (items_desc_el.text or "") if items_desc_el is not None else "",
            "filing_href": filing_href_el.text if filing_href_el is not None else None,
            "updated": updated_el.text if updated_el is not None else None,
        })
    return entries


def _list_filing_exhibits(filing_href: Optional[str]) -> list[str]:
    """
    Given a filing's "...-index.htm" URL, return absolute URLs of its
    Exhibit 99.x documents via the filing's machine-readable index.json —
    SEC's near-universal filename convention for press releases/exhibits
    includes "ex99" (case-insensitive), verified against real filings from
    multiple filers/filing agents.
    """
    if not filing_href or "-index.htm" not in filing_href:
        return []
    base_url = filing_href.rsplit("/", 1)[0]
    resp = _get_with_backoff(f"{base_url}/index.json")
    if resp is None:
        return []
    try:
        data = resp.json()
    except ValueError:
        return []

    items = data.get("directory", {}).get("item", [])
    return [
        f"{base_url}/{item['name']}"
        for item in items
        if "ex99" in item.get("name", "").lower()
    ]


def _extract_capex_snippets(html_text: str, max_snippets: int = 2) -> list[str]:
    """
    Strip HTML and pull short text windows (±150 chars) around capex-context
    phrases (_CAPEX_CONTEXT_TERMS). This is intentionally NOT trying to
    classify direction (cut vs. increase) itself — that's the Event Severity
    Gate's job via its existing keyword matching; this just surfaces the real
    sentence so that matching has real text to work with instead of
    boilerplate. Skips windows that overlap an already-captured one so two
    context terms in the same sentence don't produce near-duplicate snippets.
    """
    text = re.sub(r"<[^>]+>", " ", html_text)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()

    snippets = []
    seen_spans: list[tuple[int, int]] = []
    for term in _CAPEX_CONTEXT_TERMS:
        for m in re.finditer(re.escape(term), text, re.IGNORECASE):
            start, end = max(0, m.start() - 150), min(len(text), m.end() + 150)
            if any(abs(start - s) < 100 for s, _ in seen_spans):
                continue
            seen_spans.append((start, end))
            snippets.append(text[start:end])
            if len(snippets) >= max_snippets:
                return snippets
    return snippets


def fetch_hyperscaler_capex_snippets(
    ticker: str,
    filing_limit: int = 5,
    max_relevant_filings: int = 3,
    max_snippets_per_filing: int = 2,
) -> list[dict]:
    """
    Fetch `ticker`'s recent earnings/operational 8-Ks (Items 2.02/7.01/8.01 —
    where capex commentary actually appears), pull each one's Exhibit 99.x
    press release, and return short text snippets mentioning capex-context
    terms as article-shaped dicts (same shape as fetch_recent_8k_filings).

    Intended for the four hyperscalers (AMZN/MSFT/GOOGL/META — see
    config/swing_config.yaml watchlist.sectors.semiconductors.
    capex_context_tickers) as a semiconductor-sector demand signal: AI
    infrastructure capex is the demand driver behind chip sector moves, and
    it shows up in these filings before it reaches general news. Not
    ticker-specific to the semiconductor watchlist itself — these are context
    tickers, not part of the tradeable list.

    Returns [] if the ticker's CIK can't be resolved, no earnings-related
    filing is found, or none of the exhibits mention a capex-context term.
    """
    cik_map = _load_ticker_cik_map()
    cik = cik_map.get(ticker.upper())
    if not cik:
        logger.warning(f"[sec_edgar] No CIK found for {ticker} — skipping capex snippet fetch.")
        return []

    entries = _fetch_filing_entries(cik, filing_limit)
    relevant_entries = [
        e for e in entries
        if any(item in e["items_desc"] for item in _EARNINGS_RELATED_ITEMS)
    ][:max_relevant_filings]

    articles = []
    for entry in relevant_entries:
        exhibit_urls = _list_filing_exhibits(entry["filing_href"])
        ts = _parse_atom_timestamp(entry["updated"])

        for ex_url in exhibit_urls:
            resp = _get_with_backoff(ex_url)
            if resp is None:
                continue
            for snippet in _extract_capex_snippets(resp.text, max_snippets=max_snippets_per_filing):
                snippet_hash = hashlib.md5(snippet.encode("utf-8")).hexdigest()[:12]
                articles.append({
                    "article_id": f"{ex_url}#{snippet_hash}",
                    "timestamp_utc": ts.isoformat(),
                    "title": f'{ticker} 8-K exhibit: "{snippet}"',
                    "url": ex_url,
                    "source": "SEC EDGAR",
                    "source_domain": "sec.gov",
                    "overall_sentiment_score": None,
                    "overall_sentiment_label": None,
                    "ticker_sentiment": [],
                })

    logger.info(f"SEC EDGAR: fetched {len(articles)} capex-context snippet(s) for {ticker}.")
    return articles
