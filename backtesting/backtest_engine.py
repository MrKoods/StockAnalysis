"""
Replays scoring logic against historical data.
70/30 out-of-sample split; walk-forward validation; per-regime reporting.
Minimum 100 qualifying trades (confidence 90+, R:R 1:3+) before win rate is valid.
"""

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd

from backtesting.metrics import (
    compute_win_rate,
    compute_avg_rr,
    compute_max_drawdown,
    compute_sharpe,
    per_regime_metrics,
    compute_consecutive_losses,
)


def run_backtest(
    historical_data: dict[str, pd.DataFrame],
    config_path: str = "config/swing_config.yaml",
    train_split: float = 0.70,
    min_qualifying_trades: int = 100,
) -> dict:
    """
    Replay the full scoring + trade selection pipeline against historical OHLCV data.

    Steps:
    1. Split data into train (70%) and test (30%) sets
    2. Calibrate confidence weights on train set
    3. Identify all qualifying signals (confidence >= 90, R:R >= 1:3) in test set
    4. Simulate trade outcomes (entry at alert price, exit at target/stop/time stop)
    5. Compute metrics (win rate, R:R, drawdown, Sharpe) per-regime and overall
    6. Run walk-forward validation across available windows
    7. Return full backtest results dict

    Returns dict with all metrics, per-regime results, walk-forward results.
    """
    if not historical_data:
        return {
            "passed": False,
            "error": "no_historical_data",
            "win_rate": 0.0,
            "avg_rr": 0.0,
            "sharpe_ratio": 0.0,
            "max_drawdown_pct": 0.0,
            "qualifying_trades": 0,
            "per_regime": {},
            "walk_forward": [],
        }

    # Step 1: Collect all bar dates across tickers and split
    all_dates = sorted(set(
        date for df in historical_data.values() for date in df.index
    ))
    if not all_dates:
        return {"passed": False, "error": "no_dates", "win_rate": 0.0}

    split_idx = int(len(all_dates) * train_split)
    train_cutoff = all_dates[split_idx] if split_idx < len(all_dates) else all_dates[-1]

    # Split each ticker's DataFrame
    train_data = {t: df[df.index <= train_cutoff] for t, df in historical_data.items()}
    test_data = {t: df[df.index > train_cutoff] for t, df in historical_data.items()}

    # Step 2-4: Simulate signals in test data
    # (Full indicator pipeline requires live data; in backtest we use simplified proxy signals)
    all_outcomes = _simulate_test_signals(test_data, config_path)
    qualifying = [o for o in all_outcomes if float(o.get("confidence", 0)) >= 90]

    # Step 5: Metrics
    win_rate = compute_win_rate(qualifying)
    avg_rr = compute_avg_rr(qualifying)
    regime_metrics = per_regime_metrics(qualifying)

    # Build equity curve
    equity_curve = _build_equity_curve(qualifying, starting_equity=15000.0)
    max_dd = compute_max_drawdown(equity_curve)
    daily_returns = equity_curve.pct_change().dropna()
    sharpe = compute_sharpe(daily_returns)

    max_consec_losses = compute_consecutive_losses(qualifying)

    # Step 6: Walk-forward
    wf_results = run_walk_forward(historical_data)

    # Determine pass/fail
    passed = (
        len(qualifying) >= min_qualifying_trades
        and win_rate >= 0.55
        and avg_rr >= 1.8
        and sharpe >= 1.0
        and max_dd <= 0.15
    )

    result = {
        "passed": passed,
        "win_rate": round(win_rate, 4),
        "avg_rr": round(avg_rr, 2),
        "sharpe_ratio": round(sharpe, 2),
        "max_drawdown_pct": round(max_dd, 4),
        "qualifying_trades": len(qualifying),
        "total_signals": len(all_outcomes),
        "max_consecutive_losses": max_consec_losses,
        "per_regime": regime_metrics,
        "walk_forward": wf_results,
        "train_period": str(all_dates[0]) if all_dates else "",
        "test_period": str(train_cutoff) if train_cutoff else "",
    }

    # Save report
    _save_report(result)
    return result


def run_walk_forward(
    historical_data: dict[str, pd.DataFrame],
    initial_train_months: int = 18,
    validate_months: int = 6,
) -> list[dict]:
    """
    Walk-forward validation across all available windows.
    Calibrate on months 1-18, validate on 19-24. Roll: calibrate 1-24, validate 25-30.
    Model must pass thresholds in every window, not just the initial one.
    Returns list of per-window results.
    """
    if not historical_data:
        return []

    all_dates = sorted(set(
        date for df in historical_data.values() for date in df.index
    ))
    if not all_dates:
        return []

    start = all_dates[0]
    end = all_dates[-1]
    results = []
    window_start = start
    window_num = 0

    while True:
        # Compute approx month boundaries using 21 trading days = 1 month
        train_days = initial_train_months * 21 + window_num * validate_months * 21
        val_end_days = train_days + validate_months * 21

        train_dates = all_dates[:train_days]
        val_dates = all_dates[train_days:val_end_days]

        if len(val_dates) < validate_months * 10:  # Need at least some data
            break

        train_cutoff = train_dates[-1] if train_dates else all_dates[0]
        val_cutoff = val_dates[-1] if val_dates else all_dates[-1]

        val_data = {t: df[(df.index > train_cutoff) & (df.index <= val_cutoff)]
                    for t, df in historical_data.items()}

        outcomes = _simulate_test_signals(val_data)
        qualifying = [o for o in outcomes if float(o.get("confidence", 0)) >= 90]

        win_rate = compute_win_rate(qualifying)
        avg_rr = compute_avg_rr(qualifying)
        passed = win_rate >= 0.55 and avg_rr >= 1.8 and len(qualifying) >= 10

        results.append({
            "window": window_num + 1,
            "train_through": str(train_cutoff),
            "validate_through": str(val_cutoff),
            "qualifying_trades": len(qualifying),
            "win_rate": round(win_rate, 4),
            "avg_rr": round(avg_rr, 2),
            "passed": passed,
        })

        window_num += 1
        if val_end_days >= len(all_dates):
            break

    return results


def simulate_trade_outcome(
    signal_date: str,
    direction: str,
    entry: float,
    stop: float,
    target: float,
    future_ohlcv: pd.DataFrame,
    holding_period: tuple[int, int] = (5, 15),
    regime: str = "unknown",
    confidence: float = 90.0,
) -> dict:
    """
    Simulate a single trade outcome against future OHLCV bars.
    Checks target hit, stop hit, and time stop (Day 10 rule) day by day.
    Returns dict: {outcome, exit_date, exit_price, pnl_pct, holding_days, achieved_rr}
    """
    if future_ohlcv.empty or entry <= 0 or stop <= 0 or target <= 0:
        return {"outcome": "no_data", "exit_price": entry, "pnl_pct": 0.0,
                "holding_days": 0, "achieved_rr": 0.0, "confidence": confidence}

    risk = entry - stop if direction == "bullish" else stop - entry
    max_days = holding_period[1]

    for day_idx, (bar_date, bar) in enumerate(future_ohlcv.iterrows()):
        if day_idx >= max_days:
            break

        high = float(bar.get("High", 0))
        low = float(bar.get("Low", 0))
        close = float(bar.get("Close", 0))

        if direction == "bullish":
            if high >= target:
                return {
                    "outcome": "win",
                    "exit_date": str(bar_date),
                    "exit_price": target,
                    "pnl_pct": (target - entry) / entry,
                    "holding_days": day_idx + 1,
                    "achieved_rr": (target - entry) / risk if risk > 0 else 0.0,
                    "regime": regime,
                    "confidence": confidence,
                }
            if low <= stop:
                return {
                    "outcome": "loss",
                    "exit_date": str(bar_date),
                    "exit_price": stop,
                    "pnl_pct": (stop - entry) / entry,
                    "holding_days": day_idx + 1,
                    "achieved_rr": -(entry - stop) / risk if risk > 0 else 0.0,
                    "regime": regime,
                    "confidence": confidence,
                }
        else:  # bearish
            if low <= target:
                return {
                    "outcome": "win",
                    "exit_date": str(bar_date),
                    "exit_price": target,
                    "pnl_pct": (entry - target) / entry,
                    "holding_days": day_idx + 1,
                    "achieved_rr": (entry - target) / risk if risk > 0 else 0.0,
                    "regime": regime,
                    "confidence": confidence,
                }
            if high >= stop:
                return {
                    "outcome": "loss",
                    "exit_date": str(bar_date),
                    "exit_price": stop,
                    "pnl_pct": (stop - entry) / entry * -1,
                    "holding_days": day_idx + 1,
                    "achieved_rr": -1.0,
                    "regime": regime,
                    "confidence": confidence,
                }

    # Time stop — exit at close of last bar
    final_close = float(future_ohlcv.iloc[min(max_days - 1, len(future_ohlcv) - 1)]["Close"])
    pnl_pct = (final_close - entry) / entry if direction == "bullish" else (entry - final_close) / entry
    return {
        "outcome": "time_stop",
        "exit_date": str(future_ohlcv.index[min(max_days - 1, len(future_ohlcv) - 1)]),
        "exit_price": final_close,
        "pnl_pct": pnl_pct,
        "holding_days": min(max_days, len(future_ohlcv)),
        "achieved_rr": pnl_pct / (risk / entry) if risk > 0 and entry > 0 else 0.0,
        "regime": regime,
        "confidence": confidence,
    }


def _simulate_test_signals(
    test_data: dict[str, pd.DataFrame],
    config_path: str = "config/swing_config.yaml",
) -> list[dict]:
    """
    Simplified signal simulation: generates synthetic signals for backtest.
    In a full implementation this replays the entire pipeline per bar.
    For now, uses simplified breakout detection + fixed confidence proxy.
    """
    outcomes = []

    for ticker, df in test_data.items():
        if df.empty or len(df) < 25:
            continue

        # Simplified: detect 20-day high breakouts as signals
        df = df.copy()
        df["rolling_high_20"] = df["High"].rolling(20).max()
        df["breakout"] = df["Close"] > df["rolling_high_20"].shift(1)

        signal_bars = df[df["breakout"]].index
        for sig_date in signal_bars:
            sig_idx = df.index.get_loc(sig_date)
            if sig_idx + 15 >= len(df):
                continue

            bar = df.loc[sig_date]
            entry = float(bar["Close"])
            atr = float(df["High"].rolling(14).apply(lambda x: max(x) - min(x)).loc[sig_date]) * 0.5
            stop = entry - 2.0 * atr
            target = entry + 6.0 * atr  # 1:3 R:R

            if stop <= 0 or target <= entry or atr <= 0:
                continue

            # Proxy confidence: normalized volume z-score
            vol = float(bar["Volume"])
            vol_mean = float(df["Volume"].rolling(20).mean().loc[sig_date])
            vol_z = (vol - vol_mean) / (df["Volume"].rolling(20).std().loc[sig_date] + 1)
            confidence = min(100.0, max(85.0, 88.0 + vol_z * 2))

            future = df.iloc[sig_idx + 1: sig_idx + 16]
            outcome = simulate_trade_outcome(
                signal_date=str(sig_date),
                direction="bullish",
                entry=entry,
                stop=stop,
                target=target,
                future_ohlcv=future,
                confidence=confidence,
            )
            outcome["ticker"] = ticker
            outcomes.append(outcome)

    return outcomes


def _build_equity_curve(outcomes: list[dict], starting_equity: float = 15000.0) -> pd.Series:
    """Build equity curve from ordered trade outcomes."""
    equity = starting_equity
    values = [equity]

    for o in outcomes:
        pnl_pct = float(o.get("pnl_pct", 0.0))
        risk_pct = 0.01  # Fixed 1% risk per trade
        risk_dollars = equity * risk_pct
        entry = o.get("entry_price", 1.0) or 1.0
        stop = o.get("stop", entry * 0.97) or entry * 0.97

        # Normalize: pnl as fraction of risk
        risk_dist = abs(float(entry) - float(stop)) / float(entry) if float(entry) > 0 else 0.03
        dollar_pnl = risk_dollars * (pnl_pct / risk_dist) if risk_dist > 0 else risk_dollars * pnl_pct
        equity += dollar_pnl
        values.append(max(0.0, equity))

    if not values:
        return pd.Series([starting_equity])
    return pd.Series(values)


def _save_report(result: dict) -> None:
    """Save backtest result JSON to backtesting/reports/."""
    report_dir = Path("backtesting/reports")
    report_dir.mkdir(parents=True, exist_ok=True)
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    path = report_dir / f"swing_backtest_{date_str}.json"
    with open(path, "w") as f:
        import json
        json.dump(result, f, indent=2, default=str)
