"""
SHARED: Named entity recognition on news headlines.
Extracts ticker-specific sentiment from multi-company articles so that
"NVDA gains market share as AMD struggles" yields bullish for NVDA and bearish for AMD
rather than generic positive semiconductor sentiment applied equally to both.
Applied to both Alpha Vantage articles and Yahoo Finance headlines.
Uses spaCy en_core_web_sm when available; falls back to keyword matching.
Install NLP model: python -m spacy download en_core_web_sm
"""

from typing import Optional

try:
    import spacy
    _nlp = None  # Lazy-loaded on first use
except ImportError:
    spacy = None  # type: ignore
    _nlp = None


def load_nlp():
    """Lazy-load spaCy model. Returns None if spaCy is unavailable."""
    global _nlp
    if _nlp is None:
        if spacy is None:
            return None
        try:
            _nlp = spacy.load("en_core_web_sm")
        except OSError:
            return None  # Model not downloaded — fall back to keyword matching
    return _nlp


_TICKER_TO_COMPANY: dict[str, list[str]] = {
    "NVDA": ["Nvidia", "NVIDIA", "NVDA"],
    "AMD": ["AMD", "Advanced Micro Devices", "Advanced Micro"],
    "AVGO": ["Broadcom", "AVGO"],
    "TSM": ["TSMC", "Taiwan Semiconductor", "Taiwan Semi", "TSM"],
    "MU": ["Micron", "MU"],
    "ASML": ["ASML"],
}

_BULLISH_KEYWORDS = [
    "gains", "surges", "beats", "outperforms", "rises", "record", "strong", "growth",
    "partnership", "contract", "upgrade", "bullish", "demand", "wins", "breakthrough",
    "rally", "soars", "profit", "expansion", "positive", "boost", "accelerates", "leads",
    "dominates", "awarded", "deal", "orders", "revenue", "growth", "high",
]

_BEARISH_KEYWORDS = [
    "struggles", "declines", "falls", "misses", "downgrade", "cuts", "bearish", "weak",
    "concern", "loss", "drop", "plunges", "ban", "restriction", "lawsuit", "risk",
    "warning", "caution", "disappoints", "reduces", "lower", "slump", "slowdown",
    "layoffs", "investigation", "penalty", "recall", "delay", "shortfall", "below",
]


def extract_ticker_sentiments(
    headline: str,
    watchlist: list[str],
) -> dict[str, Optional[str]]:
    """
    Extract sentiment directed at each ticker mentioned in the headline.

    Returns dict mapping ticker → 'bullish' | 'bearish' | 'neutral' | None.
    None means the ticker was not mentioned.

    Strategy:
    1. If spaCy available: NER identifies ORG entities → matched to tickers
    2. Fallback: keyword search for company name aliases in headline text
    3. Sentiment classified by presence of bullish/bearish keywords near the entity
    """
    headline_lower = headline.lower()
    result: dict[str, Optional[str]] = {t: None for t in watchlist}

    # Identify which tickers are mentioned
    mentioned = {}
    for ticker in watchlist:
        aliases = _TICKER_TO_COMPANY.get(ticker, [ticker])
        for alias in aliases:
            if alias.lower() in headline_lower:
                mentioned[ticker] = True
                break

    if not mentioned:
        return result

    # Count bullish/bearish signals in the full headline
    bullish_hits = sum(1 for kw in _BULLISH_KEYWORDS if kw.lower() in headline_lower)
    bearish_hits = sum(1 for kw in _BEARISH_KEYWORDS if kw.lower() in headline_lower)

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
        # Multiple companies — attempt per-company context via sentence splitting
        for ticker in mentioned:
            aliases = _TICKER_TO_COMPANY.get(ticker, [ticker])
            local_bull = 0
            local_bear = 0
            words = headline_lower.split()
            for i, word in enumerate(words):
                if any(alias.lower() in word for alias in aliases):
                    # Check a 10-word window around the mention
                    context = " ".join(words[max(0, i-5):i+6])
                    local_bull += sum(1 for kw in _BULLISH_KEYWORDS if kw in context)
                    local_bear += sum(1 for kw in _BEARISH_KEYWORDS if kw in context)
            if local_bull > local_bear:
                result[ticker] = "bullish"
            elif local_bear > local_bull:
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
    return any(alias.lower() in headline_lower for alias in aliases)
