"""
Tests for shared/utils/source_credibility.py's score_news_outlet().

Covers the substring-collision fix: "ft.com" (Financial Times, 0.88) is a
literal substring of "microsoft.com" ("micro" + "ft.com" + nothing — the
characters f,t,.,c,o,m line up exactly inside "microsoft.com"), so any
Microsoft-sourced article used to silently inherit Financial Times'
credibility score instead of the correct 0.50 unknown-outlet fallback. This
fed directly into News scoring and into event_gate.py's credibility
downgrade check.
"""

from shared.utils.source_credibility import score_news_outlet


class TestDomainCollisionFix:
    def test_microsoft_does_not_inherit_financial_times_score(self):
        assert score_news_outlet("microsoft.com") == 0.50

    def test_microsoft_subdomain_does_not_inherit_financial_times_score(self):
        assert score_news_outlet("news.microsoft.com") == 0.50
        assert score_news_outlet("blogs.microsoft.com") == 0.50

    def test_shaft_com_does_not_inherit_financial_times_score(self):
        assert score_news_outlet("shaft.com") == 0.50


class TestLegitimateDomainMatchesStillWork:
    def test_exact_domain_match(self):
        assert score_news_outlet("ft.com") == 0.88
        assert score_news_outlet("reuters.com") == 0.95
        assert score_news_outlet("cnbc.com") == 0.80

    def test_proper_subdomain_match(self):
        assert score_news_outlet("www.ft.com") == 0.88
        assert score_news_outlet("www.cnbc.com") == 0.80

    def test_domain_with_path_still_matches(self):
        assert score_news_outlet("www.cnbc.com/markets") == 0.80

    def test_outlet_name_key_still_matches(self):
        assert score_news_outlet("Reuters") == 0.95
        assert score_news_outlet("Financial Times") == 0.88

    def test_unknown_outlet_falls_back_to_neutral(self):
        assert score_news_outlet("some-random-blog.net") == 0.50

    def test_empty_source_falls_back_to_neutral(self):
        assert score_news_outlet("") == 0.50
        assert score_news_outlet(None) == 0.50
