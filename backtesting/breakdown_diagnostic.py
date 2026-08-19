"""
Phase 0 diagnostic for bearish/breakdown signal parity (see the approved plan
for "Add Symmetric Bearish/Breakdown Detection to the Swing Model").

Answers one question before any scoring/backtest code is built: does the
existing historical OHLCV data (2013-2026, all 4 sectors) actually contain
enough real breakdown/downtrend setups to validate a bearish path against,
or is this a data-availability dead end worth knowing about before writing
the full scoring/calibration stack?

Read-only — no scoring/config changes, same pattern as
architecture_diagnostic.py. Reuses is_breakout()'s own rolling_low/sma/rsi
primitives (shared/indicators/technical_common.py) rather than
reimplementing them, so these counts reflect the real indicators a later
phase will wire into compute_technical_indicators() as breakdown_confirmed/
downtrend_intact.

Usage: python -m backtesting.breakdown_diagnostic
"""

from pathlib import Path

import pandas as pd

from backtesting.backtest_engine import _SECTOR_DATASETS
from backtesting.run_backtest import load_historical_data
from shared.indicators.technical_common import rolling_low, sma, rsi
from shared.utils.logger import get_logger

logger = get_logger(__name__)

# Mirrors _simulate_test_signals' bullish RSI band (45-82, see
# backtesting/simulation.py) reflected around 50 — a rough starting point for
# counting purposes only. A future phase will re-derive the real bearish band
# from backtest evidence, the same way the bullish 45-82 band was itself
# re-tested rather than assumed (see that function's own docstring history).
_RSI_MIN_BEARISH = 18.0
_RSI_MAX_BEARISH = 55.0

_MIN_HISTORY_BARS = 65
_WARMUP_BARS = 60


def _breakdown_candidate_mask(df: pd.DataFrame) -> pd.Series:
    """Mirrors is_breakout()'s close > prior_high, inverted: close < prior 20-day low."""
    prior_20d_low = rolling_low(df["Low"], period=20).shift(1)
    return df["Close"] < prior_20d_low


def _downtrend_mask(close: pd.Series) -> pd.Series:
    """Mirrors trend_intact's sma20>sma50 and close>sma50, inverted."""
    sma20 = sma(close, 20)
    sma50 = sma(close, 50)
    return (sma20 < sma50) & (close < sma50)


def count_breakdown_candidates(sector: str, data_dir: str, benchmark: str) -> dict:
    """
    Count raw breakdown bars and bars that also clear the mirrored quality
    gates simulation.py applies to bullish breakouts: sector downtrend,
    20-day underperformance vs. benchmark, and an RSI oversold band.
    """
    historical_data = load_historical_data(data_dir)
    if not historical_data:
        logger.warning(f"{sector}: no historical data in {data_dir}, skipping")
        return {"sector": sector, "n_tickers": 0, "n_raw_breakdowns": 0, "n_qualifying": 0, "by_year": {}}

    smh_df = historical_data.get(benchmark)
    smh_downtrend = None
    if smh_df is not None and len(smh_df) >= 55:
        smh_downtrend = _downtrend_mask(smh_df["Close"])

    n_raw = 0
    n_qualifying = 0
    by_year: dict[int, int] = {}
    n_tickers = 0

    for ticker, df in historical_data.items():
        if ticker == benchmark or df.empty or len(df) < _MIN_HISTORY_BARS:
            continue
        n_tickers += 1

        breakdown_mask = _breakdown_candidate_mask(df)
        downtrend = _downtrend_mask(df["Close"])
        rsi_series = rsi(df["Close"], 14)
        bench_aligned = smh_df["Close"].reindex(df.index, method="ffill") if smh_df is not None else None

        for i in range(_WARMUP_BARS, len(df) - 1):
            if not bool(breakdown_mask.iloc[i]):
                continue
            n_raw += 1

            if not bool(downtrend.iloc[i]):
                continue
            if smh_downtrend is not None:
                idx = smh_downtrend.index.get_indexer([df.index[i]], method="ffill")
                if idx[0] >= 0 and not bool(smh_downtrend.iloc[idx[0]]):
                    continue
            if bench_aligned is not None and i >= 20:
                stock_ret_20d = float(df["Close"].iloc[i] / df["Close"].iloc[i - 20]) - 1.0
                bench_ret_20d = float(bench_aligned.iloc[i] / bench_aligned.iloc[i - 20]) - 1.0
                if stock_ret_20d > bench_ret_20d:
                    continue  # stock outperformed the benchmark -> not a bearish-confirming underperformer
            rsi_val = float(rsi_series.iloc[i])
            if rsi_val < _RSI_MIN_BEARISH or rsi_val > _RSI_MAX_BEARISH:
                continue

            n_qualifying += 1
            year = df.index[i].year
            by_year[year] = by_year.get(year, 0) + 1

    return {
        "sector": sector,
        "n_tickers": n_tickers,
        "n_raw_breakdowns": n_raw,
        "n_qualifying": n_qualifying,
        "by_year": dict(sorted(by_year.items())),
    }


def main() -> None:
    print(
        "Counting breakdown/downtrend candidate bars across all 4 sectors "
        "(mirrors the bullish breakout+trend_intact+RS+RSI gate structure in "
        "simulation.py, inverted) ...\n"
    )

    rows = []
    for sector, (data_dir, benchmark) in _SECTOR_DATASETS.items():
        result = count_breakdown_candidates(sector, data_dir, benchmark)
        rows.append(result)
        by_year_str = ", ".join(f"{y}:{c}" for y, c in result["by_year"].items()) or "(none)"
        print(
            f"{sector:24s} tickers={result['n_tickers']:3d}  raw_breakdowns={result['n_raw_breakdowns']:5d}  "
            f"qualifying={result['n_qualifying']:5d}  by_year=[{by_year_str}]"
        )

    df = pd.DataFrame([{k: v for k, v in r.items() if k != "by_year"} for r in rows])
    report_dir = Path("backtesting/reports")
    report_dir.mkdir(parents=True, exist_ok=True)
    df.to_csv(report_dir / "breakdown_diagnostic.csv", index=False)
    print(f"\nSaved to {report_dir / 'breakdown_diagnostic.csv'}")
    print(
        "\nNote: 'qualifying' uses a placeholder RSI band (18-55, a rough mirror of "
        "the bullish 45-82 band) purely for this count — a later phase will re-derive "
        "the real bearish band from backtest evidence, same as the bullish band's own history."
    )


if __name__ == "__main__":
    main()
