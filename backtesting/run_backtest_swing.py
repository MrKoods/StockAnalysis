import json
from datetime import datetime
from pathlib import Path

import yaml

from backtesting.backtest_engine import BacktestEngine
from backtesting.metrics import generate_report, compute_monthly_breakdown
from shared.utils.logger import get_logger
from swing_model.scoring import SwingScorer
from swing_model.trade_selector import SwingTradeSelector

logger = get_logger(__name__)


def _load_configs() -> tuple[dict, dict]:
    with open("config/swing_config.yaml") as f:
        swing = yaml.safe_load(f)
    with open("config/global_config.yaml") as f:
        global_ = yaml.safe_load(f)
    return swing, global_


def main():
    """Load swing config, run backtest engine with swing scorer/selector, and output metrics report."""
    swing_config, _ = _load_configs()
    bt_cfg = swing_config.get("backtesting", {})

    start_date: str = bt_cfg.get("start_date", "2019-01-01")
    end_date: str = bt_cfg.get("end_date", "2024-12-31")
    min_win_rate: float = bt_cfg.get("min_win_rate", 0.50)
    min_profit_factor: float = bt_cfg.get("min_profit_factor", 1.5)
    max_risk_norm_drawdown: float = bt_cfg.get("max_risk_norm_drawdown", 0.20)

    tickers: list[str] = swing_config["watchlist"]["tickers"]

    scorer = SwingScorer(swing_config)
    selector = SwingTradeSelector(swing_config)
    engine = BacktestEngine(scorer, selector, swing_config)

    logger.info(f"Swing backtest  {start_date} -> {end_date}  tickers={tickers}")
    trades = engine.run(tickers, start_date, end_date)

    if not trades:
        print("\nNo trades generated. Try widening the date range or reviewing scoring thresholds.")
        return

    # Build a simple equity curve (dollar-neutral, compound each trade in sequence)
    equity = 1.0
    equity_curve = [equity]
    for t in sorted(trades, key=lambda x: x["entry_date"]):
        equity *= 1 + t.get("pnl_pct", 0.0)
        equity_curve.append(equity)

    report = generate_report(trades, equity_curve)
    monthly = compute_monthly_breakdown(trades)
    _print_report(report, trades, monthly, start_date, end_date, tickers, min_win_rate, min_profit_factor, max_risk_norm_drawdown)
    _save_report(report, trades, monthly, swing_config)


def _print_report(
    report: dict,
    trades: list[dict],
    monthly: list[dict],
    start_date: str,
    end_date: str,
    tickers: list[str],
    min_win_rate: float,
    min_profit_factor: float,
    max_risk_norm_drawdown: float,
) -> None:
    pf = report["profit_factor"]
    pf_str = f"{pf:.2f}" if pf != float("inf") else "∞"

    print("\n=== Swing Model Backtest Report ===")
    print(f"  Period           : {start_date} -> {end_date}  (6-week max hold)")
    print(f"  Tickers          : {', '.join(tickers)}")
    print(f"  Total trades     : {report['total_trades']}")
    print(f"  Wins / Losses    : {report['winning_trades']} / {report['losing_trades']}")
    print(f"  Win rate         : {report['win_rate']:.1%}   (gate: >{min_win_rate:.0%})")
    print(f"  Profit factor    : {pf_str}    (gate: >{min_profit_factor:.1f})  [gross wins / gross losses]")
    print(f"  Risk-norm DD     : {report['risk_norm_drawdown']:.1%}  (gate: <{max_risk_norm_drawdown:.0%})  [1%-risk-per-trade curve]")
    print(f"  Avg R:R (ref)    : {report['avg_rr']:.2f}")
    print(f"  Raw max DD (ref) : {report['max_drawdown']:.1%}")
    print(f"  Sharpe ratio     : {report['sharpe_ratio']:.2f}")

    passed = (
        report["win_rate"] >= min_win_rate
        and pf >= min_profit_factor
        and report["risk_norm_drawdown"] <= max_risk_norm_drawdown
    )
    print(f"\n  Validation    : {'PASSED' if passed else 'FAILED'}")
    if not passed:
        if report["win_rate"] < min_win_rate:
            print(f"    FAIL  Win rate {report['win_rate']:.1%} < minimum {min_win_rate:.0%}")
        if pf < min_profit_factor:
            print(f"    FAIL  Profit factor {pf_str} < minimum {min_profit_factor:.1f}")
        if report["risk_norm_drawdown"] > max_risk_norm_drawdown:
            print(f"    FAIL  Risk-norm drawdown {report['risk_norm_drawdown']:.1%} > maximum {max_risk_norm_drawdown:.0%}")

    if monthly:
        print("\n  Monthly breakdown:")
        header = f"  {'Month':<9}  {'Trades':>6}  {'Wins':>4}  {'Win %':>6}  {'Avg P&L':>8}"
        print(header)
        print("  " + "-" * (len(header) - 2))
        for m in monthly:
            print(
                f"  {m['month']:<9}  {m['trades']:>6}  {m['wins']:>4}  "
                f"{m['win_rate']:>6.1%}  {m['avg_pnl_pct']*100:>+8.2f}%"
            )

    if trades:
        print("\n  Sample trades (first 10):")
        header = f"  {'Ticker':<6}  {'Entry date':<12}  {'Exit date':<12}  {'Dir':<8}  {'Exit reason':<10}  {'P&L %':>6}  {'R:R':>5}"
        print(header)
        print("  " + "-" * (len(header) - 2))
        for t in trades[:10]:
            print(
                f"  {t['ticker']:<6}  {str(t['entry_date'])[:10]:<12}  "
                f"{str(t.get('exit_date','?'))[:10]:<12}  {t['direction']:<8}  "
                f"{t.get('exit_reason','?'):<10}  {t.get('pnl_pct',0)*100:>+6.1f}%  "
                f"{t.get('realized_rr',0):>5.2f}"
            )


def _save_report(report: dict, trades: list[dict], monthly: list[dict], swing_config: dict) -> None:
    report_dir = Path("backtesting/reports")
    report_dir.mkdir(parents=True, exist_ok=True)
    today = datetime.today().strftime("%Y-%m-%d")
    out = {
        "generated": today,
        "summary": report,
        "monthly_breakdown": monthly,
        "trades": [
            {k: str(v) if hasattr(v, "strftime") else v for k, v in t.items()}
            for t in trades
        ],
    }
    path = report_dir / f"swing_backtest_{today}.json"
    with open(path, "w") as f:
        json.dump(out, f, indent=2)
    logger.info(f"Report saved to {path}")


if __name__ == "__main__":
    main()
