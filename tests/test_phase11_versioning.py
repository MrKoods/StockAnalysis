"""
Tests for Phase 11: model_versioning -- version parsing, backtest enforcement,
CHANGELOG bump logic.
"""

import pytest
from pathlib import Path

from swing_model.model_versioning import (
    get_current_version,
    check_backtest_required,
    validate_version_increment,
    bump_version,
)


def _write(path, text):
    """Write file with explicit UTF-8 encoding (avoids Windows CP1252 issues)."""
    Path(path).write_text(text, encoding="utf-8")


# ---------------------------------------------------------------------------
# get_current_version
# ---------------------------------------------------------------------------

class TestGetCurrentVersion:
    def test_returns_default_when_no_file(self, tmp_path):
        version = get_current_version(tmp_path / "CHANGELOG.md")
        assert version == "v0.0.0"

    def test_parses_version_from_changelog(self, tmp_path):
        cl = tmp_path / "CHANGELOG.md"
        _write(cl, "## [v1.2.3] - 2026-06-01\n### Changed\n- stuff\n")
        assert get_current_version(cl) == "v1.2.3"

    def test_returns_first_version_when_multiple(self, tmp_path):
        cl = tmp_path / "CHANGELOG.md"
        _write(cl,
            "## [v2.1.0] - 2026-06-15\n- Latest\n"
            "## [v1.0.0] - 2026-01-01\n- Initial\n"
        )
        assert get_current_version(cl) == "v2.1.0"

    def test_handles_malformed_changelog(self, tmp_path):
        cl = tmp_path / "CHANGELOG.md"
        _write(cl, "No version here\nJust random text\n")
        assert get_current_version(cl) == "v0.0.0"


# ---------------------------------------------------------------------------
# check_backtest_required
# ---------------------------------------------------------------------------

class TestCheckBacktestRequired:
    def test_no_change_no_backtest(self):
        weights = {"technical": 0.60, "sentiment": 0.25}
        assert check_backtest_required(weights, weights) is False

    def test_small_change_no_backtest(self):
        current = {"technical": 0.60}
        new = {"technical": 0.62}  # 2pp change < 5pp
        assert check_backtest_required(new, current) is False

    def test_large_change_requires_backtest(self):
        current = {"technical": 0.60}
        new = {"technical": 0.50}  # 10pp change > 5pp
        assert check_backtest_required(new, current) is True

    def test_new_key_at_threshold_requires_backtest(self):
        current = {}
        new = {"new_weight": 0.10}
        assert check_backtest_required(new, current, change_threshold=0.05) is True

    def test_small_change_not_required(self):
        # 3pp change is clearly below the 5pp threshold (no floating-point ambiguity)
        current = {"w": 0.60}
        new = {"w": 0.63}
        assert check_backtest_required(new, current, change_threshold=0.05) is False

    def test_above_threshold_required(self):
        current = {"w": 0.60}
        new = {"w": 0.66}  # 6pp > 5pp threshold
        assert check_backtest_required(new, current, change_threshold=0.05) is True


# ---------------------------------------------------------------------------
# validate_version_increment
# ---------------------------------------------------------------------------

class TestValidateVersionIncrement:
    def _changelog(self, tmp_path, version, backtest_pass=True):
        """
        Build a changelog where v1.0.0 is the CURRENT version (first entry)
        and `version` is a draft entry below it (with backtest result).
        This way get_current_version returns v1.0.0 and validating `version`
        (which is semantically newer) checks the draft backtest entry.
        """
        cl = tmp_path / "CHANGELOG.md"
        marker = "backtest: PASS" if backtest_pass else "backtest: FAIL"
        _write(cl,
            f"## [v1.0.0] - 2026-01-01\n- Initial\n\n"
            f"## [{version}] - 2026-06-20\n"
            f"### Backtest Results\n"
            f"- {marker}\n"
            f"- Sharpe Ratio: 1.85\n\n"
        )
        return cl

    def test_initial_version_allowed(self, tmp_path):
        ok, reason = validate_version_increment("v1.0.0", tmp_path / "CHANGELOG.md")
        assert ok is True

    def test_newer_version_with_backtest_allowed(self, tmp_path):
        cl = self._changelog(tmp_path, "v1.1.0", backtest_pass=True)
        ok, reason = validate_version_increment("v1.1.0", cl)
        assert ok is True

    def test_older_version_blocked(self, tmp_path):
        cl = tmp_path / "CHANGELOG.md"
        _write(cl, "## [v2.0.0] - 2026-06-01\n- backtest: PASS\n")
        ok, reason = validate_version_increment("v1.0.0", cl)
        assert ok is False
        assert "not_newer_than_current" in reason

    def test_same_version_blocked(self, tmp_path):
        cl = tmp_path / "CHANGELOG.md"
        _write(cl, "## [v1.0.0] - 2026-01-01\n- backtest: PASS\n")
        ok, reason = validate_version_increment("v1.0.0", cl)
        assert ok is False

    def test_no_backtest_blocked(self, tmp_path):
        cl = self._changelog(tmp_path, "v1.1.0", backtest_pass=False)
        ok, reason = validate_version_increment("v1.1.0", cl)
        assert ok is False
        assert "no_passing_backtest" in reason


# ---------------------------------------------------------------------------
# bump_version
# ---------------------------------------------------------------------------

class TestBumpVersion:
    def _passing_result(self):
        return {
            "passed": True,
            "sharpe_ratio": 1.85,
            "win_rate": 0.72,
            "max_drawdown_pct": 0.08,
        }

    def test_patch_bump(self, tmp_path):
        cl = tmp_path / "CHANGELOG.md"
        _write(cl, "## [v1.0.0] - 2026-01-01\n- Initial\n")
        new = bump_version("patch", "fix bug", self._passing_result(), cl)
        assert new == "v1.0.1"

    def test_minor_bump(self, tmp_path):
        cl = tmp_path / "CHANGELOG.md"
        _write(cl, "## [v1.0.5] - 2026-01-01\n- Test\n")
        new = bump_version("minor", "add feature", self._passing_result(), cl)
        assert new == "v1.1.0"

    def test_major_bump(self, tmp_path):
        cl = tmp_path / "CHANGELOG.md"
        _write(cl, "## [v1.5.3] - 2026-01-01\n- Test\n")
        new = bump_version("major", "breaking change", self._passing_result(), cl)
        assert new == "v2.0.0"

    def test_requires_backtest_result(self, tmp_path):
        cl = tmp_path / "CHANGELOG.md"
        _write(cl, "## [v1.0.0] - 2026-01-01\n- Initial\n")
        with pytest.raises(ValueError, match="backtest"):
            bump_version("patch", "change", None, cl)

    def test_requires_passing_backtest(self, tmp_path):
        cl = tmp_path / "CHANGELOG.md"
        _write(cl, "## [v1.0.0] - 2026-01-01\n- Initial\n")
        failing = {"passed": False, "sharpe_ratio": 0.5, "win_rate": 0.40, "max_drawdown_pct": 0.20}
        with pytest.raises(ValueError, match="did not pass"):
            bump_version("patch", "bad change", failing, cl)

    def test_changelog_updated(self, tmp_path):
        cl = tmp_path / "CHANGELOG.md"
        _write(cl, "## [v1.0.0] - 2026-01-01\n- Initial\n")
        bump_version("patch", "test reason", self._passing_result(), cl)
        content = cl.read_text(encoding="utf-8")
        assert "v1.0.1" in content
        assert "backtest: PASS" in content
        assert "test reason" in content

    def test_new_entry_is_first_in_changelog(self, tmp_path):
        cl = tmp_path / "CHANGELOG.md"
        _write(cl, "## [v1.0.0] - 2026-01-01\n- Initial\n")
        bump_version("patch", "new thing", self._passing_result(), cl)
        content = cl.read_text(encoding="utf-8")
        assert content.index("v1.0.1") < content.index("v1.0.0")
