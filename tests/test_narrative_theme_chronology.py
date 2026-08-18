"""
Tests for the narrative-theme chronological-order fix.

narrative_tracker.identify_dominant_theme()'s momentum calc splits its input
list in half and compares — it implicitly assumes texts[0] is the OLDEST
item. Its only caller, news_layer.compute_news_score(), builds that list
from `relevant`, which used to be built by concatenating Alpha Vantage +
Yahoo + Finnhub + Seeking Alpha + SEC EDGAR articles one source at a time,
never sorted by real timestamp — so a genuinely newest-and-rising theme
could register as "declining" purely because of which source happened to
come first in the concatenation.

Constructs the exact failure shape: articles that DON'T mention the theme
are older and placed in a source that's concatenated first; articles that DO
mention the theme are newer and placed in a source concatenated second — so
raw concatenation order is [new-with-theme, old-without-theme], the reverse
of real chronology.
"""

from datetime import datetime, timedelta, timezone

from swing_model.news_layer import compute_news_score


def _article(title, hours_ago, domain="reuters.com", idx=0):
    now = datetime.now(timezone.utc)
    return {
        "article_id": f"{domain}-{idx}",
        "timestamp_utc": (now - timedelta(hours=hours_ago)).isoformat(),
        "title": title,
        "url": f"https://{domain}/news",
        "source": domain,
        "source_domain": domain,
        "overall_sentiment_score": 0.0,
        "overall_sentiment_label": "neutral",
        "ticker_sentiment": [],
    }


class TestThemeMomentumUsesRealChronology:
    def test_rising_ai_theme_is_not_misread_as_declining(self):
        # Newer articles (1h old) mention AI/GPU strongly; older articles
        # (4 days old, still within the 5-day decay window) mention
        # earnings instead, not AI. Real chronological order is
        # old-without-AI -> new-with-AI, i.e. genuinely RISING AI mentions.
        new_ai_articles = [
            _article("NVIDIA GPU AI chip demand grows", hours_ago=1, domain="alphavantage.com", idx=0),
            _article("NVIDIA Blackwell GPU inference growth", hours_ago=1, domain="alphavantage.com", idx=1),
        ]
        old_non_ai_articles = [
            _article("NVIDIA quarterly earnings beat expectations", hours_ago=96, domain="yahoo.com", idx=0),
            _article("NVIDIA revenue guidance for fiscal year", hours_ago=96, domain="yahoo.com", idx=1),
        ]

        # Concatenation order in compute_news_score is AV then Yahoo — this
        # puts the NEWER AI-heavy articles FIRST and the OLDER non-AI ones
        # SECOND, the reverse of real time order. Without sorting by
        # timestamp before computing momentum, this reads as "declining."
        result = compute_news_score(new_ai_articles, old_non_ai_articles, "NVDA")

        assert result["dominant_narrative_theme"] == "ai_demand"
        assert result["theme_momentum"] == "rising"
