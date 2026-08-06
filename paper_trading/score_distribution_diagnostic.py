"""
Measures how far real (live/paper) composite scores land from the 90-point
go-live threshold, and how much headroom each of the 5 scoring categories has
left unused. Built after a review found paper trading had logged 215 real
ticker-scans across 9 days without ever reaching 90 (max ever: 71.72) or even
the 80-89 near-miss band once — this quantifies that gap precisely instead of
eyeballing it, and is a companion diagnostic to
paper_trading/live_collinearity_diagnostic.py (same DB, same data source).

Usage: python -m paper_trading.score_distribution_diagnostic
"""

from pathlib import Path
from typing import Optional

import pandas as pd

from app_ui import db as app_db

_MIN_ROWS_FOR_MEANINGFUL_READ = 30

# Only the 5 scoring categories — modifier layers (regime, sector_rotation,
# earnings, cross_ticker, seasonality, macro_overlay) are bounded deltas, not
# 0-to-max category scores, so "% of ceiling" isn't a meaningful measure for them.
_CATEGORY_MAX_POINTS = {
    "technical": 40,
    "market_positioning": 20,
    "sentiment": 15,
    "news": 15,
    "fundamental": 10,
}


def collect_composite_scores(db_path: Optional[Path] = None) -> pd.DataFrame:
    """One row per logged ticker_result: result_id, ticker, sector, composite_score."""
    conn = app_db.get_connection(db_path)
    try:
        rows = conn.execute(
            "SELECT result_id, ticker, sector, composite_score FROM ticker_results"
        ).fetchall()
    finally:
        conn.close()
    return pd.DataFrame([dict(r) for r in rows])


def collect_category_scores(db_path: Optional[Path] = None) -> pd.DataFrame:
    """
    One row per logged ticker_result with each of the 5 scoring categories as
    its own column. Rows missing a given category's layer score just get NaN
    in that column rather than being dropped — unlike the collinearity
    diagnostic's pairwise join, per-category stats here don't need every
    category present on every row.
    """
    conn = app_db.get_connection(db_path)
    try:
        case_clauses = "\n".join(
            f"MAX(CASE WHEN ls.layer_name = '{cat}' THEN ls.score END) AS {cat},"
            for cat in _CATEGORY_MAX_POINTS
        ).rstrip(",")
        rows = conn.execute(
            f"""
            SELECT tr.result_id, tr.ticker,
                   {case_clauses}
            FROM ticker_results tr
            JOIN layer_scores ls ON ls.result_id = tr.result_id
            GROUP BY tr.result_id
            """
        ).fetchall()
    finally:
        conn.close()
    return pd.DataFrame([dict(r) for r in rows])


def threshold_qualification_rates(
    scores_df: pd.DataFrame,
    thresholds: Optional[list[int]] = None,
) -> pd.DataFrame:
    """
    For each candidate confidence threshold, what fraction of real logged
    scans would have qualified. Live counterpart to
    backtesting/metrics.py::run_sensitivity_analysis() (same default threshold
    list — 85/87/90/92/95, matching config/swing_config.yaml's
    confidence.sensitivity_thresholds), applied to real scan history instead
    of backtest replay outcomes. Unlike the backtest version, this can't
    report win_rate/avg_rr per threshold — paper trading only tracks full
    outcomes for tickers that actually qualified at the live 90-point bar
    (data/logs from below-90 tickers were never opened as trades), so there's
    no live P&L to look up at a hypothetical lower threshold. This answers a
    narrower but still load-bearing question: how much more often would a
    signal have even fired.

    Returns DataFrame with columns: threshold, qualifying_rows, total_rows, qualification_rate.
    """
    if thresholds is None:
        thresholds = [85, 87, 90, 92, 95]
    if scores_df.empty:
        return pd.DataFrame(columns=["threshold", "qualifying_rows", "total_rows", "qualification_rate"])

    total = len(scores_df)
    rows = []
    for threshold in thresholds:
        qualifying = int((scores_df["composite_score"] >= threshold).sum())
        rows.append({
            "threshold": threshold,
            "qualifying_rows": qualifying,
            "total_rows": total,
            "qualification_rate": round(qualifying / total, 4) if total else 0.0,
        })
    return pd.DataFrame(rows)


_NEAR_CEILING_FRACTION = 0.98  # within 2% of a category's own max counts as "saturated"


def saturation_rates(category_df: pd.DataFrame, near_ceiling_fraction: float = _NEAR_CEILING_FRACTION) -> pd.DataFrame:
    """
    What fraction of logged rows sit at or within `near_ceiling_fraction` of
    each category's own max points — distinct from "best-ever reached the
    ceiling once" (a single occurrence tells you nothing about frequency).
    A category saturating often means many different tickers/scans are
    getting compressed into the same top score, losing exactly the resolution
    a threshold-based decision near that ceiling needs most.

    Returns one row per category: n_rows, saturated_count, saturation_rate.
    """
    rows = []
    for cat, max_pts in _CATEGORY_MAX_POINTS.items():
        if cat not in category_df.columns:
            continue
        vals = category_df[cat].dropna()
        if vals.empty:
            continue
        threshold = max_pts * near_ceiling_fraction
        saturated = int((vals >= threshold).sum())
        rows.append({
            "category": cat,
            "max_points": max_pts,
            "n_rows": len(vals),
            "saturated_count": saturated,
            "saturation_rate": round(saturated / len(vals), 4),
        })
    return pd.DataFrame(rows)


def joint_peak_rate(category_df: pd.DataFrame, quantile: float = 0.8, min_categories: int = 2) -> float:
    """
    Fraction of logged rows where at least `min_categories` of the 5 scoring
    categories were simultaneously at/above their own quantile-th percentile —
    a proxy for "how often do categories jointly peak," which is what a fixed
    composite threshold like 90 structurally requires (all 5 near their
    ceiling at once), not any single category peaking in isolation.
    """
    cols = [c for c in _CATEGORY_MAX_POINTS if c in category_df.columns]
    if category_df.empty or not cols:
        return 0.0
    thresholds = {c: category_df[c].quantile(quantile) for c in cols}
    above = pd.DataFrame({c: category_df[c] >= thresholds[c] for c in cols})
    count_above = above.sum(axis=1)
    return float((count_above >= min_categories).mean())


def main() -> None:
    scores_df = collect_composite_scores()
    if scores_df.empty:
        print("No logged scan results found — nothing to analyze.")
        return

    n = len(scores_df)
    print(f"\nScore distribution diagnostic — {n} logged ticker results, {scores_df['ticker'].nunique()} tickers\n")

    percentiles = [50, 75, 90, 95, 99, 100]
    pct_values = scores_df["composite_score"].quantile([p / 100 for p in percentiles])
    print("Composite score percentiles:")
    for p, val in zip(percentiles, pct_values):
        print(f"  p{p}: {val:.2f}")

    print(f"\nRows >= 90 (qualifying):  {(scores_df['composite_score'] >= 90).sum()}")
    print(f"Rows >= 80 (near-miss+):  {(scores_df['composite_score'] >= 80).sum()}")
    print(f"Rows >= 70:               {(scores_df['composite_score'] >= 70).sum()}")

    category_df = collect_category_scores()
    print("\nPer-category ceiling utilization (mean / best-ever, as % of category max points):")
    rows_out = []
    for cat, max_pts in _CATEGORY_MAX_POINTS.items():
        if cat not in category_df.columns or category_df[cat].dropna().empty:
            continue
        vals = category_df[cat].dropna()
        mean_pct = vals.mean() / max_pts
        max_pct = vals.max() / max_pts
        print(
            f"  {cat:20s} mean={vals.mean():6.2f}/{max_pts} ({mean_pct:5.1%})   "
            f"best-ever={vals.max():6.2f}/{max_pts} ({max_pct:5.1%})"
        )
        rows_out.append({
            "category": cat, "max_points": max_pts,
            "mean_score": round(vals.mean(), 2), "mean_pct_of_max": round(mean_pct, 4),
            "best_ever_score": round(vals.max(), 2), "best_ever_pct_of_max": round(max_pct, 4),
        })

    sat_df = saturation_rates(category_df)
    print(f"\nCeiling saturation rate (fraction of rows within {_NEAR_CEILING_FRACTION:.0%} of category max):")
    for _, row in sat_df.iterrows():
        print(
            f"  {row['category']:20s} {row['saturated_count']:4d}/{row['n_rows']:4d} rows "
            f"saturated ({row['saturation_rate']:.1%})"
        )

    joint_rate_2 = joint_peak_rate(category_df, quantile=0.8, min_categories=2)
    joint_rate_all5 = joint_peak_rate(category_df, quantile=0.8, min_categories=5)
    print(
        f"\nJoint-peak rate: {joint_rate_2:.1%} of rows had >=2 of 5 categories simultaneously "
        f"in their own top 20% (80th percentile); {joint_rate_all5:.1%} had all 5 simultaneously "
        "there. A fixed 90-point composite threshold effectively requires something close to "
        "the latter, not the former."
    )

    threshold_df = threshold_qualification_rates(scores_df)
    print("\nThreshold sensitivity — qualification rate against real logged scans (live counterpart")
    print("to backtesting/metrics.py::run_sensitivity_analysis(), same default threshold candidates):")
    for _, row in threshold_df.iterrows():
        print(
            f"  threshold={int(row['threshold']):3d}: {int(row['qualifying_rows']):4d}/{int(row['total_rows']):4d} "
            f"rows qualify ({row['qualification_rate']:.1%})"
        )

    if n < _MIN_ROWS_FOR_MEANINGFUL_READ:
        print(
            f"\nOnly {n} rows logged so far (< {_MIN_ROWS_FOR_MEANINGFUL_READ}) — treat this "
            "reading as an early signal, not a final answer. Re-run as paper trading accumulates "
            "more scan history."
        )

    report_dir = Path("paper_trading/reports")
    report_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows_out).to_csv(report_dir / "score_distribution_diagnostic.csv", index=False)
    scores_df.to_csv(report_dir / "score_distribution_composite_scores.csv", index=False)
    threshold_df.to_csv(report_dir / "threshold_sensitivity_live.csv", index=False)
    sat_df.to_csv(report_dir / "score_saturation_rates.csv", index=False)
    print("\nSaved category summary to paper_trading/reports/score_distribution_diagnostic.csv")
    print("Saved raw composite scores to paper_trading/reports/score_distribution_composite_scores.csv")
    print("Saved threshold sensitivity to paper_trading/reports/threshold_sensitivity_live.csv")
    print("Saved saturation rates to paper_trading/reports/score_saturation_rates.csv")


if __name__ == "__main__":
    main()
