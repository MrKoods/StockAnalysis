"""
Third follow-up to CHANGELOG v2.2.58's bearish backtest finding (after
bearish_rsi_band_sweep.py and bearish_exit_sizing_sweep.py, both of which
found real-but-insufficient improvement — Sharpe moved from -2.44 to -1.73
at best, never close to positive).

This sweeps require_confirmation_bar — an existing _simulate_test_signals
parameter, unused in either prior sweep — which requires the bar AFTER a
breakdown to still close below the breakdown level before the signal counts
at all, entry shifting to that confirmation bar. Directly targets the
specific failure pattern observed in the real trade data: breakdown signals
that get stopped out by a sharp reversal shortly after entry (e.g. one AMD
2022 short: entered $77.99, stopped out $89.53 fourteen days later) — a
one-day undercut that immediately reverses ("bear trap") would fail to
confirm and never generate a signal at all under this filter.

Base parameters held at the best-found combination from the two prior
sweeps (RSI 30-55, 1x ATR stop, 1.5R target) so this isolates the
confirmation-bar effect on top of those findings rather than confounding.

Usage: python -m backtesting.bearish_confirmation_sweep
"""

from pathlib import Path

import pandas as pd

from backtesting.backtest_engine import _SECTOR_DATASETS
from backtesting.walk_forward import run_walk_forward
from backtesting.metrics import compute_win_rate, compute_avg_rr, compute_sharpe, _build_equity_curve, _trades_per_year
from backtesting.run_backtest import load_historical_data
from shared.utils.logger import get_logger

logger = get_logger(__name__)

_BASE = {
    "rsi_min_bearish": 30.0, "rsi_max_bearish": 55.0,
    "min_rr_bearish": 1.5, "stop_atr_multiplier_bearish": 1.0,
}

VARIANTS = {
    "no_confirmation_bar (prior best)": {**_BASE, "require_confirmation_bar": False},
    "confirmation_bar_required": {**_BASE, "require_confirmation_bar": True},
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
    df.to_csv(report_dir / "bearish_confirmation_sweep.csv", index=False)
    return df


def main() -> None:
    print("Testing require_confirmation_bar for bearish signals (base: RSI 30-55, "
          "1x ATR stop, 1.5R target — the best combo found so far)...\n")
    df = run_sweep()
    pd.set_option("display.width", 160)
    print(df.to_string(index=False))
    print("\nSaved to backtesting/reports/bearish_confirmation_sweep.csv")


if __name__ == "__main__":
    main()
