"""
SHARED: Ticker-specific sentiment extraction from news headlines, via keyword/
alias matching + nearest-mention attribution (NOT spaCy NER — an earlier
version of this module scaffolded a spaCy-backed named-entity path
(load_nlp()) that was never actually wired into extract_ticker_sentiments
below; removed 2026-08-24 along with the spacy dependency, since nothing in
this codebase called it. If real NER is wanted later, it needs a deliberate
design + backtest revalidation, not a silent re-add here — this is a live
News-category input).
Extracts ticker-specific sentiment from multi-company articles so that
"NVDA gains market share as AMD struggles" yields bullish for NVDA and bearish for AMD
rather than generic positive semiconductor sentiment applied equally to both.
Applied to both Alpha Vantage articles and Yahoo Finance headlines.
"""

import re
from typing import Optional


_TICKER_TO_COMPANY: dict[str, list[str]] = {
    "NVDA": ["Nvidia", "NVIDIA", "NVDA"],
    "AMD": ["AMD", "Advanced Micro Devices", "Advanced Micro"],
    "AVGO": ["Broadcom", "AVGO"],
    "TSM": ["TSMC", "Taiwan Semiconductor", "Taiwan Semi", "TSM"],
    "MU": ["Micron", "MU"],
    "ASML": ["ASML"],
    # Regional banks (v2.2.10) and healthcare (v2.2.24) were added to the
    # watchlist without corresponding entries here — every headline for these
    # 11 tickers was falling through to the ticker-symbol-only fallback
    # (_TICKER_TO_COMPANY.get(ticker, [ticker])), and none of these symbols
    # realistically appear as literal text in a news headline (coverage uses
    # company names, e.g. "Zions Bancorporation", not "ZION"). Confirmed live:
    # HBAN/RF/FITB/KEY were scoring news=0.0/15 on every scan despite Finnhub
    # returning real articles for them.
    "ZION": ["Zions Bancorporation", "Zions Bank", "ZION"],
    "KEY": ["KeyCorp", "KeyBank"],  # bare "Key" deliberately excluded — too generic, would false-match unrelated headlines
    "HBAN": ["Huntington Bancshares", "Huntington Bank", "HBAN"],
    "RF": ["Regions Financial", "Regions Bank"],  # bare "RF" excluded — collides with common word substrings (e.g. "perform")
    "FITB": ["Fifth Third Bancorp", "Fifth Third Bank", "FITB"],
    "LLY": ["Eli Lilly", "Lilly", "LLY"],
    "PFE": ["Pfizer", "PFE"],
    "MRK": ["Merck", "MRK"],
    "ABBV": ["AbbVie", "ABBV"],
    "UNH": ["UnitedHealth", "UnitedHealth Group", "UNH"],
    "JNJ": ["Johnson & Johnson", "Johnson and Johnson", "JNJ"],
    # consumer_discretionary — added proactively at sector creation this time
    # (see the note above: two prior sectors both scored News=0.0/15 silently
    # for weeks before this table caught up). "Target" and bare "HD" are
    # deliberately excluded as too generic (any "price target"/"rate target"
    # headline, or "HD" as in high-definition, would false-match) — same
    # reasoning as KEY/RF above.
    "AMZN": ["Amazon", "Amazon.com", "AMZN"],
    "TSLA": ["Tesla", "TSLA"],
    "HD": ["Home Depot"],
    "NKE": ["Nike", "NKE"],
    "SBUX": ["Starbucks", "SBUX"],
    "TGT": ["Target Corp", "Target Corporation", "TGT"],
    # Sector ticker-universe expansion, 2026-08-24 (full model audit Phase 2)
    # — same "add proactively, don't repeat the ZION/KEY/HBAN/RF/FITB gap"
    # lesson as consumer_discretionary's own note above. Bare ticker aliases
    # excluded wherever the string is also a common English word/abbreviation
    # that would false-match unrelated headlines (same reasoning as
    # KEY/RF/HD/TGT above) — CFR (Code of Federal Regulations), VRTX/ABT
    # (informal "abt" = about) excluded on that basis.
    "TXN": ["Texas Instruments", "TXN"],
    "ADI": ["Analog Devices", "ADI"],
    "AMAT": ["Applied Materials", "AMAT"],
    "QCOM": ["Qualcomm", "QCOM"],
    "KLAC": ["KLA Corporation", "KLA", "KLAC"],
    "CFG": ["Citizens Financial Group", "Citizens Financial", "CFG"],
    "TFC": ["Truist Financial", "Truist", "TFC"],
    "MTB": ["M&T Bank", "M&T Bank Corporation", "MTB"],
    "WBS": ["Webster Financial", "Webster Bank", "WBS"],
    "CFR": ["Cullen/Frost Bankers", "Frost Bank"],  # bare "CFR" excluded — collides with Code of Federal Regulations citations
    "PNFP": ["Pinnacle Financial Partners", "Pinnacle Financial", "PNFP"],
    "ONB": ["Old National Bancorp", "Old National Bank", "ONB"],
    "UMBF": ["UMB Financial", "UMB Bank", "UMBF"],
    "AMGN": ["Amgen", "AMGN"],
    "GILD": ["Gilead Sciences", "Gilead", "GILD"],
    "BMY": ["Bristol-Myers Squibb", "Bristol Myers Squibb", "BMY"],
    "VRTX": ["Vertex Pharmaceuticals", "Vertex Pharma"],  # bare "Vertex" excluded — too generic (geometry/math usage)
    "TMO": ["Thermo Fisher Scientific", "Thermo Fisher", "TMO"],
    "ABT": ["Abbott Laboratories", "Abbott"],  # bare "ABT" excluded — collides with informal "abt" = about
    "ISRG": ["Intuitive Surgical", "ISRG"],
    "SYK": ["Stryker Corporation", "Stryker", "SYK"],
    "MCD": ["McDonald's", "McDonalds", "MCD"],
    "BKNG": ["Booking Holdings", "Booking.com", "BKNG"],
    "TJX": ["TJX Companies", "TJ Maxx", "TJX"],
    "LOW": ["Lowe's", "Lowes"],  # bare "LOW" excluded — common English word, would false-match almost any headline
    "ORLY": ["O'Reilly Automotive", "O'Reilly Auto Parts", "ORLY"],
}

_BULLISH_KEYWORDS = [
    "gains", "surges", "beats", "outperforms", "rises", "record", "strong", "growth",
    "partnership", "contract", "upgrade", "bullish", "demand", "wins", "breakthrough",
    "rally", "soars", "profit", "expansion", "positive", "boost", "accelerates", "leads",
    "dominates", "awarded", "deal", "orders", "revenue", "high",
]

_BEARISH_KEYWORDS = [
    "struggles", "declines", "falls", "misses", "downgrade", "cuts", "bearish", "weak",
    "concern", "loss", "drop", "plunges", "ban", "restriction", "lawsuit", "risk",
    "warning", "caution", "disappoints", "reduces", "lower", "slump", "slowdown",
    "layoffs", "investigation", "penalty", "recall", "delay", "shortfall", "below",
]


def _keyword_positions(keyword: str, text: str) -> list[int]:
    """
    All word-boundary (`\\b`) match start offsets for `keyword` in `text`.

    Previously the directional-sentiment keyword matching below used plain
    substring checks (`kw in text` / `text.find(kw)`), the same bug class
    `_find_alias` above was already hardened against for ticker aliases
    (e.g. "MU" false-matching inside "stimulus") — never applied to keywords
    like "high" matching inside "highlights", "lower" inside "slower", or
    "leads" inside "misleads" (an opposite-connotation word). `.find()` also
    only located the FIRST occurrence — if the same word legitimately
    appeared near two different mentioned tickers, only one got credited;
    this returns every match so each occurrence can be attributed on its own
    (Signal Integrity Audit finding E.4).
    """
    return [m.start() for m in re.finditer(r"\b" + re.escape(keyword) + r"\b", text)]


def _find_alias(alias_lower: str, headline_lower: str) -> Optional[int]:
    """
    Return the character offset of alias_lower's first whole-word match in
    headline_lower, or None. Word-boundary (`\\b`) rather than plain substring
    matching — short all-caps ticker aliases ("MU", "RF", "HD") otherwise
    false-match inside unrelated words (e.g. "MU" inside "stimulus", confirmed
    live: is_ticker_relevant("Fed stimulus must continue", "MU") returned True).
    `\\b` also matches at the edges of a multi-word phrase, so this works the
    same for "Fifth Third Bancorp" as it does for "MU".
    """
    m = re.search(r"\b" + re.escape(alias_lower) + r"\b", headline_lower)
    return m.start() if m else None


def extract_ticker_sentiments(
    headline: str,
    watchlist: list[str],
) -> dict[str, Optional[str]]:
    """
    Extract sentiment directed at each ticker mentioned in the headline.

    Returns dict mapping ticker → 'bullish' | 'bearish' | 'neutral' | None.
    None means the ticker was not mentioned.

    Strategy:
    1. Keyword search for company name aliases in headline text (_TICKER_TO_COMPANY)
    2. When multiple tickers are mentioned, each bullish/bearish keyword is
       attributed to whichever mentioned ticker's alias sits nearest to it in
       the headline (see the multi-company branch below)
    """
    headline_lower = headline.lower()
    result: dict[str, Optional[str]] = {t: None for t in watchlist}

    # Identify which tickers are mentioned
    mentioned = {}
    for ticker in watchlist:
        aliases = _TICKER_TO_COMPANY.get(ticker, [ticker])
        for alias in aliases:
            if _find_alias(alias.lower(), headline_lower) is not None:
                mentioned[ticker] = True
                break

    if not mentioned:
        return result

    # Count bullish/bearish signals in the full headline (word-boundary
    # matches only — see _keyword_positions' docstring)
    bullish_hits = sum(len(_keyword_positions(kw, headline_lower)) for kw in _BULLISH_KEYWORDS)
    bearish_hits = sum(len(_keyword_positions(kw, headline_lower)) for kw in _BEARISH_KEYWORDS)

    if len(mentioned) == 1:
        # Single company — apply headline sentiment directly
        ticker = next(iter(mentioned))
        if bullish_hits > bearish_hits:
            result[ticker] = "bullish"
        elif bearish_hits > bullish_hits:
            result[ticker] = "bearish"
        else:
            result[ticker] = "neutral"
    else:
        # Multiple companies — attribute each directional keyword to whichever
        # mentioned ticker's alias sits nearest to it in the headline, rather
        # than a fixed word/character window. Two bugs in the old window
        # approach: (1) it split the headline into single whitespace tokens and
        # tested `alias.lower() in word` — a longer string can never be a
        # substring of one shorter token, so multi-word aliases ("Advanced
        # Micro Devices", "Taiwan Semiconductor", "Eli Lilly", "Home Depot",
        # "Fifth Third Bancorp", ...) could never match, silently resolving
        # "neutral" in every multi-company headline — including the one in
        # this module's own docstring example. (2) even for single-word
        # aliases, a window wide enough to reach a keyword also let every
        # OTHER mentioned ticker's window claim that same keyword in a short
        # headline (e.g. "gains" meant for one company bleeding into a
        # different company's count). Nearest-mention attribution fixes both:
        # each keyword occurrence counts for exactly one ticker.
        entity_positions: dict[str, int] = {}
        for ticker in mentioned:
            aliases = _TICKER_TO_COMPANY.get(ticker, [ticker])
            best_pos = None
            for alias in aliases:
                pos = _find_alias(alias.lower(), headline_lower)
                if pos is not None and (best_pos is None or pos < best_pos):
                    best_pos = pos
            if best_pos is not None:
                entity_positions[ticker] = best_pos

        local_bull = {t: 0 for t in mentioned}
        local_bear = {t: 0 for t in mentioned}

        def _nearest_ticker(kw_pos: int) -> Optional[str]:
            if not entity_positions:
                return None
            return min(entity_positions, key=lambda t: abs(entity_positions[t] - kw_pos))

        for kw in _BULLISH_KEYWORDS:
            for idx in _keyword_positions(kw, headline_lower):
                nearest = _nearest_ticker(idx)
                if nearest:
                    local_bull[nearest] += 1
        for kw in _BEARISH_KEYWORDS:
            for idx in _keyword_positions(kw, headline_lower):
                nearest = _nearest_ticker(idx)
                if nearest:
                    local_bear[nearest] += 1

        for ticker in mentioned:
            if local_bull[ticker] > local_bear[ticker]:
                result[ticker] = "bullish"
            elif local_bear[ticker] > local_bull[ticker]:
                result[ticker] = "bearish"
            else:
                result[ticker] = "neutral"

    return result


def is_ticker_relevant(headline: str, ticker: str) -> bool:
    """
    Returns True if the headline references the given ticker.
    Used to filter generic sector headlines from ticker-specific ones.
    """
    headline_lower = headline.lower()
    aliases = _TICKER_TO_COMPANY.get(ticker, [ticker])
    return any(_find_alias(alias.lower(), headline_lower) is not None for alias in aliases)
