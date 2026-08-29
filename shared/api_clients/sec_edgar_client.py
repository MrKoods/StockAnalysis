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
from datetime import datetime, timezone
from typing import Optional
from xml.etree import ElementTree as ET

from shared.utils.logger import get_logger, write_validation_entry
from shared.api_clients._http_backoff import http_get_with_backoff
from shared.api_clients import cache, rate_limiter

logger = get_logger(__name__)

_TICKER_MAP_URL = "https://www.sec.gov/files/company_tickers.json"
_BROWSE_EDGAR_URL = "https://www.sec.gov/cgi-bin/browse-edgar"
_ATOM_NS = {"atom": "http://www.w3.org/2005/Atom"}

# data.sec.gov JSON API — the fast structured feed (submissions history +
# XBRL financial facts), distinct from the slow browse-edgar Atom endpoint the
# news-filing path above uses. One submissions call returns a company's entire
# recent filing list with form types; one companyconcept call returns a single
# financial line item as a full time series.
_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
_COMPANY_CONCEPT_URL = "https://data.sec.gov/api/xbrl/companyconcept/CIK{cik}/{taxonomy}/{concept}.json"

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

# Which current-report form each ticker actually files, discovered on first
# fetch and reused for the rest of the process. See fetch_recent_8k_filings.
_ticker_form_type_cache: dict[str, str] = {}

# A domestic filer's current report is an 8-K; a FOREIGN PRIVATE ISSUER files a
# 6-K instead and never files an 8-K at all. Verified against SEC's submissions
# API on 2026-08-26: TSM has 712 6-K filings and 0 8-K, ASML has 361 and 0,
# while domestic NVDA has 63 8-K. EDGAR's browse-edgar `type` parameter takes a
# single value, so covering both means trying one and falling back.
_FORM_8K = "8-K"
_FORM_6K = "6-K"


def _user_agent() -> str:
    return os.environ.get(
        "SEC_EDGAR_USER_AGENT",
        "StockAnalysis-SwingModel research@stockanalysis.local",
    )


def _get_with_backoff(url: str, params: Optional[dict] = None, retries: int = 3):
    """GET with exponential backoff (30s -> 60s -> 120s). Returns the raw Response or None."""
    rate_limiter.acquire("www.sec.gov")
    return http_get_with_backoff(
        url, params=params, headers={"User-Agent": _user_agent()},
        retries=retries, parse_json=False, label="sec_edgar", timeout=30,
    )


def _load_ticker_cik_map() -> dict:
    """
    SEC's ticker -> CIK mapping. Cached in-process AND on disk for 30 days
    (cache.TTL["sec_cik_map"]) — it's an ~800KB download that changes rarely,
    and each scan is a fresh process, so a process-only cache meant re-fetching
    it 3x/day. Returns {ticker: 10-digit zero-padded CIK string}, {} on failure.
    """
    global _ticker_cik_cache
    if _ticker_cik_cache is not None:
        return _ticker_cik_cache

    _ticker_cik_cache = cache.cached_call(
        "news", "sec_cik_map", cache.TTL["sec_cik_map"], _fetch_ticker_cik_map,
    ) or {}
    return _ticker_cik_cache


def _fetch_ticker_cik_map() -> dict:
    resp = _get_with_backoff(_TICKER_MAP_URL)
    if resp is None:
        return {}

    try:
        raw = resp.json()
    except ValueError as exc:
        logger.error(f"[sec_edgar] Ticker map response wasn't JSON: {exc}")
        return {}

    mapping = {}
    for entry in raw.values():
        ticker = str(entry.get("ticker", "")).upper()
        cik = entry.get("cik_str")
        if ticker and cik is not None:
            mapping[ticker] = str(cik).zfill(10)
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
    Fetch recent current-report filings for `ticker` from SEC EDGAR.

    Returns list of dicts (same shape as fetch_news_yahoo/fetch_news_finnhub):
    {article_id, timestamp_utc, title, url, source, source_domain,
     overall_sentiment_score, overall_sentiment_label, ticker_sentiment}
    No pre-computed sentiment — NER applied downstream like the other free
    sources. Title always embeds the ticker symbol (e.g. "NVDA 8-K: Item
    5.02: ...") so is_ticker_relevant() matches it even when the item
    description alone doesn't name the company.
    Returns [] if the ticker's CIK can't be resolved or the feed is unavailable.

    Covers BOTH 8-K and 6-K (2026-08-26, v2.2.107). This asked for `type=8-K`
    only, which a foreign private issuer never files — it files a 6-K instead,
    the same "material event happened" current report. TSM and ASML therefore
    returned zero filings on every scan since the SEC source was added, and
    silently: an empty feed is indistinguishable from "nothing was filed". That
    is 2 of 11 semiconductors permanently blind on this input, and because
    these filings feed the Event Severity Gate, neither could ever raise a
    ticker-specific critical event from its own disclosures. Verified against
    SEC's submissions API on 2026-08-26 — TSM: 712 6-K / 0 8-K, ASML: 361 / 0,
    domestic NVDA: 63 8-K.

    EDGAR's `type` parameter takes one value, so this tries 8-K first and falls
    back to 6-K when that comes back empty, caching whichever produced results
    for the rest of the process. Domestic filers therefore cost exactly one
    request as before; a foreign issuer costs two on its first fetch of the run.
    Deliberately discovery-based rather than a hardcoded ticker list: it works
    for any foreign issuer added to the watchlist later without anyone
    remembering this distinction exists.

    Cross-scan result cached ~20h (cache.TTL["sec_submissions"]): a company's
    own 8-K/6-K stream changes at most a couple of times a week, and the slow
    browse-edgar endpoint was the dominant contributor to scan wall-time.
    """
    return cache.cached_call(
        "news", f"sec_{ticker}_{limit}", cache.TTL["sec_submissions"],
        lambda: _fetch_recent_8k_filings_uncached(ticker, limit),
    )


def _fetch_recent_8k_filings_uncached(ticker: str, limit: int = 10) -> list[dict]:
    cik_map = _load_ticker_cik_map()
    cik = cik_map.get(ticker.upper())
    if not cik:
        logger.warning(f"[sec_edgar] No CIK found for {ticker} — skipping filing fetch.")
        return []

    key = ticker.upper()
    cached = _ticker_form_type_cache.get(key)
    form_types = [cached] if cached else [_FORM_8K, _FORM_6K]

    for form_type in form_types:
        articles = _fetch_filings_for_form(ticker, cik, form_type, limit)

        # None means the REQUEST failed (network error, SEC throttle/block,
        # unparseable feed); [] means the request succeeded and this company
        # genuinely has no recent filings of this type. Collapsing the two was
        # the real hazard here (2026-08-26, v2.2.109): an SEC block returned
        # exactly what a quiet news week returns, so the model would lose one
        # of five news sources AND all filing-based Event Severity Gate
        # triggers while looking completely healthy — scores drifting down
        # across the board with no visible cause. Precisely the shape of the
        # TSM/ASML 8-K bug fixed one version earlier.
        #
        # This also matters for the 8-K -> 6-K fallback directly above: on a
        # FAILED 8-K request we must not fall through and cache 6-K as this
        # ticker's form type, which would silently mislabel a domestic filer
        # off the back of a transient outage.
        if articles is None:
            write_validation_entry(
                ticker, "sec_edgar", f"sec_edgar_request_failed_{form_type}"
            )
            logger.warning(
                f"[sec_edgar] {ticker}: {form_type} request FAILED (not an empty result) — "
                f"filings unavailable this scan; news and event-gate coverage reduced."
            )
            return []

        if articles:
            _ticker_form_type_cache[key] = form_type
            return articles

    logger.info(f"SEC EDGAR: no recent filings for {ticker} (request succeeded).")
    return []


def _fetch_filings_for_form(
    ticker: str, cik: str, form_type: str, limit: int,
) -> Optional[list[dict]]:
    """
    One EDGAR browse-edgar Atom request for a single form type.

    Returns None if the request or parse FAILED, [] if it succeeded and there
    are no filings of this type. The caller depends on telling those apart —
    see fetch_recent_8k_filings.
    """
    params = {
        "action": "getcompany",
        "CIK": cik,
        "type": form_type,
        "dateb": "",
        "owner": "include",
        "count": limit,
        "output": "atom",
    }
    resp = _get_with_backoff(_BROWSE_EDGAR_URL, params=params)
    if resp is None:
        return None  # request failed — NOT "no filings"

    try:
        root = ET.fromstring(resp.content)
    except ET.ParseError as exc:
        logger.error(f"[sec_edgar] Failed to parse Atom feed for {ticker}: {exc}")
        return None  # malformed feed is a failure, not an empty result

    articles = []
    for entry in root.findall("atom:entry", _ATOM_NS):
        summary_el = entry.find("atom:summary", _ATOM_NS)
        updated_el = entry.find("atom:updated", _ATOM_NS)
        link_el = entry.find("atom:link", _ATOM_NS)

        item_desc = _extract_item_descriptions(summary_el.text if summary_el is not None else None)
        title = f"{ticker} {form_type}: {item_desc}" if item_desc else f"{ticker} {form_type} filing"
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

    logger.info(f"SEC EDGAR: fetched {len(articles)} {form_type} filing(s) for {ticker}.")
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


# ===========================================================================
# data.sec.gov JSON API — structured filing history + XBRL financial facts.
# Used by the Fundamental layer (companyfacts) and Positioning (13F/13D-G/Form4
# detection from the submissions feed). Free, uncapped, no key.
# ===========================================================================


def _get_json(url: str) -> Optional[dict]:
    """GET a data.sec.gov JSON endpoint (via the paced _get_with_backoff). Returns the parsed dict or None."""
    resp = _get_with_backoff(url)
    if resp is None:
        return None
    try:
        return resp.json()
    except ValueError as exc:
        logger.warning(f"[sec_edgar] {url}: response wasn't JSON ({exc})")
        return None


def fetch_submissions(ticker: str) -> Optional[dict]:
    """
    A company's recent filing history from data.sec.gov/submissions/CIK.json —
    one call returns the last ~1000 filings with form type, date, and accession
    number. Cached ~20h (cache.TTL["sec_submissions"]).

    Returns the trimmed dict {cik, name, recent: [{form, filingDate,
    accessionNumber, primaryDocument}, ...]} or None if the CIK can't be
    resolved / the request fails.
    """
    cik = _load_ticker_cik_map().get(ticker.upper())
    if not cik:
        logger.warning(f"[sec_edgar] No CIK for {ticker} — cannot fetch submissions.")
        return None

    def _fetch():
        data = _get_json(_SUBMISSIONS_URL.format(cik=cik))
        if not data:
            return None
        recent = data.get("filings", {}).get("recent", {})
        forms = recent.get("form", [])
        dates = recent.get("filingDate", [])
        accns = recent.get("accessionNumber", [])
        docs = recent.get("primaryDocument", [])
        rows = [
            {
                "form": forms[i],
                "filingDate": dates[i] if i < len(dates) else None,
                "accessionNumber": accns[i] if i < len(accns) else None,
                "primaryDocument": docs[i] if i < len(docs) else None,
            }
            for i in range(len(forms))
        ]
        return {"cik": cik, "name": data.get("name", ""), "recent": rows}

    return cache.cached_call("sec_submissions", f"subs_{ticker}", cache.TTL["sec_submissions"], _fetch)


# Forms that signal informed-money positioning, checked against the submissions
# feed. 13F-HR = institutional manager holdings (quarterly). SC 13D = an
# activist / control-intent >5% stake. SC 13G = a passive >5% stake. 4 = an
# insider (officer/director/10% holder) transaction. Suffixed variants (/A
# amendments, 13F-HR/A, SC 13D/A) are matched by prefix.
_POSITIONING_FORM_PREFIXES = ("SC 13D", "SC 13G", "13F-HR", "4")


def fetch_recent_ownership_filings(ticker: str, lookback_days: int = 120) -> dict:
    """
    Pull recent ownership/positioning filings for `ticker` out of its
    submissions feed: activist/passive >5% stakes (SC 13D/13G), institutional
    holdings reports (13F-HR), and insider transactions (Form 4).

    Returns {"activist_13d": [...], "passive_13g": [...], "institutional_13f":
    [...], "insider_form4": [...]} where each list holds {form, filingDate,
    accessionNumber} dicts inside the lookback window, most-recent-first.
    Empty lists (never None) so callers can treat "no filing" as a real,
    neutral signal. Cached via fetch_submissions.
    """
    out = {"activist_13d": [], "passive_13g": [], "institutional_13f": [], "insider_form4": []}
    subs = fetch_submissions(ticker)
    if not subs:
        return out

    cutoff = (datetime.now(timezone.utc).date()).toordinal() - lookback_days
    bucket = {
        "SC 13D": "activist_13d",
        "SC 13G": "passive_13g",
        "13F-HR": "institutional_13f",
        "4": "insider_form4",
    }
    for row in subs["recent"]:
        form = (row.get("form") or "").strip()
        fdate = row.get("filingDate")
        try:
            if fdate and datetime.strptime(fdate, "%Y-%m-%d").date().toordinal() < cutoff:
                continue
        except ValueError:
            continue
        for prefix, key in bucket.items():
            if form == prefix or form.startswith(prefix + "/"):
                out[key].append({
                    "form": form,
                    "filingDate": fdate,
                    "accessionNumber": row.get("accessionNumber"),
                })
                break
    return out


def fetch_financial_facts(ticker: str, concepts: list[str], taxonomy: str = "us-gaap") -> dict:
    """
    Fetch a set of XBRL financial line items for `ticker` from
    data.sec.gov/api/xbrl/companyconcept — one HTTP call per concept, each
    cached ~7 days (cache.TTL["sec_companyfacts"]).

    concepts: GAAP concept names, e.g. ["Revenues", "GrossProfit",
      "ResearchAndDevelopmentExpense"] for semis, or ["Deposits",
      "InterestAndDividendIncomeOperating", "NetIncomeLoss"] for banks.

    Returns {concept: [{"end": "YYYY-MM-DD", "val": float, "fy": int,
    "fp": "Q1".."FY", "form": "10-Q"|"10-K"}, ...]} sorted oldest-first, with
    only the most recent value per period end kept (later amendments win).
    A concept with no data (the filer tags it differently, or doesn't report
    it) is simply absent from the returned dict.
    """
    cik = _load_ticker_cik_map().get(ticker.upper())
    if not cik:
        return {}

    result: dict = {}
    for concept in concepts:
        def _fetch(_c=concept):
            data = _get_json(_COMPANY_CONCEPT_URL.format(cik=cik, taxonomy=taxonomy, concept=_c))
            if not data:
                return None
            points: dict = {}
            for unit_key, entries in (data.get("units") or {}).items():
                for e in entries:
                    end = e.get("end")
                    if not end or e.get("val") is None:
                        continue
                    points[end] = {
                        "end": end,
                        "val": float(e["val"]),
                        "fy": e.get("fy"),
                        "fp": e.get("fp"),
                        "form": e.get("form"),
                        "unit": unit_key,
                    }
            return sorted(points.values(), key=lambda p: p["end"]) or None

        series = cache.cached_call(
            "sec_companyfacts", f"{ticker}_{taxonomy}_{concept}",
            cache.TTL["sec_companyfacts"], _fetch,
        )
        if series:
            result[concept] = series
    return result
