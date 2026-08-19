"""
Paper trade outcome updater. Run each morning (or anytime) to check open paper
trades against recent price action and fill in outcomes.

A signal's entry_zone_lower/upper is a breakout/breakdown trigger price (see
shared/utils/risk_reward.py's compute_entry_zone), not a price the stock is
already at — it's frequently anchored to a rolling high/low that sits away
from the close at signal time. A trade shouldn't start accruing stop/target
risk until price actually trades into that zone, so each open trade first
goes through a fill check (_find_fill): still pending, filled (starts the
stop/target walk from the fill bar), or expired (zone never reached within
FILL_WINDOW_DAYS — no capital was ever really at risk). The first time a
trade's fill is confirmed, fill_date/fill_price get stamped onto its row and
a "PAPER TRADE OPENED" Discord alert fires — the counterpart to the "PAPER
TRADE PENDING" alert paper_runner.py sends when the signal was first logged.

Once filled, checks each bar's High/Low for:
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
from shared.utils.discord_alerts import (
    send_paper_outcome_alert,
    send_paper_expired_alert,
    send_paper_fill_alert,
    send_calibration_alert,
)
from shared.utils.atomic_io import atomic_write_text, exclusive_lock
from swing_model.feedback_loop import (
    load_calibration_outcomes_from_paper_trades,
    run_calibration,
    should_recalibrate,
)
from swing_model.indicator_pipeline import load_config
# Imported, not duplicated — this module previously kept its own copy of the
# column list that had already drifted from paper_runner.py's real schema
# (missing positioning_score, structure_recommended, ev_per_dollar,
# event_gate_blocked, event_gate_trigger). _save_trades' DictWriter runs with
# extrasaction="ignore", so that drift wasn't a KeyError — it was silent data
# loss: the first paper_updater.py run to close *any* trade would rewrite the
# whole CSV and drop those columns from every row, not just the closed one.
# One shared list closes that gap structurally instead of relying on the two
# modules being hand-kept in sync.
from paper_trading.paper_runner import _CSV_COLUMNS, PAPER_TRADES_LOCK_FILE

logger = get_logger(__name__)

PAPER_TRADES_CSV = Path("paper_trading/paper_trades.csv")
MAX_HOLDING_DAYS = 15  # trading days before automatic time stop

# Trading days a breakout/breakdown entry order is allowed to sit unfilled
# before the signal is treated as stale and expired. Deliberately shorter
# than MAX_HOLDING_DAYS — that clock is for a position that's actually on,
# this one is for an order that hasn't triggered yet.
FILL_WINDOW_DAYS = 5


def _load_trades() -> list[dict]:
    if not PAPER_TRADES_CSV.exists():
        logger.warning(f"{PAPER_TRADES_CSV} not found — nothing to update.")
        return []
    with open(PAPER_TRADES_CSV, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _row_key(row: dict) -> tuple:
    """Same (signal_date, ticker) key paper_runner.py's own dedup already
    uses — good enough uniqueness for merge purposes since paper_runner.py
    itself refuses to log a second signal for the same key same-day."""
    return (row.get("signal_date", ""), row.get("ticker", ""))


def _save_trades(trades: list[dict]) -> None:
    """
    Full-file rewrite on every update, atomic and lock-protected.

    update_paper_trades()'s per-ticker yfinance walk between _load_trades()
    and this call can take minutes (real network I/O, one call per open
    ticker) — during that window paper_runner.py can append a brand-new
    signal directly to this same CSV. A naive rewrite from the stale
    in-memory `trades` snapshot would silently erase that row with no error.
    Fixed by re-reading the live file under the lock right before writing
    and merging in any row whose key isn't already in `trades` — the two
    writers never touch the same rows (paper_runner.py only ever appends new
    ones; this function only ever updates existing ones' outcome fields), so
    a key-based merge is safe. The lock itself is held only for this brief
    read-merge-write, not for the multi-minute fetch loop before it —
    paper_runner.py's own appends (equally brief) shouldn't have to wait
    minutes for a scan-time Discord alert to go out.
    """
    with exclusive_lock(PAPER_TRADES_LOCK_FILE, timeout=15.0):
        known_keys = {_row_key(t) for t in trades}
        live_trades = _load_trades()
        merged = list(trades) + [t for t in live_trades if _row_key(t) not in known_keys]

        buf = io.StringIO(newline="")
        writer = csv.DictWriter(buf, fieldnames=_CSV_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(merged)
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
    direction: str = "bullish",
) -> Optional[dict]:
    """
    Walk bars chronologically and return outcome dict when stop, target,
    or time stop is triggered. Returns None if trade is still open.

    Stop is checked before target within each bar (conservative — worst case first).
    Bullish: stop is below entry (loss when price falls to/through it, Low <=
    stop_loss), target is above entry (win when price rises to/through it,
    High >= target). Bearish is the mirror image — stop above entry (loss on
    High >= stop_loss), target below entry (win on Low <= target).
    """
    trading_days = 0
    bearish = direction == "bearish"

    for bar_date, bar in df.iterrows():
        trading_days += 1
        high = float(bar["High"])
        low = float(bar["Low"])
        close = float(bar["Close"])
        open_px = float(bar["Open"])

        stop_hit = (high >= stop_loss) if bearish else (low <= stop_loss)
        if stop_hit:
            # Stop hit — could also check if open gapped through the stop
            exit_px = max(stop_loss, open_px) if bearish else min(stop_loss, open_px)
            return {
                "outcome": "loss",
                "exit_date": bar_date.strftime("%Y-%m-%d"),
                "exit_price": exit_px,
                "holding_days": trading_days,
            }

        target_hit = (low <= target) if bearish else (high >= target)
        if target_hit:
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


def _find_fill(
    df: pd.DataFrame,
    entry_zone_lower: float,
    entry_zone_upper: float,
    direction: str = "bullish",
    window_days: int = FILL_WINDOW_DAYS,
) -> Optional[dict]:
    """
    Walk bars chronologically looking for the first bar where price actually
    trades into the entry zone. Bullish zones sit at/above the close at
    signal time (breakout trigger), so they fill when price rises into them
    (High >= entry_zone_lower); bearish zones sit at/below it (breakdown
    trigger), filling when price falls into them (Low <= entry_zone_upper) —
    same mirroring convention _resolve_outcome uses for stop/target.

    Returns:
      {"fill_date": Timestamp, "fill_price": float, "bars_from_fill": df from
        that bar onward} on fill
      {"expired": True, "last_date": Timestamp} if window_days pass with no fill
      None if still inside the window and not filled yet (caller should wait)

    fill_price is the boundary that was actually confirmed reached (the
    trigger price), UNLESS the bar's Open already gapped past it — same
    "worse of trigger-vs-open" convention _resolve_outcome already uses for
    a stop hit. Previously the caller used the entry-zone MIDPOINT (a value
    fixed at signal time, a full 0.25xATR away from either boundary by
    default) for every downstream P&L figure regardless of which price this
    function actually confirmed the stock traded at — this closes that gap
    between what was validated and what was priced.
    """
    bearish = direction == "bearish"
    trading_days = 0

    for bar_date, bar in df.iterrows():
        trading_days += 1
        high = float(bar["High"])
        low = float(bar["Low"])
        open_px = float(bar["Open"])

        filled = (low <= entry_zone_upper) if bearish else (high >= entry_zone_lower)
        if filled:
            fill_price = min(entry_zone_upper, open_px) if bearish else max(entry_zone_lower, open_px)
            return {
                "fill_date": bar_date,
                "fill_price": fill_price,
                "bars_from_fill": df[df.index >= bar_date],
            }

        if trading_days >= window_days:
            return {"expired": True, "last_date": bar_date}

    return None  # Still within the fill window, not triggered yet


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

        # Download from day after earliest signal (entry is next session).
        # A same-day signal pushes fetch_from into the future — no bar can
        # possibly exist yet, so skip the doomed yfinance call rather than
        # let it print an ugly "possibly delisted" trace for a ticker that's
        # simply too new to check.
        earliest = min(dates)
        fetch_from_dt = earliest + timedelta(days=1)
        if fetch_from_dt.date() > datetime.now().date():
            logger.info(f"{ticker}: signal is from today — no bars possible yet, skipping")
            continue
        fetch_from = fetch_from_dt.strftime("%Y-%m-%d")
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

            # Defaults to "bullish" for rows logged before this column existed —
            # matches how every trade was actually built at signal time.
            direction = trade.get("direction") or "bullish"
            bearish = direction == "bearish"

            # Only look at bars strictly after the signal date
            signal_dt = pd.Timestamp(signal_date)
            df_after = df[df.index > signal_dt]
            if df_after.empty:
                logger.info(f"{ticker} {signal_date}: no bars after signal yet — still open")
                continue

            # Confirm the breakout/breakdown entry order actually filled before
            # tracking stop/target against it. Older rows logged before these
            # columns existed have no zone to check — fall back to the prior
            # behavior (assume filled from the first bar after signal).
            ez_lower_raw = (trade.get("entry_zone_lower") or "").strip()
            ez_upper_raw = (trade.get("entry_zone_upper") or "").strip()
            bars_for_outcome = df_after
            # Defaults to the zone-midpoint entry_price stored at signal time;
            # replaced below with the price _find_fill actually confirmed the
            # stock traded at, when that check ran. Previously every P&L
            # figure used the midpoint regardless — a fixed value up to
            # 0.25xATR away from the boundary _find_fill validated, so the
            # fill-confirmation check and the P&L basis were silently
            # checking two different price levels.
            pnl_entry_price = entry_price
            if ez_lower_raw and ez_upper_raw:
                try:
                    ez_lower = float(ez_lower_raw)
                    ez_upper = float(ez_upper_raw)
                except ValueError:
                    ez_lower = ez_upper = 0.0

                if ez_lower > 0 and ez_upper > 0:
                    fill = _find_fill(df_after, ez_lower, ez_upper, direction=direction)

                    if fill is None:
                        logger.info(
                            f"{ticker} {signal_date}: entry zone (${ez_lower:.2f}-${ez_upper:.2f}) "
                            f"not reached yet — order still pending"
                        )
                        continue

                    if fill.get("expired"):
                        trade["outcome"] = "expired"
                        trade["exit_date"] = fill["last_date"].strftime("%Y-%m-%d")
                        trade["exit_price"] = ""
                        trade["pnl_pct"] = ""
                        trade["achieved_rr"] = ""
                        trade["holding_days"] = str(FILL_WINDOW_DAYS)
                        trade["pnl_dollars"] = ""

                        logger.info(
                            f"{ticker} {signal_date}: entry zone (${ez_lower:.2f}-${ez_upper:.2f}) "
                            f"never reached within {FILL_WINDOW_DAYS} trading days — expired, no capital ever at risk"
                        )
                        try:
                            send_paper_expired_alert(trade)
                        except Exception as exc:
                            logger.warning(f"{ticker}: paper expired alert failed — {exc}")

                        closed_count += 1
                        continue

                    bars_for_outcome = fill["bars_from_fill"]
                    pnl_entry_price = float(fill["fill_price"])

            # First time this trade's fill is confirmed — whether via the
            # zone check above or the legacy no-zone fallback — stamp it and
            # fire the "now open" alert exactly once. trade["fill_date"]
            # being blank is the only signal we have that this hasn't
            # already fired (nothing else is persisted between runs), so an
            # already-open trade whose fill happened before this column
            # existed gets backfilled — and alerted on — the first time it's
            # checked after this shipped, same as pnl_entry_price always was.
            if not (trade.get("fill_date") or "").strip():
                fill_dt = bars_for_outcome.index[0]
                trade["fill_date"] = fill_dt.strftime("%Y-%m-%d")
                trade["fill_price"] = f"{pnl_entry_price:.2f}"
                try:
                    send_paper_fill_alert(trade, pnl_entry_price, trade["fill_date"])
                except Exception as exc:
                    logger.warning(f"{ticker}: paper fill alert failed — {exc}")

            result = _resolve_outcome(bars_for_outcome, entry_price, stop_loss, target, direction=direction)
            if result is None:
                logger.info(f"{ticker} {signal_date}: still open after {len(df_after)} trading days")
                continue

            # Compute P&L and R multiple. Bearish mirrors bullish throughout:
            # a price move that hurts a long (price falling) is what a short
            # profits from, so price_change flips sign, and risk_per_r is the
            # stop's distance from entry regardless of which side it sits on.
            exit_px = float(result["exit_price"])
            price_change = (pnl_entry_price - exit_px) if bearish else (exit_px - pnl_entry_price)
            risk_per_r = abs(pnl_entry_price - stop_loss)
            pnl_pct = price_change / pnl_entry_price
            achieved_rr = price_change / risk_per_r if risk_per_r > 0 else 0.0

            # Dollar P&L = achieved_rr * the position's actual dollar risk, not
            # a re-derivation of price * shares here. This mirrors
            # trade_selector.py's own convention of pricing every structure off
            # the shared entry/stop/target R:R rather than per-structure option
            # Greeks — an options structure's dollar P&L isn't linear in the
            # underlying's move, but this system doesn't model real option
            # pricing at exit anywhere else either, so achieved_rr * risk keeps
            # this consistent with how EV was ranked, rather than being precise
            # about something nothing else here is precise about either.
            #
            # actual_dollar_risk (position_size * risk_per_unit), not
            # dollar_risk (the pre-cap tier budget) — whenever the 5% capital
            # cap binds tighter than the risk budget, the position actually
            # opened carries less real risk than the budget alone would imply
            # (e.g. AMZN 2026-08-07: $75 budget implied 3 shares, capital cap
            # capped it to 2, real risk $43.14), and booking P&L against the
            # unrealized budget overstates both wins and losses on every
            # capital-capped trade. Falls back to dollar_risk for rows logged
            # before actual_dollar_risk existed in the CSV. Blank (not 0.0)
            # when neither is present — a missing input, not a $0 risk trade.
            actual_risk_raw = (trade.get("actual_dollar_risk") or "").strip()
            dollar_risk_raw = actual_risk_raw or (trade.get("dollar_risk") or "").strip()
            pnl_dollars_str = ""
            if dollar_risk_raw:
                try:
                    pnl_dollars_str = f"{achieved_rr * float(dollar_risk_raw):.2f}"
                except ValueError:
                    pass

            # Update trade dict in-place
            trade["outcome"] = result["outcome"]
            trade["exit_date"] = result["exit_date"]
            trade["exit_price"] = f"{exit_px:.2f}"
            trade["pnl_pct"] = f"{pnl_pct:.4f}"
            trade["achieved_rr"] = f"{achieved_rr:.3f}"
            trade["holding_days"] = str(result["holding_days"])
            trade["pnl_dollars"] = pnl_dollars_str

            logger.info(
                f"{ticker} {signal_date}: {result['outcome']} | exit={exit_px:.2f} | "
                f"pnl={pnl_pct * 100:+.2f}% | {achieved_rr:+.2f}R"
                + (f" | ${float(pnl_dollars_str):+.2f}" if pnl_dollars_str else "") +
                f" | {result['holding_days']}d"
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

    # Expired (entry zone never reached) trades never had capital at risk —
    # exclude them from win-rate/R:R math the same way an open trade is,
    # just report the count separately.
    expired = [t for t in closed if t.get("outcome") == "expired"]
    scored = [t for t in closed if t.get("outcome") != "expired"]

    wins = [t for t in scored if t.get("outcome") == "win"]
    losses = [t for t in scored if t.get("outcome") == "loss"]
    time_stops = [t for t in scored if t.get("outcome") == "time_stop"]
    ts_pos = [t for t in time_stops if float(t.get("pnl_pct", 0)) > 0]

    effective_wins = len(wins) + len(ts_pos)
    win_rate = effective_wins / len(scored) if scored else 0.0

    rr_values = [float(t.get("achieved_rr", 0)) for t in wins]
    avg_rr = sum(rr_values) / len(rr_values) if rr_values else 0.0

    print(f"\n{'=' * 50}")
    print(f"PAPER TRADING SUMMARY  ({len(scored)} closed, {open_ct} open, {len(expired)} expired)")
    print(f"{'=' * 50}")
    print(f"  Win rate (wins + profitable time stops): {win_rate:.1%}")
    print(f"  Target hits:        {len(wins)}")
    print(f"  Stops:              {len(losses)}")
    print(f"  Time stops:         {len(time_stops)}  (+{len(ts_pos)} profitable)")
    print(f"  Avg R:R on wins:    {avg_rr:.2f}R")
    print(f"  Expired (never filled): {len(expired)}")
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
