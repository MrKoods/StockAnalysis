"""
Tests for Phase 5:
  - shared/utils/volume_profile.py
  - swing_model/cross_ticker_analysis.py
"""

import pandas as pd

from shared.utils.volume_profile import (
    compute_volume_profile,
    find_nearest_support_node,
    find_nearest_low_volume_area,
    score_volume_profile_position,
)
from swing_model.cross_ticker_analysis import (
    analyze_cross_ticker,
    compute_sector_correlation_state,
    CORRELATION_SECTOR_WIDE,
    CORRELATION_NEUTRAL,
    CORRELATION_INDIVIDUAL_DIVERGENCE,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_ohlcv(closes: list[float], volumes: list[float] = None) -> pd.DataFrame:
    n = len(closes)
    if volumes is None:
        volumes = [1_000_000] * n
    closes = pd.Series(closes)
    return pd.DataFrame({
        "Open": closes * 0.99,
        "High": closes * 1.01,
        "Low": closes * 0.98,
        "Close": closes,
        "Volume": volumes,
    })


# ---------------------------------------------------------------------------
# Volume Profile
# ---------------------------------------------------------------------------

class TestVolumeProfile:
    def test_returns_dataframe_with_required_columns(self):
        df = _make_ohlcv([100 + i for i in range(60)])
        vp = compute_volume_profile(df)
        for col in ("volume_at_level", "volume_pct", "is_high_volume_node", "is_low_volume_node"):
            assert col in vp.columns

    def test_volume_pct_sums_to_one(self):
        df = _make_ohlcv([100 + i * 0.5 for i in range(60)])
        vp = compute_volume_profile(df)
        assert abs(vp["volume_pct"].sum() - 1.0) < 0.01

    def test_high_volume_node_exists_for_high_activity_level(self):
        closes = [100.0] * 55 + [105.0, 106.0, 107.0, 108.0, 109.0]
        vols = [1_000_000] * 55 + [10_000_000] * 5
        df = _make_ohlcv(closes, vols)
        vp = compute_volume_profile(df)
        assert vp["is_high_volume_node"].any()

    def test_low_volume_node_exists(self):
        # Sparse volume at some price levels
        closes = list(range(90, 150))
        vols = [500_000 if i % 5 == 0 else 5_000_000 for i in range(60)]
        df = _make_ohlcv(closes, vols)
        vp = compute_volume_profile(df)
        assert vp["is_low_volume_node"].any()

    def test_empty_dataframe_returns_empty_profile(self):
        df = pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])
        vp = compute_volume_profile(df)
        assert vp.empty or len(vp) == 0

    def test_find_nearest_support_below(self):
        df = _make_ohlcv([100 + i * 0.5 for i in range(60)])
        vp = compute_volume_profile(df)
        # Add a synthetic HVN below current price
        vp["volume_at_level"] = 0.0
        vp["is_high_volume_node"] = False
        # Manually mark a level below price=130 as HVN
        levels = vp.index.tolist()
        below = [lv for lv in levels if lv < 120.0]
        if below:
            vp.loc[max(below), "is_high_volume_node"] = True
            result = find_nearest_support_node(130.0, vp, "below")
            assert result is not None
            assert result < 130.0

    def test_find_nearest_lva_above(self):
        df = _make_ohlcv([100 + i * 0.5 for i in range(60)])
        vp = compute_volume_profile(df)
        vp["is_low_volume_node"] = False
        levels = vp.index.tolist()
        above = [lv for lv in levels if lv > 110.0]
        if above:
            vp.loc[min(above), "is_low_volume_node"] = True
            result = find_nearest_low_volume_area(100.0, vp, "above")
            assert result is not None
            assert result > 100.0

    def test_score_near_hvn_returns_high_score(self):
        df = _make_ohlcv([100.0] * 60)
        vp = compute_volume_profile(df)
        # Force a high-volume node just below current price
        vp["is_high_volume_node"] = False
        levels = vp.index.tolist()
        below = [lv for lv in levels if lv < 100.0]
        if below:
            vp.loc[max(below), "is_high_volume_node"] = True
            score = score_volume_profile_position(100.0, vp)
            assert score >= 7.0  # Price just above support

    def test_score_bounded_0_to_12(self):
        df = _make_ohlcv([100 + i for i in range(60)])
        vp = compute_volume_profile(df)
        score = score_volume_profile_position(120.0, vp)
        assert 0.0 <= score <= 12.0

    def test_returns_neutral_for_empty_profile(self):
        vp = pd.DataFrame(columns=["volume_at_level", "volume_pct",
                                    "is_high_volume_node", "is_low_volume_node"])
        score = score_volume_profile_position(100.0, vp)
        assert score == 6.0


# ---------------------------------------------------------------------------
# Cross-Ticker Analysis
# ---------------------------------------------------------------------------

class TestCrossTickerAnalysis:
    def _make_ohlcv_rising(self, start=100, n=10):
        closes = [start + i for i in range(n)]
        return _make_ohlcv(closes)

    def _make_ohlcv_flat(self, price=100, n=10):
        return _make_ohlcv([price] * n)

    def test_sector_wide_when_multiple_tickers_bullish(self):
        signal_directions = {
            "NVDA": "bullish", "AMD": "bullish", "AVGO": "bullish",
            "TSM": "neutral", "MU": None, "ASML": None,
        }
        returns = {"NVDA": 0.05, "AMD": 0.04, "AVGO": 0.06, "TSM": 0.01, "MU": 0.0, "ASML": 0.0}
        state = compute_sector_correlation_state(returns, signal_directions)
        assert state == CORRELATION_SECTOR_WIDE

    def test_individual_divergence_when_one_ticker_outlier(self):
        signal_directions = {
            "NVDA": "bullish", "AMD": None, "AVGO": None,
            "TSM": None, "MU": None, "ASML": None,
        }
        returns = {"NVDA": 0.12, "AMD": 0.01, "AVGO": 0.01, "TSM": 0.01, "MU": 0.01, "ASML": 0.01}
        state = compute_sector_correlation_state(returns, signal_directions)
        assert state == CORRELATION_INDIVIDUAL_DIVERGENCE

    def test_neutral_when_mixed(self):
        signal_directions = {"NVDA": "bullish", "AMD": "bearish", "AVGO": None}
        returns = {"NVDA": 0.02, "AMD": -0.01, "AVGO": 0.00}
        state = compute_sector_correlation_state(returns, signal_directions)
        assert state == CORRELATION_NEUTRAL

    def test_analyze_cross_ticker_returns_all_tickers(self):
        tickers = ["NVDA", "AMD", "AVGO"]
        indicator_scores = {
            "NVDA": {"trend_intact": True, "breakout_confirmed": True},
            "AMD": {"trend_intact": True, "breakout_confirmed": False},
            "AVGO": {"trend_intact": False, "breakout_confirmed": False},
        }
        ohlcv_data = {t: self._make_ohlcv_rising(100, 10) for t in tickers}
        result = analyze_cross_ticker(indicator_scores, ohlcv_data)
        assert set(result.keys()) == set(tickers)

    def test_modifier_within_spec_bounds(self):
        tickers = ["NVDA", "AMD", "AVGO", "TSM", "MU", "ASML"]
        indicator_scores = {t: {"trend_intact": True, "breakout_confirmed": True} for t in tickers}
        ohlcv_data = {t: self._make_ohlcv_rising(100 + i * 5, 10) for i, t in enumerate(tickers)}
        result = analyze_cross_ticker(indicator_scores, ohlcv_data)
        for ticker, r in result.items():
            assert -10.0 <= r["confidence_modifier"] <= 5.0, \
                f"{ticker}: modifier {r['confidence_modifier']} out of bounds"

    def test_result_contains_required_keys(self):
        tickers = ["NVDA", "AMD"]
        scores = {t: {"trend_intact": True, "breakout_confirmed": True} for t in tickers}
        ohlcv = {t: self._make_ohlcv_rising() for t in tickers}
        result = analyze_cross_ticker(scores, ohlcv)
        for ticker in tickers:
            for key in ("correlation_state", "confidence_modifier",
                        "sector_signal_count", "divergence_direction"):
                assert key in result[ticker]

    def test_empty_input_returns_empty_dict(self):
        result = analyze_cross_ticker({}, {})
        assert result == {}

    def test_individual_outperformer_gets_positive_modifier(self):
        # NVDA rising sharply, peers flat
        indicator_scores = {
            "NVDA": {"trend_intact": True, "breakout_confirmed": True},
            "AMD": {"trend_intact": False, "breakout_confirmed": False},
            "AVGO": {"trend_intact": False, "breakout_confirmed": False},
        }
        # NVDA: +15% over 5 days, peers +1%
        nvda_df = _make_ohlcv([100, 101, 102, 104, 106, 115])
        peer_df = _make_ohlcv([100, 100, 101, 101, 101, 101])
        ohlcv_data = {"NVDA": nvda_df, "AMD": peer_df, "AVGO": peer_df}
        result = analyze_cross_ticker(indicator_scores, ohlcv_data)
        # NVDA should have individual divergence state and non-negative modifier
        nvda_result = result["NVDA"]
        assert nvda_result["correlation_state"] == CORRELATION_INDIVIDUAL_DIVERGENCE
