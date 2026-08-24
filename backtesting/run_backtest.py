"""
Entry point for backtesting.
--sensitivity flag: run threshold sensitivity analysis (85/87/90/92/95) before full backtest.
Full run: 70/30 split, walk-forward validation, per-regime reporting.
"""

import argparse
from pathlib import Path

import pandas as pd

from backtesting.backtest_engine import run_backtest, _get_test_outcomes
from backtesting.metrics import run_sensitivity_analysis
from shared.utils.logger import get_logger

logger = get_logger(__name__)


def load_historical_data(data_dir: str) -> dict[str, pd.DataFrame]:
    """
    Load historical OHLCV data from data_dir.
    Expects one CSV per ticker: {ticker}.csv with columns [Date, Open, High, Low, Close, Volume].
    Returns dict mapping ticker -> DataFrame.
    """
    data_dir = Path(data_dir)
    result = {}

    if not data_dir.exists():
        logger.warning(f"Historical data directory not found: {data_dir}")
        return {}

    for csv_path in data_dir.glob("*.csv"):
        ticker = csv_path.stem.upper()
        try:
            df = pd.read_csv(csv_path, parse_dates=["Date"], index_col="Date")
            df.index = pd.to_datetime(df.index, utc=True)
            for col in ["Open", "High", "Low", "Close", "Volume"]:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors="coerce")
            df = df.dropna(subset=["Close"])
            result[ticker] = df[["Open", "High", "Low", "Close", "Volume"]]
            logger.info(f"Loaded {len(df)} bars for {ticker}")
        except Exception as exc:
            logger.warning(f"Failed to load {csv_path}: {exc}")

    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Run backtest or sensitivity analysis")
    parser.add_argument(
        "--sensitivity",
        action="store_true",
        help="Run threshold sensitivity analysis only (85/87/90/92/95) and save to reports/",
    )
    parser.add_argument(
        "--historical-dir",
        default="data/historical",
        help="Path to historical OHLCV data directory",
    )
    args = parser.parse_args()

    historical_data = load_historical_data(args.historical_dir)

    if not historical_data:
        logger.error("No historical data loaded. Place {ticker}.csv files in data/historical/")
        return

    if args.sensitivity:
        logger.info("Running sensitivity analysis across thresholds: 85, 87, 90, 92, 95")
        all_outcomes, test_months, all_dates, train_cutoff = _get_test_outcomes(historical_data)
        if not all_dates:
            logger.error("No dates in historical data — cannot run sensitivity analysis.")
            return
        df = run_sensitivity_analysis(all_outcomes, test_months)
        print(df.to_string(index=False))
        logger.info("Sensitivity analysis complete. Saved to backtesting/reports/sensitivity_analysis.csv")
    else:
        logger.info("Running full backtest (70/30 split + walk-forward)")
        result = run_backtest(historical_data)

        print("\nBacktest Results:")
        print(f"  Passed:           {result.get('passed')}")
        print(f"  Win Rate:         {result.get('win_rate', 0.0):.1%}")
        print(f"  Avg R:R:          {result.get('avg_rr', 0.0):.2f}")
        print(f"  Sharpe Ratio:     {result.get('sharpe_ratio', 0.0):.2f}")
        print(f"  Max Drawdown:     {result.get('max_drawdown_pct', 0.0):.1%}")
        print(f"  Qualifying Trades:{result.get('qualifying_trades', 0)}")
        print(f"  Max Consec Loss:  {result.get('max_consecutive_losses', 0)}")
        print(f"  Walk-Fwd Pooled:  passed={result.get('walk_forward_pooled_passed')} "
              f"sharpe={result.get('walk_forward_pooled_sharpe', 0.0):.2f} "
              f"trades={result.get('walk_forward_pooled_qualifying_trades', 0)}")
        print(f"  Deflated Sharpe:  {result.get('deflated_sharpe', 0.0):.2f} "
              f"(PSR={result.get('deflated_sharpe_psr', 0.0):.2f}, "
              f"n_trials={result.get('deflated_sharpe_n_trials', 0)}) — reported only, doesn't gate passed")

        # Information Coefficient — complementary read on the FULL scored
        # population (total_signals, not just qualifying_trades). Additive,
        # doesn't gate `passed`. See compute_information_coefficient's
        # docstring (backtesting/metrics.py) for the score_field caveats.
        ic_conf = result.get("ic_confidence") or {}
        ic_tech = result.get("ic_technical") or {}
        ic_real = result.get("ic_real_only") or {}
        print(f"\nInformation Coefficient (n={result.get('total_signals', 0)} scored, "
              f"vs. {result.get('qualifying_trades', 0)} qualifying) — reported only, doesn't gate passed:")
        print(f"  Full composite score:  IC={ic_conf.get('ic', 0.0):+.4f} (p={ic_conf.get('p_value', 1.0):.4f}, "
              f"n={ic_conf.get('n', 0)}) — includes backtest-only Positioning/Sentiment proxies")
        print(f"  Technical-only:        IC={ic_tech.get('ic', 0.0):+.4f} (p={ic_tech.get('p_value', 1.0):.4f}, "
              f"n={ic_tech.get('n', 0)}) — fully real data, heaviest-weighted category")
        print(f"  Real-only composite:   IC={ic_real.get('ic', 0.0):+.4f} (p={ic_real.get('p_value', 1.0):.4f}, "
              f"n={ic_real.get('n', 0)}) — technical + news + fundamental, excludes both proxies")

        if result.get("per_regime"):
            print("\nPer-Regime Results:")
            for regime, metrics in result["per_regime"].items():
                print(f"  {regime}: win={metrics['win_rate']:.1%} "
                      f"avg_rr={metrics['avg_rr']:.2f} trades={metrics['trade_count']}")

        logger.info(
            f"Backtest complete. Passed={result.get('passed')} "
            f"WinRate={result.get('win_rate', 0):.1%} "
            f"Sharpe={result.get('sharpe_ratio', 0):.2f}"
        )


if __name__ == "__main__":
    main()
