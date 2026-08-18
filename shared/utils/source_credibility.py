"""
SHARED: Scores news outlets by historical accuracy and reputation.
Credibility scores stored per outlet and updated on each data pull.
A Reuters article on NVDA carries more weight than an obscure financial blog.
"""

import re

# Default outlet credibility scores (0.0-1.0, calibrated manually)
_DEFAULT_OUTLET_SCORES: dict[str, float] = {
    # A company's own SEC filing — not reported through a third party, so it
    # outranks even wire services for accuracy (it IS the primary source).
    "sec.gov": 1.0,
    "SEC EDGAR": 1.0,
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


def score_news_outlet(source_domain: str) -> float:
    """
    Score a news outlet's credibility (0.0-1.0).
    Falls back to 0.50 (unknown outlet) if not in the credibility map.
    """
    if not source_domain:
        return 0.50
    # Match when a known outlet key/domain appears within the parsed source
    # string (e.g. "cnbc.com" found inside "www.cnbc.com/markets"). Only this
    # direction is safe: the reverse (checking whether the parsed string is
    # contained *within* a key, e.g. clean="ft" matching key="ft.com") lets a
    # short or garbled parsed source string spuriously inherit a premium outlet's
    # credibility score — a real risk since event_gate.py uses this score to
    # decide whether a critical-news trigger gets downgraded for a low-credibility
    # source, so a junk source being mis-scored as premium could let a block through
    # that should have been downgraded.
    #
    # That reasoning missed a second collision risk in this SAME direction:
    # a short domain-style key can itself be a substring of an unrelated
    # domain — "ft.com" (Financial Times) is a literal substring of
    # "microsoft.com" (...micro-ft.com-m... lines up at "microsoft.com"[7:13]),
    # so any Microsoft-sourced article used to inherit FT's 0.88 score.
    # Fixed by requiring a domain-style key (one containing ".") to match the
    # host as a whole label — either an exact match or a proper subdomain
    # (host.endswith("." + key)) — rather than an unanchored substring. A
    # plain outlet NAME key (no ".", e.g. "Reuters") still uses substring
    # matching, but word-boundary-bound so it can't match inside an unrelated
    # longer word either.
    clean = source_domain.lower().strip().rstrip("/")
    host = clean.split("/")[0]
    for key, val in _DEFAULT_OUTLET_SCORES.items():
        key_l = key.lower()
        if "." in key_l:
            if host == key_l or host.endswith("." + key_l):
                return val
        elif re.search(r"\b" + re.escape(key_l) + r"\b", clean):
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
