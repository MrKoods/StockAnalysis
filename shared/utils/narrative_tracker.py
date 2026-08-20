"""
SHARED: Clusters news/social keywords into dominant themes per ticker.
Tracks theme momentum over time. A bullish NVDA breakout during "AI demand"
dominance has more conviction than the same setup during "supply chain uncertainty."
"""



THEME_KEYWORDS: dict[str, list[str]] = {
    "ai_demand": [
        "AI", "artificial intelligence", "data center", "GPU", "LLM", "ChatGPT",
        "training", "inference", "Blackwell", "H100", "H200", "generative",
    ],
    "supply_chain": [
        "supply chain", "shortage", "inventory", "wafer", "fab", "capacity",
        "lead time", "backlog",
    ],
    "china_export": [
        "export restriction", "chip ban", "China", "Taiwan Strait", "embargo",
        "tariff", "trade war", "BIS", "entity list",
    ],
    "earnings_expectations": [
        "earnings", "revenue", "guidance", "forecast", "EPS", "beat", "miss",
        "outlook", "estimate", "quarter",
    ],
    "competitive_dynamics": [
        "market share", "competition", "AMD vs", "NVDA vs", "Intel", "Qualcomm",
        "architecture", "benchmark", "next gen",
    ],
    "memory_cycle": [
        "DRAM", "NAND", "memory pricing", "HBM", "bandwidth", "Micron", "SK Hynix",
        "Samsung", "inventory normalization",
    ],
    "macro_rates": [
        "interest rate", "Fed", "Federal Reserve", "yield", "inflation", "rate hike",
        "rate cut", "dollar",
    ],
}

# Themes where bullish trade direction has alignment (positive modifier)
_BULLISH_ALIGNED_THEMES = {"ai_demand", "earnings_expectations", "competitive_dynamics"}
# Themes that are inherently adverse regardless of sentiment
_ADVERSE_THEMES = {"china_export", "macro_rates"}


def identify_dominant_theme(
    texts: list[str],
    ticker: str,
    lookback_days: int = 5,
) -> dict:
    """
    Identify the dominant narrative theme for a ticker from recent texts.

    texts MUST be in chronological order, oldest first — the momentum calc
    below compares the first half of the list to the second half, so an
    unsorted or reverse-sorted input silently produces a meaningless
    momentum read (a genuinely newest-and-rising theme could register as
    "declining" purely from list order). Callers combining multiple sources
    (news_layer.py concatenates 5 of them) must sort by real timestamp
    before calling this, not just concatenate.

    Returns dict:
    {
        dominant_theme: str,
        theme_score: float,       # relative strength of dominant theme (0-1)
        theme_momentum: str,      # 'rising', 'stable', 'declining'
        all_theme_scores: dict,   # {theme: count}
    }
    """
    if not texts:
        return {
            "dominant_theme": "none",
            "theme_score": 0.0,
            "theme_momentum": "stable",
            "all_theme_scores": {},
        }

    theme_counts: dict[str, int] = {theme: 0 for theme in THEME_KEYWORDS}

    for text in texts:
        text_lower = text.lower()
        for theme, keywords in THEME_KEYWORDS.items():
            for kw in keywords:
                if kw.lower() in text_lower:
                    theme_counts[theme] += 1
                    break  # Count theme once per text even if multiple keywords hit

    total = sum(theme_counts.values())
    if total == 0:
        return {
            "dominant_theme": "none",
            "theme_score": 0.0,
            "theme_momentum": "stable",
            "all_theme_scores": theme_counts,
        }

    dominant = max(theme_counts, key=lambda t: theme_counts[t])
    dom_score = theme_counts[dominant] / total

    # Momentum: compare first half to second half of texts
    half = max(1, len(texts) // 2)
    first_half_texts = texts[:half]
    second_half_texts = texts[half:]
    first_count = sum(1 for t in first_half_texts if any(
        kw.lower() in t.lower() for kw in THEME_KEYWORDS.get(dominant, [])))
    second_count = sum(1 for t in second_half_texts if any(
        kw.lower() in t.lower() for kw in THEME_KEYWORDS.get(dominant, [])))

    if second_count > first_count * 1.25:
        momentum = "rising"
    elif second_count < first_count * 0.75:
        momentum = "declining"
    else:
        momentum = "stable"

    return {
        "dominant_theme": dominant,
        "theme_score": round(dom_score, 3),
        "theme_momentum": momentum,
        "all_theme_scores": theme_counts,
    }


def theme_alignment_modifier(
    dominant_theme: str,
    trade_direction: str,
    ticker: str,
) -> float:
    """
    Return alignment modifier for news/sentiment contribution.
    Bullish breakout aligned with 'ai_demand' → +1.0.
    Bullish breakout during 'china_export' dominance → -1.0.
    Returns value in [-1, +1].
    """
    if dominant_theme == "none":
        return 0.0

    if trade_direction == "bullish":
        if dominant_theme in _BULLISH_ALIGNED_THEMES:
            return 1.0
        if dominant_theme in _ADVERSE_THEMES:
            return -1.0
        if dominant_theme == "supply_chain":
            return -0.5
        if dominant_theme == "memory_cycle":
            return 0.5 if ticker in ("MU",) else 0.0
    elif trade_direction == "bearish":
        if dominant_theme in _ADVERSE_THEMES:
            return 1.0
        if dominant_theme in _BULLISH_ALIGNED_THEMES:
            return -1.0
        if dominant_theme == "supply_chain":
            return 0.5
        if dominant_theme == "memory_cycle":
            return -0.5 if ticker in ("MU",) else 0.0

    return 0.0
