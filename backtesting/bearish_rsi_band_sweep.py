"""
Sweeps candidate bearish RSI bands (rsi_min_bearish/rsi_max_bearish, see
_simulate_test_signals' docstring) against real historical data, pooled across
walk-forward windows — the same methodology entry_filter_variants.py already
established for the bullish RSI band (see CHANGELOG v2.2.5/v2.2.29/v2.2.33),
applied here for the first time to its bearish counterpart instead of trusting
the shipped default (18-55, a naive 100-minus-RSI mirror of the bullish 45-82
band with no validation of its own — see CHANGELOG v2.2.58).

Motivating hypothesis (from CHANGELOG v2.2.58's backtest result): the mirrored
bearish path lost heavily to stop-outs, several of them sharp reversals shortly
after entry (e.g. one AMD 2022 short: entered $77.99, stopped out $89.53
fourteen days later). RSI isn't naturally symmetric — an overbought reading in
a strong uptrend tends to keep going, but a deeply oversold reading often
precedes a bounce, not continuation ("shorting into capitulation"). The variants
below test whether raising the band's floor (avoiding the deepest oversold
readings) fixes this, rather than assuming it does.

Run across all 4 sector datasets (not just semiconductors, unlike
entry_filter_variants.py) since the bearish underperformance in CHANGELOG
v2.2.58 was consistent across all 4 sectors, not sector-specific.

Usage: python -m backtesting.bearish_rsi_band_sweep
"""

from pathlib import Path

import pandas as pd

from backtesting.backtest_engine import _SECTOR_DATASETS
from backtesting.walk_forward import run_walk_forward
from backtesting.metrics import compute_win_rate, compute_avg_rr, compute_sharpe, _build_equity_curve, _trades_per_year
from backtesting.run_backtest import load_historical_data
from shared.utils.logger import get_logger

logger = get_logger(__name__)

_CONFIDENCE_THRESHOLD_BACKTEST = 90.0

# Current default (100-minus-RSI mirror of the bullish 45-82 band) plus
# candidates that progressively avoid the deepest oversold readings, testing
# the "shorting into capitulation gets bounced" hypothesis directly.
VARIANTS = {
    "mirror_default_18_55": {"rsi_min_bearish": 18.0, "rsi_max_bearish": 55.0},
    "avoid_deep_oversold_25_55": {"rsi_min_bearish": 25.0, "rsi_max_bearish": 55.0},
    "avoid_deep_oversold_30_55": {"rsi_min_bearish": 30.0, "rsi_max_bearish": 55.0},
    "avoid_deep_oversold_35_55": {"rsi_min_bearish": 35.0, "rsi_max_bearish": 55.0},
    "narrow_symmetric_30_50": {"rsi_min_bearish": 30.0, "rsi_max_bearish": 50.0},
    "moderate_soft_only_40_55": {"rsi_min_bearish": 40.0, "rsi_max_bearish": 55.0},
}


def _pooled_bearish_metrics(windows: list[dict]) -> dict:
    pooled = [o for w in windows for o in w.get("outcomes", []) if o.get("direction") == "bearish"]
    if not pooled:
        return {"n_trades": 0, "win_rate": None, "avg_rr": None, "sharpe": None}
    chrono = sorted(pooled, key=lambda o: o.get("exit_date") or o.get("signal_date") or "")
    equity_curve = _build_equity_curve(chrono)
    trade_returns = equity_curve.pct_change().dropna()
    sharpe = compute_sharpe(trade_returns, periods_per_year=_trades_per_year(chrono)) if len(chrono) > 1 else 0.0
    return {
        "n_trades": len(pooled),
        "win_rate": round(compute_win_rate(pooled), 4),
        "avg_rr": round(compute_avg_rr(pooled), 2),
        "sharpe": round(sharpe, 2),
    }


def run_sweep() -> pd.DataFrame:
    rows = []
    for variant_name, signal_kwargs in VARIANTS.items():
        pooled_all_sectors = []
        for sector, (data_dir, benchmark) in _SECTOR_DATASETS.items():
            historical_data = load_historical_data(data_dir)
            if not historical_data:
                continue
            kwargs = {**signal_kwargs, "benchmark_ticker": benchmark}
            logger.info(f"{variant_name} / {sector}: running walk-forward with {kwargs}")
            windows = run_walk_forward(historical_data, signal_kwargs=kwargs, include_outcomes=True)
            metrics = _pooled_bearish_metrics(windows)
            rows.append({"variant": variant_name, "sector": sector, **metrics})
            pooled_all_sectors.extend(
                o for w in windows for o in w.get("outcomes", []) if o.get("direction") == "bearish"
            )

        if pooled_all_sectors:
            chrono = sorted(pooled_all_sectors, key=lambda o: o.get("exit_date") or o.get("signal_date") or "")
            equity_curve = _build_equity_curve(chrono)
            trade_returns = equity_curve.pct_change().dropna()
            sharpe = compute_sharpe(trade_returns, periods_per_year=_trades_per_year(chrono)) if len(chrono) > 1 else 0.0
            rows.append({
                "variant": variant_name, "sector": "ALL (pooled)",
                "n_trades": len(pooled_all_sectors),
                "win_rate": round(compute_win_rate(pooled_all_sectors), 4),
                "avg_rr": round(compute_avg_rr(pooled_all_sectors), 2),
                "sharpe": round(sharpe, 2),
            })

    df = pd.DataFrame(rows)
    report_dir = Path("backtesting/reports")
    report_dir.mkdir(parents=True, exist_ok=True)
    df.to_csv(report_dir / "bearish_rsi_band_sweep.csv", index=False)
    return df


def main() -> None:
    print("Sweeping bearish RSI bands against real historical data, pooled across "
          "walk-forward windows, all 4 sectors...\n")
    df = run_sweep()
    pd.set_option("display.width", 160)
    print(df.to_string(index=False))
    print("\nSaved to backtesting/reports/bearish_rsi_band_sweep.csv")

    pooled_only = df[df["sector"] == "ALL (pooled)"].sort_values("sharpe", ascending=False)
    if not pooled_only.empty:
        print("\n=== Pooled-across-sectors ranking (by Sharpe) ===\n")
        print(pooled_only.to_string(index=False))


if __name__ == "__main__":
    main()
