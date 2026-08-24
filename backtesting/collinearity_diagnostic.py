"""
Measures how independent the Technical and Sentiment categories actually are
in the backtest, as opposed to live/paper trading. In backtest replay, Sentiment
is a price-momentum proxy (_sentiment_from_price_momentum in simulation.py) —
not real StockTwits data, which doesn't exist historically. Since Technical
already scores momentum/breakout/RSI directly, a proxy built from the same
price series risks being highly correlated with it: two "independent" 100-point
categories that are really one signal wearing two labels would inflate the
backtest's apparent win rate versus what real, independent sentiment data
will contribute once enough live/paper history accumulates.

Reuses the exact same candidate-detection filters as
backtesting/simulation.py::_simulate_test_signals (breakout mask, trend_intact,
sector-trend, RS, RSI band, confirmation bar) so the sampled population matches
what the real backtest actually scores — just skips outcome simulation
(entry/stop/target) since this only needs the score components, not P&L.

Usage: python -m backtesting.collinearity_diagnostic
"""

from pathlib import Path

import pandas as pd
import yaml

from backtesting.run_backtest import load_historical_data
from backtesting.simulation import _compute_vix_proxy, _sentiment_from_price_momentum
from shared.indicators.technical_common import compute_technical_indicators
from shared.utils.regime_detection import classify_regime, get_regime_modifiers
from shared.utils.tail_dependence import conditional_top_quantile_rate
from swing_model.scoring import compute_confidence_score

_NEUTRAL_FUNDAMENTAL = {"fundamental_score": 0.0, "data_quality": "unavailable"}
_NEUTRAL_NEWS = {
    "news_score_total": 7.5, "credibility_weighted_score": 3.0,
    "theme_alignment_score": 2.0, "clustering_score": 1.5, "decay_score": 1.0,
}
_NEUTRAL_POSITIONING = {
    "positioning_score_total": 10.0, "options_score": 3.0, "institutional_score": 2.5,
    "short_interest_score": 2.0, "insider_score": 1.5, "analyst_score": 1.0,
    "positioning_offline": False, "data_quality": "unavailable",
}


def collect_score_pairs(
    historical_data: dict[str, pd.DataFrame],
    config_path: str = "config/swing_config.yaml",
    rsi_min: float = 45.0,
    rsi_max: float = 70.0,
    require_confirmation_bar: bool = True,
) -> pd.DataFrame:
    """
    Replay the same candidate-detection filters as _simulate_test_signals and
    return one row per candidate bar with technical_total, sentiment_total,
    and the raw momentum inputs the sentiment proxy is built from — no trade
    outcome simulation, since correlation only needs the score components.
    """
    try:
        cfg = yaml.safe_load(Path(config_path).read_text(encoding="utf-8")) or {}
    except Exception:
        cfg = {}

    smh_df = historical_data.get("SMH")
    smh_sector_trend = None
    if smh_df is not None and len(smh_df) >= 55:
        smh_sma20 = smh_df["Close"].rolling(20).mean()
        smh_sma50 = smh_df["Close"].rolling(50).mean()
        smh_sector_trend = (smh_sma20 > smh_sma50) & (smh_df["Close"] > smh_sma50)

    rows = []

    for ticker, df in historical_data.items():
        if ticker == "SMH" or df.empty or len(df) < 65:
            continue

        bench_aligned = (
            smh_df["Close"].reindex(df.index, method="ffill")
            if smh_df is not None else pd.Series(100.0, index=df.index)
        )
        prior_20d_high = df["High"].rolling(20).max().shift(1)
        breakout_mask = df["Close"] > prior_20d_high
        signal_indices = [i for i in range(60, len(df) - 1) if breakout_mask.iloc[i]]

        for i in signal_indices:
            entry_idx = i
            if require_confirmation_bar:
                if i + 1 >= len(df):
                    continue
                if not (df["Close"].iloc[i + 1] > prior_20d_high.iloc[i]):
                    continue
                entry_idx = i + 1

            bar_date = df.index[entry_idx]
            df_slice = df.iloc[:entry_idx + 1]
            bench_slice = bench_aligned.iloc[:entry_idx + 1]

            try:
                indicators = compute_technical_indicators(df_slice, bench_slice, cfg)
            except Exception:
                continue

            if not indicators.get("trend_intact", False):
                continue
            if smh_sector_trend is not None:
                idx = smh_sector_trend.index.get_indexer([bar_date], method="ffill")
                if idx[0] >= 0 and not bool(smh_sector_trend.iloc[idx[0]]):
                    continue
            if float(indicators.get("rs_zscore", -2.0)) < 0.0:
                continue
            if len(df_slice) >= 21 and len(bench_slice) >= 21:
                stock_ret_20d = float(df_slice["Close"].iloc[-1] / df_slice["Close"].iloc[-21]) - 1.0
                bench_ret_20d = float(bench_slice.iloc[-1] / bench_slice.iloc[-21]) - 1.0
                if stock_ret_20d < bench_ret_20d:
                    continue
            rsi_val = float(indicators.get("rsi_14", 50.0))
            if rsi_val < rsi_min or rsi_val > rsi_max:
                continue

            regime = "choppy"
            regime_mod = 0.0
            if smh_df is not None:
                smh_slice = smh_df[smh_df.index <= bar_date]
                if len(smh_slice) >= 22:
                    try:
                        vix_proxy = _compute_vix_proxy(smh_slice)
                        regime = classify_regime(vix=vix_proxy, smh_ohlcv=smh_slice)
                        regime_mod = get_regime_modifiers(regime, cfg).get("regime_modifier", 0.0)
                    except Exception:
                        pass

            sentiment = _sentiment_from_price_momentum(df_slice)
            close = df_slice["Close"].values
            mom_5d = (close[-1] - close[-6]) / close[-6] if len(close) >= 6 else 0.0

            try:
                score = compute_confidence_score(
                    technical=indicators,
                    positioning=_NEUTRAL_POSITIONING,
                    sentiment=sentiment,
                    news=_NEUTRAL_NEWS,
                    regime_modifier=regime_mod,
                    sector_rotation_modifier=0.0,
                    earnings_modifier=0.0,
                    cross_ticker_modifier=0.0,
                    seasonality_modifier=0.0,
                    macro_modifier=0.0,
                    cfg=cfg,
                    regime=regime,
                    fundamental=_NEUTRAL_FUNDAMENTAL,
                )
            except Exception:
                continue

            rows.append({
                "ticker": ticker,
                "date": bar_date,
                "technical_total": score.get("technical_total", 0.0),
                "sentiment_total": score.get("sentiment_total", 0.0),
                "rs_zscore": float(indicators.get("rs_zscore", 0.0)),
                "rsi_14": rsi_val,
                "mom_5d": mom_5d,
            })

    return pd.DataFrame(rows)


def main() -> None:
    historical_data = load_historical_data("data/historical")
    if not historical_data:
        print("No historical data loaded. Place {ticker}.csv files in data/historical/")
        return

    df = collect_score_pairs(historical_data)
    if df.empty:
        print("No candidate bars found — nothing to correlate.")
        return

    r_total = df["technical_total"].corr(df["sentiment_total"])
    rho_total = df["technical_total"].corr(df["sentiment_total"], method="spearman")
    r_rs_mom = df["rs_zscore"].corr(df["mom_5d"])
    rho_rs_mom = df["rs_zscore"].corr(df["mom_5d"], method="spearman")

    print(f"\nCollinearity diagnostic — {len(df)} candidate bars, {df['ticker'].nunique()} tickers\n")
    print(f"Pearson r  (technical_total, sentiment_total)          = {r_total:.3f}")
    print(f"Spearman rho (technical_total, sentiment_total)        = {rho_total:.3f}")
    print(f"Pearson r  (rs_zscore, mom_5d) [inputs each is built on] = {r_rs_mom:.3f}")
    print(f"Spearman rho (rs_zscore, mom_5d)                       = {rho_rs_mom:.3f}")
    print(
        "\nInterpretation: |r| > 0.5 means Technical and Sentiment are substantially "
        "the same signal under two labels in this backtest (the proxy limitation "
        "documented in PROJECT_OVERVIEW.md §13) — the backtest's apparent win rate "
        "is a soft upper bound, not a lower bound, on what independent live "
        "sentiment data will contribute. |r| < 0.3 would suggest the categories are "
        "adding meaningfully separate information even under the proxy."
    )

    tail = conditional_top_quantile_rate(df, "technical_total", "sentiment_total", quantile=0.75)
    print(
        f"\nTail dependence (top-quartile co-occurrence): P(sentiment top 25%% | technical top 25%%) "
        f"= {tail['conditional_rate']:.1%} vs. unconditional {tail['unconditional_rate']:.1%} "
        f"(lift={tail['lift']:.2f}x, n_conditioned={tail['n_conditioned']}). A low bulk r above "
        "doesn't rule out elevated joint-extreme co-occurrence — lift near 1.0 means the two "
        "categories peak together no more than chance would predict; lift meaningfully above "
        "1.0 means the backtest's apparent joint-high-score rate (what the real qualifying "
        "threshold actually depends on) is inflated by the proxy beyond what the bulk correlation reading "
        "alone would suggest."
    )

    report_dir = Path("backtesting/reports")
    report_dir.mkdir(parents=True, exist_ok=True)
    df.to_csv(report_dir / "collinearity_diagnostic.csv", index=False)
    print(f"\nSaved {len(df)} rows to backtesting/reports/collinearity_diagnostic.csv")


if __name__ == "__main__":
    main()
