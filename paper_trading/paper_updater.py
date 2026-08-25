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
  - Day time_stop_day (config's signal_decay.time_stop_day, default 10) reached
    with < time_stop_no_progress_pct of the target move captured → outcome =
    "time_stop" early, instead of always riding to the 15-day hold-to-close
  - 15 trading days elapsed → outcome = "time_stop" (closed at that day's close)
  - Still open AND earnings now 0-5 days out for an undefined-risk shares
    position → outcome = "earnings_exit" (flattened at the latest close; see
    _check_earnings_exit — signal-time-only earnings screening otherwise lets
    a trade age into an unhedged earnings print it was never re-checked
    against)

NOT currently active: confidence-decay early exit (_check_confidence_decay_exit
is defined below but not called — see the comment at its would-be call site for
why: rescoring with neutral sentiment/news and zeroed market modifiers produces
a large, mechanical confidence gap unrelated to real deterioration, not a usable
signal yet).

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
    send_daily_summary_alert,
)
from shared.utils.atomic_io import atomic_write_text, exclusive_lock
from swing_model.feedback_loop import (
    load_calibration_outcomes_from_paper_trades,
    run_calibration,
    should_recalibrate,
)
from swing_model.indicator_pipeline import load_config, run_pipeline
from swing_model.position_rescoring import rescore_open_positions
from shared.utils.earnings_calendar import fetch_next_earnings_date, get_earnings_modifier
from shared.utils.fill_simulation import find_fill as _find_fill
from shared.utils.sector_config import get_active_sectors
# Imported, not duplicated — this module previously kept its own copy of the
# column list that had already drifted from paper_runner.py's real schema
# (missing positioning_score, structure_recommended, ev_per_dollar,
# event_gate_blocked, event_gate_trigger). _save_trades' DictWriter runs with
# extrasaction="ignore", so that drift wasn't a KeyError — it was silent data
# loss: the first paper_updater.py run to close *any* trade would rewrite the
# whole CSV and drop those columns from every row, not just the closed one.
# One shared list closes that gap structurally instead of relying on the two
# modules being hand-kept in sync.
from paper_trading.paper_runner import _CSV_COLUMNS, PAPER_TRADES_LOCK_FILE, RANK_TRADES_CSV, RANK_TRADES_LOCK_FILE
from paper_trading.paper_trade_metrics import compute_expired_signal_opportunity_cost, generate_daily_summary

logger = get_logger(__name__)

PAPER_TRADES_CSV = Path("paper_trading/paper_trades.csv")
MAX_HOLDING_DAYS = 15  # trading days before automatic time stop

# Trading days a breakout/breakdown entry order is allowed to sit unfilled
# before the signal is treated as stale and expired. Deliberately shorter
# than MAX_HOLDING_DAYS — that clock is for a position that's actually on,
# this one is for an order that hasn't triggered yet.
FILL_WINDOW_DAYS = 5

# Position types with no capped max loss (trade_selector.py's
# _GAP_RISK_STRUCTURES — long_stock/long_stock_trailing_stop/short_stock all
# collapse to position_type "shares"). Only these get flattened early ahead
# of earnings; a capped-loss options structure's max loss is already known
# and bounded, so there's nothing extra to protect against a gap.
EARNINGS_EXIT_POSITION_TYPES = {"shares"}


def _load_trades(csv_path: Optional[Path] = None) -> list[dict]:
    """
    csv_path (2026-08-24, rank-based parallel paper-trading track): defaults
    to PAPER_TRADES_CSV (today's exact behavior) — pass RANK_TRADES_CSV to
    load the rank track's own ledger instead.
    """
    path = csv_path if csv_path is not None else PAPER_TRADES_CSV
    if not path.exists():
        logger.warning(f"{path} not found — nothing to update.")
        return []
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _row_key(row: dict) -> tuple:
    """Same (signal_date, ticker) key paper_runner.py's own dedup already
    uses — good enough uniqueness for merge purposes since paper_runner.py
    itself refuses to log a second signal for the same key same-day."""
    return (row.get("signal_date", ""), row.get("ticker", ""))


def _save_trades(trades: list[dict], csv_path: Optional[Path] = None, lock_path: Optional[Path] = None) -> None:
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

    csv_path/lock_path (2026-08-24, rank-based parallel paper-trading
    track): default to PAPER_TRADES_CSV/PAPER_TRADES_LOCK_FILE (today's
    exact behavior) — pass RANK_TRADES_CSV/RANK_TRADES_LOCK_FILE to update
    the rank track's own ledger instead.
    """
    path = csv_path if csv_path is not None else PAPER_TRADES_CSV
    lock = lock_path if lock_path is not None else PAPER_TRADES_LOCK_FILE
    with exclusive_lock(lock, timeout=15.0):
        known_keys = {_row_key(t) for t in trades}
        live_trades = _load_trades(path)
        merged = list(trades) + [t for t in live_trades if _row_key(t) not in known_keys]

        buf = io.StringIO(newline="")
        writer = csv.DictWriter(buf, fieldnames=_CSV_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(merged)
        atomic_write_text(path, buf.getvalue(), newline="")


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


def _fmt_dollars(x: float) -> str:
    """
    Format a dollar P&L figure, collapsing float negative-zero (a negative
    R-multiple times a $0 actual_dollar_risk — a sized-to-0, no-real-capital
    trade — evaluates to -0.0, which prints as the misleading "-$0.00")
    down to a plain "0.00".
    """
    if x == 0.0:
        x = 0.0
    return f"{x:.2f}"


def _resolve_outcome(
    df: pd.DataFrame,
    entry_price: float,
    stop_loss: float,
    target: float,
    direction: str = "bullish",
    time_stop_day: int = 10,
    min_progress_pct: float = 0.30,
) -> Optional[dict]:
    """
    Walk bars chronologically and return outcome dict when stop, target,
    or time stop is triggered. Returns None if trade is still open.

    Stop is checked before target within each bar (conservative — worst case first).
    Bullish: stop is below entry (loss when price falls to/through it, Low <=
    stop_loss), target is above entry (win when price rises to/through it,
    High >= target). Bearish is the mirror image — stop above entry (loss on
    High >= stop_loss), target below entry (win on Low <= target).

    Also enforces config's signal_decay.time_stop_day/time_stop_no_progress_pct
    (day-10, <30% of target captured) as an early time_stop, not just the
    day-15 hold-to-close below — previously this rule existed only in config
    and in position_rescoring.py's check_time_stop(), which nothing in this
    automated loop ever called (Signal Integrity Audit finding C.2). Pure
    price check against bars already being walked here, no extra fetch
    needed. time_stop_day=0 disables it (day-15 only).
    """
    trading_days = 0
    bearish = direction == "bearish"
    target_move = (target - entry_price) if not bearish else (entry_price - target)

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

        if time_stop_day and trading_days >= time_stop_day and target_move > 0:
            progress_move = (close - entry_price) if not bearish else (entry_price - close)
            if (progress_move / target_move) < min_progress_pct:
                return {
                    "outcome": "time_stop",
                    "exit_date": bar_date.strftime("%Y-%m-%d"),
                    "exit_price": close,
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


def _resolve_hypothetical_outcome(
    trade: dict, time_stop_day: int, min_progress_pct: float,
) -> bool:
    """
    Entry-zone opportunity cost for an expired (never-filled) signal —
    simulates the trade as if it had been entered immediately at the
    signal-time entry_price instead of waiting for the breakout/breakdown
    trigger, walked against the same stop/target/time-stop rules real trades
    use (_resolve_outcome above). Answers "was requiring the breakout the
    mistake," independent of win-rate, which stays correctly scoped to
    trades that actually resolved for real (see paper_trade_metrics.py's
    compute_signal_accuracy docstring).

    Mutates trade's hypothetical_* fields in place. Returns True once a
    terminal outcome is recorded, False if still unresolved (leaves
    hypothetical_outcome="pending" for a future run to re-check against
    fresh bars) or required inputs are missing. Idempotent to re-run on an
    already-resolved row — callers should skip those first.
    """
    ticker = trade.get("ticker", "")
    signal_date = trade.get("signal_date", "")
    try:
        entry_price = float(trade.get("entry_price") or 0)
        stop_loss = float(trade.get("stop_loss") or 0)
        target = float(trade.get("target") or 0)
    except (TypeError, ValueError):
        return False
    if entry_price <= 0 or stop_loss <= 0 or target <= 0 or not signal_date:
        return False

    direction = trade.get("direction") or "bullish"
    bearish = direction == "bearish"

    df = _download_ohlcv(ticker, signal_date)
    if df is None or df.empty:
        return False
    df_after = df[df.index > pd.Timestamp(signal_date)]
    if df_after.empty:
        return False

    result = _resolve_outcome(
        df_after, entry_price, stop_loss, target, direction=direction,
        time_stop_day=time_stop_day, min_progress_pct=min_progress_pct,
    )
    trade["hypothetical_outcome"] = "pending"
    if result is None:
        return False

    exit_px = float(result["exit_price"])
    price_change = (entry_price - exit_px) if bearish else (exit_px - entry_price)
    risk_per_r = abs(entry_price - stop_loss)
    pnl_pct = price_change / entry_price
    achieved_rr = price_change / risk_per_r if risk_per_r > 0 else 0.0

    # Same actual_dollar_risk basis a real fill would have used — sizing is
    # computed at signal time off this same entry_price regardless of
    # whether the order ever filled (see _CSV_COLUMNS' capital_deployed
    # comment in paper_runner.py), so it's the right risk basis here too.
    actual_risk_raw = (trade.get("actual_dollar_risk") or "").strip()
    dollar_risk_raw = actual_risk_raw or (trade.get("dollar_risk") or "").strip()
    pnl_dollars_str = ""
    if dollar_risk_raw:
        try:
            pnl_dollars_str = _fmt_dollars(achieved_rr * float(dollar_risk_raw))
        except ValueError:
            pass

    trade["hypothetical_outcome"] = result["outcome"]
    trade["hypothetical_exit_date"] = result["exit_date"]
    trade["hypothetical_exit_price"] = f"{exit_px:.2f}"
    trade["hypothetical_pnl_pct"] = f"{pnl_pct:.4f}"
    trade["hypothetical_achieved_rr"] = f"{achieved_rr:.3f}"
    trade["hypothetical_holding_days"] = str(result["holding_days"])
    trade["hypothetical_pnl_dollars"] = pnl_dollars_str

    logger.info(
        f"{ticker} {signal_date}: hypothetical (immediate-fill) outcome "
        f"{result['outcome']} | {achieved_rr:+.2f}R — entry-zone opportunity cost"
    )
    return True


def _update_hypothetical_outcomes(trades: list[dict], time_stop_day: int, min_progress_pct: float) -> int:
    """
    Resolve (or re-check) the hypothetical opportunity-cost simulation for
    every expired trade that hasn't reached a terminal hypothetical outcome
    yet. Separate from the main open_trades loop above — expired rows are
    excluded from that loop's open_trades filter since their real outcome is
    already final, but the hypothetical needs its own independent tracking
    until IT resolves. Returns count newly resolved this run.
    """
    pending = [
        t for t in trades
        if t.get("outcome") == "expired"
        and (t.get("hypothetical_outcome") or "") in ("", "pending")
    ]
    resolved_count = 0
    for trade in pending:
        if _resolve_hypothetical_outcome(trade, time_stop_day, min_progress_pct):
            resolved_count += 1
    return resolved_count


def _check_earnings_exit(
    trade: dict,
    bars: pd.DataFrame,
    earnings_date,
    cfg: Optional[dict] = None,
) -> Optional[dict]:
    """
    Flatten an open, undefined-risk (plain shares) position early once it
    ages into shared.utils.earnings_calendar's own force-defined-risk window
    (0-5 days out) without ever having been re-checked since entry.

    get_earnings_modifier already requires a NEW signal inside that window to
    use a capped-loss structure instead of bare shares — but that check runs
    exactly once, at signal time. A trade signaled 6+ days before earnings
    (allowed to size as plain shares back then) can still be open when
    earnings lands inside its up-to-15-day holding window, and nothing was
    ever re-evaluating it as that window closed. Only called when
    _resolve_outcome already found the trade still open through the latest
    bar, so this can't preempt a stop/target/time-stop that already fired.
    """
    if (trade.get("position_type") or "shares") not in EARNINGS_EXIT_POSITION_TYPES:
        return None
    if earnings_date is None or bars.empty:
        return None

    modifier = get_earnings_modifier(trade.get("ticker", ""), earnings_date, cfg=cfg)
    if not (modifier["force_defined_risk"] or modifier["no_new_trades"]):
        return None

    last_bar_date = bars.index[-1]
    last_close = float(bars.iloc[-1]["Close"])
    return {
        "outcome": "earnings_exit",
        "exit_date": last_bar_date.strftime("%Y-%m-%d"),
        "exit_price": last_close,
        "holding_days": len(bars),
    }


def _fetch_rescore_indicators(ticker: str, sector: Optional[str], cfg: dict, cache: dict) -> Optional[dict]:
    """
    Fetch fresh technical+positioning indicators for one still-open ticker,
    for the confidence-decay early-exit check only (position_rescoring.py's
    early_exit_confidence_drop) — memoized per ticker per run in `cache` so
    a ticker with multiple open rows only costs one fetch.

    Reuses indicator_pipeline.run_pipeline (the same OHLCV+fundamental+
    positioning machinery every other caller uses) rather than a bespoke
    fetch, so the indicators shape rescore_open_positions expects
    ('_positioning_full'/'_positioning_full_bearish' etc.) is guaranteed
    correct by construction. Best-effort: a failure here degrades to "skip
    the early-exit check this run," never to blocking normal stop/target/
    time-stop resolution, which has already run by the time this is called.
    """
    if ticker in cache:
        return cache[ticker]
    indicators = None
    if sector is not None:
        try:
            sector_cfg = get_active_sectors(cfg).get(sector, {})
            benchmark = sector_cfg.get("benchmark", "SMH")
            result = run_pipeline([ticker], benchmark=benchmark, scan_type="post_close", cfg=cfg)
            indicators = result.get(ticker)
        except Exception as exc:
            logger.warning(f"{ticker}: rescore indicator fetch failed — {exc}")
            indicators = None
    cache[ticker] = indicators
    return indicators


def _check_confidence_decay_exit(
    trade: dict,
    ticker: str,
    direction: str,
    bars: pd.DataFrame,
    entry_price: float,
    stop_loss: float,
    target: float,
    cfg: dict,
    ticker_sector_map: dict,
    indicators_cache: dict,
    earnings_date,
    early_exit_drop: float,
) -> Optional[dict]:
    """
    Flatten an open position early if its confidence has cratered post-entry
    (config's signal_decay.early_exit_confidence_drop) — previously this
    config value was only ever read by position_rescoring.py, which nothing
    in this automated loop called, so it had zero effect on any position
    actually being tracked (Signal Integrity Audit finding C.2). Only called
    when _resolve_outcome/_check_earnings_exit already found the trade still
    open through the latest bar, so this can't preempt a stop/target/
    time-stop/earnings-exit that already fired.

    Reuses position_rescoring.rescore_open_positions on a single-position
    list rather than duplicating its confidence-recompute logic — that
    function already honors this position's own stored direction and picks
    the matching positioning mirror (both fixed alongside this wiring; see
    Signal Integrity Audit finding B.2), and already forfeits
    earnings/cross_ticker/regime/seasonality/macro modifiers it has no fresh
    market-context data for (documented in its own docstring), so
    confidence_drop here reflects technical/positioning/fundamental drift
    plus the real earnings_modifier this caller already fetched — not a
    full re-run of entry-time scoring.
    """
    entry_confidence_raw = (trade.get("confidence") or "").strip()
    if not entry_confidence_raw:
        return None

    sector = ticker_sector_map.get(ticker)
    indicators = _fetch_rescore_indicators(ticker, sector, cfg, indicators_cache)
    if indicators is None:
        return None

    try:
        rescored = rescore_open_positions(
            [{
                "ticker": ticker,
                "direction": direction,
                "entry_price": entry_price,
                "confidence": float(entry_confidence_raw),
                "stop_loss": stop_loss,
                "target": target,
                "opened_at_utc": (trade.get("fill_date") or trade.get("signal_date") or ""),
                "highest_close_since_entry": entry_price,
                "lowest_close_since_entry": entry_price,
                "open": True,
            }],
            {ticker: indicators},
            cfg=cfg,
            earnings_date_by_ticker={ticker: earnings_date} if earnings_date is not None else None,
        )
    except Exception as exc:
        logger.warning(f"{ticker}: confidence-decay rescore failed — {exc}")
        return None

    if not rescored or not rescored[0].get("early_exit_flag"):
        return None

    last_bar_date = bars.index[-1]
    last_close = float(bars.iloc[-1]["Close"])
    logger.info(
        f"{ticker} {trade.get('signal_date')}: confidence dropped "
        f"{rescored[0].get('confidence_drop', 0.0):.1f} pts (> {early_exit_drop:.0f}) since entry "
        f"— flattening early at ${last_close:.2f} instead of holding to stop/target/time-stop"
    )
    return {
        "outcome": "early_exit",
        "exit_date": last_bar_date.strftime("%Y-%m-%d"),
        "exit_price": last_close,
        "holding_days": len(bars),
    }


def update_paper_trades(
    csv_path: Optional[Path] = None,
    lock_path: Optional[Path] = None,
    track: str = "threshold",
    run_calibration: bool = True,
) -> int:
    """
    Load open paper trades, check outcomes, update CSV, send Discord alerts.
    Returns count of trades closed this run.

    csv_path/lock_path/track (2026-08-24, rank-based parallel paper-trading
    track): default to PAPER_TRADES_CSV/PAPER_TRADES_LOCK_FILE/"threshold"
    (today's exact behavior) — pass RANK_TRADES_CSV/RANK_TRADES_LOCK_FILE/
    "rank" to run this same update cycle against the rank track's own
    ledger instead. track is threaded through only into Discord alerts
    (fill/outcome/expired), for branding — see discord_alerts.py's
    _TRACK_BRANDING.

    run_calibration: whether a run that closes trades may call
    _maybe_run_calibration() at the end. Defaults True (today's exact
    behavior for the threshold track). The rank-track's daily cycle passes
    False explicitly — see _maybe_run_calibration's docstring for why:
    calibration writes into data/processed/calibrated_weights.json, which
    feeds LIVE SCORING WEIGHTS shared by both tracks (same scoring.py
    engine) — the rank track's very different outcome distribution
    shouldn't silently recalibrate weights the threshold track also
    depends on, at least not until there's real data to have an informed
    opinion about whether it should.
    """
    trades = _load_trades(csv_path)
    if not trades:
        return 0

    open_trades = [t for t in trades if not t.get("outcome")]
    logger.info(f"{len(open_trades)} open paper trade(s) to check")

    try:
        cfg = load_config()
    except Exception as exc:
        logger.warning(f"Could not load config — earnings-exit penalties will use defaults: {exc}")
        cfg = {}

    _decay_cfg = cfg.get("signal_decay", {})
    _time_stop_day = int(_decay_cfg.get("time_stop_day", 10))
    _min_progress_pct = float(_decay_cfg.get("time_stop_no_progress_pct", 0.30))
    # early_exit_confidence_drop is read by _check_confidence_decay_exit,
    # which isn't called below — see the comment at that call site.

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

        # Fetched once per ticker per run, not per trade (PFE-style tickers can
        # have multiple open rows) — only worth the yfinance call at all if
        # something open here could actually act on it (see
        # EARNINGS_EXIT_POSITION_TYPES).
        earnings_date = None
        if any((t.get("position_type") or "shares") in EARNINGS_EXIT_POSITION_TYPES for t in ticker_trades):
            try:
                earnings_date = fetch_next_earnings_date(ticker)
            except Exception as exc:
                logger.warning(f"{ticker}: earnings date fetch failed — {exc}")

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
                        trade["mark_price"] = ""
                        trade["mark_date"] = ""
                        trade["unrealized_rr"] = ""
                        trade["unrealized_pnl_dollars"] = ""

                        logger.info(
                            f"{ticker} {signal_date}: entry zone (${ez_lower:.2f}-${ez_upper:.2f}) "
                            f"never reached within {FILL_WINDOW_DAYS} trading days — expired, no capital ever at risk"
                        )
                        try:
                            send_paper_expired_alert(trade, track=track)
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

                # Re-anchor actual_dollar_risk to the real fill price for
                # shares positions. It was frozen at signal time off the
                # zone-midpoint entry_price (position sizing runs before a
                # fill exists), but achieved_rr/unrealized_rr below are
                # always computed off pnl_entry_price (the real fill) — when
                # the fill lands away from that midpoint, which the fill
                # simulator allows by design, the R-multiple and the dollar
                # figure it gets multiplied by stop sharing the same price
                # basis (seen up to ~30% off on real trades). Share count is
                # fixed at this point, so shares * risk_per_unit is an exact
                # recompute — not an approximation. Options structures'
                # actual_dollar_risk is a defined max-loss/premium figure,
                # not price * contracts, so it's left untouched; that
                # approximation is unrelated to this fix (see the pnl_dollars
                # comment below).
                if trade.get("position_type") == "shares":
                    try:
                        shares = int(trade.get("position_size") or 0)
                        if shares > 0:
                            trade["actual_dollar_risk"] = f"{shares * abs(pnl_entry_price - stop_loss):.2f}"
                    except ValueError:
                        # position_size is always written as str(int) today
                        # (position_sizer.py's contracts_or_shares) — this
                        # branch shouldn't currently fire. If that invariant
                        # ever drifts (e.g. a float-formatted string), fail
                        # visibly rather than silently keeping the stale
                        # signal-time actual_dollar_risk with no trace of why
                        # (2026-08-23 full model audit finding).
                        logger.warning(
                            f"{ticker} {signal_date}: position_size "
                            f"{trade.get('position_size')!r} isn't a plain int — "
                            f"actual_dollar_risk re-anchor skipped, stale value kept"
                        )

                try:
                    send_paper_fill_alert(trade, pnl_entry_price, trade["fill_date"], track=track)
                except Exception as exc:
                    logger.warning(f"{ticker}: paper fill alert failed — {exc}")

            result = _resolve_outcome(
                bars_for_outcome, entry_price, stop_loss, target, direction=direction,
                time_stop_day=_time_stop_day, min_progress_pct=_min_progress_pct,
            )
            if result is None:
                result = _check_earnings_exit(trade, bars_for_outcome, earnings_date, cfg=cfg)
            # _check_confidence_decay_exit is NOT called here — see its
            # docstring. Wired in and tested this same day, then disabled
            # after a live run showed it firing on 7 of 8 open positions in
            # one pass: rescore_open_positions substitutes NEUTRAL sentiment
            # (0) and news (~7.5) for real entry-time values (real sentiment
            # alone is commonly 10-20+ points), and this caller doesn't pass
            # market_modifiers, so real entry-time regime/seasonality/macro
            # modifiers also drop to 0 on rescore — a large, systematic,
            # MECHANICAL confidence gap on nearly every position regardless
            # of real deterioration, not a signal. Left wired (function still
            # defined below, tested by tests/test_position_rescoring_wiring.py)
            # for a future fix that either fetches real sentiment/news/market
            # context here or compares only the technical+positioning+
            # fundamental sub-total on both sides — do not re-enable this
            # call site without one of those first.
            if result is None:
                mark_note = ""
                try:
                    mark_price = float(bars_for_outcome["Close"].iloc[-1])
                    mark_date = bars_for_outcome.index[-1].strftime("%Y-%m-%d")
                    # Same convention as the closed-trade P&L just below
                    # (achieved_rr * actual_dollar_risk, not price_change *
                    # shares) — this system doesn't model real option pricing
                    # anywhere, so an options structure's mark stays
                    # comparable to a shares structure's the same way a
                    # closed trade's pnl_dollars already is.
                    price_change = (pnl_entry_price - mark_price) if bearish else (mark_price - pnl_entry_price)
                    risk_per_r = abs(pnl_entry_price - stop_loss)
                    unrealized_rr = price_change / risk_per_r if risk_per_r > 0 else 0.0
                    actual_risk_raw = (trade.get("actual_dollar_risk") or "").strip()
                    dollar_risk_raw = actual_risk_raw or (trade.get("dollar_risk") or "").strip()
                    unrealized_pnl_dollars = ""
                    if dollar_risk_raw:
                        try:
                            unrealized_pnl_dollars = _fmt_dollars(unrealized_rr * float(dollar_risk_raw))
                        except ValueError:
                            pass
                    trade["mark_price"] = f"{mark_price:.2f}"
                    trade["mark_date"] = mark_date
                    trade["unrealized_rr"] = f"{unrealized_rr:.3f}"
                    trade["unrealized_pnl_dollars"] = unrealized_pnl_dollars
                    if unrealized_pnl_dollars:
                        mark_note = f" | mark={mark_price:.2f} | ${float(unrealized_pnl_dollars):+.2f} ({unrealized_rr:+.2f}R)"
                    else:
                        mark_note = f" | mark={mark_price:.2f}"
                except Exception as exc:
                    logger.warning(f"{ticker} {signal_date}: unrealized P&L calc failed — {exc}")
                logger.info(f"{ticker} {signal_date}: still open after {len(df_after)} trading days{mark_note}")
                continue
            if result["outcome"] == "earnings_exit":
                logger.info(
                    f"{ticker} {signal_date}: earnings inside force-defined-risk window "
                    f"(0-5 days out) for an undefined-risk shares position — flattening early "
                    f"at ${result['exit_price']:.2f} instead of holding through the print"
                )

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
                    pnl_dollars_str = _fmt_dollars(achieved_rr * float(dollar_risk_raw))
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
            trade["mark_price"] = ""
            trade["mark_date"] = ""
            trade["unrealized_rr"] = ""
            trade["unrealized_pnl_dollars"] = ""

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
                }, track=track)
            except Exception as exc:
                logger.warning(f"{ticker}: paper outcome Discord alert failed — {exc}")

            closed_count += 1

    hypothetical_resolved = _update_hypothetical_outcomes(trades, _time_stop_day, _min_progress_pct)
    if hypothetical_resolved:
        logger.info(f"{hypothetical_resolved} hypothetical (entry-zone opportunity cost) outcome(s) resolved")

    _save_trades(trades, csv_path=csv_path, lock_path=lock_path)
    logger.info(f"Paper updater complete — {closed_count} trade(s) closed")

    if closed_count > 0 and run_calibration:
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


def _try_send_daily_summary(csv_path: Optional[Path] = None, track: str = "threshold") -> None:
    """
    Best-effort daily Discord report — open positions, anything closed
    today, pending orders, P&L, and rule-based takeaways (see
    generate_daily_summary's own docstring). Called once per real scheduled
    update_paper_trades() run (paper_updater's own daily task), not on the
    ad hoc --summary CLI path — a manual on-demand check shouldn't also post
    to Discord. Never lets a summary/send failure take down the run that got
    this far; the CSV is already saved by the time this runs.

    csv_path/track (2026-08-24, rank-based parallel paper-trading track):
    default to PAPER_TRADES_CSV/"threshold" (today's exact behavior) — pass
    RANK_TRADES_CSV/"rank" for the rank track's own daily summary instead.
    """
    try:
        summary = generate_daily_summary(csv_path=csv_path)
        send_daily_summary_alert(summary, track=track)
    except Exception as exc:
        logger.warning(f"Daily summary Discord alert failed — {exc}")


def print_summary(csv_path: Optional[Path] = None) -> None:
    """
    Print a quick performance summary of all paper trades to stdout.

    csv_path (2026-08-24, rank-based parallel paper-trading track): defaults
    to PAPER_TRADES_CSV (today's exact behavior) — pass RANK_TRADES_CSV for
    the rank track's own summary instead.
    """
    trades = _load_trades(csv_path)
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
    # Same "closed without hitting stop or target" shape as a time stop —
    # counts as a win by the same pnl_pct > 0 rule, so it doesn't silently
    # drag win_rate down just for landing in the scored denominator without
    # ever entering the wins/ts_pos numerators.
    earnings_exits = [t for t in scored if t.get("outcome") == "earnings_exit"]
    ee_pos = [t for t in earnings_exits if float(t.get("pnl_pct", 0)) > 0]
    # Same "closed without hitting stop or target" shape as a time stop/
    # earnings exit — same profitable-count rule, so it can't silently drag
    # win_rate down just for landing in the scored denominator without ever
    # entering a numerator (same bug this pattern already guards against for
    # time_stop/earnings_exit above).
    early_exits = [t for t in scored if t.get("outcome") == "early_exit"]
    ex_pos = [t for t in early_exits if float(t.get("pnl_pct", 0)) > 0]

    effective_wins = len(wins) + len(ts_pos) + len(ee_pos) + len(ex_pos)
    win_rate = effective_wins / len(scored) if scored else 0.0

    rr_values = [float(t.get("achieved_rr", 0)) for t in wins]
    avg_rr = sum(rr_values) / len(rr_values) if rr_values else 0.0

    print(f"\n{'=' * 50}")
    print(f"PAPER TRADING SUMMARY  ({len(scored)} closed, {open_ct} open, {len(expired)} expired)")
    print(f"{'=' * 50}")
    print(f"  Win rate (wins + profitable time stops/earnings/confidence exits): {win_rate:.1%}")
    print(f"  Target hits:        {len(wins)}")
    print(f"  Stops:              {len(losses)}")
    print(f"  Time stops:         {len(time_stops)}  (+{len(ts_pos)} profitable)")
    print(f"  Earnings exits:     {len(earnings_exits)}  (+{len(ee_pos)} profitable)")
    print(f"  Confidence early exits: {len(early_exits)}  (+{len(ex_pos)} profitable)")
    print(f"  Avg R:R on wins:    {avg_rr:.2f}R")
    print(f"  Expired (never filled): {len(expired)}")
    if expired:
        opp_cost = compute_expired_signal_opportunity_cost(csv_path)
        if opp_cost["resolved_count"]:
            print(
                f"    -> entry-zone opportunity cost: {opp_cost['resolved_count']} resolved "
                f"({opp_cost['pending_count']} still pending), hypothetical win rate "
                f"{opp_cost['hypothetical_win_rate']:.1%}, avg {opp_cost['avg_hypothetical_r']:+.2f}R "
                f"if filled immediately at signal time"
            )
        elif opp_cost["pending_count"]:
            print(f"    -> entry-zone opportunity cost: {opp_cost['pending_count']} still pending resolution")
    print(f"  Open trades:        {open_ct}")

    # Sum of the mark-to-market snapshot paper_updater.py's own run just left
    # on each still-open, filled trade — blank for pending/expired/zero-size
    # rows, so this naturally only totals real open capital at risk.
    marked = [t for t in trades if (t.get("unrealized_pnl_dollars") or "").strip()]
    if marked:
        unrealized_total = sum(float(t["unrealized_pnl_dollars"]) for t in marked)
        print(f"  Open unrealized P&L: ${unrealized_total:+.2f}  ({len(marked)} marked position(s))")

    print(f"{'=' * 50}\n")


def _run_daily_cycle(csv_path: Path, lock_path: Path, track: str, run_calibration: bool) -> int:
    """
    Run one paper-trading track's full daily cycle: resolve outcomes, print
    a summary, send the daily Discord summary. Extracted (2026-08-24,
    rank-based parallel paper-trading track) so __main__ below runs this
    once per track — same logic, different CSV/lock/Discord identity/
    calibration-eligibility — instead of two near-duplicate blocks.
    """
    count = update_paper_trades(csv_path=csv_path, lock_path=lock_path, track=track, run_calibration=run_calibration)
    print_summary(csv_path=csv_path)
    print(f"[{track}] Closed {count} trade(s) this run.")
    _try_send_daily_summary(csv_path=csv_path, track=track)
    return count


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Paper trade outcome updater")
    parser.add_argument("--summary", action="store_true", help="Print performance summary and exit")
    args = parser.parse_args()

    if args.summary:
        print_summary()
        print_summary(csv_path=RANK_TRADES_CSV)
    else:
        # Threshold track first (as before, and the only one allowed to feed
        # calibration); rank track second, with run_calibration=False — see
        # update_paper_trades' own docstring for why. Each wrapped in its
        # own try/except so the two tracks are genuinely independent — an
        # uncaught exception in one (e.g. a yfinance outage mid-walk) must
        # not prevent the other from getting its own chance to run.
        try:
            _run_daily_cycle(PAPER_TRADES_CSV, PAPER_TRADES_LOCK_FILE, "threshold", run_calibration=True)
        except Exception as exc:
            logger.error(f"Threshold track daily cycle failed — {exc}")
        try:
            _run_daily_cycle(RANK_TRADES_CSV, RANK_TRADES_LOCK_FILE, "rank", run_calibration=False)
        except Exception as exc:
            logger.error(f"Rank track daily cycle failed — {exc}")
    sys.exit(0)
