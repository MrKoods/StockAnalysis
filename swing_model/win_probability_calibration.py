"""
Calibrates the composite confidence score (0-100) into an actual win
probability, backed by real backtest replay data — replacing
trade_selector.py's previous `win_prob = confidence / 100.0`, which fed every
one of the 42 structures' EV formulas a literal "90 means 90% chance of
winning" assumption with zero evidence behind it. The model's own backtested
win rate at the qualifying threshold (confidence>=90) is ~60-63%, not 90% —
see backtesting/fit_win_probability_calibration.py for how the real numbers
in data/processed/win_probability_calibration.json were produced.

Calibration points are isotonic-smoothed (shared/utils/isotonic.py) so a
single noisy threshold's dip (small-sample win rate can wobble non-monotonically
even though the true underlying relationship is "higher score, no worse odds")
doesn't get taken at face value.
"""

import json
from pathlib import Path
from typing import Optional

DEFAULT_CALIBRATION_PATH = Path("data/processed/win_probability_calibration.json")


def fit_calibration_curve(sensitivity_rows: list[dict]) -> list[dict]:
    """
    sensitivity_rows: rows from backtesting.metrics.run_sensitivity_analysis's
    output (or any list of dicts with "threshold", "win_rate", "qualifying_trades"
    keys) — ascending by threshold.

    Returns [{"threshold": int, "win_rate": float, "n_trades": int}, ...] with
    win_rate isotonic-smoothed (weighted by n_trades) so it's guaranteed
    non-decreasing in threshold — a higher composite score should never imply
    calibrated odds *worse* than a lower one, even where the raw backtest
    reading dipped from small-sample noise.
    """
    from shared.utils.isotonic import isotonic_regression

    rows = [r for r in sensitivity_rows if r.get("qualifying_trades", 0) > 0]
    if not rows:
        return []
    rows = sorted(rows, key=lambda r: r["threshold"])

    thresholds = [r["threshold"] for r in rows]
    win_rates = [float(r["win_rate"]) for r in rows]
    weights = [float(r["qualifying_trades"]) for r in rows]
    smoothed = isotonic_regression(win_rates, weights)

    return [
        {"threshold": t, "win_rate": round(w, 4), "n_trades": int(n)}
        for t, w, n in zip(thresholds, smoothed, weights)
    ]


def calibrate_win_probability(confidence: float, calibration_points: list[dict]) -> float:
    """
    Piecewise-linear interpolation of `confidence` against calibration_points'
    (threshold, win_rate) pairs. Clamped to the endpoint win_rate outside the
    observed threshold range — extrapolating a calibration curve past the data
    that built it is a well-known way to manufacture false confidence, so a
    score of 20 or 99 (well outside the ~40-95 range any real backtest sweep
    covers) gets the nearest edge's real reading, not a linear guess beyond it.

    Falls back to confidence/100 (the old, uncalibrated behavior) only when
    calibration_points is empty — callers should treat that fallback as
    explicitly uncalibrated, not as a real probability.
    """
    if not calibration_points:
        return confidence / 100.0

    points = sorted(calibration_points, key=lambda p: p["threshold"])
    if confidence <= points[0]["threshold"]:
        return float(points[0]["win_rate"])
    if confidence >= points[-1]["threshold"]:
        return float(points[-1]["win_rate"])

    for lo, hi in zip(points, points[1:]):
        if lo["threshold"] <= confidence <= hi["threshold"]:
            span = hi["threshold"] - lo["threshold"]
            if span <= 0:
                return float(lo["win_rate"])
            progress = (confidence - lo["threshold"]) / span
            return float(lo["win_rate"] + progress * (hi["win_rate"] - lo["win_rate"]))

    return float(points[-1]["win_rate"])  # unreachable given the bounds checks above


def load_calibration(path: Optional[Path] = None) -> Optional[list[dict]]:
    """
    Loads calibration points from `path` (default DEFAULT_CALIBRATION_PATH).
    Returns None — not an empty list — when the file doesn't exist or fails to
    parse, so callers can distinguish "no calibration file yet" from "a real
    calibration that happens to have zero points."
    """
    p = path or DEFAULT_CALIBRATION_PATH
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        points = data.get("calibration_points")
        return points if points else None
    except Exception:
        return None


def save_calibration(
    calibration_points: list[dict],
    source_description: str,
    path: Optional[Path] = None,
) -> None:
    """Persists calibration_points as JSON, plus source_description (e.g. which
    backtest run/sectors/date range produced it) so the artifact is self-documenting."""
    from shared.utils.atomic_io import atomic_write_json

    p = path or DEFAULT_CALIBRATION_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(p, {
        "source": source_description,
        "calibration_points": calibration_points,
    })
