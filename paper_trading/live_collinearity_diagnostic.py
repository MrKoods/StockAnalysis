"""
Measures how independent every scored category and modifier actually is from
every other one, in real paper trading — the live counterpart to
backtesting/collinearity_diagnostic.py. That backtest version exists because
backtest replay scores Sentiment from a price-momentum proxy (no historical
StockTwits data), which risked being the same signal as Technical wearing two
labels. Paper trading has no such proxy problem — every scan uses real
StockTwits/Seeking Alpha sentiment data — so this isn't re-testing the same
concern. It answers a different, complementary question: now that real data
is accumulating, does independence actually hold live, across every pair of
signals the composite score sums, not just Technical vs. Sentiment?

v2.2.16 originally checked exactly one pair (technical_total, sentiment_total).
That narrow scope is exactly why the live regime_modifier/sector_rotation_modifier
double-count (scoring.py's own in-code NOTE: both derived from the same SMH
price action, summed as if independent) went unnoticed until it turned up by
hand while reading scan logs — this tool structurally couldn't see a
modifier-to-modifier pair. This version checks every pair of the 5 categories
+ 6 modifiers paper_runner.py already logs to layer_scores, so a redundancy
like that gets caught automatically instead of by manual log-reading.

Unlike the backtest version (restricted to breakout-candidate bars, to match
what the backtest actually scores), this uses every logged scan result
regardless of qualification — v2.1.2 already logs every ticker's score every
scan, so there's no equivalent sampling restriction here, and using the full
set gives more statistical power rather than less.

Usage: python -m paper_trading.live_collinearity_diagnostic
"""

import itertools
from pathlib import Path
from typing import Optional

import pandas as pd

from app_ui import db as app_db
from shared.utils.tail_dependence import conditional_top_quantile_rate

_MIN_ROWS_FOR_MEANINGFUL_READ = 30

# A pair is flagged if EITHER bulk correlation or tail co-occurrence is
# elevated — a low bulk r doesn't rule out the two columns still tending to
# peak together, which is what a fixed 90-point composite threshold actually
# depends on (see tail_dependence.py's own module docstring).
_FLAG_PEARSON_R_THRESHOLD = 0.5
_FLAG_TAIL_LIFT_THRESHOLD = 1.5

# Mirrors paper_runner.py's _LAYER_SCORE_FIELDS (layer_name -> score dict key)
# so columns here read the same as scoring.py's own field names instead of the
# raw DB layer_name strings. A layer_name not in this map (e.g. a new one
# added to _LAYER_SCORE_FIELDS later) is kept under its raw name rather than
# dropped, so it still shows up in the pairwise matrix instead of vanishing
# silently.
_LAYER_NAME_TO_COLUMN = {
    "technical": "technical_total",
    "market_positioning": "positioning_total",
    "sentiment": "sentiment_total",
    "news": "news_total",
    "fundamental": "fundamental_score",
    "regime": "regime_modifier",
    "sector_rotation": "sector_rotation_modifier",
    "earnings": "earnings_modifier",
    "cross_ticker": "cross_ticker_modifier",
    "seasonality": "seasonality_modifier",
    "macro_overlay": "macro_modifier",
}


def collect_score_pairs(db_path: Optional[Path] = None) -> pd.DataFrame:
    """
    Pull every logged layer_name/score for every ticker_result, pivoted wide —
    one row per result_id, one column per layer actually logged (technical_total,
    sentiment_total, regime_modifier, sector_rotation_modifier, ...).

    Rows are kept even when some layers are missing for that result (a partial
    layer_scores write, or an older row logged before a layer existed) — the
    missing layers show up as NaN rather than dropping the whole row, since
    different pairs in compute_pairwise_collinearity have different data
    availability and each pair should use all the data it actually has.

    Returns DataFrame with columns: result_id, ticker, plus one column per
    layer logged so far.
    """
    conn = app_db.get_connection(db_path)
    try:
        rows = conn.execute(
            """
            SELECT tr.result_id, tr.ticker, ls.layer_name, ls.score
            FROM ticker_results tr
            JOIN layer_scores ls ON ls.result_id = tr.result_id
            """
        ).fetchall()
    finally:
        conn.close()

    if not rows:
        return pd.DataFrame()

    long_df = pd.DataFrame([dict(r) for r in rows])
    wide = long_df.pivot_table(
        index=["result_id", "ticker"], columns="layer_name", values="score", aggfunc="first",
    ).reset_index()
    wide.columns.name = None
    return wide.rename(columns=lambda c: _LAYER_NAME_TO_COLUMN.get(c, c))


def compute_pairwise_collinearity(df: pd.DataFrame, columns: Optional[list] = None) -> pd.DataFrame:
    """
    Pearson r, Spearman rho, and top-quartile tail-dependence lift for every
    unique pair of score columns in `df`. Generalizes what v2.2.16 checked for
    exactly one pair (technical_total, sentiment_total) to every category and
    every modifier — the regime_modifier/sector_rotation_modifier double-count
    (both derived from the same SMH price action) is exactly the kind of pair
    this would have caught automatically had it existed sooner.

    columns: score columns to test pairwise; defaults to every column in `df`
    other than result_id/ticker.

    Each pair's dropna() is computed independently — a result missing one of
    the two layers in a given pair just doesn't count toward that pair, rather
    than the whole row being excluded from every pair.

    Returns one row per unordered pair, sorted by |pearson_r| descending, with
    columns: col_a, col_b, n, pearson_r, spearman_rho, tail_lift, flagged.
    `flagged` is True when |pearson_r| >= _FLAG_PEARSON_R_THRESHOLD or
    tail_lift >= _FLAG_TAIL_LIFT_THRESHOLD.
    """
    if columns is None:
        columns = [c for c in df.columns if c not in ("result_id", "ticker")]

    rows = []
    for col_a, col_b in itertools.combinations(sorted(columns), 2):
        pair_df = df[[col_a, col_b]].dropna()
        n = len(pair_df)
        if n < 2 or pair_df[col_a].std() == 0 or pair_df[col_b].std() == 0:
            pearson_r = 0.0
            spearman_rho = 0.0
        else:
            pearson_r = float(pair_df[col_a].corr(pair_df[col_b]))
            spearman_rho = float(pair_df[col_a].corr(pair_df[col_b], method="spearman"))

        tail = conditional_top_quantile_rate(df, col_a, col_b, quantile=0.75)
        tail_lift = tail["lift"]
        flagged = abs(pearson_r) >= _FLAG_PEARSON_R_THRESHOLD or tail_lift >= _FLAG_TAIL_LIFT_THRESHOLD

        rows.append({
            "col_a": col_a, "col_b": col_b, "n": n,
            "pearson_r": round(pearson_r, 3), "spearman_rho": round(spearman_rho, 3),
            "tail_lift": tail_lift, "flagged": flagged,
        })

    result = pd.DataFrame(rows)
    if result.empty:
        return result
    return result.sort_values(
        "pearson_r", key=lambda s: s.abs(), ascending=False,
    ).reset_index(drop=True)


def main() -> None:
    df = collect_score_pairs()
    if df.empty:
        print("No logged scan results found — nothing to correlate.")
        return

    n = len(df)
    score_columns = [c for c in df.columns if c not in ("result_id", "ticker")]
    print(
        f"\nLive collinearity diagnostic — {n} logged ticker results, "
        f"{df['ticker'].nunique()} tickers, {len(score_columns)} score columns "
        f"({', '.join(score_columns)})\n"
    )

    if n < _MIN_ROWS_FOR_MEANINGFUL_READ:
        print(
            f"Only {n} rows logged so far (< {_MIN_ROWS_FOR_MEANINGFUL_READ}) — treat every "
            "reading below as a placeholder, not a real answer yet. Re-run as paper trading "
            "accumulates more scan history.\n"
        )

    pairwise = compute_pairwise_collinearity(df, score_columns)
    flagged = pairwise[pairwise["flagged"]]

    print(f"{len(pairwise)} pairs checked across {len(score_columns)} score columns.\n")
    if flagged.empty:
        print(
            f"No pairs flagged (|pearson r| >= {_FLAG_PEARSON_R_THRESHOLD} or "
            f"tail-lift >= {_FLAG_TAIL_LIFT_THRESHOLD}x) — categories and modifiers are "
            "behaving as independent signals so far."
        )
    else:
        print(
            f"{len(flagged)} pair(s) flagged (|pearson r| >= {_FLAG_PEARSON_R_THRESHOLD} or "
            f"tail-lift >= {_FLAG_TAIL_LIFT_THRESHOLD}x):\n"
        )
        for _, row in flagged.iterrows():
            print(
                f"  {row['col_a']} <-> {row['col_b']}: r={row['pearson_r']:+.3f}, "
                f"rho={row['spearman_rho']:+.3f}, tail_lift={row['tail_lift']:.2f}x (n={row['n']})"
            )
        print(
            "\nA flagged pair means those two signals are summed into final_score as if "
            "independent while the data says they move together — the same shape of bug as "
            "regime_modifier/sector_rotation_modifier (see scoring.py's in-code NOTE). Worth "
            "checking whether the pair shares an underlying data source before trusting their "
            "combined contribution."
        )

    print("\nFull pairwise matrix (top 10 by |r|):")
    print(pairwise.head(10).to_string(index=False))

    report_dir = Path("paper_trading/reports")
    report_dir.mkdir(parents=True, exist_ok=True)
    df.to_csv(report_dir / "live_collinearity_diagnostic.csv", index=False)
    pairwise.to_csv(report_dir / "live_collinearity_pairwise.csv", index=False)
    print(f"\nSaved {n} rows to paper_trading/reports/live_collinearity_diagnostic.csv")
    print(f"Saved {len(pairwise)} pairs to paper_trading/reports/live_collinearity_pairwise.csv")


if __name__ == "__main__":
    main()
