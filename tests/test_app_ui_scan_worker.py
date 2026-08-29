"""Tests for app_ui/scan_worker.py's Alpha Vantage budget guard (App_UI_Scope.md §6)."""

from app_ui import scan_worker


def _cfg():
    # v2.2.116: per-scan estimates live under the single `alpha_vantage` block
    # (was a separate `alpha_vantage_budget` block with its own daily_limit).
    return {
        "alpha_vantage": {
            "daily_limit": 24,
            "reserve_for_owner_scan": 8,
            "per_scan_estimate": {"post_close": 8, "pre_market": 6, "mid_session": 6},
        },
    }


class TestAvBudgetStatus:
    def test_under_budget(self, monkeypatch):
        monkeypatch.setattr(scan_worker, "_read_av_call_count", lambda: 5)
        status = scan_worker.get_av_budget_status("post_close", cfg=_cfg())
        assert status == {
            "used": 5, "estimated": 8, "daily_limit": 24, "projected": 13, "would_exceed": False,
        }

    def test_would_exceed(self, monkeypatch):
        monkeypatch.setattr(scan_worker, "_read_av_call_count", lambda: 20)
        status = scan_worker.get_av_budget_status("post_close", cfg=_cfg())
        assert status["projected"] == 28
        assert status["would_exceed"] is True

    def test_exactly_at_limit_does_not_exceed(self, monkeypatch):
        monkeypatch.setattr(scan_worker, "_read_av_call_count", lambda: 18)
        status = scan_worker.get_av_budget_status("post_close", cfg=_cfg())
        assert status["projected"] == 26
        assert status["would_exceed"] is True
        # boundary at exactly the limit (24)
        monkeypatch.setattr(scan_worker, "_read_av_call_count", lambda: 16)
        status = scan_worker.get_av_budget_status("post_close", cfg=_cfg())
        assert status["projected"] == 24
        assert status["would_exceed"] is False

    def test_unknown_scan_type_estimates_zero(self, monkeypatch):
        monkeypatch.setattr(scan_worker, "_read_av_call_count", lambda: 0)
        status = scan_worker.get_av_budget_status("nonexistent", cfg=_cfg())
        assert status["estimated"] == 0
