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
from shared.utils.logger import get_logger

logger = get_logger(__name__)

_CONFIDENCE_THRESHOLD_BACKTEST = 90.0
_HOLDOUT_FRACTION = 0.20


def _train_holdout_split(outcomes: list[dict]) -> tuple[list[dict], list[dict]]:
    """Chronological split — holdout is the most recent _HOLDOUT_FRACTION of
    outcomes, never randomly sampled (a random split would let the fit see
    outcomes chronologically after ones it's validated against, which real
    live scoring never gets to do)."""
    chrono = sorted(outcomes, key=lambda o: o.get("exit_date") or o.get("signal_date") or "")
    holdout_n = max(1, int(len(chrono) * _HOLDOUT_FRACTION))
    return chrono[:-holdout_n], chrono[-holdout_n:]


def run() -> dict:
    print("Loading historical data and replaying signals for all 4 sectors...")
    per_sector = collect_per_sector_outcomes()

    train_by_sector: dict[str, list[dict]] = {}
    holdout_by_sector: dict[str, list[dict]] = {}
    for sector, outcomes in per_sector.items():
        qualifying = [o for o in outcomes if float(o.get("confidence", 0)) >= _CONFIDENCE_THRESHOLD_BACKTEST]
        train, holdout = _train_holdout_split(qualifying)
        train_by_sector[sector] = train
        holdout_by_sector[sector] = holdout

    print(f"\n{'Sector':<25}{'Train':>8}{'Holdout':>10}{'Fit-eligible':>15}")
    for sector, train in train_by_sector.items():
        eligible = "yes" if len(train) >= _MIN_SAMPLES_FOR_SECTOR_CALIBRATION else "no (< 100)"
        print(f"{sector:<25}{len(train):>8}{len(holdout_by_sector[sector]):>10}{eligible:>15}")

    fitted = fit_sector_calibrated_weights(train_by_sector)

    print("\n=== Holdout validation (true out-of-sample — fit never saw this data) ===\n")
    print(f"{'Sector':<25}{'Default score':>15}{'Fitted score':>15}{'Passes?':>10}")
    saved: dict[str, dict] = {}
    for sector, weights in fitted.items():
        holdout = holdout_by_sector.get(sector, [])
        old_score = _score_outcomes(holdout, _DEFAULT_WEIGHTS)
        new_score = _score_outcomes(holdout, weights)
        passes = new_score >= old_score
        print(f"{sector:<25}{old_score:>15.4f}{new_score:>15.4f}{'PASS' if passes else 'FAIL':>10}")
        if passes:
            saved[sector] = weights
        else:
            logger.warning(
                f"{sector}: fitted weights scored worse on holdout ({new_score:.4f} < "
                f"{old_score:.4f}) — keeping shared default for this sector, not saving a fit."
            )

    skipped = [s for s in train_by_sector if s not in fitted]
    if skipped:
        print(f"\nNot fit-eligible (< {_MIN_SAMPLES_FOR_SECTOR_CALIBRATION} training trades): {', '.join(skipped)} "
              "— will keep using the shared default weights until more data exists.")

    # Version-bump gate — the SAME enforcement point run_calibration() (the
    # global/live-paper-trading calibration) already uses before saving a
    # weight change, applied here too. Previously this script wrote straight
    # to the file live scoring reads (feedback_loop.load_live_weights_if_
    # calibrated -> compute_confidence_score) with no check at all: exactly
    # the "no scoring change goes live without a version bump — no
    # exceptions" rule CHANGELOG.md documents, silently not applied to this
    # newer per-sector path.
    version_blocked = {}
    for sector in list(saved.keys()):
        if model_versioning.check_backtest_required(saved[sector], _DEFAULT_WEIGHTS):
            version_blocked[sector] = saved.pop(sector)

    if version_blocked:
        print(
            f"\nWeight change > 5pp requires a version bump + re-backtest logged in "
            f"CHANGELOG.md before going live (see model_versioning.py) — NOT auto-saved "
            f"for: {', '.join(version_blocked.keys())}. Re-run after bumping the version, "
            f"or these sectors keep using the shared default weights."
        )

    if saved:
        save_sector_weights(saved)
        print(f"\nSaved calibrated weights for: {', '.join(saved.keys())} "
              "to data/processed/calibrated_weights_by_sector.json")
    else:
        print("\nNo sector's fitted weights beat the shared default on holdout — nothing saved.")

    return {
        "fitted": fitted, "saved": saved, "version_blocked": version_blocked,
        "train_counts": {s: len(o) for s, o in train_by_sector.items()},
    }


if __name__ == "__main__":
    run()
