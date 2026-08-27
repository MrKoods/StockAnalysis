"""
Tests for research/reconcile.py — the Phase 1 pass bar.

The split checks matter most. An unadjusted split is the most likely way this
panel could be silently wrong and the most damaging to a momentum signal: a 4:1
split reads as a -75% return, which a ranking strategy would happily act on. So
these tests verify the check actually fires on corrupted data, not just that it
passes on clean data.
"""

import pandas as pd
import pytest

from research import config, reconcile

SPLIT_DATE = "2020-08-31"


def _series_with_split(ratio, adjusted, n=60, base=100.0, split_date=SPLIT_DATE):
    """
    A price series spanning `split_date`, either correctly adjusted or not.

    The break must land exactly ON the split date, not at an arbitrary index:
    check_splits compares the last close before the date against the first close
    on or after it, so a fixture that drops the price a few bars early tests
    nothing. (That mistake made the first version of these tests pass a series
    that was genuinely corrupt.)
    """
    idx = pd.bdate_range(end=pd.Timestamp(split_date) + pd.Timedelta(days=40), periods=n)
    split_ts = pd.Timestamp(split_date)
    values = []
    for i, ts in enumerate(idx):
        raw = base + i * 0.1
        values.append(raw if (adjusted or ts < split_ts) else raw / ratio)
    return pd.Series(values, index=idx)


class TestCheckSplits:
    def test_adjusted_series_passes(self, monkeypatch):
        monkeypatch.setattr(reconcile, "KNOWN_SPLITS", [("AAPL", "2020-08-31", 4.0)])
        prices = pd.DataFrame({"AAPL": _series_with_split(4.0, adjusted=True)})
        result = reconcile.check_splits(prices)[0]
        assert result["status"] == "pass"

    def test_unadjusted_split_is_caught_and_named(self, monkeypatch):
        monkeypatch.setattr(reconcile, "KNOWN_SPLITS", [("AAPL", "2020-08-31", 4.0)])
        prices = pd.DataFrame({"AAPL": _series_with_split(4.0, adjusted=False)})
        result = reconcile.check_splits(prices)[0]
        assert result["status"] == "FAIL"
        assert "UNADJUSTED" in result["detail"]

    def test_unadjusted_20_to_1_split_is_caught(self, monkeypatch):
        monkeypatch.setattr(reconcile, "KNOWN_SPLITS", [("AMZN", "2020-08-31", 20.0)])
        prices = pd.DataFrame({"AMZN": _series_with_split(20.0, adjusted=False)})
        assert reconcile.check_splits(prices)[0]["status"] == "FAIL"

    def test_ticker_absent_from_panel_is_skipped_not_failed(self, monkeypatch):
        monkeypatch.setattr(reconcile, "KNOWN_SPLITS", [("NVDA", "2024-06-10", 10.0)])
        prices = pd.DataFrame({"AAPL": _series_with_split(4.0, adjusted=True)})
        result = reconcile.check_splits(prices)[0]
        assert result["status"] == "skipped"
        assert "not in panel" in result["detail"]

    def test_split_date_outside_coverage_is_skipped(self, monkeypatch):
        monkeypatch.setattr(reconcile, "KNOWN_SPLITS", [("AAPL", "1999-01-01", 2.0)])
        prices = pd.DataFrame({"AAPL": _series_with_split(4.0, adjusted=True)})
        assert reconcile.check_splits(prices)[0]["status"] == "skipped"


class TestCheckSPYAnnualReturns:
    def _spy_year(self, year, total_return, n=252):
        """
        A SPY series for `year` PLUS a prior-December tail.

        The tail is required, not decoration: a published calendar-year return
        is measured from the prior year's final close, so a fixture containing
        only the target year gives the check nothing to measure from and it
        correctly reports "skipped". Omitting it is what made the first version
        of these tests fail against correct code.
        """
        idx = pd.bdate_range(f"{year}-01-01", periods=n)
        start = 100.0
        end = start * (1.0 + total_return)
        step = (end - start) / (n - 1)
        year_series = pd.Series([start + i * step for i in range(n)], index=idx)

        prior_idx = pd.bdate_range(end=idx[0] - pd.Timedelta(days=1), periods=10)
        prior = pd.Series([start] * 10, index=prior_idx)
        return pd.concat([prior, year_series])

    def test_matching_return_passes(self, monkeypatch):
        monkeypatch.setattr(reconcile, "SPY_ANNUAL_TOTAL_RETURN", {2020: 0.184})
        context = pd.DataFrame({config.BENCHMARK: self._spy_year(2020, 0.184)})
        assert reconcile.check_spy_annual_returns(context)[0]["status"] == "pass"

    def test_materially_wrong_return_fails(self, monkeypatch):
        monkeypatch.setattr(reconcile, "SPY_ANNUAL_TOTAL_RETURN", {2020: 0.184})
        context = pd.DataFrame({config.BENCHMARK: self._spy_year(2020, -0.40)})
        result = reconcile.check_spy_annual_returns(context)[0]
        assert result["status"] == "FAIL"
        assert "delta" in result["detail"]

    def test_small_difference_within_tolerance_passes(self, monkeypatch):
        # Reinvestment timing legitimately moves this by a little. Derived from
        # the tolerance constant rather than hardcoded, so tightening the
        # tolerance can't silently invalidate the test's premise — which is
        # exactly what happened when it dropped from 2pp to 0.5pp.
        monkeypatch.setattr(reconcile, "SPY_ANNUAL_TOTAL_RETURN", {2020: 0.184})
        within = 0.184 + reconcile._SPY_RETURN_TOLERANCE * 0.6
        context = pd.DataFrame({config.BENCHMARK: self._spy_year(2020, within)})
        assert reconcile.check_spy_annual_returns(context)[0]["status"] == "pass"

    def test_difference_just_outside_tolerance_fails(self, monkeypatch):
        monkeypatch.setattr(reconcile, "SPY_ANNUAL_TOTAL_RETURN", {2020: 0.184})
        outside = 0.184 + reconcile._SPY_RETURN_TOLERANCE * 1.5
        context = pd.DataFrame({config.BENCHMARK: self._spy_year(2020, outside)})
        assert reconcile.check_spy_annual_returns(context)[0]["status"] == "FAIL"

    def test_missing_benchmark_is_a_failure_not_a_skip(self):
        result = reconcile.check_spy_annual_returns(pd.DataFrame({"QQQ": [1.0, 2.0]}))[0]
        assert result["status"] == "FAIL"

    def test_thin_year_is_skipped(self, monkeypatch):
        monkeypatch.setattr(reconcile, "SPY_ANNUAL_TOTAL_RETURN", {2020: 0.184})
        context = pd.DataFrame({config.BENCHMARK: self._spy_year(2020, 0.184, n=20)})
        assert reconcile.check_spy_annual_returns(context)[0]["status"] == "skipped"


class TestRunReconciliation:
    @pytest.fixture
    def clean_panel(self, tmp_path, monkeypatch):
        from research import panel

        idx = pd.bdate_range("2019-01-01", "2021-12-31")
        prices = pd.DataFrame(
            {"AAA": [100.0 + i * 0.05 for i in range(len(idx))]}, index=idx
        )
        context = pd.DataFrame(
            {config.BENCHMARK: [100.0 + i * 0.05 for i in range(len(idx))]}, index=idx
        )
        monkeypatch.setattr(panel, "_PRICE_PANEL", tmp_path / "p.pkl")
        monkeypatch.setattr(panel, "_VOLUME_PANEL", tmp_path / "v.pkl")
        monkeypatch.setattr(panel, "_CONTEXT_PANEL", tmp_path / "c.pkl")
        panel._write_frame(prices, panel._PRICE_PANEL)
        panel._write_frame(prices * 1000, panel._VOLUME_PANEL)
        panel._write_frame(context, panel._CONTEXT_PANEL)

    def test_summary_counts_and_overall_verdict(self, clean_panel, monkeypatch):
        monkeypatch.setattr(reconcile, "KNOWN_SPLITS", [])
        monkeypatch.setattr(reconcile, "SPY_ANNUAL_TOTAL_RETURN", {})
        report = reconcile.run_reconciliation(skip_network=True)
        assert report["summary"]["failed"] == 0
        assert report["summary"]["passed_overall"] is True

    def test_a_single_failure_fails_the_whole_run(self, clean_panel, monkeypatch):
        monkeypatch.setattr(reconcile, "KNOWN_SPLITS", [])
        # The panel's synthetic SPY rises ~28% over 2020; claim it should fall.
        monkeypatch.setattr(reconcile, "SPY_ANNUAL_TOTAL_RETURN", {2020: -0.40})
        report = reconcile.run_reconciliation(skip_network=True)
        assert report["summary"]["failed"] >= 1
        assert report["summary"]["passed_overall"] is False

    def test_skips_do_not_fail_the_run(self, clean_panel, monkeypatch):
        monkeypatch.setattr(reconcile, "KNOWN_SPLITS", [("ZZZZ", "2020-01-02", 2.0)])
        monkeypatch.setattr(reconcile, "SPY_ANNUAL_TOTAL_RETURN", {})
        report = reconcile.run_reconciliation(skip_network=True)
        assert report["summary"]["skipped"] == 1
        assert report["summary"]["passed_overall"] is True

    def test_offline_mode_runs_no_network_checks(self, clean_panel, monkeypatch):
        monkeypatch.setattr(reconcile, "KNOWN_SPLITS", [])
        monkeypatch.setattr(reconcile, "SPY_ANNUAL_TOTAL_RETURN", {})
        report = reconcile.run_reconciliation(skip_network=True)
        assert report["independent_fetch"] == []
