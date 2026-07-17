"""
Tests for swing_model/fundamental_layer.py's outlier-exclusion logic.

Scope: _exclude_outliers() and its integration into score_valuation_vs_peers().
Not a full-module test suite for fundamental_layer.py (no coverage existed
before this file) — focused on the outlier-exclusion fix specifically.
"""

from swing_model.fundamental_layer import FundamentalScorer, _exclude_outliers


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
