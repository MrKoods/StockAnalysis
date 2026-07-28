"""
Paper trade outcome updater. Run each morning (or anytime) to check open paper
trades against recent price action and fill in outcomes.

Checks each open trade's High/Low each bar for:
  - Stop hit  → outcome = "loss"   (stop price assumed filled)
  - Target hit → outcome = "win"   (target price assumed filled)
  - 15 trading days elapsed → outcome = "time_stop" (closed at that day's close)

When a trade closes, sends a Discord embed and updates paper_trades.csv in-place.

Usage:
    python -m paper_trading.paper_updater
"""

import csv
import io
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import pandas as pd
import yfinance as yf

from shared.utils.logger import get_logger
from shared.utils.discord_alerts import send_paper_outcome_alert, send_calibration_alert
from shared.utils.atomic_io import atomic_write_text
from swing_model.feedback_loop import (
    load_calibration_outcomes_from_paper_trades,
    run_calibration,
    should_recalibrate,
)
from swing_model.indicator_pipeline import load_config

logger = get_logger(__name__)

PAPER_TRADES_CSV = Path("paper_trading/paper_trades.csv")
MAX_HOLDING_DAYS = 15  # trading days before automatic time stop

_CSV_COLUMNS = [
    "signal_date", "ticker", "confidence",
    "technical_score", "sentiment_score", "news_score", "fundamental_score",
    "regime", "vix_at_signal",
    "rsi_14", "rs_zscore", "mom_5d", "trend_intact",
    "entry_zone_lower", "entry_zone_upper", "entry_price", "stop_loss", "target", "rr_ratio",
    "news_article_count", "dominant_news_theme", "fundamental_data_quality",
    "outcome", "exit_date", "exit_price", "pnl_pct", "achieved_rr", "holding_days",
]


def _load_trades() -> list[dict]:
    if not PAPER_TRADES_CSV.exists():
        logger.warning(f"{PAPER_TRADES_CSV} not found — nothing to update.")
        return []
    with open(PAPER_TRADES_CSV, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _save_trades(trades: list[dict]) -> None:
    # Full-file rewrite on every update — write atomically so a crash or an
    # overlapping run mid-write can't truncate the whole trade history.
    buf = io.StringIO(newline="")
    writer = csv.DictWriter(buf, fieldnames=_CSV_COLUMNS, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(trades)
    atomic_write_text(PAPER_TRADES_CSV, buf.getvalue(), newline="")


def _download_ohlcv(ticker: str, start: str) -> Optional[pd.DataFrame]:
    """Download daily OHLCV from yfinance for ticker starting at start (YYYY-MM-DD)."""
    try:
        df = yf.download(ticker, start=start, auto_adjust=True, progress=False)
        if df.empty:
            return None
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df.index = pd.to_datetime(df.index)
        return df[["Open", "High", "Low", "Close"]].dropna()
    except Exception as exc:
        logger.error(f"{ticker}: yfinance download failed — {exc}")
        return None


def _resolve_outcome(
    df: pd.DataFrame,
    entry_price: float,
    stop_loss: float,
    target: float,
) -> Optional[dict]:
    """
    Walk bars chronologically and return outcome dict when stop, target,
    or time stop is triggered. Returns None if trade is still open.

    Stop is checked before target within each bar (conservative — worst case first).
    """
    trading_days = 0

    for bar_date, bar in df.iterrows():
        trading_days += 1
        high = float(bar["High"])
        low = float(bar["Low"])
        close = float(bar["Close"])

        if low <= stop_loss:
            # Stop hit — could also check if open gapped below stop
            exit_px = min(stop_loss, float(bar["Open"]))
            return {
                "outcome": "loss",
                "exit_date": bar_date.strftime("%Y-%m-%d"),
                "exit_price": exit_px,
                "holding_days": trading_days,
            }

        if high >= target:
            return {
                "outcome": "win",
                "exit_date": bar_date.strftime("%Y-%m-%d"),
                "exit_price": target,
                "holding_days": trading_days,
            }

        if trading_days >= MAX_HOLDING_DAYS:
            return {
                "outcome": "time_stop",
                "exit_date": bar_date.strftime("%Y-%m-%d"),
                "exit_price": close,
                "holding_days": trading_days,
            }

    return None  # Still open


def update_paper_trades() -> int:
    """
    Load open paper trades, check outcomes, update CSV, send Discord alerts.
    Returns count of trades closed this run.
    """
    trades = _load_trades()
    if not trades:
        return 0

    open_trades = [t for t in trades if not t.get("outcome")]
    logger.info(f"{len(open_trades)} open paper trade(s) to check")

    # Group open trades by ticker to minimise yfinance calls
    by_ticker: dict[str, list[dict]] = {}
    for t in open_trades:
        tk = t.get("ticker", "")
        if tk:
            by_ticker.setdefault(tk, []).append(t)

    closed_count = 0

    for ticker, ticker_trades in by_ticker.items():
        # Earliest signal date across this ticker's open trades
        dates = []
        for t in ticker_trades:
            try:
                dates.append(datetime.strptime(t["signal_date"], "%Y-%m-%d"))
            except Exception:
                pass
        if not dates:
            continue

        # Download from day after earliest signal (entry is next session)
        earliest = min(dates)
        fetch_from = (earliest + timedelta(days=1)).strftime("%Y-%m-%d")
        df = _download_ohlcv(ticker, fetch_from)
        if df is None or df.empty:
            logger.warning(f"{ticker}: no price data since {fetch_from} — skipping")
            continue

        for trade in ticker_trades:
            try:
                signal_date = trade["signal_date"]
                entry_price = float(trade.get("entry_price", 0.0))
                stop_loss = float(trade.get("stop_loss", 0.0))
                target = float(trade.get("target", 0.0))
            except (ValueError, KeyError) as exc:
                logger.warning(f"{ticker} {trade.get('signal_date')}: bad numeric field — {exc}")
                continue

            if entry_price <= 0 or stop_loss <= 0 or target <= 0:
                logger.warning(f"{ticker} {signal_date}: invalid entry/stop/target — skipping")
                continue

            # Only look at bars strictly after the signal date
            signal_dt = pd.Timestamp(signal_date)
            df_after = df[df.index > signal_dt]
            if df_after.empty:
                logger.info(f"{ticker} {signal_date}: no bars after signal yet — still open")
                continue

            result = _resolve_outcome(df_after, entry_price, stop_loss, target)
            if result is None:
                logger.info(f"{ticker} {signal_date}: still open after {len(df_after)} trading days")
                continue

            # Compute P&L and R multiple
            exit_px = float(result["exit_price"])
            risk_per_r = entry_price - stop_loss  # positive: distance from entry to stop
            pnl_pct = (exit_px - entry_price) / entry_price
            achieved_rr = (exit_px - entry_price) / risk_per_r if risk_per_r > 0 else 0.0

            # Update trade dict in-place
            trade["outcome"] = result["outcome"]
            trade["exit_date"] = result["exit_date"]
            trade["exit_price"] = f"{exit_px:.2f}"
            trade["pnl_pct"] = f"{pnl_pct:.4f}"
            trade["achieved_rr"] = f"{achieved_rr:.3f}"
            trade["holding_days"] = str(result["holding_days"])

            logger.info(
                f"{ticker} {signal_date}: {result['outcome']} | exit={exit_px:.2f} | "
                f"pnl={pnl_pct * 100:+.2f}% | {achieved_rr:+.2f}R | "
                f"{result['holding_days']}d"
            )

            # Discord alert for this closed trade
            try:
                send_paper_outcome_alert({
                    **trade,
                    "entry_price": entry_price,
                    "exit_price": exit_px,
                    "pnl_pct": pnl_pct,
                    "achieved_rr": achieved_rr,
                    "holding_days": result["holding_days"],
                })
            except Exception as exc:
                logger.warning(f"{ticker}: paper outcome Discord alert failed — {exc}")

            closed_count += 1

    _save_trades(trades)
    logger.info(f"Paper updater complete — {closed_count} trade(s) closed")

    if closed_count > 0:
        _maybe_run_calibration(trades)

    return closed_count


def _maybe_run_calibration(trades: list[dict]) -> None:
    """
    Check whether a feedback-loop calibration pass is due (see
    feedback_loop.should_recalibrate) and, if so, run it against paper
    trading's own closed-trade history. A calibration that passes holdout and
    doesn't need a version bump saves automatically (feedback_loop.run_calibration
    handles that); a failure or a >5pp change needing a version bump is
    surfaced via Discord rather than silently dropped, since that's a human
    decision point. Best-effort throughout — a failure here shouldn't affect
    the trade-outcome update this function's caller cares about.
    """
    try:
        cfg = load_config()
    except Exception as exc:
        logger.warning(f"Could not load config for calibration check — {exc}")
        cfg = {}

    closed_count_total = sum(1 for t in trades if t.get("outcome"))
    if not should_recalibrate(closed_count_total, cfg=cfg):
        return

    try:
        outcomes = load_calibration_outcomes_from_paper_trades()
        result = run_calibration(outcomes=outcomes, cfg=cfg)
    except Exception as exc:
        logger.warning(f"Calibration run failed — {exc}")
        return

    logger.info(f"Calibration check: status={result.get('status')} weights_updated={result.get('weights_updated')}")

    needs_alert = result.get("status") == "fail" or (
        result.get("status") == "pass" and result.get("needs_version_increment")
    )
    if needs_alert:
        try:
            send_calibration_alert(result)
        except Exception as exc:
            logger.warning(f"Calibration Discord alert failed — {exc}")


def print_summary() -> None:
    """Print a quick performance summary of all paper trades to stdout."""
    trades = _load_trades()
    if not trades:
        print("No paper trades found.")
        return

    closed = [t for t in trades if t.get("outcome")]
    open_ct = len(trades) - len(closed)

    if not closed:
        print(f"Paper trades: {len(trades)} total, {open_ct} open, 0 closed")
        return

    wins = [t for t in closed if t.get("outcome") == "win"]
    losses = [t for t in closed if t.get("outcome") == "loss"]
    time_stops = [t for t in closed if t.get("outcome") == "time_stop"]
    ts_pos = [t for t in time_stops if float(t.get("pnl_pct", 0)) > 0]

    effective_wins = len(wins) + len(ts_pos)
    win_rate = effective_wins / len(closed) if closed else 0.0

    rr_values = [float(t.get("achieved_rr", 0)) for t in wins]
    avg_rr = sum(rr_values) / len(rr_values) if rr_values else 0.0

    print(f"\n{'=' * 50}")
    print(f"PAPER TRADING SUMMARY  ({len(closed)} closed, {open_ct} open)")
    print(f"{'=' * 50}")
    print(f"  Win rate (wins + profitable time stops): {win_rate:.1%}")
    print(f"  Target hits:        {len(wins)}")
    print(f"  Stops:              {len(losses)}")
    print(f"  Time stops:         {len(time_stops)}  (+{len(ts_pos)} profitable)")
    print(f"  Avg R:R on wins:    {avg_rr:.2f}R")
    print(f"  Open trades:        {open_ct}")
    print(f"{'=' * 50}\n")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Paper trade outcome updater")
    parser.add_argument("--summary", action="store_true", help="Print performance summary and exit")
    args = parser.parse_args()

    if args.summary:
        print_summary()
    else:
        count = update_paper_trades()
        print_summary()
        print(f"Closed {count} trade(s) this run.")
    sys.exit(0)
