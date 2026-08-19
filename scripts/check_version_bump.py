"""
CI gate: fail if config/swing_config.yaml or swing_model/scoring.py's
scoring-relevant constants changed between two git refs without
CHANGELOG.md's top version entry also changing.

CHANGELOG.md's own "Quick reference" table states the project's rule
plainly: "no change to scoring weights, indicator settings, or thresholds
goes live without a version bump and a fresh backtest result logged below
it — enforced automatically by the code, no exceptions." That claim was
only ever true for one narrow path (feedback_loop.py's own automatic
calibration, gated by model_versioning.check_backtest_required) — it never
caught a human directly editing swing_config.yaml or scoring.py's constants
(Signal Integrity Audit finding G.1). This script is the actual, general
enforcement the CHANGELOG already claims exists.

Usage:
    python scripts/check_version_bump.py --base <ref> --head <ref>

Defaults to comparing HEAD~1 -> HEAD (a normal push). CI passes explicit
refs for pull_request events (comparing the PR head against its merge base)
via GITHUB_BASE_REF. Exits 0 (pass) if neither watched file changed, or if
both a watched file AND CHANGELOG.md's top version changed. Exits 1 (fail)
if a watched file changed but the version didn't. Exits 0 with a warning
(does not block CI) if the base ref can't be resolved at all — a shallow
clone or missing history is an infra gap, not evidence of an unbumped
change, and this gate shouldn't be the thing that breaks CI over that.
"""

import argparse
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from swing_model.model_versioning import get_current_version  # noqa: E402

_WATCHED_PATHS = ("config/swing_config.yaml", "swing_model/scoring.py")


def _git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args], capture_output=True, text=True, check=True,
    )
    return result.stdout


def _file_changed(base: str, head: str, path: str) -> bool:
    diff = subprocess.run(
        ["git", "diff", "--name-only", f"{base}..{head}", "--", path],
        capture_output=True, text=True,
    )
    return bool(diff.stdout.strip())


def _changelog_version_at(ref: str) -> str:
    """CHANGELOG.md's top ## [vX.Y.Z] entry as of `ref`, via `git show` —
    reads the historical blob rather than the working tree so this works
    identically whether `ref` is HEAD, a branch, or an older commit."""
    try:
        content = _git("show", f"{ref}:CHANGELOG.md")
    except subprocess.CalledProcessError:
        return "v0.0.0"
    tmp_path = Path(__file__).resolve().parent / f".changelog_check_{ref.replace('/', '_')}.tmp"
    tmp_path.write_text(content, encoding="utf-8")
    try:
        return get_current_version(tmp_path)
    finally:
        tmp_path.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="HEAD~1")
    parser.add_argument("--head", default="HEAD")
    args = parser.parse_args()

    try:
        _git("rev-parse", "--verify", args.base)
    except subprocess.CalledProcessError:
        print(
            f"::warning::check_version_bump: could not resolve base ref "
            f"'{args.base}' (shallow clone / no history?) — skipping, not failing CI."
        )
        return 0

    changed_watched = [p for p in _WATCHED_PATHS if _file_changed(args.base, args.head, p)]
    if not changed_watched:
        print("check_version_bump: no scoring-relevant files changed — OK.")
        return 0

    base_version = _changelog_version_at(args.base)
    head_version = _changelog_version_at(args.head)

    if head_version != base_version:
        print(
            f"check_version_bump: {changed_watched} changed, and CHANGELOG.md's "
            f"version moved {base_version} -> {head_version} — OK."
        )
        return 0

    print(
        f"::error::check_version_bump: {changed_watched} changed but CHANGELOG.md's "
        f"top version entry is still {head_version} (unchanged from {args.base}). "
        f"Add a new ## [vX.Y.Z] entry with a fresh backtest result before merging — "
        f"see CHANGELOG.md's own stated rule and swing_model/model_versioning.py."
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
