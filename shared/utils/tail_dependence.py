"""
Measures tail dependence between two score columns — how much more often one
column lands in its own top tail when the other is also in its own top tail,
versus the unconditional rate.

Why this exists alongside plain correlation (used by
backtesting/collinearity_diagnostic.py and paper_trading/live_collinearity_diagnostic.py,
both v2.2.16): a low bulk Pearson/Spearman r can still coexist with elevated
tail dependence — two columns can look "mostly independent" across their full
range while still tending to spike together in the tails. That's exactly the
joint-extreme event a fixed high composite-score threshold (90/100, which
structurally requires several categories to be near their own ceiling at the
same time — see paper_trading/score_distribution_diagnostic.py) depends on,
and it's a question the v2.2.16 bulk-correlation reading never actually asked.
"""

import pandas as pd


def conditional_top_quantile_rate(
    df: pd.DataFrame,
    condition_col: str,
    target_col: str,
    quantile: float = 0.75,
) -> dict:
    """
    P(target_col in its own top (1-quantile) tail | condition_col in its own
    top (1-quantile) tail), compared against the unconditional rate.

    Returns dict:
    {
        quantile, n, n_conditioned,
        conditional_rate:    P(target in top tail | condition in top tail)
        unconditional_rate:  P(target in top tail)
        lift:                conditional_rate / unconditional_rate
                              (1.0 = no tail dependence beyond independence;
                              > 1.0 = extremes co-occur more than chance would predict)
    }
    Rows missing either column are dropped before computing quantile thresholds.
    """
    empty_result = {
        "quantile": quantile, "n": 0, "n_conditioned": 0,
        "conditional_rate": 0.0, "unconditional_rate": 0.0, "lift": 0.0,
    }
    if df.empty or condition_col not in df.columns or target_col not in df.columns:
        return empty_result

    valid = df[[condition_col, target_col]].dropna()
    n = len(valid)
    if n == 0:
        return empty_result

    cond_threshold = valid[condition_col].quantile(quantile)
    target_threshold = valid[target_col].quantile(quantile)

    unconditional_rate = float((valid[target_col] >= target_threshold).mean())

    conditioned = valid[valid[condition_col] >= cond_threshold]
    n_conditioned = len(conditioned)
    conditional_rate = (
        float((conditioned[target_col] >= target_threshold).mean()) if n_conditioned else 0.0
    )
    lift = (conditional_rate / unconditional_rate) if unconditional_rate > 0 else 0.0

    return {
        "quantile": quantile,
        "n": n,
        "n_conditioned": n_conditioned,
        "conditional_rate": round(conditional_rate, 4),
        "unconditional_rate": round(unconditional_rate, 4),
        "lift": round(lift, 4),
    }
