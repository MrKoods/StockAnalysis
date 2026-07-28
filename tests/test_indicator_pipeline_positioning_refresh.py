"""
Tests for swing_model/indicator_pipeline.py's fetch_positioning_data() IV-history
accumulation — added alongside the Greeks filter (CHANGELOG v2.2.22) so
trade_selector.py can prefer premium-selling/buying structures based on a real
IV percentile instead of an always-neutral 50. Covers: history grows once per
ticker per refresh day (not per call), percentile is computed against PRIOR
days only (not diluted by including today's own reading), the neutral-until-
enough-data fallback, and the rolling history cap.
"""

import contextlib
from datetime import datetime
from unittest.mock import patch

import pytest

import swing_model.indicator_pipeline as ip


@pytest.fixture(autouse=True)
def _isolate_state_file(tmp_path, monkeypatch):
    monkeypatch.setattr(ip, "_POSITIONING_STATE_PATH", tmp_path / "positioning_state.json")


@contextlib.contextmanager
def _frozen_now(dt):
    """Same technique as test_indicator_pipeline_fundamental_refresh.py's
    _frozen_now — patches ip.datetime.now so the ET-aware cadence check
    resolves to a fixed instant, while leaving .strptime pointed at the real
    implementation."""
    with patch.object(ip, "datetime") as mock_dt:
        mock_dt.now.side_effect = lambda tz=None: dt.replace(tzinfo=tz) if tz else dt
        mock_dt.strptime = datetime.strptime
        yield


def _fake_positioning(atm_iv):
    def _fetch(ticker, current_price=None, min_dte=5):
        return {
            "ticker": ticker,
            "options": {"put_call_ratio": 1.0, "iv_skew": 0.0, "atm_iv": atm_iv, "chain": [], "dte": 10},
            "institutional": None, "short_interest": None, "analyst_trend": None, "insider_transactions": None,
        }
    return _fetch


class TestIvHistoryAccumulation:
    def test_history_grows_one_reading_per_refresh_day(self):
        state = None
        for day, iv in enumerate([0.30, 0.32, 0.28], start=20):
            with patch.object(ip, "fetch_all_positioning", side_effect=_fake_positioning(iv)):
                with _frozen_now(datetime(2026, 7, day, 9, 0)):
                    state = ip.fetch_positioning_data(["NVDA"], {"NVDA": 100.0})
        assert state["iv_history"]["NVDA"] == [0.30, 0.32, 0.28]

    def test_same_day_second_call_does_not_duplicate_history(self):
        with patch.object(ip, "fetch_all_positioning", side_effect=_fake_positioning(0.30)):
            with _frozen_now(datetime(2026, 7, 20, 9, 0)):
                ip.fetch_positioning_data(["NVDA"], {"NVDA": 100.0})
                state = ip.fetch_positioning_data(["NVDA"], {"NVDA": 100.0})
        assert state["iv_history"]["NVDA"] == [0.30]

    def test_iv_percentile_computed_against_prior_history_not_including_today(self):
        # 10 identical low-IV days, then one high-IV day — today's reading should
        # score at the top of the *prior* 10 days, not be diluted by itself.
        with patch.object(ip, "fetch_all_positioning", side_effect=_fake_positioning(0.20)):
            for day in range(1, 11):
                with _frozen_now(datetime(2026, 7, day, 9, 0)):
                    ip.fetch_positioning_data(["NVDA"], {"NVDA": 100.0})

        with patch.object(ip, "fetch_all_positioning", side_effect=_fake_positioning(0.50)):
            with _frozen_now(datetime(2026, 7, 11, 9, 0)):
                state = ip.fetch_positioning_data(["NVDA"], {"NVDA": 100.0})

        options = state["tickers"]["NVDA"]["options"]
        assert options["iv_percentile"] == 100.0
        assert options["data_quality"] == "sufficient_history"

    def test_insufficient_history_reports_neutral_percentile(self):
        with patch.object(ip, "fetch_all_positioning", side_effect=_fake_positioning(0.30)):
            with _frozen_now(datetime(2026, 7, 20, 9, 0)):
                state = ip.fetch_positioning_data(["NVDA"], {"NVDA": 100.0})
        options = state["tickers"]["NVDA"]["options"]
        assert options["iv_percentile"] == 50.0
        assert options["data_quality"] == "insufficient_history"

    def test_history_capped_at_max_days(self):
        state = None
        with patch.object(ip, "fetch_all_positioning", side_effect=_fake_positioning(0.30)):
            for day_offset in range(1, ip._MAX_IV_HISTORY_DAYS + 20):
                dt = datetime.fromordinal(datetime(2020, 1, 1).toordinal() + day_offset)
                with _frozen_now(dt):
                    state = ip.fetch_positioning_data(["NVDA"], {"NVDA": 100.0})
        assert len(state["iv_history"]["NVDA"]) == ip._MAX_IV_HISTORY_DAYS

    def test_min_dte_passed_through_from_cfg(self):
        captured = {}

        def _fetch(ticker, current_price=None, min_dte=5):
            captured["min_dte"] = min_dte
            return _fake_positioning(0.30)()(ticker, current_price, min_dte)

        with patch.object(ip, "fetch_all_positioning", side_effect=_fetch):
            with _frozen_now(datetime(2026, 7, 20, 9, 0)):
                ip.fetch_positioning_data(["NVDA"], {"NVDA": 100.0}, cfg={"greeks_filter": {"min_dte": 7}})
        assert captured["min_dte"] == 7
