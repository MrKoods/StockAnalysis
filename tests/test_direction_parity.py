"""
CI gate: every scoring/modifier "producer" function in swing_model/ or
shared/utils/ must be classified in tests/direction_parity_registry.py —
MIRRORS or NEUTRAL(reason) — before it can merge.

Why: two full-model audits (2026-08-19) found the same recurring shape
repeatedly — a new signal handles the bullish case correctly but is
bullish-only or incompletely mirrored for bearish, sometimes for years
before anyone notices (narrative_tracker.theme_alignment_modifier's
supply_chain/memory_cycle branches, fixed the same day this test was
written). Nothing in the project's process checked for this; it was only
ever caught by one-off manual sweeps. This test is the general enforcement:
a brand-new producer function that isn't in the registry fails the build
until someone makes a deliberate MIRRORS/NEUTRAL call — not a silent
bullish-only ship.

This test does NOT re-verify that a MIRRORS-classified producer actually
mirrors correctly — that's each producer's own unit tests' job (see e.g.
tests/test_news_layer.py, tests/test_insider_selling_signal.py). It only
enforces that every producer has been looked at and classified.
"""

import importlib
import inspect
import re
from pathlib import Path

from tests.direction_parity_registry import REGISTRY

_REPO_ROOT = Path(__file__).resolve().parent.parent
_TARGET_DIRS = ("swing_model", "shared/utils")

# Matches the naming idioms this codebase actually uses for scoring
# sub-scores and modifiers: compute_*score*, (_)score_*, *_modifier(s)(*),
# *_signal. Deliberately broad/over-inclusive — a false-positive match just
# means one extra NEUTRAL(reason) entry in the registry; a false negative
# means a real gap goes uncaught, which is the failure mode this test
# exists to prevent.
_PRODUCER_NAME_RE = re.compile(r"^(compute_\w*score\w*|_?score_\w+|\w*_modifier\w*|\w+_signal)$")

# Known real producers whose names don't fit the naming convention above —
# found by direct code read during the 2026-08-19 recurring-pattern sweep.
# Add here (not by loosening the regex) when a genuine producer is missed.
_ADDITIONAL_PRODUCERS = {
    "swing_model.cross_ticker_analysis.analyze_cross_ticker",
    "shared.utils.macro_overlay.compute_macro_state",
    "shared.utils.sector_rotation.dampen_rotation_penalty_for_leader",
    "swing_model.news_layer.count_independent_cluster",
}


def _module_dotted_names(rel_dir: str) -> list[str]:
    names = []
    for path in (_REPO_ROOT / rel_dir).glob("*.py"):
        if path.name == "__init__.py":
            continue
        rel = path.relative_to(_REPO_ROOT).with_suffix("")
        names.append(".".join(rel.parts))
    return names


def _discover_producers() -> set[str]:
    found = set()
    for rel_dir in _TARGET_DIRS:
        for dotted in _module_dotted_names(rel_dir):
            module = importlib.import_module(dotted)
            for name, func in inspect.getmembers(module, inspect.isfunction):
                if func.__module__ != dotted:
                    continue  # imported from elsewhere, not defined here
                qualified = f"{dotted}.{name}"
                if _PRODUCER_NAME_RE.match(name) or qualified in _ADDITIONAL_PRODUCERS:
                    found.add(qualified)
    return found


class TestDirectionParityRegistryCoverage:
    def test_every_discovered_producer_is_classified(self):
        discovered = _discover_producers()
        unclassified = sorted(discovered - REGISTRY.keys())
        assert not unclassified, (
            "New scoring/modifier producer(s) found with no entry in "
            "tests/direction_parity_registry.py: "
            f"{unclassified}. Classify each as MIRRORS (verified to branch/"
            "flip on `direction`) or NEUTRAL('reason') — a deliberate call, "
            "not a silent bullish-only ship."
        )

    def test_registry_has_no_stale_entries(self):
        """A registry entry for a function that no longer exists (renamed,
        deleted) silently stops proving anything — catch it so the registry
        stays a live map of real code, not accumulated cruft."""
        discovered = _discover_producers()
        stale = sorted(REGISTRY.keys() - discovered)
        assert not stale, (
            f"tests/direction_parity_registry.py has entries for functions "
            f"that no longer exist (or no longer match the producer naming "
            f"convention): {stale}. Remove them."
        )
