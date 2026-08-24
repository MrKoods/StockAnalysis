"""
Reports what the real backtest data suggests the confidence-score go-live
threshold should be — without silently changing CONFIDENCE_THRESHOLD
(swing_model/scoring.py) itself. Once win_probability_calibration.py maps a
score to a real, backtest-derived win probability, "90" stops being a
natural cutoff on its own; this answers two different, more useful
questions instead:

1. Which threshold maximizes expected value per trade (in R-multiples),
   using each threshold's own real win rate and avg R:R from the backtest?
2. What's the LOWEST threshold that still clears this project's existing
   go-live gate (bootstrapped expectancy CI lower bound, Sharpe, drawdown —
   the same criteria backtest_engine.run_backtest() already gates on)?

Changing CONFIDENCE_THRESHOLD is a live-trading-behavior decision (it
changes how often a signal fires at all), not a calibration bug — this
script surfaces the data point, it doesn't act on it.

Usage: python -m backtesting.threshold_optimization_analysis
"""

from backtesting.backtest_engine import _get_test_outcomes, _SECTOR_DATASETS
from backtesting.metrics import (
    compute_win_rate,
    compute_avg_rr,
    compute_r_multiples,
    bootstrap_expectancy_ci,
    compute_max_drawdown,
    compute_sharpe,
    _build_equity_curve,
    _trades_per_year,
)
from backtesting.run_backtest import load_historical_data
from shared.utils.logger import get_logger

logger = get_logger(__name__)

_THRESHOLD_GRID = list(range(40, 100, 5))
_MIN_QUALIFYING_TRADES = 100
_MIN_EXPECTANCY_R = 0.3


def collect_pooled_outcomes(config_path: str = "config/swing_config.yaml") -> list[dict]:
    """Same pooling as fit_win_probability_calibration.py — every sector's
    out-of-sample outcomes, unfiltered by confidence threshold."""
    pooled: list[dict] = []
    for sector, (data_dir, benchmark) in _SECTOR_DATASETS.items():
        historical_data = load_historical_data(data_dir)
        if not historical_data:
            logger.warning(f"{sector}: no historical data in {data_dir}, skipping")
            continue
        outcomes, _months, _dates, _cutoff = _get_test_outcomes(
            historical_data, config_path, train_split=0.70, benchmark_ticker=benchmark,
        )
        pooled.extend(outcomes)
    return pooled


def evaluate_thresholds(outcomes: list[dict], thresholds: list[int]) -> list[dict]:
    """
    Per-threshold: win_rate, avg_rr, ev_per_trade_r (win_rate * avg_rr -
    (1 - win_rate), i.e. expected R gained per trade assuming a full -1R
    loss on losers), expectancy CI lower bound, Sharpe, max drawdown, and
    whether this threshold alone would clear the existing go-live gate.
    """
    rows = []
    for threshold in thresholds:
        qualifying = [o for o in outcomes if float(o.get("confidence", 0)) >= threshold]
        if not qualifying:
            rows.append({
                "threshold": threshold, "qualifying_trades": 0, "win_rate": 0.0, "avg_rr": 0.0,
                "ev_per_trade_r": 0.0, "expectancy_r_ci_lower": 0.0, "sharpe_ratio": 0.0,
                "max_drawdown_pct": 0.0, "clears_go_live_gate": False,
            })
            continue

        win_rate = compute_win_rate(qualifying)
        avg_rr = compute_avg_rr(qualifying)
        ev_per_trade_r = win_rate * avg_rr - (1.0 - win_rate)

        expectancy_ci = bootstrap_expectancy_ci(compute_r_multiples(qualifying))
        chrono = sorted(qualifying, key=lambda o: o.get("exit_date") or o.get("signal_date") or "")
        equity_curve = _build_equity_curve(chrono)
        max_dd = compute_max_drawdown(equity_curve)
        trade_returns = equity_curve.pct_change().dropna()
        sharpe = compute_sharpe(trade_returns, periods_per_year=_trades_per_year(chrono))

        clears_gate = (
            len(qualifying) >= _MIN_QUALIFYING_TRADES
            and expectancy_ci["ci_lower"] >= _MIN_EXPECTANCY_R
            and sharpe >= 1.0
            and max_dd <= 0.15
        )

        rows.append({
            "threshold": threshold,
            "qualifying_trades": len(qualifying),
            "win_rate": round(win_rate, 4),
            "avg_rr": round(avg_rr, 2),
            "ev_per_trade_r": round(ev_per_trade_r, 4),
            "expectancy_r_ci_lower": round(expectancy_ci["ci_lower"], 3),
            "sharpe_ratio": round(sharpe, 2),
            "max_drawdown_pct": round(max_dd, 4),
            "clears_go_live_gate": clears_gate,
        })
    return rows


def main() -> None:
    outcomes = collect_pooled_outcomes()
    if not outcomes:
        print("No historical outcomes across any sector — nothing to analyze.")
        return

    rows = evaluate_thresholds(outcomes, _THRESHOLD_GRID)

    print(f"\nThreshold optimization analysis — {len(outcomes)} pooled out-of-sample outcomes\n")
    print(f"{'threshold':>9} {'trades':>7} {'win_rate':>9} {'avg_rr':>7} {'ev_R/trade':>11} "
          f"{'exp_CI_lo':>10} {'sharpe':>7} {'max_dd':>7} {'gate':>6}")
    for r in rows:
        print(
            f"{r['threshold']:>9} {r['qualifying_trades']:>7} {r['win_rate']:>9.4f} {r['avg_rr']:>7.2f} "
            f"{r['ev_per_trade_r']:>11.4f} {r['expectancy_r_ci_lower']:>10.3f} {r['sharpe_ratio']:>7.2f} "
            f"{r['max_drawdown_pct']:>7.4f} {'YES' if r['clears_go_live_gate'] else 'no':>6}"
        )

    scored = [r for r in rows if r["qualifying_trades"] > 0]
    if scored:
        ev_optimal = max(scored, key=lambda r: r["ev_per_trade_r"])
        print(
            f"\nEV-optimal threshold (max expected R per trade): {ev_optimal['threshold']} "
            f"(ev_per_trade_r={ev_optimal['ev_per_trade_r']}, win_rate={ev_optimal['win_rate']:.1%}, "
            f"n={ev_optimal['qualifying_trades']})"
        )

    gate_clearing = [r for r in rows if r["clears_go_live_gate"]]
    if gate_clearing:
        lowest = min(gate_clearing, key=lambda r: r["threshold"])
        print(
            f"Lowest threshold clearing the existing go-live gate "
            f"(>={_MIN_QUALIFYING_TRADES} trades, expectancy CI lower>={_MIN_EXPECTANCY_R}R, "
            f"Sharpe>=1.0, drawdown<=15%): {lowest['threshold']}"
        )
    else:
        print("No threshold in the tested grid clears the existing go-live gate on this pooled dataset.")

    from swing_model.scoring import CONFIDENCE_THRESHOLD
    print(
        f"\nCONFIDENCE_THRESHOLD (swing_model/scoring.py) is currently {CONFIDENCE_THRESHOLD} and was NOT "
        "changed by this script — deciding whether to move it is a live-trading-behavior call, not "
        "something to apply automatically from a backtest reading."
    )


if __name__ == "__main__":
    main()
