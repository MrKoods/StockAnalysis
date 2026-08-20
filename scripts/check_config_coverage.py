"""
CI gate: fail if config/swing_config.yaml declares a leaf key that no real
(non-test) code reads.

Two full-model audits (2026-08-19) found the same recurring shape repeatedly:
a config key computed or documented but never wired to a real consumer — the
project's own `app_ui/config_validation.py` only sum-checks a handful of
sections, it doesn't verify any key is actually *read* by the scoring/trading
code. This script is the general enforcement that was missing: it fails CI
the moment a *new* decorative key is added, rather than waiting for the next
manual sweep to notice.

Method: flatten every leaf in the YAML tree (a "leaf" is a scalar, a list —
including a list of dicts, e.g. `position_sizing.tiers`, which is not
descended into — or a dict whose keys aren't all valid identifiers, e.g.
`modifiers.seasonality.monthly_modifiers` keyed 1-12). For each leaf's final
key name, search all non-test `*.py` files for that name appearing as a
quoted dict-key string literal (`"name"` / `'name'`) — this codebase reads
config exclusively via plain nested dicts (`cfg.get("section", {})...`), so a
quoted-literal match is a real reference; a bare identifier match (e.g. the
word "min" inside `series.min()`) is not, and quoted-literal matching avoids
that false-positive class deliberately.

`app_ui/config_validation.py` is excluded from the search — its sum-checks
(weights sum to 100, sub-signals sum to parent max, threshold in range) read
key names without the code ever *acting* on the values, which is exactly the
kind of non-real "consumer" the original audit flagged. Counting it would
silently hide the entire `scoring_weights` / `*_sub_signals` / stale
`confidence.min_threshold` cluster this check exists to catch.

Known-decorative keys (today's backlog, scoped separately — see CHANGELOG.md
and the "recurring pattern audit" — not fixed by this change) are allowlisted
in `_KNOWN_DECORATIVE` below, each with a one-line reason. A newly-added
decorative key is NOT allowlisted, so it fails the build until someone wires
it in for real or makes a deliberate, documented call to allowlist it.

Usage:
    python scripts/check_config_coverage.py
"""

import re
import sys
from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).resolve().parent.parent
_CONFIG_PATH = _REPO_ROOT / "config" / "swing_config.yaml"

_EXCLUDED_DIR_NAMES = {"tests", ".git", "__pycache__", ".venv", "venv", "node_modules"}
_EXCLUDED_FILES = {
    # Sum-checks key *names* without ever consuming the values — not a real
    # consumer, see module docstring above.
    _REPO_ROOT / "app_ui" / "config_validation.py",
    # This file's own docstring/allowlist mentions every decorative key name.
    Path(__file__).resolve(),
}

# Confirmed-decorative as of the 2026-08-19 recurring-pattern audit follow-up.
# Tier B/C/D backlog — intentionally not fixed here, see CHANGELOG.md and
# memory entry project_recurring_pattern_audit_2026-08-19. Each entry is a
# real leaf key with zero real code reference; remove an entry only once the
# key is actually wired in (and this script will then confirm it for free).
_KNOWN_DECORATIVE: dict[str, str] = {
    # --- Tier B, 2026-08-19: full 109-key inventory triaged and resolved.
    # 68 genuinely-dead keys were removed from config/swing_config.yaml
    # entirely (v2.2.72). 39 were wired for real across batches 2-3
    # (v2.2.73-74). The 2 below are permanent, deliberate exceptions — see
    # each entry's own reason. Remove an entry only once its key is actually
    # wired (script confirms it for free).
    "confidence.min_threshold": "corrected to 70 (was stale at 90) but deliberately left unwired — CONFIDENCE_THRESHOLD gates real trading and is imported directly by 5+ files; scoring.py's own docstring says changing what gates a trade is a deliberate decision, not a config-coverage fix",
    "positioning.institutional_distribution_threshold": "handled by design — symmetric with accumulation_threshold for this linear formula, not read independently (see positioning_layer.py _score_institutional)",
}


def _flatten_leaves(node, prefix: str = ""):
    """Yield (dotted_path, leaf_key_name) for every leaf in the config tree."""
    if isinstance(node, dict) and node and all(
        isinstance(k, str) and k.isidentifier() for k in node
    ):
        for key, value in node.items():
            path = f"{prefix}.{key}" if prefix else key
            yield from _flatten_leaves(value, path)
    else:
        leaf_name = prefix.rsplit(".", 1)[-1]
        yield prefix, leaf_name


def _collect_py_files() -> list[Path]:
    files = []
    for path in _REPO_ROOT.rglob("*.py"):
        if path in _EXCLUDED_FILES:
            continue
        if any(part in _EXCLUDED_DIR_NAMES for part in path.parts):
            continue
        files.append(path)
    return files


def _is_referenced(leaf_name: str, py_files: list[Path]) -> bool:
    pattern = re.compile(r"['\"]" + re.escape(leaf_name) + r"['\"]")
    for path in py_files:
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if pattern.search(text):
            return True
    return False


def main() -> int:
    if not _CONFIG_PATH.exists():
        print(f"::error::check_config_coverage: config file not found at {_CONFIG_PATH}")
        return 1

    config = yaml.safe_load(_CONFIG_PATH.read_text(encoding="utf-8"))
    leaves = list(_flatten_leaves(config))
    py_files = _collect_py_files()

    reference_cache: dict[str, bool] = {}
    unreferenced = []
    allowlisted = []
    for dotted_path, leaf_name in leaves:
        if leaf_name not in reference_cache:
            reference_cache[leaf_name] = _is_referenced(leaf_name, py_files)
        if reference_cache[leaf_name]:
            continue
        if dotted_path in _KNOWN_DECORATIVE:
            allowlisted.append(dotted_path)
        else:
            unreferenced.append(dotted_path)

    if allowlisted:
        print(
            f"check_config_coverage: {len(allowlisted)} known-decorative key(s) "
            f"allowlisted (existing backlog, not touched by this check):"
        )
        for path in sorted(allowlisted):
            print(f"  - {path}: {_KNOWN_DECORATIVE[path]}")

    if unreferenced:
        print(
            f"::error::check_config_coverage: {len(unreferenced)} leaf key(s) in "
            f"config/swing_config.yaml have no real (non-test) code reference and "
            f"are not in the allowlist:"
        )
        for path in sorted(unreferenced):
            print(f"  - {path}")
        print(
            "::error::check_config_coverage: either wire this key into real code, "
            "or add it to _KNOWN_DECORATIVE in scripts/check_config_coverage.py "
            "with a one-line reason — a deliberate call, not a silent gap."
        )
        return 1

    print(f"check_config_coverage: all {len(leaves)} leaf keys referenced or allowlisted — OK.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
