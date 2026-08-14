"""
Tests for swing_model/run_swing_model.py's _compute_china_tension_count().

Covers the fix for the previously hardcoded china_keyword_count_5d=0 (see
CHANGELOG) — this now does a real, free (Yahoo, no API budget) keyword count
across the semiconductor watchlist, scoped to that sector since it's the
only one macro_overlay's China-tension signal is validated for.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import swing_model.run_swing_model as rsm


def _cfg(keywords=None, lookback_days=5):
    return {
        "modifiers": {
            "macro_overlay": {
                "china_keywords": keywords if keywords is not None else ["chip ban", "export restriction"],
                "china_keyword_lookback_days": lookback_days,
            }
        }
    }


def _article(title, days_ago=0):
    ts = (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()
    return {"title": title, "timestamp_utc": ts}


class TestComputeChinaTensionCount:
    def test_counts_matching_headlines_within_lookback(self):
        cfg = _cfg()
        with patch.object(rsm, "get_sector_tickers", return_value=["NVDA"]):
            with patch.object(rsm, "_fetch_yahoo_news_safe", return_value=[
                _article("US weighs new chip ban on China", days_ago=1),
                _article("NVDA earnings beat estimates", days_ago=1),
            ]):
                count = rsm._compute_china_tension_count(cfg)
        assert count == 1

    def test_excludes_headlines_outside_lookback_window(self):
        cfg = _cfg(lookback_days=5)
        with patch.object(rsm, "get_sector_tickers", return_value=["NVDA"]):
            with patch.object(rsm, "_fetch_yahoo_news_safe", return_value=[
                _article("New export restriction announced", days_ago=10),
            ]):
                count = rsm._compute_china_tension_count(cfg)
        assert count == 0

    def test_dedupes_same_headline_across_tickers(self):
        cfg = _cfg()
        shared_article = _article("Chip ban tightened on China trade", days_ago=0)
        with patch.object(rsm, "get_sector_tickers", return_value=["NVDA", "AMD"]):
            with patch.object(rsm, "_fetch_yahoo_news_safe", return_value=[shared_article]):
                count = rsm._compute_china_tension_count(cfg)
        # Same headline surfaces for both tickers (both hold semiconductor
        # exposure) — must not double-count it as two independent signals.
        assert count == 1

    def test_no_keywords_configured_returns_zero_without_fetching(self):
        cfg = _cfg(keywords=[])
        with patch.object(rsm, "_fetch_yahoo_news_safe") as mock_fetch:
            count = rsm._compute_china_tension_count(cfg)
        assert count == 0
        mock_fetch.assert_not_called()

    def test_one_ticker_with_no_news_does_not_block_others(self):
        # _fetch_yahoo_news_safe's real contract is to never raise — a fetch
        # failure surfaces as an empty list, not an exception. Confirm a
        # ticker with nothing returned doesn't stop the count from picking
        # up a real hit on another ticker.
        cfg = _cfg()

        def fetch_side_effect(ticker):
            if ticker == "NVDA":
                return []
            return [_article("New chip ban proposed on China trade", days_ago=0)]

        with patch.object(rsm, "get_sector_tickers", return_value=["NVDA", "AMD"]):
            with patch.object(rsm, "_fetch_yahoo_news_safe", side_effect=fetch_side_effect):
                count = rsm._compute_china_tension_count(cfg)
        assert count == 1
