"""
Version tracking, re-backtest enforcement before version increment.
Current model version stamped into every audit log entry and every Discord alert.

Rule: no changes to scoring weights, indicator parameters, or thresholds go live without
a version increment and successful re-backtest logged in CHANGELOG.md. No exceptions.
Weight changes > 5pp require version increment (enforced here + checked by feedback_loop.py).
"""

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


_CHANGELOG_PATH = Path("CHANGELOG.md")

# Sentinel string that must appear in the CHANGELOG entry to mark a passing backtest
_BACKTEST_PASS_MARKER = "backtest: PASS"


def get_current_version(changelog_path: Optional[Path] = None) -> str:
    """
    Parse CHANGELOG.md and return the current model version string (e.g., 'v1.0.0').
    Returns 'v0.0.0' if CHANGELOG.md is missing or unparseable.
    """
    path = changelog_path or _CHANGELOG_PATH
    try:
        content = path.read_text(encoding="utf-8")
        for line in content.splitlines():
            if re.match(r"^## \[v\d+\.\d+\.\d+\]", line):
                return re.search(r"v\d+\.\d+\.\d+", line).group()
    except Exception:
        pass
    return "v0.0.0"


def check_backtest_required(
    new_weights: dict,
    current_weights: dict,
    change_threshold: float = 0.05,
) -> bool:
    """
    Return True if any weight change exceeds change_threshold (5pp).
    Caller must run run_backtest.py and log result to CHANGELOG.md before incrementing version.
    """
    for key in new_weights:
        old = current_weights.get(key, 0)
        if abs(new_weights[key] - old) > change_threshold:
            return True
    return False


def validate_version_increment(
    new_version: str,
    changelog_path: Optional[Path] = None,
) -> tuple[bool, str]:
    """
    Validate that a new version increment is allowed.
    Requirements:
    - new_version is semantically newer than current version
    - CHANGELOG.md has a passing backtest entry for new_version

    Returns (allowed: bool, reason: str).
    """
    path = changelog_path or _CHANGELOG_PATH
    current = get_current_version(path)

    if current == "v0.0.0":
        return True, "initial_version"

    # Semantic version comparison
    def _parse(v):
        return tuple(int(x) for x in v.lstrip("v").split("."))

    try:
        if _parse(new_version) <= _parse(current):
            return False, f"new_version_{new_version}_not_newer_than_current_{current}"
    except ValueError:
        return False, f"invalid_version_format_{new_version}"

    # Check if CHANGELOG has a passing backtest entry for this version
    content = path.read_text(encoding="utf-8") if path.exists() else ""
    version_section = _extract_version_section(content, new_version)

    if version_section and _BACKTEST_PASS_MARKER.lower() in version_section.lower():
        return True, "backtest_verified"

    return False, f"no_passing_backtest_logged_for_{new_version}"


def bump_version(
    bump_type: str = "patch",
    reason: str = "",
    backtest_result: Optional[dict] = None,
    changelog_path: Optional[Path] = None,
) -> str:
    """
    Increment version in CHANGELOG.md and return new version string.
    bump_type: 'major' | 'minor' | 'patch'
    Requires backtest_result to be provided — will not increment without it.
    """
    if backtest_result is None:
        raise ValueError(
            "Cannot bump version without backtest_result. "
            "Run run_backtest.py first and pass the result."
        )

    if not backtest_result.get("passed", False):
        raise ValueError(
            f"Cannot bump version: backtest did not pass. "
            f"Backtest result: {backtest_result}"
        )

    path = changelog_path or _CHANGELOG_PATH
    current = get_current_version(path)

    def _parse(v):
        return list(int(x) for x in v.lstrip("v").split("."))

    parts = _parse(current if current != "v0.0.0" else "v1.0.0")
    if bump_type == "major":
        parts = [parts[0] + 1, 0, 0]
    elif bump_type == "minor":
        parts = [parts[0], parts[1] + 1, 0]
    else:
        parts = [parts[0], parts[1], parts[2] + 1]

    new_version = f"v{parts[0]}.{parts[1]}.{parts[2]}"
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    sharpe = backtest_result.get("sharpe_ratio", 0.0)
    win_rate = backtest_result.get("win_rate", 0.0)
    max_dd = backtest_result.get("max_drawdown_pct", 0.0)

    new_entry = (
        f"## [{new_version}] — {now}\n"
        f"### Changed\n"
        f"- {reason}\n\n"
        f"### Backtest Results\n"
        f"- backtest: PASS\n"
        f"- Sharpe Ratio: {sharpe:.2f}\n"
        f"- Win Rate: {win_rate:.1%}\n"
        f"- Max Drawdown: {max_dd:.1%}\n\n"
    )

    if path.exists():
        existing = path.read_text(encoding="utf-8")
        updated = new_entry + existing
    else:
        updated = new_entry

    path.write_text(updated, encoding="utf-8")
    return new_version


def _extract_version_section(content: str, version: str) -> Optional[str]:
    """Extract the CHANGELOG section for a specific version."""
    pattern = rf"## \[{re.escape(version)}\].*?(?=## \[v|\Z)"
    match = re.search(pattern, content, re.DOTALL)
    if match:
        return match.group()
    return None
