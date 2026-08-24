"""
CI gate: fail if any file hardcodes a numeric copy of the go-live confidence
qualifying threshold instead of importing the real one.

This exact bug shape recurred 3 times within 2 days (2026-08-22/23):
`backtesting/backtest_engine.py` hardcoded `confidence >= 90` well after
v2.2.46 lowered the real live threshold (`swing_model.scoring.
CONFIDENCE_THRESHOLD`) to 70 (fixed v2.2.75); the identical hardcode turned
out to be independently duplicated in `backtesting/walk_forward.py`,
`backtesting/architecture_diagnostic.py`, and
`backtesting/sector_weight_calibration.py` (fixed v2.2.83), silently
invalidating every walk-forward window verdict, per-sector Sharpe number,
and bearish-sweep conclusion this project had been citing that whole time.
Manual greps caught it after the fact; nothing caught it as it was
introduced. This is the automated guardrail that was missing.

Two shapes, matching exactly what was actually found (not a broad "any
number near the word confidence" heuristic, which would false-positive on
this project's own extensive prose documenting the bug's history):

1. `<something>.get("confidence", ...) >= <bare number>` — the real
   qualifying-filter comparison shape every instance of this bug used.
2. `SOME_CONFIDENCE_THRESHOLD_LIKE_NAME = <bare number>` — a module-level
   constant whose name suggests it mirrors the real threshold, but whose
   value is a hardcoded copy rather than `= CONFIDENCE_THRESHOLD` (or an
   import of it). `architecture_diagnostic.py` and `sector_weight_
   calibration.py` both had exactly this shape.

A file containing either shape is required to actually import
CONFIDENCE_THRESHOLD from swing_model.scoring somewhere in the same file —
if it does, the assumption is the flagged line was already fixed to
reference it (this check doesn't try to prove the two are used together,
just that the file has the real constant in scope at all, which every
current fix does). If it doesn't import it, that's precisely the bug.

Known false-positive shapes this deliberately does NOT flag: a bare
`confidence` variable/parameter (not a `.get("confidence", ...)` dict
lookup) defaulting to a number — e.g. simulation.py's `simulate_trade_
outcome(..., confidence: float = 90.0)`, a test-utility default value
unrelated to the qualifying-threshold comparison, confirmed by hand during
the 2026-08-23 audit that produced this script.

Usage:
    python scripts/check_confidence_threshold_duplication.py
"""

import re
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_EXCLUDED_DIR_NAMES = {"tests", ".git", "__pycache__", ".venv", "venv", "node_modules"}
_EXCLUDED_FILES = {
    # This file's own docstring/patterns mention the bug shapes literally.
    Path(__file__).resolve(),
    # The canonical definition itself — CONFIDENCE_THRESHOLD = 70 legitimately
    # lives here as a bare number; every OTHER file is required to import it
    # from here, not duplicate it.
    _REPO_ROOT / "swing_model" / "scoring.py",
}

# Real, single source of truth this check requires every flagged file to import.
_REAL_IMPORT_PATTERN = re.compile(
    r"from\s+swing_model\.scoring\s+import\s+[^#\n]*\bCONFIDENCE_THRESHOLD\b"
)

# Shape 1: a dict .get("confidence", ...) lookup compared against a bare
# numeric literal — the exact qualifying-filter shape every real instance of
# this bug used (backtest_engine.py, walk_forward.py, architecture_
# diagnostic.py, sector_weight_calibration.py all had this literal pattern).
_HARDCODED_COMPARISON_PATTERN = re.compile(
    r'\.get\(\s*["\']confidence["\'][^)]*\)\s*\)?\s*>=\s*\d+(?:\.\d+)?'
)

# Shape 2: a module-level constant whose name says "confidence threshold"
# but whose value is a bare number, not a reference to the real constant.
_HARDCODED_CONSTANT_PATTERN = re.compile(
    r"^[A-Za-z_]*CONFIDENCE_THRESHOLD[A-Za-z_]*\s*=\s*\d+(?:\.\d+)?\s*(?:#.*)?$",
    re.MULTILINE,
)

# Allowlist for a deliberate, reasoned exception — empty today. Any entry
# needs a one-line reason, same convention as check_config_coverage.py.
_KNOWN_EXCEPTIONS: dict[str, str] = {}


def _collect_py_files() -> list[Path]:
    files = []
    for path in _REPO_ROOT.rglob("*.py"):
        if path in _EXCLUDED_FILES:
            continue
        if any(part in _EXCLUDED_DIR_NAMES for part in path.parts):
            continue
        files.append(path)
    return files


def check_file(path: Path) -> list[str]:
    """Returns a list of human-readable findings for one file (empty if clean)."""
    try:
        text = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return []

    hits = []
    for m in _HARDCODED_COMPARISON_PATTERN.finditer(text):
        line_no = text.count("\n", 0, m.start()) + 1
        hits.append(f"line {line_no}: hardcoded confidence comparison — {m.group(0)!r}")
    for m in _HARDCODED_CONSTANT_PATTERN.finditer(text):
        line_no = text.count("\n", 0, m.start()) + 1
        hits.append(f"line {line_no}: hardcoded confidence-threshold-like constant — {m.group(0).strip()!r}")

    if not hits:
        return []

    if _REAL_IMPORT_PATTERN.search(text):
        return []  # file has the real constant in scope — assume it's used, not duplicated

    return hits


def main() -> int:
    py_files = _collect_py_files()
    findings: dict[str, list[str]] = {}

    for path in py_files:
        hits = check_file(path)
        if not hits:
            continue
        rel = str(path.relative_to(_REPO_ROOT))
        if rel in _KNOWN_EXCEPTIONS:
            continue
        findings[rel] = hits

    if findings:
        print(
            f"::error::check_confidence_threshold_duplication: {len(findings)} file(s) hardcode a "
            f"confidence-threshold comparison/constant without importing the real "
            f"swing_model.scoring.CONFIDENCE_THRESHOLD:"
        )
        for rel, hits in sorted(findings.items()):
            print(f"  - {rel}")
            for hit in hits:
                print(f"      {hit}")
        print(
            "::error::check_confidence_threshold_duplication: import CONFIDENCE_THRESHOLD from "
            "swing_model.scoring and use it instead of a hardcoded number — this exact bug shape "
            "already recurred 3 times (see CHANGELOG.md v2.2.75/v2.2.83). If this really is a "
            "deliberate, reasoned exception, add it to _KNOWN_EXCEPTIONS in this script with a "
            "one-line reason."
        )
        return 1

    print(f"check_confidence_threshold_duplication: scanned {len(py_files)} files — OK.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
