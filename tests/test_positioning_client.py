"""
Tests for shared/api_clients/positioning_client.py's pure/testable helpers —
_pick_expiration, _build_chain_list, compute_iv_percentile. The live
fetch_option_chain_metrics() call itself isn't tested here (no yfinance
mocking convention exists elsewhere in this suite — see test_positioning_layer.py,
which tests compute_positioning_score against hand-built dicts instead of the
live fetch), consistent with the rest of this project's test style.
"""

from datetime import datetime, timedelta, timezone

import pandas as pd

from shared.api_clients.positioning_client import (
    _pick_expiration,
    _build_chain_list,
    compute_iv_percentile,
)


def _exp_str(days_out: int) -> str:
    return (datetime.now(timezone.utc).date() + timedelta(days=days_out)).strftime("%Y-%m-%d")


class TestPickExpiration:
    def test_picks_first_expiration_clearing_min_dte(self):
        expirations = (_exp_str(1), _exp_str(3), _exp_str(10), _exp_str(30))
        assert _pick_expiration(expirations, min_dte=5) == _exp_str(10)

    def test_nearest_expiration_used_when_it_already_clears_floor(self):
        expirations = (_exp_str(7), _exp_str(14))
        assert _pick_expiration(expirations, min_dte=5) == _exp_str(7)

    def test_falls_back_to_longest_dated_when_none_clear_floor(self):
        expirations = (_exp_str(0), _exp_str(1), _exp_str(2))
        assert _pick_expiration(expirations, min_dte=5) == _exp_str(2)

    def test_malformed_expiration_strings_are_skipped(self):
        expirations = ("not-a-date", _exp_str(10))
        assert _pick_expiration(expirations, min_dte=5) == _exp_str(10)


class TestBuildChainList:
    _COLUMNS = ["strike", "bid", "ask", "impliedVolatility", "openInterest"]

    def _chain_df(self, rows: list[dict]) -> pd.DataFrame:
        # yfinance's real option_chain() always returns these columns even when
        # 0 rows — pd.DataFrame([]) alone drops all columns, which _build_chain_list
        # would never actually see in production.
        return pd.DataFrame(rows, columns=self._COLUMNS) if not rows else pd.DataFrame(rows)

    def test_restricts_to_band_around_current_price(self):
        calls = self._chain_df([
            {"strike": 90.0, "bid": 1.0, "ask": 1.2, "impliedVolatility": 0.3, "openInterest": 50},
            {"strike": 100.0, "bid": 2.0, "ask": 2.2, "impliedVolatility": 0.3, "openInterest": 100},
            {"strike": 200.0, "bid": 0.1, "ask": 0.2, "impliedVolatility": 0.3, "openInterest": 10},
        ])
        puts = self._chain_df([])
        result = _build_chain_list(calls, puts, current_price=100.0, expiration="2027-01-01")
        strikes = {c["strike"] for c in result}
        assert 90.0 in strikes and 100.0 in strikes
        assert 200.0 not in strikes  # outside +/-20% band

    def test_no_current_price_uses_full_chain(self):
        calls = self._chain_df([
            {"strike": 10.0, "bid": 1.0, "ask": 1.1, "impliedVolatility": 0.3, "openInterest": 5},
            {"strike": 500.0, "bid": 0.5, "ask": 0.6, "impliedVolatility": 0.3, "openInterest": 5},
        ])
        puts = self._chain_df([])
        result = _build_chain_list(calls, puts, current_price=None, expiration="2027-01-01")
        assert len(result) == 2

    def test_contracts_missing_bid_ask_or_iv_are_skipped(self):
        calls = self._chain_df([
            {"strike": 100.0, "bid": None, "ask": 1.2, "impliedVolatility": 0.3, "openInterest": 50},
            {"strike": 101.0, "bid": 1.0, "ask": 1.2, "impliedVolatility": None, "openInterest": 50},
            {"strike": 102.0, "bid": 1.0, "ask": 1.2, "impliedVolatility": 0.3, "openInterest": 50},
        ])
        puts = self._chain_df([])
        result = _build_chain_list(calls, puts, current_price=100.0, expiration="2027-01-01")
        assert len(result) == 1
        assert result[0]["strike"] == 102.0

    def test_output_shape(self):
        calls = self._chain_df([
            {"strike": 100.0, "bid": 2.0, "ask": 2.2, "impliedVolatility": 0.35, "openInterest": 123},
        ])
        puts = self._chain_df([
            {"strike": 100.0, "bid": 1.8, "ask": 2.0, "impliedVolatility": 0.40, "openInterest": 88},
        ])
        result = _build_chain_list(calls, puts, current_price=100.0, expiration="2027-01-01")
        by_type = {c["option_type"] for c in result}
        assert by_type == {"call", "put"}
        for c in result:
            assert set(c.keys()) == {"strike", "option_type", "bid", "ask", "iv", "open_interest", "expiration"}


class TestComputeIvPercentile:
    def test_current_iv_none_reports_unavailable(self):
        result = compute_iv_percentile(None, [0.2, 0.3, 0.4])
        assert result["data_quality"] == "unavailable"
        assert result["iv_percentile"] == 50.0

    def test_insufficient_history_reports_neutral(self):
        result = compute_iv_percentile(0.35, [0.2, 0.3])  # below _MIN_IV_HISTORY_SAMPLES
        assert result["data_quality"] == "insufficient_history"
        assert result["iv_percentile"] == 50.0

    def test_sufficient_history_computes_real_percentile(self):
        history = [round(0.10 + 0.01 * i, 2) for i in range(20)]  # 0.10 .. 0.29
        result = compute_iv_percentile(0.29, history)  # highest of the history
        assert result["data_quality"] == "sufficient_history"
        assert result["iv_percentile"] == 100.0

    def test_low_current_iv_scores_low_percentile(self):
        history = [round(0.10 + 0.01 * i, 2) for i in range(20)]
        result = compute_iv_percentile(0.10, history)  # lowest of the history
        assert result["data_quality"] == "sufficient_history"
        assert result["iv_percentile"] <= 10.0

    def test_none_values_in_history_are_ignored(self):
        history = [0.2] * 10 + [None, None]
        result = compute_iv_percentile(0.2, history)
        assert result["data_quality"] == "sufficient_history"
