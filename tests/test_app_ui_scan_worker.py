"""Tests for app_ui/scan_worker.py's Alpha Vantage budget guard (App_UI_Scope.md §6)."""

from app_ui import scan_worker


def _cfg():
    return {
        "alpha_vantage_budget": {
            "post_close": 8, "pre_market": 6, "mid_session": 6, "daily_total": 20, "daily_limit": 25,
        },
    }


class TestAvBudgetStatus:
    def test_under_budget(self, monkeypatch):
        monkeypatch.setattr(scan_worker, "_read_av_call_count", lambda: 5)
        status = scan_worker.get_av_budget_status("post_close", cfg=_cfg())
        assert status == {
            "used": 5, "estimated": 8, "daily_limit": 25, "projected": 13, "would_exceed": False,
        }

    def test_would_exceed(self, monkeypatch):
        monkeypatch.setattr(scan_worker, "_read_av_call_count", lambda: 20)
        status = scan_worker.get_av_budget_status("post_close", cfg=_cfg())
        assert status["projected"] == 28
        assert status["would_exceed"] is True

    def test_exactly_at_limit_does_not_exceed(self, monkeypatch):
        monkeypatch.setattr(scan_worker, "_read_av_call_count", lambda: 19)
        status = scan_worker.get_av_budget_status("post_close", cfg=_cfg())
        assert status["projected"] == 27
        # 19 used + 8 estimated = 27 > 25 -> exceeds; sanity-check boundary at exactly 25
        monkeypatch.setattr(scan_worker, "_read_av_call_count", lambda: 17)
        status = scan_worker.get_av_budget_status("post_close", cfg=_cfg())
        assert status["projected"] == 25
        assert status["would_exceed"] is False

    def test_unknown_scan_type_estimates_zero(self, monkeypatch):
        monkeypatch.setattr(scan_worker, "_read_av_call_count", lambda: 0)
        status = scan_worker.get_av_budget_status("nonexistent", cfg=_cfg())
        assert status["estimated"] == 0
