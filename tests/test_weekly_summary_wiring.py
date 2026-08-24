"""
monitoring/performance_dashboard.py::generate_weekly_summary() had two real
gaps found in the 2026-08-23 full model audit: its own docstring claimed
"generate weekly performance summary and send to Discord" but never actually
sent anything, and nothing outside tests ever called it (no scheduled task).
Both fixed — this covers the send wiring itself; shared/utils/discord_alerts.py's
own send_weekly_summary_alert formatting is covered in tests/test_discord_alerts.py.
"""

import csv

from monitoring.performance_dashboard import generate_weekly_summary


def _fake_webhook(monkeypatch):
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


class TestGenerateWeeklySummarySendsAlert:
    def test_send_alert_true_posts_to_discord_on_no_data_path(self, tmp_path, monkeypatch):
        posted = _fake_webhook(monkeypatch)
        result = generate_weekly_summary(
            trade_outcomes_path=str(tmp_path / "does_not_exist.csv"),
            paper_trades_path=tmp_path / "paper_trades_does_not_exist.csv",
        )
        assert result["status"] == "no_data"
        assert "json" in posted  # a post was actually attempted

    def test_send_alert_false_skips_discord(self, tmp_path, monkeypatch):
        # No DISCORD_WEBHOOK_URL set at all, and requests.post left
        # unpatched — if this somehow tried to send, it would either raise
        # (no real webhook) or send a real request; neither happens.
        monkeypatch.delenv("DISCORD_WEBHOOK_URL", raising=False)
        result = generate_weekly_summary(
            trade_outcomes_path=str(tmp_path / "does_not_exist.csv"),
            paper_trades_path=tmp_path / "paper_trades_does_not_exist.csv",
            send_alert=False,
        )
        assert result["status"] == "no_data"

    def test_discord_failure_does_not_crash_the_summary(self, tmp_path, monkeypatch):
        """A Discord/network failure must not take down the computed summary
        or its CSV log entry — same best-effort pattern as every other
        _try_send_* wrapper in this codebase."""
        monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://discord.example/webhook")

        def _raising_post(*args, **kwargs):
            raise ConnectionError("simulated network failure")

        import requests
        monkeypatch.setattr(requests, "post", _raising_post)

        result = generate_weekly_summary(
            trade_outcomes_path=str(tmp_path / "does_not_exist.csv"),
            paper_trades_path=tmp_path / "paper_trades_does_not_exist.csv",
        )
        assert result["status"] == "no_data"  # computation still succeeded

    def test_ok_path_with_real_rows_also_sends(self, tmp_path, monkeypatch):
        posted = _fake_webhook(monkeypatch)
        outcomes_path = tmp_path / "trade_outcomes.csv"
        cols = ["timestamp_utc", "ticker", "entry_date", "exit_date", "entry_price",
                "exit_price", "direction", "structure", "confidence_score",
                "technical_total", "sentiment_total", "news_total", "holding_days",
                "pnl_dollars", "pnl_pct", "outcome", "signal_key"]
        with open(outcomes_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=cols)
            writer.writeheader()
            for i in range(12):
                writer.writerow({
                    "timestamp_utc": f"2026-08-{i+1:02d}T00:00:00+00:00", "ticker": "NVDA",
                    "entry_date": "", "exit_date": "", "entry_price": "100.0",
                    "exit_price": "105.0", "direction": "bullish", "structure": "",
                    "confidence_score": "72.0", "technical_total": "", "sentiment_total": "",
                    "news_total": "", "holding_days": "3",
                    "pnl_dollars": "50.0", "pnl_pct": "5.0",
                    "outcome": "win" if i % 2 == 0 else "loss", "signal_key": "",
                })
        result = generate_weekly_summary(
            trade_outcomes_path=str(outcomes_path),
            paper_trades_path=tmp_path / "paper_trades_does_not_exist.csv",
        )
        assert result["status"] == "ok"
        assert "json" in posted
        embed = posted["json"]["embeds"][0]
        assert any(f["name"].startswith("Win Rate") for f in embed["fields"])
