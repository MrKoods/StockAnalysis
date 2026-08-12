"""
Tests for shared/utils/discord_alerts.py::send_calibration_alert — new in
v2.2.20 (feedback-loop auto-trigger wiring). Also covers send_paper_signal_alert,
extended in v2.2.51's Discord-alert follow-up to surface trade structure,
position size/type, capital deployed, and sizing_note — fields that were
already computed and persisted to paper_trades.csv but never reached the
actual Discord notification, so a 0-size row looked identical there to a
fully-deployed one. The rest of this module has no existing test coverage
(pre-existing gap, out of scope here); this is scoped to these two functions.
"""

from shared.utils.discord_alerts import send_calibration_alert, send_paper_signal_alert


def _fake_webhook(monkeypatch):
    """Patches DISCORD_WEBHOOK_URL + requests.post, returns the posted-json dict."""
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://discord.example/webhook")
    posted = {}

    class _FakeResponse:
        status_code = 204

    def _fake_post(url, json=None, timeout=10):
        posted["json"] = json
        return _FakeResponse()

    import requests
    monkeypatch.setattr(requests, "post", _fake_post)
    return posted


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


def _field(embed: dict, name: str) -> str:
    return next(f["value"] for f in embed["fields"] if f["name"] == name)


def _field_names(embed: dict) -> set:
    return {f["name"] for f in embed["fields"]}


class TestSendPaperSignalAlert:
    def test_shares_trade_shows_structure_position_and_capital(self, monkeypatch):
        posted = _fake_webhook(monkeypatch)
        send_paper_signal_alert({
            "ticker": "JNJ", "confidence": 71.0,
            "structure_recommended": "long_stock", "position_type": "shares",
            "position_size": "2", "capital_deployed": "549.80",
        })
        embed = posted["json"]["embeds"][0]
        assert _field(embed, "Trade Structure") == "Long Stock"
        assert _field(embed, "Position") == "2 shares"
        assert _field(embed, "Capital Deployed") == "$549.80"

    def test_options_trade_uses_contract_unit(self, monkeypatch):
        posted = _fake_webhook(monkeypatch)
        send_paper_signal_alert({
            "ticker": "PFE", "confidence": 71.0,
            "structure_recommended": "long_strangle", "position_type": "options",
            "position_size": "3", "capital_deployed": "72.60",
        })
        embed = posted["json"]["embeds"][0]
        assert _field(embed, "Position") == "3 options contracts"

    def test_single_unit_is_not_pluralized(self, monkeypatch):
        posted = _fake_webhook(monkeypatch)
        send_paper_signal_alert({
            "ticker": "AMZN", "confidence": 70.7,
            "structure_recommended": "", "position_type": "shares",
            "position_size": "1", "capital_deployed": "287.20",
        })
        embed = posted["json"]["embeds"][0]
        assert _field(embed, "Position") == "1 share"

    def test_zero_size_with_sizing_note_shows_warning_field(self, monkeypatch):
        posted = _fake_webhook(monkeypatch)
        send_paper_signal_alert({
            "ticker": "JNJ", "confidence": 71.0,
            "structure_recommended": "long_strangle", "position_type": "options",
            "position_size": "0", "capital_deployed": "0.00",
            "sizing_note": "signal qualifies but sizes to 0 options at this account size "
                           "(risk budget was the binding constraint)",
        })
        embed = posted["json"]["embeds"][0]
        assert _field(embed, "Position") == "0 options contracts"
        assert "⚠️ Sizing Note" in _field_names(embed)
        assert "binding constraint" in _field(embed, "⚠️ Sizing Note")

    def test_no_sizing_note_omits_the_field(self, monkeypatch):
        posted = _fake_webhook(monkeypatch)
        send_paper_signal_alert({
            "ticker": "AMZN", "confidence": 70.7,
            "structure_recommended": "", "position_type": "shares",
            "position_size": "2", "capital_deployed": "574.40",
        })
        embed = posted["json"]["embeds"][0]
        names = _field_names(embed)
        assert "Sizing Note" not in names
        assert "⚠️ Sizing Note" not in names

    def test_missing_position_type_shows_dash(self, monkeypatch):
        posted = _fake_webhook(monkeypatch)
        send_paper_signal_alert({"ticker": "XYZ", "confidence": 70.0})
        embed = posted["json"]["embeds"][0]
        assert _field(embed, "Position") == "—"
        assert _field(embed, "Trade Structure") == "—"
