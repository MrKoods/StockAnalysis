"""
Measures how independent the Technical and Sentiment categories actually are
in real paper trading — the live counterpart to
backtesting/collinearity_diagnostic.py. That backtest version exists because
backtest replay scores Sentiment from a price-momentum proxy (no historical
StockTwits data), which risked being the same signal as Technical wearing two
labels. Paper trading has no such proxy problem — every scan uses real
StockTwits/Seeking Alpha sentiment data — so this isn't re-testing the same
concern. It answers a different, complementary question: now that real data
is accumulating, does Technical/Sentiment independence actually hold live,
not just in the backtest's proxy?

Unlike the backtest version (restricted to breakout-candidate bars, to match
what the backtest actually scores), this uses every logged scan result
regardless of qualification — v2.1.2 already logs every ticker's score every
scan, so there's no equivalent sampling restriction here, and using the full
set gives more statistical power rather than less.

Usage: python -m paper_trading.live_collinearity_diagnostic
"""

from pathlib import Path
from typing import Optional

import pandas as pd

from app_ui import db as app_db
from shared.utils.tail_dependence import conditional_top_quantile_rate

_MIN_ROWS_FOR_MEANINGFUL_READ = 30


def collect_score_pairs(db_path: Optional[Path] = None) -> pd.DataFrame:
    """
    Pull one row per logged ticker_result with its technical_total and
    sentiment_total layer scores, across every scan ever run.

    Returns DataFrame with columns: ticker, result_id, technical_total, sentiment_total.
    Rows missing either layer score (should not happen in practice, but a scan
    with a partial layer_scores failure shouldn't crash this) are dropped.
    """
    conn = app_db.get_connection(db_path)
    try:
        rows = conn.execute(
            """
            SELECT tr.ticker, tr.result_id,
                   MAX(CASE WHEN ls.layer_name = 'technical' THEN ls.score END) AS technical_total,
                   MAX(CASE WHEN ls.layer_name = 'sentiment' THEN ls.score END) AS sentiment_total
            FROM ticker_results tr
            JOIN layer_scores ls ON ls.result_id = tr.result_id
            GROUP BY tr.result_id
            """
        ).fetchall()
    finally:
        conn.close()

    df = pd.DataFrame([dict(r) for r in rows])
    if df.empty:
        return df
    return df.dropna(subset=["technical_total", "sentiment_total"])


def main() -> None:
    df = collect_score_pairs()
    if df.empty:
        print("No logged scan results found — nothing to correlate.")
        return

    n = len(df)
    r_total = df["technical_total"].corr(df["sentiment_total"])
    rho_total = df["technical_total"].corr(df["sentiment_total"], method="spearman")

    print(f"\nLive collinearity diagnostic — {n} logged ticker results, {df['ticker'].nunique()} tickers\n")
    print(f"Pearson r    (technical_total, sentiment_total) = {r_total:.3f}")
    print(f"Spearman rho (technical_total, sentiment_total) = {rho_total:.3f}")

    if n < _MIN_ROWS_FOR_MEANINGFUL_READ:
        print(
            f"\nOnly {n} rows logged so far (< {_MIN_ROWS_FOR_MEANINGFUL_READ}) — treat this "
            "reading as a placeholder, not a real answer yet. Re-run as paper trading "
            "accumulates more scan history."
        )
    print(
        "\nInterpretation: |r| > 0.5 would mean Technical and Sentiment are substantially "
        "the same signal under two labels even with real (non-proxy) sentiment data — a "
        "materially worse finding than the backtest's proxy-driven collinearity concern, "
        "since it would mean the redundancy is real, not a simulation artifact. |r| < 0.3 "
        "means the categories are adding meaningfully separate information live, "
        "consistent with (or better than) the backtest's own reading (v2.2.16: r=0.115)."
    )

    tail = conditional_top_quantile_rate(df, "technical_total", "sentiment_total", quantile=0.75)
    print(
        f"\nTail dependence (top-quartile co-occurrence): P(sentiment top 25%% | technical top 25%%) "
        f"= {tail['conditional_rate']:.1%} vs. unconditional {tail['unconditional_rate']:.1%} "
        f"(lift={tail['lift']:.2f}x, n_conditioned={tail['n_conditioned']}). Complements the bulk "
        "r/rho above — a low bulk correlation doesn't rule out the two categories still tending "
        "to peak together, which is what a fixed 90-point composite threshold actually depends on."
    )

    report_dir = Path("paper_trading/reports")
    report_dir.mkdir(parents=True, exist_ok=True)
    df.to_csv(report_dir / "live_collinearity_diagnostic.csv", index=False)
    print(f"\nSaved {n} rows to paper_trading/reports/live_collinearity_diagnostic.csv")


if __name__ == "__main__":
    main()
