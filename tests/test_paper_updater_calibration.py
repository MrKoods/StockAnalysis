"""
Tests for paper_trading/paper_updater.py::_maybe_run_calibration — the v2.2.20
auto-trigger hook wiring feedback_loop.py's calibration into the system that
actually runs (paper trading), rather than the never-used live/manual-
confirmation path. Mocks should_recalibrate/run_calibration/send_calibration_alert
directly rather than exercising the full update_paper_trades() (which needs
live yfinance calls, out of scope for this coverage).
"""

import paper_trading.paper_updater as pu


def _trades(n_closed, n_open=0):
    trades = [{"outcome": "win"} for _ in range(n_closed)]
    trades += [{"outcome": ""} for _ in range(n_open)]
    return trades


class TestMaybeRunCalibration:
    def test_not_due_skips_calibration_entirely(self, monkeypatch):
        monkeypatch.setattr(pu, "load_config", lambda: {})
        monkeypatch.setattr(pu, "should_recalibrate", lambda count, cfg=None: False)

        called = {"run_calibration": False}
        monkeypatch.setattr(pu, "run_calibration", lambda **kw: called.__setitem__("run_calibration", True))

        pu._maybe_run_calibration(_trades(5))
        assert called["run_calibration"] is False

    def test_due_and_passes_cleanly_sends_no_alert(self, monkeypatch):
        monkeypatch.setattr(pu, "load_config", lambda: {})
        monkeypatch.setattr(pu, "should_recalibrate", lambda count, cfg=None: True)
        monkeypatch.setattr(pu, "load_calibration_outcomes_from_paper_trades", lambda: [])
        monkeypatch.setattr(
            pu, "run_calibration",
            lambda **kw: {"status": "pass", "needs_version_increment": False, "weights_updated": True},
        )
        alerted = {"sent": False}
        monkeypatch.setattr(pu, "send_calibration_alert", lambda result: alerted.__setitem__("sent", True))

        pu._maybe_run_calibration(_trades(20))
        assert alerted["sent"] is False

    def test_failed_holdout_sends_alert(self, monkeypatch):
        monkeypatch.setattr(pu, "load_config", lambda: {})
        monkeypatch.setattr(pu, "should_recalibrate", lambda count, cfg=None: True)
        monkeypatch.setattr(pu, "load_calibration_outcomes_from_paper_trades", lambda: [])
        monkeypatch.setattr(
            pu, "run_calibration",
            lambda **kw: {"status": "fail", "needs_version_increment": False, "weights_updated": False},
        )
        alerted = {"result": None}
        monkeypatch.setattr(pu, "send_calibration_alert", lambda result: alerted.__setitem__("result", result))

        pu._maybe_run_calibration(_trades(20))
        assert alerted["result"] is not None
        assert alerted["result"]["status"] == "fail"

    def test_pass_needing_version_bump_sends_alert(self, monkeypatch):
        monkeypatch.setattr(pu, "load_config", lambda: {})
        monkeypatch.setattr(pu, "should_recalibrate", lambda count, cfg=None: True)
        monkeypatch.setattr(pu, "load_calibration_outcomes_from_paper_trades", lambda: [])
        monkeypatch.setattr(
            pu, "run_calibration",
            lambda **kw: {"status": "pass", "needs_version_increment": True, "weights_updated": False},
        )
        alerted = {"sent": False}
        monkeypatch.setattr(pu, "send_calibration_alert", lambda result: alerted.__setitem__("sent", True))

        pu._maybe_run_calibration(_trades(20))
        assert alerted["sent"] is True

    def test_calibration_exception_does_not_propagate(self, monkeypatch):
        monkeypatch.setattr(pu, "load_config", lambda: {})
        monkeypatch.setattr(pu, "should_recalibrate", lambda count, cfg=None: True)

        def _raise():
            raise RuntimeError("boom")
        monkeypatch.setattr(pu, "load_calibration_outcomes_from_paper_trades", _raise)

        pu._maybe_run_calibration(_trades(20))  # must not raise

    def test_config_load_failure_still_checks_recalibration(self, monkeypatch):
        def _raise():
            raise RuntimeError("no config file")
        monkeypatch.setattr(pu, "load_config", _raise)

        checked = {"cfg": "not_called"}
        monkeypatch.setattr(pu, "should_recalibrate", lambda count, cfg=None: checked.__setitem__("cfg", cfg) or False)

        pu._maybe_run_calibration(_trades(20))  # must not raise
        assert checked["cfg"] == {}

    def test_closed_count_excludes_open_trades(self, monkeypatch):
        monkeypatch.setattr(pu, "load_config", lambda: {})
        seen_counts = []
        monkeypatch.setattr(
            pu, "should_recalibrate",
            lambda count, cfg=None: seen_counts.append(count) or False,
        )
        pu._maybe_run_calibration(_trades(n_closed=7, n_open=3))
        assert seen_counts == [7]
