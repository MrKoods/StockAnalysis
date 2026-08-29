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

import shared.api_clients.positioning_client as positioning_client
from shared.api_clients.positioning_client import (
    _pick_expiration,
    _build_chain_list,
    compute_iv_percentile,
    compute_put_call_ratio_percentile,
    compute_iv_skew_percentile,
    fetch_short_interest,
    fetch_analyst_rating_trend,
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

    def test_void_bid_ask_pair_is_skipped(self):
        """
        bid=0.0 AND ask=0.0 together (not NaN) is a void/unquoted contract, not
        a real market — confirmed live (2026-08-03) across NVDA/ZION/ASML/HD/
        TGT/SBUX, where yfinance's free-tier chain returned real volume/lastPrice
        alongside bid=ask=0.0 on every near-the-money contract. Left in, this
        would look like a perfect $0.00-wide spread instead of the absent quote
        it actually is.
        """
        calls = self._chain_df([
            {"strike": 100.0, "bid": 0.0, "ask": 0.0, "impliedVolatility": 0.25, "openInterest": 0},
            {"strike": 101.0, "bid": 1.0, "ask": 1.2, "impliedVolatility": 0.3, "openInterest": 50},
        ])
        puts = self._chain_df([])
        result = _build_chain_list(calls, puts, current_price=100.0, expiration="2027-01-01")
        assert len(result) == 1
        assert result[0]["strike"] == 101.0

    def test_real_zero_bid_with_nonzero_ask_is_kept(self):
        """A genuinely far-OTM contract can legitimately have bid=0 (no one will
        pay anything) while still carrying a real ask — that's a real, if
        unattractive, one-sided quote, not the void bid=ask=0.0 failure mode."""
        calls = self._chain_df([
            {"strike": 100.0, "bid": 0.0, "ask": 0.05, "impliedVolatility": 0.25, "openInterest": 3},
        ])
        puts = self._chain_df([])
        result = _build_chain_list(calls, puts, current_price=100.0, expiration="2027-01-01")
        assert len(result) == 1

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


class TestComputePutCallRatioPercentile:
    def test_current_ratio_none_reports_unavailable(self):
        result = compute_put_call_ratio_percentile(None, [0.8, 1.0, 1.2])
        assert result["data_quality"] == "unavailable"
        assert result["put_call_ratio_percentile"] == 50.0

    def test_insufficient_history_reports_neutral(self):
        result = compute_put_call_ratio_percentile(1.0, [0.9, 1.1])
        assert result["data_quality"] == "insufficient_history"
        assert result["put_call_ratio_percentile"] == 50.0

    def test_lowest_ratio_scores_zero_percentile(self):
        history = [round(0.8 + 0.05 * i, 2) for i in range(20)]  # 0.80 .. 1.75
        result = compute_put_call_ratio_percentile(0.80, history)
        assert result["data_quality"] == "sufficient_history"
        assert result["put_call_ratio_percentile"] <= 10.0


class TestComputeIvSkewPercentile:
    def test_current_skew_none_reports_unavailable(self):
        result = compute_iv_skew_percentile(None, [0.02, 0.03, 0.04])
        assert result["data_quality"] == "unavailable"
        assert result["iv_skew_percentile"] == 50.0

    def test_insufficient_history_reports_neutral(self):
        result = compute_iv_skew_percentile(0.03, [0.02, 0.04])
        assert result["data_quality"] == "insufficient_history"
        assert result["iv_skew_percentile"] == 50.0

    def test_highest_skew_scores_max_percentile(self):
        history = [round(0.01 + 0.005 * i, 3) for i in range(20)]
        result = compute_iv_skew_percentile(history[-1], history)
        assert result["data_quality"] == "sufficient_history"
        assert result["iv_skew_percentile"] == 100.0


class TestFetchShortInterestConfigWiredThresholds:
    """Tier B batch 2 (2026-08-19): declining/increasing thresholds now read
    from config instead of being hardcoded ±5%."""

    def _mock_retry(self, monkeypatch, shares_short, shares_short_prior):
        monkeypatch.setattr(
            positioning_client, "retry_with_backoff",
            lambda fn, label=None: {
                "sharesShort": shares_short, "sharesShortPriorMonth": shares_short_prior,
                "shortRatio": 2.0, "shortPercentOfFloat": 0.05,
            },
        )

    def test_default_thresholds_classify_as_flat(self, monkeypatch):
        # -3% change — inside the default ±5% band
        self._mock_retry(monkeypatch, shares_short=970_000, shares_short_prior=1_000_000)
        result = fetch_short_interest("NVDA")
        assert result["trend"] == "flat"

    def test_narrower_configured_threshold_classifies_as_declining(self, monkeypatch):
        self._mock_retry(monkeypatch, shares_short=970_000, shares_short_prior=1_000_000)
        cfg = {"positioning": {"short_interest_declining_threshold": -0.02}}
        result = fetch_short_interest("NVDA", cfg=cfg)
        assert result["trend"] == "declining"

    def test_narrower_configured_threshold_classifies_as_increasing(self, monkeypatch):
        self._mock_retry(monkeypatch, shares_short=1_030_000, shares_short_prior=1_000_000)
        cfg = {"positioning": {"short_interest_increasing_threshold": 0.02}}
        result = fetch_short_interest("NVDA", cfg=cfg)
        assert result["trend"] == "increasing"


class TestFetchAnalystRatingTrend:
    """MR-3 (2026-08 API audit): analyst-rating trend now comes from Finnhub
    /stock/recommendation (a clean monthly strongBuy/buy/hold/sell/strongSell
    series) instead of yfinance Ticker.upgrades_downgrades."""

    @staticmethod
    def _series(monkeypatch, rows):
        from shared.api_clients import finnhub_client
        monkeypatch.setattr(finnhub_client, "get_recommendation_trend", lambda t: rows)

    def test_no_data_is_neutral(self, monkeypatch):
        self._series(monkeypatch, [])
        assert fetch_analyst_rating_trend("NVDA")["net_action"] == "none"

    def test_board_shifting_bullish_reads_as_upgrade(self, monkeypatch):
        self._series(monkeypatch, [
            {"period": "2026-08-01", "strongBuy": 20, "buy": 5, "hold": 2, "sell": 0, "strongSell": 0},
            {"period": "2026-07-01", "strongBuy": 5, "buy": 15, "hold": 5, "sell": 2, "strongSell": 1},
        ])
        r = fetch_analyst_rating_trend("NVDA", lookback_days=30)
        assert r["net_action"] == "upgrade" and r["recent_upgrades"] > 0

    def test_board_shifting_bearish_reads_as_downgrade(self, monkeypatch):
        self._series(monkeypatch, [
            {"period": "2026-08-01", "strongBuy": 2, "buy": 3, "hold": 8, "sell": 6, "strongSell": 4},
            {"period": "2026-07-01", "strongBuy": 10, "buy": 8, "hold": 3, "sell": 1, "strongSell": 0},
        ])
        assert fetch_analyst_rating_trend("NVDA")["net_action"] == "downgrade"

    def test_flat_board_reads_as_none(self, monkeypatch):
        row = {"period": "x", "strongBuy": 10, "buy": 10, "hold": 5, "sell": 1, "strongSell": 0}
        self._series(monkeypatch, [dict(row, period="2026-08-01"), dict(row, period="2026-07-01")])
        assert fetch_analyst_rating_trend("NVDA")["net_action"] == "none"

    def test_lookback_days_selects_comparison_month(self, monkeypatch):
        # 3 months of data; lookback_days=90 should compare Aug to May.
        self._series(monkeypatch, [
            {"period": "2026-08-01", "strongBuy": 20, "buy": 2, "hold": 1, "sell": 0, "strongSell": 0},
            {"period": "2026-07-01", "strongBuy": 19, "buy": 3, "hold": 1, "sell": 0, "strongSell": 0},
            {"period": "2026-05-01", "strongBuy": 1, "buy": 5, "hold": 10, "sell": 5, "strongSell": 2},
        ])
        assert fetch_analyst_rating_trend("NVDA", lookback_days=90)["net_action"] == "upgrade"


class TestFetchAllPositioningNewFields:
    """MSPR + SEC ownership filings are recorded on the positioning data (audit
    trail / future scoring), not yet a scored sub-signal (2026-08 API audit)."""

    def _stub_yf(self, monkeypatch):
        # Every yfinance-backed sub-fetch degrades to empty/None quickly.
        import shared.api_clients.positioning_client as pc
        monkeypatch.setattr(pc, "fetch_option_chain_metrics", lambda *a, **k: {})
        monkeypatch.setattr(pc, "fetch_institutional_ownership", lambda *a, **k: {})
        monkeypatch.setattr(pc, "fetch_short_interest", lambda *a, **k: {})
        monkeypatch.setattr(pc, "fetch_analyst_rating_trend", lambda *a, **k: {})
        monkeypatch.setattr(pc, "fetch_insider_transactions", lambda *a, **k: [])

    def test_mspr_and_ownership_filings_recorded(self, monkeypatch):
        from shared.api_clients import positioning_client as pc, finnhub_client
        from shared.api_clients import sec_edgar_client
        self._stub_yf(monkeypatch)
        monkeypatch.setattr(finnhub_client, "get_insider_mspr",
                            lambda t: [{"year": 2026, "month": 8, "mspr": -42.0, "change": -1000}])
        monkeypatch.setattr(sec_edgar_client, "fetch_recent_ownership_filings",
                            lambda t, **k: {"activist_13d": [{"form": "SC 13D", "filingDate": "2026-08-01", "accessionNumber": "a"}],
                                            "passive_13g": [], "institutional_13f": [], "insider_form4": []})
        out = pc.fetch_all_positioning("NVDA")
        assert out["insider_mspr"]["mspr"] == -42.0
        assert len(out["ownership_filings"]["activist_13d"]) == 1

    def test_new_field_fetch_failures_are_non_fatal(self, monkeypatch):
        from shared.api_clients import positioning_client as pc, finnhub_client
        from shared.api_clients import sec_edgar_client
        self._stub_yf(monkeypatch)
        monkeypatch.setattr(finnhub_client, "get_insider_mspr", lambda t: (_ for _ in ()).throw(RuntimeError("boom")))
        monkeypatch.setattr(sec_edgar_client, "fetch_recent_ownership_filings", lambda t, **k: (_ for _ in ()).throw(RuntimeError("boom")))
        out = pc.fetch_all_positioning("NVDA")
        assert out["insider_mspr"] is None and out["ownership_filings"] is None
        assert out["ticker"] == "NVDA"  # rest of the dict still intact
