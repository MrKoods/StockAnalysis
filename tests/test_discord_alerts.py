"""
Tests for shared/utils/discord_alerts.py::send_calibration_alert — new in
v2.2.20 (feedback-loop auto-trigger wiring). Also covers send_paper_signal_alert,
extended in v2.2.51's Discord-alert follow-up to surface trade structure,
position size/type, capital deployed, and sizing_note — fields that were
already computed and persisted to paper_trades.csv but never reached the
actual Discord notification, so a 0-size row looked identical there to a
fully-deployed one.

Also covers send_trade_alert/send_near_miss_alert's "Score Breakdown" field —
previously untested (a pre-existing gap), which is exactly how send_trade_alert
sat broken for a while: a partial refactor had removed its local
technical_score/positioning_score/... variable extraction in favor of the
shared _format_score_breakdown()/_extract_score_breakdown() helpers, but the
embed body was never updated to actually call them — every real call would
have raised NameError. Nothing here caught it until these tests were added.
"""

from shared.utils.discord_alerts import (
    send_calibration_alert,
    send_paper_signal_alert,
    send_trade_alert,
    send_near_miss_alert,
    send_weekly_summary_alert,
    send_macro_warning,
    _extract_score_breakdown,
    _format_score_breakdown,
)


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


class TestSendWeeklySummaryAlert:
    """
    2026-08-23 full model audit: generate_weekly_summary()'s docstring long
    claimed it "sends to Discord" but never actually did, and had no
    scheduled caller either — this safety mechanism (a review alert when the
    rolling 20-trade win rate drops below 70%) was completely dormant. These
    cover the actual send, handling both the "ok" (real trade_outcomes.csv
    history exists) and "no_data"/"no_trades" (go_live_gate/signal_accuracy
    still populated from paper_trades.csv either way) summary shapes.
    """

    def test_posts_ok_summary_with_win_rate_fields(self, monkeypatch):
        posted = _fake_webhook(monkeypatch)
        summary = {
            "status": "ok",
            "total_trades": 42,
            "win_rate_10": 0.6, "win_rate_20": 0.55, "win_rate_50": 0.52,
            "avg_rr_20": 1.8, "peak_to_trough_pct": 4.2,
            "review_triggered": False,
            "go_live_gate": {"overall_pass": False, "data_status": "insufficient_trades", "failures": ["only_11_trading_days_need_60"]},
            "signal_accuracy": {"total_closed": 2, "funded_count": 2, "unfunded_count": 0,
                                 "win_rate_all": 0.5, "win_rate_funded": 0.5, "win_rate_unfunded": 0.0},
        }
        result = send_weekly_summary_alert(summary, model_version="v2.2.78")
        assert result is True
        embed = posted["json"]["embeds"][0]
        assert "WEEKLY PERFORMANCE SUMMARY" in embed["title"]
        field_names = [f["name"] for f in embed["fields"]]
        assert "Win Rate (last 10 / 20 / 50)" in field_names
        assert "Go-Live Gate" in field_names

    def test_review_triggered_changes_title_and_color_to_red(self, monkeypatch):
        posted = _fake_webhook(monkeypatch)
        summary = {
            "status": "ok", "total_trades": 25,
            "win_rate_10": 0.4, "win_rate_20": 0.45, "win_rate_50": 0.5,
            "avg_rr_20": 1.2, "peak_to_trough_pct": 9.0,
            "review_triggered": True,
            "go_live_gate": {"overall_pass": False, "data_status": "evaluated", "failures": []},
            "signal_accuracy": {"total_closed": 25, "funded_count": 20, "unfunded_count": 5,
                                 "win_rate_all": 0.45, "win_rate_funded": 0.45, "win_rate_unfunded": 0.4},
        }
        result = send_weekly_summary_alert(summary, model_version="v2.2.78")
        assert result is True
        embed = posted["json"]["embeds"][0]
        assert "WEEKLY REVIEW" in embed["title"]
        assert embed["color"] == 0xFF4444  # _COLORS["red"]

    def test_no_data_summary_still_posts_go_live_gate(self, monkeypatch):
        """The early-return "no_data" shape (no trade_outcomes.csv rows yet)
        must not crash the send or silently omit go_live_gate/signal_accuracy
        — those are populated from paper_trades.csv independent of that file."""
        posted = _fake_webhook(monkeypatch)
        summary = {
            "status": "no_data",
            "win_rate_10": 0.0, "win_rate_20": 0.0, "win_rate_50": 0.0,
            "avg_rr_20": 0.0, "peak_to_trough_pct": 0.0,
            "total_trades": 0, "review_triggered": False,
            "go_live_gate": {"overall_pass": False, "data_status": "insufficient_trades", "failures": ["insufficient_trade_data_2_below_30"]},
            "signal_accuracy": {"total_closed": 2, "funded_count": 2, "unfunded_count": 0,
                                 "win_rate_all": 0.5, "win_rate_funded": 0.5, "win_rate_unfunded": 0.0},
        }
        result = send_weekly_summary_alert(summary, model_version="v2.2.78")
        assert result is True
        embed = posted["json"]["embeds"][0]
        field_names = [f["name"] for f in embed["fields"]]
        assert "Go-Live Gate" in field_names
        assert "Win-Rate Trend" in field_names  # not the win-rate-numbers field
        assert "Win Rate (last 10 / 20 / 50)" not in field_names

    def test_no_webhook_configured_returns_false(self, monkeypatch):
        monkeypatch.delenv("DISCORD_WEBHOOK_URL", raising=False)
        summary = {
            "status": "no_data", "total_trades": 0, "review_triggered": False,
            "go_live_gate": {}, "signal_accuracy": {},
        }
        assert send_weekly_summary_alert(summary) is False


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


class TestSendTradeAlert:
    """Regression coverage for the NameError described in this module's
    docstring — send_trade_alert's candidate dict uses scoring.py's own
    "_total"-suffixed keys (it's built as {**score, ...} in run_swing_model.py),
    unlike send_paper_signal_alert/send_near_miss_alert's "_score"-suffixed
    payloads."""

    def test_posts_successfully_with_scoring_total_suffixed_keys(self, monkeypatch):
        posted = _fake_webhook(monkeypatch)
        result = send_trade_alert({
            "ticker": "NVDA", "direction": "bullish", "confidence": 75.0,
            "entry_zone_lower": 100.0, "entry_zone_upper": 102.0,
            "stop_loss": 95.0, "target": 115.0, "rr_ratio": 3.0,
            "technical_total": 30.0, "positioning_total": 12.0,
            "sentiment_total": 10.0, "news_total": 8.0, "fundamental_score": 5.0,
        })
        assert result is True
        embed = posted["json"]["embeds"][0]
        breakdown = _field(embed, "Signal Breakdown")
        assert "Technical: 30.0/40" in breakdown
        assert "Positioning: 12.0/20" in breakdown
        assert "Sentiment: 10.0/15" in breakdown
        assert "News: 8.0/15" in breakdown
        assert "Fundamental: 5.0/10" in breakdown

    def test_reweighted_category_max_reflected_not_stale_nominal(self, monkeypatch):
        """technical_max/sentiment_max/news_max (set by scoring.py when
        calibrated live_weights are active) must show up in the breakdown
        instead of the hardcoded nominal 40/15/15."""
        posted = _fake_webhook(monkeypatch)
        send_trade_alert({
            "ticker": "AMZN", "direction": "bullish", "confidence": 80.0,
            "entry_zone_lower": 100.0, "entry_zone_upper": 102.0,
            "stop_loss": 95.0, "target": 115.0, "rr_ratio": 3.0,
            "technical_total": 20.0, "technical_max": 28.0,
            "sentiment_total": 21.3, "sentiment_max": 28.0,
            "positioning_total": 12.0, "news_total": 8.0, "news_max": 14.0,
            "fundamental_score": 5.0,
        })
        embed = posted["json"]["embeds"][0]
        breakdown = _field(embed, "Signal Breakdown")
        assert "Technical: 20.0/28" in breakdown
        assert "Sentiment: 21.3/28" in breakdown
        assert "News: 8.0/14" in breakdown


class TestSendNearMissAlert:
    def test_posts_successfully_with_score_suffixed_keys(self, monkeypatch):
        posted = _fake_webhook(monkeypatch)
        result = send_near_miss_alert({
            "ticker": "MU", "confidence": 66.5, "direction": "bullish", "regime": "trending_up",
            "technical_score": 31.3, "positioning_score": 9.7,
            "sentiment_score": 8.3, "news_score": 3.6, "fundamental_score": 8.7,
            "total_modifier": 5.0,
        })
        assert result is True
        embed = posted["json"]["embeds"][0]
        breakdown = _field(embed, "Score Breakdown")
        assert "Tech: **31.3**/40" in breakdown
        assert "Pos: **9.7**/20" in breakdown
        assert "Sent: **8.3**/15" in breakdown
        assert "News: **3.6**/15" in breakdown
        assert "Fund: **8.7**/10" in breakdown


class TestScoreBreakdownKeyNormalization:
    """_extract_score_breakdown must read either key convention this project
    uses for the same data — a caller passing the "wrong" shape previously
    silently rendered 0.0 instead of the real score."""

    def test_reads_total_suffixed_keys(self):
        s = _extract_score_breakdown({"technical_total": 30.0, "positioning_total": 12.0})
        assert s["technical_score"] == 30.0
        assert s["positioning_score"] == 12.0

    def test_reads_score_suffixed_keys(self):
        s = _extract_score_breakdown({"technical_score": 30.0, "positioning_score": 12.0})
        assert s["technical_score"] == 30.0
        assert s["positioning_score"] == 12.0

    def test_total_suffix_takes_priority_when_both_present(self):
        s = _extract_score_breakdown({"technical_total": 30.0, "technical_score": 99.0})
        assert s["technical_score"] == 30.0

    def test_missing_both_defaults_to_zero_not_an_error(self):
        s = _extract_score_breakdown({})
        assert s["technical_score"] == 0.0
        assert s["technical_max"] == 40.0

    def test_plain_style_matches_send_trade_alert_format(self):
        text = _format_score_breakdown(
            {"technical_total": 30.0, "positioning_total": 12.0, "sentiment_total": 10.0,
             "news_total": 8.0, "fundamental_score": 5.0},
            style="plain",
        )
        assert text == (
            "Technical: 30.0/40\nPositioning: 12.0/20\n"
            "Sentiment: 10.0/15\nNews: 8.0/15\nFundamental: 5.0/10"
        )


class TestSendMacroWarning:
    """
    Wired in 2026-08-24 — send_macro_warning existed, fully built, but nothing
    ever called it. Also covers the same-day fix to its color check, which
    compared for "ADVERSE" (uppercase) against macro_overlay.py's actual
    lowercase state values ("adverse"/"neutral") and so could never have
    matched even before this alert was ever called.
    """

    def test_adverse_state_uses_orange(self, monkeypatch):
        posted = _fake_webhook(monkeypatch)
        send_macro_warning({"macro_state": "adverse", "tnx_trend": "rising"})
        embed = posted["json"]["embeds"][0]
        assert embed["color"] == 0xFF8800  # orange

    def test_neutral_state_uses_blue(self, monkeypatch):
        posted = _fake_webhook(monkeypatch)
        send_macro_warning({"macro_state": "neutral"})
        embed = posted["json"]["embeds"][0]
        assert embed["color"] == 0x33B5E5  # blue

    def test_sector_included_in_title_when_provided(self, monkeypatch):
        posted = _fake_webhook(monkeypatch)
        send_macro_warning({"macro_state": "adverse"}, sector="semiconductors")
        embed = posted["json"]["embeds"][0]
        assert "semiconductors" in embed["title"]

    def test_sector_omitted_from_title_when_not_provided(self, monkeypatch):
        posted = _fake_webhook(monkeypatch)
        send_macro_warning({"macro_state": "adverse"})
        embed = posted["json"]["embeds"][0]
        assert "—  —" not in embed["title"]
