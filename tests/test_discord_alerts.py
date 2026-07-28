"""
Tests for shared/utils/discord_alerts.py::send_calibration_alert — new in
v2.2.20 (feedback-loop auto-trigger wiring). The rest of this module has no
existing test coverage (pre-existing gap, out of scope here); this is scoped
to the one new function.
"""

from shared.utils.discord_alerts import send_calibration_alert


class TestSendCalibrationAlert:
    def test_posts_when_webhook_configured(self, monkeypatch):
        monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://discord.example/webhook")

        posted = {}

        class _FakeResponse:
            status_code = 204

        def _fake_post(url, json=None, timeout=10):
            posted["url"] = url
            posted["json"] = json
            return _FakeResponse()

        import requests
        monkeypatch.setattr(requests, "post", _fake_post)

        result = send_calibration_alert({
            "status": "fail",
            "needs_version_increment": False,
            "train_count": 15,
            "holdout_count": 5,
            "holdout_win_rate_old": 0.1,
            "holdout_win_rate_new": 0.05,
            "current_weights": {"technical": 0.6, "sentiment": 0.25, "news": 0.15},
            "new_weights": {"technical": 0.62, "sentiment": 0.23, "news": 0.15},
        })
        assert result is True
        assert "embeds" in posted["json"]

    def test_no_webhook_configured_returns_false(self, monkeypatch):
        monkeypatch.delenv("DISCORD_WEBHOOK_URL", raising=False)
        result = send_calibration_alert({"status": "fail", "needs_version_increment": False})
        assert result is False

    def test_needs_version_increment_changes_title(self, monkeypatch):
        monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://discord.example/webhook")

        posted = {}

        class _FakeResponse:
            status_code = 204

        def _fake_post(url, json=None, timeout=10):
            posted["json"] = json
            return _FakeResponse()

        import requests
        monkeypatch.setattr(requests, "post", _fake_post)

        send_calibration_alert({"status": "pass", "needs_version_increment": True})
        title = posted["json"]["embeds"][0]["title"]
        assert "Version Bump Required" in title
