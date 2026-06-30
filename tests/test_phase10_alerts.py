"""
Tests for Phase 10: Discord alert formatting, notification routing priority,
run_swing_model helpers. No real HTTP calls or file writes.
"""

import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone

from shared.utils.discord_alerts import format_trade_alert_text
from shared.utils.notification_router import classify_alert_priority, PRIORITY_NORMAL, PRIORITY_CRITICAL, PRIORITY_HIGHEST
from swing_model.run_swing_model import get_model_version, check_for_missed_scan


# ---------------------------------------------------------------------------
# Alert priority classification
# ---------------------------------------------------------------------------

class TestAlertPriority:
    def test_trade_alert_is_normal(self):
        assert classify_alert_priority("trade_alert") == PRIORITY_NORMAL

    def test_circuit_breaker_yellow_is_critical(self):
        assert classify_alert_priority("circuit_breaker_yellow") == PRIORITY_CRITICAL

    def test_circuit_breaker_orange_is_critical(self):
        assert classify_alert_priority("circuit_breaker_orange") == PRIORITY_CRITICAL

    def test_black_swan_is_highest(self):
        assert classify_alert_priority("black_swan") == PRIORITY_HIGHEST

    def test_circuit_breaker_red_is_highest(self):
        assert classify_alert_priority("circuit_breaker_red") == PRIORITY_HIGHEST

    def test_time_stop_is_critical(self):
        assert classify_alert_priority("time_stop") == PRIORITY_CRITICAL

    def test_missed_scan_is_critical(self):
        assert classify_alert_priority("missed_scan") == PRIORITY_CRITICAL

    def test_unknown_type_is_normal(self):
        assert classify_alert_priority("some_unknown_alert") == PRIORITY_NORMAL


# ---------------------------------------------------------------------------
# Discord alert text formatting
# ---------------------------------------------------------------------------

class TestDiscordAlertFormat:
    def _candidate(self, direction="bullish", confidence=92.0):
        return {
            "ticker": "NVDA",
            "direction": direction,
            "confidence": confidence,
            "entry_zone_lower": 498.5,
            "entry_zone_upper": 501.5,
            "stop_loss": 480.0,
            "target": 548.0,
            "rr_ratio": 3.2,
            "structure_recommended": "bull_call_spread",
            "ev_per_dollar": 0.0345,
        }

    def test_text_contains_ticker(self):
        text = format_trade_alert_text(self._candidate())
        assert "NVDA" in text

    def test_text_contains_direction(self):
        text = format_trade_alert_text(self._candidate())
        assert "BULLISH" in text

    def test_text_contains_entry_zone(self):
        text = format_trade_alert_text(self._candidate())
        assert "498" in text

    def test_text_contains_stop(self):
        text = format_trade_alert_text(self._candidate())
        assert "480" in text

    def test_text_contains_confidence(self):
        text = format_trade_alert_text(self._candidate())
        assert "92" in text

    def test_text_contains_rr(self):
        text = format_trade_alert_text(self._candidate())
        assert "3.2" in text

    def test_bearish_direction_in_text(self):
        text = format_trade_alert_text(self._candidate(direction="bearish"))
        assert "BEARISH" in text or "bearish" in text.lower()

    def test_text_contains_model_version(self):
        text = format_trade_alert_text(self._candidate(), model_version="v2.0.0")
        assert "v2.0.0" in text


# ---------------------------------------------------------------------------
# run_swing_model helpers
# ---------------------------------------------------------------------------

class TestGetModelVersion:
    def test_returns_default_when_no_changelog(self, tmp_path):
        version = get_model_version(changelog_path=str(tmp_path / "CHANGELOG.md"))
        assert version == "v1.0.0"

    def test_extracts_version_from_changelog(self, tmp_path):
        changelog = tmp_path / "CHANGELOG.md"
        changelog.write_text("## [v1.3.2] — 2026-06-15\n### Added\n- Test\n")
        version = get_model_version(changelog_path=str(changelog))
        assert version == "v1.3.2"

    def test_extracts_first_version(self, tmp_path):
        changelog = tmp_path / "CHANGELOG.md"
        changelog.write_text(
            "## [v2.0.0] — 2026-06-15\n### Added\n- Latest\n"
            "## [v1.0.0] — 2026-01-01\n### Added\n- Initial\n"
        )
        version = get_model_version(changelog_path=str(changelog))
        assert version == "v2.0.0"


class TestCheckMissedScan:
    def test_no_log_returns_false(self, tmp_path):
        result = check_for_missed_scan(str(tmp_path / "audit.csv"), "post_close")
        assert result is False

    def test_recent_scan_returns_false(self, tmp_path):
        import csv
        log = tmp_path / "audit.csv"
        now = datetime.now(timezone.utc).isoformat()
        with open(log, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=["timestamp_utc", "scan_type", "ticker"])
            writer.writeheader()
            writer.writerow({"timestamp_utc": now, "scan_type": "post_close", "ticker": "NVDA"})
        result = check_for_missed_scan(str(log), "post_close")
        assert result is False

    def test_old_scan_returns_true(self, tmp_path):
        import csv
        from datetime import timedelta
        log = tmp_path / "audit.csv"
        old = (datetime.now(timezone.utc) - timedelta(hours=30)).isoformat()
        with open(log, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=["timestamp_utc", "scan_type", "ticker"])
            writer.writeheader()
            writer.writerow({"timestamp_utc": old, "scan_type": "post_close", "ticker": "NVDA"})
        result = check_for_missed_scan(str(log), "post_close")
        assert result is True

    def test_wrong_scan_type_returns_true(self, tmp_path):
        import csv
        log = tmp_path / "audit.csv"
        now = datetime.now(timezone.utc).isoformat()
        with open(log, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=["timestamp_utc", "scan_type", "ticker"])
            writer.writeheader()
            writer.writerow({"timestamp_utc": now, "scan_type": "pre_market", "ticker": "NVDA"})
        # Looking for post_close but only pre_market is present
        result = check_for_missed_scan(str(log), "post_close")
        assert result is True
