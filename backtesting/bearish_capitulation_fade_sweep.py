"""
Tests bearish_entry_style="capitulation_fade" (shared/indicators/technical_common.py's
bounce_fade_setup()) against the shipped continuation mirror — a genuinely
different bearish entry, not another parameter tweak on the same mirror.

Motivating hypothesis (CHANGELOG v2.2.59's working theory, stated explicitly
as unconfirmed): the bullish path is momentum-continuation — buy a fresh
breakout while RSI is still healthy (50-70), not yet stretched. The bearish
mirror enters right after a breakdown, which is often already oversold —
structurally close to where a relief bounce/short-squeeze is likeliest, the
opposite of the bullish case. A real logged example: a semis short entered
$77.99, stopped out $89.53 fourteen days later. If that theory is right, no
amount of tuning the continuation mirror's parameters fixes it — three
rounds (16 variants) already tried exactly that (RSI band, exit sizing,
confirmation timing) and none came close to the go-live bar (best pooled
Sharpe -1.73). capitulation_fade instead waits for the bounce that follows a
breakdown and shorts its exhaustion, once RSI recovers into a neutral band
and rolls back over — mechanically distinct, not a mirror-parameter change.

Baseline uses v2.2.59's own best-found continuation settings (RSI 30-55,
1.5R target, 1x ATR stop — Sharpe -1.73) rather than the original naive
18-55/3R/2xATR mirror, so this isolates the entry-style effect against the
strongest continuation candidate already found, not a weaker strawman.

Same walk-forward-pooled methodology as bearish_rsi_band_sweep.py/
bearish_exit_sizing_sweep.py, across all 4 sector datasets.

Usage: python -m backtesting.bearish_capitulation_fade_sweep
"""

from pathlib import Path

import pandas as pd

from backtesting.backtest_engine import _SECTOR_DATASETS
from backtesting.walk_forward import run_walk_forward
from backtesting.metrics import compute_win_rate, compute_avg_rr, compute_sharpe, _build_equity_curve, _trades_per_year
from backtesting.run_backtest import load_historical_data
from shared.utils.logger import get_logger

logger = get_logger(__name__)

# v2.2.59's best-found continuation settings — the fair baseline to beat,
# not the original untuned 18-55/3R/2xATR mirror.
_BEST_CONTINUATION = {
    "bearish_entry_style": "continuation",
    "rsi_min_bearish": 30.0, "rsi_max_bearish": 55.0,
    "min_rr_bearish": 1.5, "stop_atr_multiplier_bearish": 1.0,
}

VARIANTS = {
    "baseline_continuation_best_known": _BEST_CONTINUATION,
    "capitulation_fade_default": {
        "bearish_entry_style": "capitulation_fade",
        "bounce_fade_lookback": 10, "bounce_fade_min_bounce_atr": 1.0,
        "bounce_fade_rsi_min": 45.0, "bounce_fade_rsi_max": 65.0,
    },
    "capitulation_fade_tighter_bounce": {
        "bearish_entry_style": "capitulation_fade",
        "bounce_fade_lookback": 10, "bounce_fade_min_bounce_atr": 0.5,
        "bounce_fade_rsi_min": 45.0, "bounce_fade_rsi_max": 65.0,
    },
    "capitulation_fade_wider_rsi": {
        "bearish_entry_style": "capitulation_fade",
        "bounce_fade_lookback": 10, "bounce_fade_min_bounce_atr": 1.0,
        "bounce_fade_rsi_min": 40.0, "bounce_fade_rsi_max": 70.0,
    },
    "capitulation_fade_shorter_lookback": {
        "bearish_entry_style": "capitulation_fade",
        "bounce_fade_lookback": 5, "bounce_fade_min_bounce_atr": 1.0,
        "bounce_fade_rsi_min": 45.0, "bounce_fade_rsi_max": 65.0,
    },
    # Same exit-sizing improvement v2.2.59 found for continuation, applied to
    # the fade entry too — isolates whether the entry-style change alone
    # helps, or whether it also benefits from the tighter target/stop.
    "capitulation_fade_best_known_exit": {
        "bearish_entry_style": "capitulation_fade",
        "bounce_fade_lookback": 10, "bounce_fade_min_bounce_atr": 1.0,
        "bounce_fade_rsi_min": 45.0, "bounce_fade_rsi_max": 65.0,
        "min_rr_bearish": 1.5, "stop_atr_multiplier_bearish": 1.0,
    },
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
    df.to_csv(report_dir / "bearish_capitulation_fade_sweep.csv", index=False)
    return df


def main() -> None:
    print("Sweeping capitulation_fade vs. the best-known continuation baseline "
          "against real historical data, pooled across walk-forward windows, "
          "all 4 sectors...\n")
    df = run_sweep()
    pd.set_option("display.width", 160)
    print(df.to_string(index=False))
    print("\nSaved to backtesting/reports/bearish_capitulation_fade_sweep.csv")

    pooled_only = df[df["sector"] == "ALL (pooled)"].sort_values("sharpe", ascending=False)
    if not pooled_only.empty:
        print("\n=== Pooled-across-sectors ranking (by Sharpe) ===\n")
        print(pooled_only.to_string(index=False))


if __name__ == "__main__":
    main()
