"""
Fits per-sector technical/sentiment/news weights from historical backtest
data (see CHANGELOG v2.2.57) instead of waiting for enough real paper-trading
history to accumulate per sector — the same "use the data already on disk"
approach architecture_diagnostic.py used to test the Technical-gate and
sector-generalization questions.

For each sector's out-of-sample outcomes (same replay
backtesting/architecture_diagnostic.py uses): holds out the most recent ~20%
chronologically as validation, fits feedback_loop.fit_sector_calibrated_weights()
on the rest, then only saves a sector's weights if they beat the shared
default on that held-out slice — the exact same train/holdout discipline
feedback_loop.run_calibration() already uses for the global live-paper-trading
calibration, just applied per sector against backtest data instead of one
pooled set against real trades.

Usage: python -m backtesting.sector_weight_calibration
"""

from backtesting.architecture_diagnostic import collect_per_sector_outcomes
from swing_model import model_versioning
from swing_model.feedback_loop import (
    fit_sector_calibrated_weights,
    save_sector_weights,
    _score_outcomes,
    _DEFAULT_WEIGHTS,
    _MIN_SAMPLES_FOR_SECTOR_CALIBRATION,
)
from swing_model.scoring import CONFIDENCE_THRESHOLD
from shared.utils.logger import get_logger

logger = get_logger(__name__)

# 2026-08-23: was hardcoded 90.0, the same stale-copy bug fixed in
# backtest_engine.py (v2.2.75) and architecture_diagnostic.py — this file's
# own copy was missed both times. The "only consumer_discretionary has
# enough data to calibrate" finding was derived from the wrong qualifying
# population; re-run after this fix before trusting that conclusion.
_CONFIDENCE_THRESHOLD_BACKTEST = CONFIDENCE_THRESHOLD
_HOLDOUT_FRACTION = 0.20


def _train_holdout_split(outcomes: list[dict]) -> tuple[list[dict], list[dict]]:
    """Chronological split — holdout is the most recent _HOLDOUT_FRACTION of
    outcomes, never randomly sampled (a random split would let the fit see
    outcomes chronologically after ones it's validated against, which real
    live scoring never gets to do)."""
    chrono = sorted(outcomes, key=lambda o: o.get("exit_date") or o.get("signal_date") or "")
    holdout_n = max(1, int(len(chrono) * _HOLDOUT_FRACTION))
    return chrono[:-holdout_n], chrono[-holdout_n:]


_DIRECTIONS = ("bullish", "bearish")


def run() -> dict:
    print("Loading historical data and replaying signals for all 4 sectors...")
    per_sector = collect_per_sector_outcomes()

    # Split each sector's outcomes by direction into composite "sector:direction"
    # keys — fit_sector_calibrated_weights()/_MIN_SAMPLES_FOR_SECTOR_CALIBRATION/
    # _SECTOR_SHRINKAGE_FULL_TRUST_N are all reused completely unchanged (that
    # function treats its outer dict key as an opaque label), so bullish and
    # bearish outcomes get independently fit/validated per sector instead of
    # pooling two mirror-image scoring formulas into one fit.
    train_by_key: dict[str, list[dict]] = {}
    holdout_by_key: dict[str, list[dict]] = {}
    for sector, outcomes in per_sector.items():
        for direction in _DIRECTIONS:
            dir_outcomes = [o for o in outcomes if o.get("direction", "bullish") == direction]
            qualifying = [o for o in dir_outcomes if float(o.get("confidence", 0)) >= _CONFIDENCE_THRESHOLD_BACKTEST]
            train, holdout = _train_holdout_split(qualifying)
            key = f"{sector}:{direction}"
            train_by_key[key] = train
            holdout_by_key[key] = holdout

    print(f"\n{'Sector:Direction':<35}{'Train':>8}{'Holdout':>10}{'Fit-eligible':>15}")
    for key, train in train_by_key.items():
        eligible = "yes" if len(train) >= _MIN_SAMPLES_FOR_SECTOR_CALIBRATION else "no (< 100)"
        print(f"{key:<35}{len(train):>8}{len(holdout_by_key[key]):>10}{eligible:>15}")

    fitted = fit_sector_calibrated_weights(train_by_key)

    print("\n=== Holdout validation (true out-of-sample — fit never saw this data) ===\n")
    print(f"{'Sector:Direction':<35}{'Default score':>15}{'Fitted score':>15}{'Passes?':>10}")
    saved: dict[str, dict] = {}
    for key, weights in fitted.items():
        holdout = holdout_by_key.get(key, [])
        old_score = _score_outcomes(holdout, _DEFAULT_WEIGHTS)
        new_score = _score_outcomes(holdout, weights)
        passes = new_score >= old_score
        print(f"{key:<35}{old_score:>15.4f}{new_score:>15.4f}{'PASS' if passes else 'FAIL':>10}")
        if passes:
            saved[key] = weights
        else:
            logger.warning(
                f"{key}: fitted weights scored worse on holdout ({new_score:.4f} < "
                f"{old_score:.4f}) — keeping shared default for this sector/direction, not saving a fit."
            )

    skipped = [k for k in train_by_key if k not in fitted]
    if skipped:
        print(f"\nNot fit-eligible (< {_MIN_SAMPLES_FOR_SECTOR_CALIBRATION} training trades): {', '.join(skipped)} "
              "— will keep using the shared default weights until more data exists. A bearish "
              "entry with few/no qualifying trades is expected for a newly-added candidate path, "
              "not necessarily a bug — see the diagnostic step run before this calibration.")

    # Version-bump gate — the SAME enforcement point run_calibration() (the
    # global/live-paper-trading calibration) already uses before saving a
    # weight change, applied here too. Previously this script wrote straight
    # to the file live scoring reads (feedback_loop.load_live_weights_if_
    # calibrated -> compute_confidence_score) with no check at all: exactly
    # the "no scoring change goes live without a version bump — no
    # exceptions" rule CHANGELOG.md documents, silently not applied to this
    # newer per-sector path.
    version_blocked = {}
    for key in list(saved.keys()):
        if model_versioning.check_backtest_required(saved[key], _DEFAULT_WEIGHTS):
            version_blocked[key] = saved.pop(key)

    if version_blocked:
        print(
            f"\nWeight change > 5pp requires a version bump + re-backtest logged in "
            f"CHANGELOG.md before going live (see model_versioning.py) — NOT auto-saved "
            f"for: {', '.join(version_blocked.keys())}. Re-run after bumping the version, "
            f"or these sector/direction pairs keep using the shared default weights."
        )

    # Reshape "sector:direction" -> weights back into the nested
    # {sector: {direction: weights}} schema load_live_weights_if_calibrated()
    # reads. A bare sector key (no ":", e.g. a caller/test driving
    # fit_sector_calibrated_weights directly with plain sector names) defaults
    # to "bullish" — the only direction that existed before this schema did.
    # Matches save_sector_weights' existing (pre-bearish-parity) contract of
    # writing exactly this run's saved sectors, not merging with whatever's
    # already on disk — unchanged here, not a new behavior this change adds.
    saved_by_sector: dict[str, dict[str, dict]] = {}
    for key, weights in saved.items():
        sector, _, direction = key.partition(":")
        saved_by_sector.setdefault(sector, {})[direction or "bullish"] = weights

    # Always call save_sector_weights, even with an empty dict — its contract
    # is a full overwrite, not a merge (see its own docstring), which is
    # exactly what's needed to correctly CLEAR a sector/direction that no
    # longer qualifies. Previously this call was skipped entirely whenever
    # nothing qualified this run, silently leaving a stale entry from a prior
    # run's now-invalid methodology sitting in the file live scoring actually
    # reads — real live impact found 2026-08-23: consumer_discretionary had a
    # calibrated-weights entry (n_trades=405, technical/sentiment/news
    # 0.4/0.4/0.2) that live/paper trading was actively using for AMZN/HD/
    # TGT/NKE/SBUX, fit under the same stale confidence>=90 bug fixed
    # elsewhere in v2.2.83 — the corrected re-run finds only 5 real training
    # trades for that sector, nowhere near enough, and the stale entry would
    # have kept being used indefinitely with no code path that could ever
    # remove it.
    save_sector_weights(saved_by_sector)
    if saved_by_sector:
        print(f"\nSaved calibrated weights for: {', '.join(saved.keys())} "
              "to data/processed/calibrated_weights_by_sector.json")
    else:
        print(
            "\nNo sector/direction's fitted weights beat the shared default on holdout — "
            "calibrated_weights_by_sector.json cleared (any stale prior-run entry is now "
            "invalidated too, not just left unmentioned)."
        )

    return {
        "fitted": fitted, "saved": saved, "version_blocked": version_blocked,
        "train_counts": {k: len(o) for k, o in train_by_key.items()},
    }


if __name__ == "__main__":
    run()
