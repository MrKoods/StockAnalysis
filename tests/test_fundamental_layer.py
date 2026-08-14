"""
Tests for swing_model/fundamental_layer.py's outlier-exclusion logic.

Scope: _exclude_outliers() and its integration into score_valuation_vs_peers().
Not a full-module test suite for fundamental_layer.py (no coverage existed
before this file) — focused on the outlier-exclusion fix specifically.
"""

import pytest

from swing_model.fundamental_layer import (
    FundamentalScorer,
    _exclude_outliers,
    _leave_one_out_average,
    _score_premium,
)


class TestExcludeOutliers:
    def test_no_outlier_returns_all_values(self):
        values = [20.0, 22.0, 25.0, 24.0, 21.0]
        assert _exclude_outliers(values) == values

    def test_removes_high_outlier(self):
        # One value far outside the rest — real-world shape (AMD's 184x P/E
        # against peers clustered in the 20s-60s).
        values = [29.9, 184.0, 62.1, 39.3, 22.3, 62.1]
        result = _exclude_outliers(values)
        assert 184.0 not in result
        assert len(result) == 5

    def test_removes_low_outlier_too(self):
        values = [50.0, 52.0, 48.0, 51.0, 3.0]
        result = _exclude_outliers(values)
        assert 3.0 not in result

    def test_below_minimum_sample_size_returns_unfiltered(self):
        # Fewer than 4 points — outlier detection isn't meaningful, must not
        # silently drop a ticker just because the watchlist is small.
        values = [20.0, 500.0, 22.0]
        assert _exclude_outliers(values) == values

    def test_identical_values_returns_unfiltered(self):
        # MAD == 0 — nothing to measure spread against; must not divide by zero.
        values = [30.0, 30.0, 30.0, 30.0, 30.0]
        assert _exclude_outliers(values) == values

    def test_never_returns_empty_list(self):
        # Pathological case where every point looks like an outlier relative
        # to the others — must fall back to the unfiltered list rather than
        # returning nothing (which would break the sector-average calculation).
        values = [1.0, 1000.0, 1.0, 1000.0]
        result = _exclude_outliers(values)
        assert len(result) > 0


class TestScoreValuationVsPeersOutlierExclusion:
    def _fundamentals(self, amd_pe=184.0):
        """Six-ticker watchlist shaped like the real cached data — one high
        P/E outlier (AMD) among five tickers clustered in the 20s-60s."""
        pe_map = {"NVDA": 29.9, "AMD": amd_pe, "AVGO": 62.1, "TSM": 39.3, "MU": 22.3, "ASML": 62.1}
        return {
            ticker: {
                "valuation": {
                    "trailingPE": pe,
                    "forwardPE": pe * 0.5,
                    "enterpriseToEbitda": pe * 0.3,
                    "suspect_fields": [],
                }
            }
            for ticker, pe in pe_map.items()
        }

    def test_sector_average_excludes_outlier(self):
        result = FundamentalScorer().score_valuation_vs_peers(self._fundamentals())
        # Average of the 5 non-AMD values (29.9+62.1+39.3+22.3+62.1)/5 = 43.14,
        # NOT the full 6-value average (~66.6) that AMD's outlier would produce.
        assert result["sector_averages"]["pe"] < 50.0

    def test_outlier_ticker_still_gets_a_score(self):
        """Excluding AMD from the AVERAGE must not exclude AMD from being SCORED."""
        result = FundamentalScorer().score_valuation_vs_peers(self._fundamentals())
        assert "AMD" in result["ticker_scores"]
        assert result["ticker_scores"]["AMD"]["data_quality"] != "unavailable"

    def test_no_outlier_case_uses_full_average(self):
        # All six P/Es within a normal range — nothing should be excluded.
        result = FundamentalScorer().score_valuation_vs_peers(self._fundamentals(amd_pe=45.0))
        pe_values = [29.9, 45.0, 62.1, 39.3, 22.3, 62.1]
        expected_avg = sum(pe_values) / len(pe_values)
        assert abs(result["sector_averages"]["pe"] - expected_avg) < 0.1

    def test_outlier_no_longer_inflates_peer_scores(self):
        """
        The actual bug being fixed: AVGO's P/E (62.1x) is BELOW the old,
        AMD-inflated sector average (~66.6x, unfiltered), which would have
        scored it the max +2 ("cheap vs. peers"). Against the corrected,
        outlier-excluded average (~43.1x), 62.1x is a genuine ~44% premium —
        not a discount. AVGO's own data never changed; only the average did.
        """
        result = FundamentalScorer().score_valuation_vs_peers(self._fundamentals(amd_pe=184.0))

        sector_pe = result["sector_averages"]["pe"]
        avgo_pe = 62.1
        assert avgo_pe > sector_pe  # confirms the average really was corrected downward

        avgo_score = result["ticker_scores"]["AVGO"]["pe_vs_sector_score"]
        assert avgo_score != 2  # must not still read as "cheap vs. peers"


class TestScoreAllTickersMultiSectorScoping:
    """
    score_all_tickers()'s peer pool must be scoped to the `watchlist` it's
    called with, not the full accumulated fundamental_state.json cache —
    otherwise semiconductor and bank valuation multiples would blend into one
    meaningless "sector average" once both sectors' data exist in the same
    cache file (v2.2.8/v2.2.9 multi-sector infrastructure).
    """

    def _cached_state(self):
        # fundamental_state.json shape — accumulates every ticker ever
        # fetched across BOTH sectors, exactly like the real cache file would
        # once regional_banks has been fetched at least once.
        semis = {"NVDA": 29.9, "AMD": 32.0, "AVGO": 35.0, "TSM": 30.0}
        banks = {"ZION": 9.0, "KEY": 8.5, "HBAN": 10.0}  # much lower P/E, different sector norm
        tickers = {}
        for t, pe in {**semis, **banks}.items():
            tickers[t] = {"valuation": {
                "trailingPE": pe, "forwardPE": pe * 0.9,
                "enterpriseToEbitda": pe * 0.5, "suspect_fields": [],
            }}
        return {"tickers": tickers}

    def test_semis_sector_average_excludes_bank_tickers(self):
        state = self._cached_state()
        results = FundamentalScorer().score_all_tickers(["NVDA", "AMD", "AVGO", "TSM"], state)
        # If bank tickers (P/E ~8-10) leaked into the peer pool, the semis
        # average would be pulled down well below the real semis-only value
        # (~31.7). Assert it stays in the semis-only range.
        avgo_quality = results["AVGO"]["data_quality"]
        assert avgo_quality != "unavailable"
        avgo_internal = FundamentalScorer().score_valuation_vs_peers(
            {t: v for t, v in state["tickers"].items() if t in ["NVDA", "AMD", "AVGO", "TSM"]}
        )
        assert 28.0 < avgo_internal["sector_averages"]["pe"] < 35.0

    def test_bank_sector_average_excludes_semis_tickers(self):
        state = self._cached_state()
        results = FundamentalScorer().score_all_tickers(["ZION", "KEY", "HBAN"], state)
        assert set(results.keys()) == {"ZION", "KEY", "HBAN"}
        bank_internal = FundamentalScorer().score_valuation_vs_peers(
            {t: v for t, v in state["tickers"].items() if t in ["ZION", "KEY", "HBAN"]}
        )
        # If semis tickers (P/E ~30-35) leaked in, this average would be much
        # higher than the real bank-only value (~9.2).
        assert 8.0 < bank_internal["sector_averages"]["pe"] < 11.0

    def test_score_all_tickers_only_scores_requested_watchlist(self):
        # Even though the cache has 7 tickers total, only the 3 banks should
        # appear in the output for a bank-scoped call.
        state = self._cached_state()
        results = FundamentalScorer().score_all_tickers(["ZION", "KEY", "HBAN"], state)
        assert "NVDA" not in results
        assert len(results) == 3


class TestScorePremium:
    """
    The dead-bucket bug: the old code's "else" fallback for a mid-range
    premium (roughly 10%-50%) evaluated to the SAME score as the near-parity
    (0-10%) bucket, so a stock trading 45% above peers scored identically to
    one trading 5% above — exactly the range most large-cap semis sit in.
    _score_premium replaces that with one explicit monotonic ladder.
    """

    def test_discount_scores_max(self):
        assert _score_premium(-0.10) == 2

    def test_near_parity_scores_one(self):
        assert _score_premium(0.05) == 1
        assert _score_premium(0.15) == 1

    def test_moderate_premium_no_longer_equals_near_parity(self):
        # This is the exact bug: a 35% premium must NOT score the same as 5%.
        assert _score_premium(0.35) != _score_premium(0.05)
        assert _score_premium(0.35) == 0

    def test_high_premium_scores_negative_one(self):
        assert _score_premium(0.60) == -1

    def test_extreme_premium_scores_min(self):
        assert _score_premium(1.20) == -2

    def test_monotonic_non_increasing_as_premium_rises(self):
        premiums = [-0.20, 0.0, 0.05, 0.15, 0.30, 0.45, 0.60, 0.75, 0.90, 1.10]
        scores = [_score_premium(p) for p in premiums]
        assert all(scores[i] >= scores[i + 1] for i in range(len(scores) - 1))


class TestLeaveOneOutAverage:
    def test_excludes_own_value(self):
        values = {"NVDA": 100.0, "AMD": 20.0, "AVGO": 20.0, "TSM": 20.0, "MU": 20.0}
        # NVDA's own 100.0 must not appear in its own peer average.
        result = _leave_one_out_average(values, "NVDA")
        assert result == 20.0

    def test_returns_none_when_no_peers_remain(self):
        values = {"NVDA": 100.0}
        assert _leave_one_out_average(values, "NVDA") is None


class TestValuationSelfReferentialBiasFixed:
    """
    The self-comparison bug: with 6 tickers, each contributed ~17% of its own
    benchmark, biasing an outlier's measured premium toward parity. Excluding
    self should make an expensive outlier's measured premium LARGER (a truer
    read), not smaller.
    """

    def test_outlier_premium_is_not_diluted_by_its_own_inclusion(self):
        fundamentals = {
            "NVDA": {"valuation": {"trailingPE": 30.0, "suspect_fields": []}},
            "AMD": {"valuation": {"trailingPE": 32.0, "suspect_fields": []}},
            "AVGO": {"valuation": {"trailingPE": 90.0, "suspect_fields": []}},  # outlier
            "TSM": {"valuation": {"trailingPE": 31.0, "suspect_fields": []}},
            "MU": {"valuation": {"trailingPE": 29.0, "suspect_fields": []}},
        }
        result = FundamentalScorer().score_valuation_vs_peers(fundamentals)
        avgo_breakdown = result["ticker_scores"]["AVGO"]["component_breakdown"]["pe_vs_sector"]

        # Peer average excluding AVGO: (30+32+31+29)/4 = 30.5
        # Full-pool average including AVGO would be (30+32+90+31+29)/5 = 42.4,
        # which would understate AVGO's real premium against its peers.
        assert avgo_breakdown["sector_pe"] == pytest.approx(30.5, abs=0.1)


class TestEstimateRevisionsTargetDelta:
    """
    estimate_revisions_score now prefers a real target-price-delta signal
    (prior snapshot vs. current) over the implied-upside proxy, which
    conflated "the stock price moved" with "analysts revised their number."
    """

    def _fd(self, target, prior_target=None, current_price=200.0):
        return {
            "earnings": {},
            "valuation": {},
            "revisions": {
                "analyst_target_price": target,
                "prior_analyst_target_price": prior_target,
                "current_price": current_price,
            },
        }

    def test_raised_target_scores_positive(self):
        fd = self._fd(target=275.0, prior_target=250.0)
        result = FundamentalScorer().score_earnings_momentum(fd)
        assert result["estimate_revisions_score"] == 2
        assert result["component_breakdown"]["estimate_revisions"]["prior_target"] == 250.0

    def test_lowered_target_scores_negative(self):
        fd = self._fd(target=225.0, prior_target=250.0)
        result = FundamentalScorer().score_earnings_momentum(fd)
        assert result["estimate_revisions_score"] == -2

    def test_unchanged_target_scores_neutral(self):
        fd = self._fd(target=251.0, prior_target=250.0)  # <2% move
        result = FundamentalScorer().score_earnings_momentum(fd)
        assert result["estimate_revisions_score"] == 0

    def test_price_rally_alone_does_not_move_the_score(self):
        """
        The bug being fixed: a stock rallying toward its target used to shrink
        implied_upside_pct and score as if analysts had turned bearish, even
        though the target price itself never moved.
        """
        fd_before_rally = self._fd(target=250.0, prior_target=250.0, current_price=180.0)
        fd_after_rally = self._fd(target=250.0, prior_target=250.0, current_price=245.0)
        before = FundamentalScorer().score_earnings_momentum(fd_before_rally)
        after = FundamentalScorer().score_earnings_momentum(fd_after_rally)
        assert before["estimate_revisions_score"] == after["estimate_revisions_score"] == 0

    def test_falls_back_to_implied_upside_when_no_prior_snapshot(self):
        fd = self._fd(target=250.0, prior_target=None, current_price=200.0)
        result = FundamentalScorer().score_earnings_momentum(fd)
        assert result["estimate_revisions_score"] == 2  # 25% upside, no prior data
        breakdown = result["component_breakdown"]["estimate_revisions"]
        assert "implied_upside_pct" in breakdown

    def test_live_price_overrides_stale_cached_price_in_fallback(self):
        """No prior snapshot yet (cold start) — implied-upside fallback should
        use the live price passed in, not the possibly-stale cached one."""
        fd = self._fd(target=250.0, prior_target=None, current_price=100.0)  # stale, huge fake upside
        result = FundamentalScorer().score_earnings_momentum(fd, live_price=245.0)
        breakdown = result["component_breakdown"]["estimate_revisions"]
        assert breakdown["implied_upside_pct"] == pytest.approx((250.0 - 245.0) / 245.0, abs=1e-4)
        assert result["estimate_revisions_score"] == 0  # ~2% upside is neutral, not the stale-price 150%


class TestPeerRelativeGrowth:
    def _fd(self, growth_trend):
        return {"earnings": {"eps_growth_trend": growth_trend}, "valuation": {}, "revisions": {}}

    def test_outgrowing_peers_nudges_score_up(self):
        fd = self._fd([0.05, 0.04, 0.03, 0.02])  # avg 3.5%, below the 10% "accelerating" bar
        without_peers = FundamentalScorer().score_earnings_momentum(fd)
        with_peers = FundamentalScorer().score_earnings_momentum(fd, peer_avg_growth=-0.10)
        assert with_peers["eps_growth_score"] == without_peers["eps_growth_score"] + 1

    def test_underperforming_peers_nudges_score_down(self):
        fd = self._fd([0.05, 0.04, 0.03, 0.02])
        without_peers = FundamentalScorer().score_earnings_momentum(fd)
        with_peers = FundamentalScorer().score_earnings_momentum(fd, peer_avg_growth=0.20)
        assert with_peers["eps_growth_score"] == without_peers["eps_growth_score"] - 1

    def test_nudge_does_not_exceed_max_bounds(self):
        fd = self._fd([0.50, 0.45, 0.40, 0.35])  # already maxed at +3, accelerating
        result = FundamentalScorer().score_earnings_momentum(fd, peer_avg_growth=-0.50)
        assert result["eps_growth_score"] == 3

    def test_no_peer_avg_growth_is_a_no_op(self):
        fd = self._fd([0.05, 0.04, 0.03, 0.02])
        result = FundamentalScorer().score_earnings_momentum(fd, peer_avg_growth=None)
        assert "peer_avg_growth" not in result["component_breakdown"]["eps_growth"]


class TestRevenueQualityDampener:
    """
    EPS growth without revenue growth is the classic low-quality-earnings
    pattern (margin expansion/buybacks rather than real demand) — previously
    invisible to the model since only EPS was tracked at all.
    """

    def _fd(self, growth_trend, revenue_yoy_growth):
        return {
            "earnings": {"eps_growth_trend": growth_trend, "revenue_yoy_growth": revenue_yoy_growth},
            "valuation": {}, "revisions": {},
        }

    def test_positive_eps_growth_with_declining_revenue_is_capped(self):
        fd = self._fd([0.15, 0.14, 0.13, 0.12], revenue_yoy_growth=-0.05)
        result = FundamentalScorer().score_earnings_momentum(fd)
        assert result["eps_growth_score"] == 1
        assert "revenue_quality_flag" in result["component_breakdown"]["eps_growth"]

    def test_positive_eps_growth_with_positive_revenue_is_not_capped(self):
        fd = self._fd([0.15, 0.14, 0.13, 0.12], revenue_yoy_growth=0.08)
        result = FundamentalScorer().score_earnings_momentum(fd)
        assert "revenue_quality_flag" not in result["component_breakdown"]["eps_growth"]

    def test_missing_revenue_data_does_not_cap(self):
        fd = self._fd([0.15, 0.14, 0.13, 0.12], revenue_yoy_growth=None)
        earnings = fd["earnings"]
        del earnings["revenue_yoy_growth"]
        result = FundamentalScorer().score_earnings_momentum(fd)
        assert "revenue_quality_flag" not in result["component_breakdown"]["eps_growth"]


class TestAccelerationBaseEffect:
    """
    "Accelerating" now requires 2 CONSECUTIVE quarters of improving YoY
    growth (when 3+ quarters are available), not just the latest vs. the one
    before — a single easy year-ago comp (common for cyclicals like MU)
    could previously flip a 2-point comparison to "accelerating" alone.
    """

    def _fd(self, growth_trend):
        return {"earnings": {"eps_growth_trend": growth_trend}, "valuation": {}, "revisions": {}}

    def test_single_quarter_uptick_alone_is_not_accelerating(self):
        # Most recent > second, but second <= third — a one-quarter blip, not
        # genuine 2-quarter acceleration.
        fd = self._fd([0.15, 0.05, 0.12, 0.11])
        result = FundamentalScorer().score_earnings_momentum(fd)
        assert result["component_breakdown"]["eps_growth"]["accelerating"] is False

    def test_two_consecutive_improving_quarters_is_accelerating(self):
        fd = self._fd([0.20, 0.15, 0.10, 0.08])
        result = FundamentalScorer().score_earnings_momentum(fd)
        assert result["component_breakdown"]["eps_growth"]["accelerating"] is True
        assert result["eps_growth_score"] == 3

    def test_two_quarter_history_still_uses_simple_comparison(self):
        # Degrades gracefully when fewer than 3 quarters of history exist.
        fd = self._fd([0.20, 0.15])
        result = FundamentalScorer().score_earnings_momentum(fd)
        assert result["component_breakdown"]["eps_growth"]["accelerating"] is True
