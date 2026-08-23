"""
Derives simulation.py's raw-score-to-confidence rescale factor from real data
instead of a theoretical category-max sum, and checks whether it still holds.

Built 2026-08-22/23 during the full-model-audit follow-up to v2.2.75. That fix
pointed backtest_engine.py's qualifying filter at the real CONFIDENCE_THRESHOLD
(70) instead of a stale hardcoded 90, but deliberately left simulation.py's
rescale (`_BACKTEST_SCORE_MAX`, previously 69.0) untouched — that constant was
a theoretical sum of category ceilings (technical <=36 + positioning 10 fixed +
sentiment <=14 + news <=15 + fundamental <=5 + regime +5 + seasonality +5 = ~90)
discounted by a "72/94 ratio" inherited from a pre-redesign scoring system that
no longer exists in this codebase — untraceable to any current, checkable
number. This module replaces that with an empirical anchor: what raw score has
the backtest's own pipeline actually produced, and what confidence score has
the real live/paper pipeline actually produced, each at their own observed
ceiling. Mapping backtest's raw ceiling onto live's real ceiling is a much
smaller, checkable claim than "theoretical max, discounted by an inherited
ratio" — it says only "both pipelines' best real output today looks about the
same," which doesn't depend on getting each category's abstract ceiling right.

Why max-to-max, not full-distribution matching: the backtest's population
(only bars that already passed the trend/RS/RSI candidate filter — a
pre-selected "looks like a real setup" subset) and live's population (every
active ticker, every scan, breakout or not) are not the same denominator, so
matching percentile-for-percentile would implicitly assume they're drawn from
comparable processes when they aren't. The ceiling each pipeline can reach
under its own real, current formula doesn't depend on how selectively the
sample was drawn — it's the one point on each distribution that's actually
comparable.

Caveat this doesn't solve: a single max is a noisy, sample-size-sensitive
statistic (extreme-value statistics 101) — expect both ceilings to drift
upward as more live scans and backtest years accumulate. Re-run this
periodically, the same "should be re-validated" caveat the old constant
carried, now with an actual mechanism to do that re-validation instead of an
unmoored number.

Usage: python -m backtesting.raw_score_calibration_diagnostic
"""

from pathlib import Path

import pandas as pd

from backtesting.run_backtest import load_historical_data
from paper_trading.score_distribution_diagnostic import collect_composite_scores


def collect_raw_backtest_scores(
    historical_data: dict[str, pd.DataFrame],
    config_path: str = "config/swing_config.yaml",
) -> list[float]:
    """
    Every RAW (pre-rescale) `final_score` the backtest's real out-of-sample
    replay path (`backtest_engine._get_test_outcomes` ->
    `simulation._simulate_test_signals`) actually computes, captured by
    monkeypatching `swing_model.scoring.compute_confidence_score` at its
    real call site rather than re-implementing the candidate-detection funnel
    separately (as collinearity_diagnostic.py does) — guarantees this can't
    silently drift from what the real backtest scores, at the cost of only
    working via monkeypatch rather than a clean functional API.
    """
    import swing_model.scoring as scoring_mod
    from backtesting.backtest_engine import _get_test_outcomes

    raw_scores: list[float] = []
    _orig = scoring_mod.compute_confidence_score

    def _capture(*args, **kwargs):
        result = _orig(*args, **kwargs)
        raw_scores.append(float(result.get("final_score", 0.0)))
        return result

    scoring_mod.compute_confidence_score = _capture
    try:
        _get_test_outcomes(historical_data, config_path, None)
    finally:
        scoring_mod.compute_confidence_score = _orig

    return raw_scores


def derive_rescale_factor(
    raw_backtest_scores: list[float],
    live_composite_scores: pd.Series,
) -> dict:
    """
    Returns the empirically-derived rescale factor and the inputs it came
    from, so the number is never cited without its provenance attached.
    """
    if not raw_backtest_scores or live_composite_scores.empty:
        return {
            "backtest_raw_ceiling": 0.0,
            "live_empirical_ceiling": 0.0,
            "rescale_factor": 1.0,
            "n_backtest_scores": len(raw_backtest_scores),
            "n_live_scores": int(live_composite_scores.shape[0]),
        }
    backtest_raw_ceiling = max(raw_backtest_scores)
    live_empirical_ceiling = float(live_composite_scores.max())
    rescale_factor = (
        live_empirical_ceiling / backtest_raw_ceiling if backtest_raw_ceiling else 1.0
    )
    return {
        "backtest_raw_ceiling": round(backtest_raw_ceiling, 2),
        "live_empirical_ceiling": round(live_empirical_ceiling, 2),
        "rescale_factor": round(rescale_factor, 4),
        "n_backtest_scores": len(raw_backtest_scores),
        "n_live_scores": int(live_composite_scores.shape[0]),
    }


def main() -> None:
    historical_data = load_historical_data("data/historical")
    raw_scores = collect_raw_backtest_scores(historical_data)

    live_df = collect_composite_scores()
    live_scores = live_df["composite_score"] if not live_df.empty else pd.Series(dtype=float)

    result = derive_rescale_factor(raw_scores, live_scores)

    print(f"\nRaw-score calibration diagnostic")
    print(f"Backtest raw scores captured: {result['n_backtest_scores']} (semiconductors, out-of-sample test period)")
    print(f"Live/paper composite scores logged: {result['n_live_scores']} (real scan history)")
    print(f"\nBacktest raw ceiling (max):  {result['backtest_raw_ceiling']}")
    print(f"Live empirical ceiling (max): {result['live_empirical_ceiling']}")
    print(f"\nDerived rescale factor: {result['rescale_factor']}  "
          f"(confidence = min(100, raw_score * {result['rescale_factor']}))")
    print(
        "\nCompare against simulation.py's current _RAW_TO_LIVE_RESCALE_FACTOR — "
        "if materially different, that constant is due for an update (re-run "
        "this after significant new backtest years or live scan history)."
    )

    if raw_scores:
        s = pd.Series(raw_scores)
        print("\nRaw backtest score percentiles:")
        for p in (50, 75, 90, 95, 99, 100):
            print(f"  p{p}: {s.quantile(p / 100):.2f}")

    report_dir = Path("backtesting/reports")
    report_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame([result]).to_csv(report_dir / "raw_score_calibration.csv", index=False)
    print("\nSaved backtesting/reports/raw_score_calibration.csv")


if __name__ == "__main__":
    main()
