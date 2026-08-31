"""
Paper trading signal runner. Run post-close each session day to detect qualifying
signals (confidence >= CONFIDENCE_THRESHOLD, see swing_model/scoring.py) and log
them to paper_trading/paper_trades.csv.

Records every layer's raw scores, regime state, and trade parameters so the paper
trading period produces a rich dataset for model calibration.

Does NOT enforce circuit breakers or position size limits — all qualifying signals
are logged regardless of portfolio state, giving an unfiltered view of model accuracy.

Discord alerts fire separately from the live model alerts (different embed format,
clearly labeled as paper trading).

Usage:
    python -m paper_trading.paper_runner
    python -m paper_trading.paper_runner --scan-type post_close
"""

import argparse
import csv
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

# Load .env before any imports that read environment variables
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from app_ui import db as app_db
from swing_model.indicator_pipeline import run_pipeline, load_config
from swing_model.sentiment_layer import compute_sentiment_score, classify_dominant_sentiment
from swing_model.news_layer import compute_news_score
from swing_model.scoring import (
    compute_confidence_score, CONFIDENCE_THRESHOLD, determine_direction,
    TECHNICAL_MAX, SENTIMENT_MAX, NEWS_MAX,
)
from swing_model.feedback_loop import load_live_weights_if_calibrated
from swing_model.win_probability_calibration import load_calibration
from shared.utils.risk_reward import compute_entry_zone, compute_stop_loss, compute_target, compute_rr_ratio
from shared.utils.regime_detection import get_regime_modifiers
from shared.utils.position_sizer import compute_position_size, derive_sizing_inputs
from shared.utils.sector_rotation import dampen_rotation_penalty_for_leader, get_rotation_modifier, ROTATION_NEUTRAL
from shared.utils.earnings_calendar import get_earnings_modifier
from shared.utils.seasonality import get_seasonality_modifier
from shared.utils.logger import get_logger, write_validation_entry
from shared.utils.discord_alerts import send_paper_signal_alert, send_near_miss_alert
from shared.utils.robust_stats import robust_z_score, DEFAULT_OUTLIER_THRESHOLD
from shared.utils.scan_lock import acquire_scan_lock
from shared.utils.price_source_comparison import log_price_source_comparison
from shared.utils.atomic_io import exclusive_lock
from swing_model.trade_selector import rank_trade_structures
from swing_model.cross_ticker_analysis import get_cross_ticker_modifier_for_direction
from shared.utils.regime_detection import REGIME_HIGH_VOL
from shared.utils.event_gate import (
    load_gate_state, save_gate_state, is_ticker_blocked, add_block,
    has_active_block_for_trigger, expire_blocks, is_thesis_opposed,
    was_critical_alert_sent, record_critical_alert,
    SCOPE_SECTOR,
)
from shared.utils.trade_outcomes import OUTCOME_SUPERSEDED
from shared.utils.sector_config import (
    get_news_weight_scale,
    get_active_sectors, get_all_tickers, get_ticker_sector_map, get_sector_tickers,
)
from shared.utils.macro_overlay import (
    dampen_news_china_theme_if_macro_confirmed, save_macro_state, MACRO_ADVERSE,
)
from shared.utils.black_swan_detector import build_black_swan_alert
from shared.utils.geopolitical_risk import apply_geopolitical_penalty

# Reuse all pipeline helpers from run_swing_model to avoid duplication
from swing_model.run_swing_model import (
    _fetch_market_context,
    _check_black_swan_per_sector,
    _try_send_black_swan_alert,
    _compute_regime_safe,
    _compute_macro_safe,
    _compute_china_tension_count,
    _compute_rotation_safe,
    _compute_cross_ticker_safe,
    _fetch_stocktwits_safe,
    _fetch_sa_engagement_safe,
    _fetch_av_news_safe,
    _should_fetch_av_confirmation,
    _fetch_yahoo_news_safe,
    _fetch_finnhub_news_safe,
    _fetch_sec_edgar_safe,
    _compute_sector_context_filings,
    _fetch_earnings_safe,
    get_model_version,
    _try_send_event_gate_alert,
    _try_send_event_gate_expired_alert,
    _write_event_gate_audit,
    _handle_open_position_critical_event,
)

logger = get_logger(__name__)

PAPER_TRADES_CSV = Path("paper_trading/paper_trades.csv")
# Shared with paper_updater.py's _save_trades — both processes touch this
# same CSV (this module appends new signals; paper_updater.py rewrites the
# whole file to fill in outcomes) and must serialize around it, or an update
# run's multi-minute yfinance walk can silently lose a signal appended here
# mid-run when it does its final rewrite. See paper_updater._save_trades'
# docstring for the full mechanism.
PAPER_TRADES_LOCK_FILE = Path("paper_trading/paper_trades.csv.lock")
# Rank-based parallel paper-trading track (2026-08-24) — own ledger, own
# lock file, same _CSV_COLUMNS schema. Independent of PAPER_TRADES_CSV in
# every way: own duplicate-position guard, own simulated $15k capital pool,
# own Discord identity (see discord_alerts.py's _TRACK_BRANDING). See
# CHANGELOG v2.2.96/v2.2.97 for why this track exists — the 70+ threshold
# track's qualifying trades are too rare to build a real dataset from in any
# reasonable timeframe.
RANK_TRADES_CSV = Path("paper_trading/rank_trades.csv")
RANK_TRADES_LOCK_FILE = Path("paper_trading/rank_trades.csv.lock")
CONFIG_PATH = Path("config/swing_config.yaml")
# CONFIDENCE_THRESHOLD imported from swing_model.scoring above — used to be its
# own separate literal here (both at 90), which is exactly the kind of drift
# risk that let this and scoring.py's copy silently agree by coincidence
# rather than by construction. Single-sourced there now; see that constant's
# comment for why it's 70, not 90.
NEAR_MISS_THRESHOLD = 65  # awareness-only Discord ping; never logged as a trade — kept just below CONFIDENCE_THRESHOLD (70)
# Below CONFIDENCE_THRESHOLD, still run rank_trade_structures() and record its
# output on the ticker_results DB row (trade_structure/expected_value columns)
# for scores in this range — pure research data on Filter 4/5's real behavior
# (see CHANGELOG v2.2.22) across a wider score range. Never written to
# paper_trades.csv, never fires the real trade Discord alert, never counts
# toward signals_logged or any go-live gate — CONFIDENCE_THRESHOLD alone still
# decides what's a real qualifying signal.
STRUCTURE_EVAL_DIAGNOSTIC_THRESHOLD = 60

# Maps a layer_scores.layer_name (app_ui/db.py) to the compute_confidence_score()
# result key it comes from — 5 scored categories + 6 modifiers, see App_UI_Scope.md §3.1/§5.
_LAYER_SCORE_FIELDS = {
    "technical": "technical_total",
    "market_positioning": "positioning_total",
    "sentiment": "sentiment_total",
    "news": "news_total",
    "fundamental": "fundamental_score",
    "regime": "regime_modifier",
    "sector_rotation": "sector_rotation_modifier",
    "earnings": "earnings_modifier",
    "cross_ticker": "cross_ticker_modifier",
    "seasonality": "seasonality_modifier",
    "macro_overlay": "macro_modifier",
}

_CSV_COLUMNS = [
    "signal_date", "ticker", "confidence", "direction",
    "technical_score", "positioning_score", "sentiment_score", "news_score", "fundamental_score",
    # The denominator each of the three reweightable scores above was actually
    # graded against (2026-08-26, v2.2.100). When scoring.py's live_weights
    # calibration is active it rescales technical/sentiment/news to the
    # calibrated fraction of their shared 70-point pool, so a category's real
    # ceiling MOVES — deliberately, and deliberately not re-clamped, since
    # re-clamping would break the three-field sum invariant base_score depends
    # on (see scoring.py's "Deliberately NOT re-clamped" note). Without these,
    # a stored score is uninterpretable: AMZN 2026-08-19 logged
    # sentiment_score=26.1 against a nominal max of 15, which reads as a bug
    # and is actually a 0.4 sentiment weight raising the real cap to 28. That
    # calibration was later deleted as invalid (v2.2.89), and because the
    # denominator was never recorded, those rows can't be re-derived from the
    # ledger at all — they're simply not comparable to anything else in it.
    #
    # Only these three: positioning_max/fundamental_max are fixed config
    # constants that calibration never touches (and scoring.py doesn't return
    # them), so they can't drift out from under a row the way these can.
    "technical_max", "sentiment_max", "news_max",
    "regime", "vix_at_signal",
    "rsi_14", "rs_zscore", "mom_5d", "trend_intact",
    "entry_zone_lower", "entry_zone_upper", "entry_price", "stop_loss", "target", "rr_ratio",
    # The reward:risk the trade actually got, measured from its FILL price —
    # stamped by paper_updater.py when the fill is confirmed, blank until then.
    # `rr_ratio` above is frozen at signal time off the zone-midpoint
    # entry_price and the target does not move when the fill lands elsewhere,
    # so the two diverge on almost every real fill (8 of 10 on 2026-08-26,
    # worst case a planned 3.01 that was really 2.00). Kept as a separate
    # column, not an overwrite: `rr_ratio` is what the signal was selected on.
    "rr_ratio_at_fill",
    "news_article_count", "dominant_news_theme", "fundamental_data_quality",
    "structure_recommended", "ev_per_dollar",
    # capital_required is the winning structure's own theoretical dollar risk
    # from rank_trade_structures() — distinct from capital_deployed below,
    # which is that figure after position sizing/tier-budget rounding.
    # structure_legs/structure_effective_days/structure_greeks_summary were
    # already computed by trade_selector.py but discarded before reaching
    # this row until now — see the comment where they're extracted above.
    "capital_required", "structure_legs", "structure_effective_days", "structure_greeks_summary",
    # "applied" | "not_implemented_no_options_chain_data" | blank (no structure
    # evaluated at all) — rank_trade_structures() already computed this per
    # signal but it previously only reached the Discord alert payload, never
    # this row, so there was no way to audit after the fact how often the
    # Greeks check (theta/vega bounds on undefined-risk/short-premium
    # structures) actually ran vs. silently skipped for lack of a live chain.
    "greeks_filter_status",
    # Real dollar max-loss/max-gain (blank = genuinely unbounded, never
    # fabricated), the actual strikes this structure's EV was priced
    # against, and a calendar expiration date (today + effective_days) —
    # all computed by resolve_structure_economics()/trade_selector.py but
    # previously discarded before reaching this row, same as the fields above.
    "structure_max_loss", "structure_max_gain", "structure_strikes", "structure_expiration_date",
    # Top 2 runner-up structures by ev_per_dollar_per_day, excluding the
    # winner — the full ranking already existed in-memory; only the winner
    # ever reached this row before this column.
    "alternative_structures",
    # Position sizing, locked in at signal time against config's starting_capital
    # (position_sizing.starting_capital, $15k by default) — see get_risk_pct's
    # tiers. capital_deployed/dollar_risk are frozen here rather than
    # recomputed later so a trade's sizing can't silently drift if config or
    # the structure ranking changes after the fact.
    "risk_pct", "dollar_risk", "actual_dollar_risk", "position_type", "position_size", "capital_deployed",
    # Why this row sizes to 0, or has no structure_recommended, when it
    # otherwise looks like it should have one — blank when sizing was normal.
    "sizing_note",
    "event_gate_blocked", "event_gate_trigger",
    # Blank until paper_updater.py confirms price actually traded into the
    # entry zone — the signal-time row here is a pending conditional order,
    # not a filled position, until these get set (and the Discord "opened"
    # alert fires exactly once, at that transition).
    "fill_date", "fill_price",
    # Mark-to-market snapshot from paper_updater.py's most recent run, blank
    # until fill and cleared again once the trade closes (outcome fields
    # below take over at that point) — previously there was no persisted way
    # to see how an open position was doing without manually pulling a live
    # quote; only the closing snapshot ever reached this file.
    # unrealized_pnl_dollars mirrors pnl_dollars' own convention below
    # (achieved_rr * actual_dollar_risk, not price_change * shares) so an
    # open position's number is directly comparable to a closed one's.
    "mark_price", "mark_date", "unrealized_rr", "unrealized_pnl_dollars",
    # Outcome fields — blank until paper_updater.py fills them in
    "outcome", "exit_date", "exit_price", "pnl_pct", "achieved_rr", "holding_days", "pnl_dollars",
    # Entry-zone opportunity cost — expired (never-filled) rows only. Simulates
    # the trade as if it had filled immediately at the signal-time entry_price
    # instead of waiting for the breakout/breakdown trigger, walked against the
    # same stop/target/time-stop rules real trades use (paper_updater.py's
    # _resolve_outcome). Answers "was requiring the breakout the mistake,"
    # independent of win-rate — which stays correctly scoped to trades that
    # actually resolved. "pending" until the hypothetical position itself
    # hits stop/target/time-stop; blank for every non-expired row.
    "hypothetical_outcome", "hypothetical_exit_date", "hypothetical_exit_price",
    "hypothetical_pnl_pct", "hypothetical_achieved_rr", "hypothetical_holding_days",
    "hypothetical_pnl_dollars",
]


def _load_logged_keys(csv_path: Optional[Path] = None) -> set[tuple[str, str]]:
    """
    Return set of (signal_date, ticker) pairs already logged.

    csv_path (2026-08-24, rank-based parallel paper-trading track): defaults
    to PAPER_TRADES_CSV (today's exact behavior) — pass RANK_TRADES_CSV to
    scope this to the rank track's own ledger instead. The two tracks never
    share a dedup key set; each only ever sees its own file.
    """
    path = csv_path if csv_path is not None else PAPER_TRADES_CSV
    if not path.exists():
        return set()
    seen: set[tuple[str, str]] = set()
    try:
        with open(path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                seen.add((row.get("signal_date", ""), row.get("ticker", "")))
    except Exception as exc:
        logger.warning(f"Could not read {path}: {exc}")
    return seen


def _load_open_positions(csv_path: Optional[Path] = None) -> set[str]:
    """
    Return set of tickers with an open (outcome blank) row in
    paper_trades.csv — the duplicate-position guard, scoped to paper
    trading's own ledger. Blocks a second signal on a ticker regardless of
    direction: since enable_bearish_signals shipped, nothing previously
    stopped the same ticker carrying simultaneous open bullish AND bearish
    positions (each sized independently off the same fixed account budget) —
    two conflicting-direction signals on one name reads as noisy/uncertain
    signal quality, not a deliberate hedge this model is designed to run
    (Signal Integrity Audit finding C.5).

    Deliberately NOT swing_model/portfolio_manager.py's can_open_new_position()
    + data/processed/position_state.json: that state file belongs to a
    separate, currently-dormant pipeline (run_swing_model.py's own live/Discord
    position tracking, not the daily paper_runner.py path — see
    PROJECT_OVERVIEW.md). CHANGELOG.md v2.2.37 already hit this exact question
    for account-equity tracking and deliberately kept paper trading's state
    out of position_state.json to avoid "silently mixed two unrelated
    pipelines' state" — same reasoning applies here.

    csv_path (2026-08-24, rank-based parallel paper-trading track): defaults
    to PAPER_TRADES_CSV (today's exact behavior) — pass RANK_TRADES_CSV to
    scope this to the rank track's own ledger. The two tracks' duplicate-
    position guards are fully independent by design: a ticker can legitimately
    be open in both simultaneously (even in opposite directions) — that
    divergence is part of what comparing the two tracks is meant to surface.
    """
    path = csv_path if csv_path is not None else PAPER_TRADES_CSV
    if not path.exists():
        return set()
    open_positions: set[str] = set()
    try:
        with open(path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if not (row.get("outcome") or "").strip():
                    open_positions.add(row.get("ticker", ""))
    except Exception as exc:
        logger.warning(f"Could not read {path} for open-position check: {exc}")
    return open_positions


def _load_pending_positions(csv_path: Optional[Path] = None) -> set[str]:
    """
    Return set of tickers whose only open row(s) are still PENDING — logged,
    but the breakout/breakdown entry order never triggered, so no capital was
    ever at risk (blank outcome AND blank fill_date).

    Subset of _load_open_positions(): a ticker with any FILLED open row is
    deliberately absent, even if it also has a pending one. See the
    duplicate-position guard's call site for why the two are treated
    differently — a pending order is a stale opinion and can be replaced, a
    filled position is real exposure and must not be doubled up on.
    """
    path = csv_path if csv_path is not None else PAPER_TRADES_CSV
    if not path.exists():
        return set()
    pending: set[str] = set()
    filled: set[str] = set()
    try:
        with open(path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if (row.get("outcome") or "").strip():
                    continue
                ticker = row.get("ticker", "")
                if (row.get("fill_date") or "").strip():
                    filled.add(ticker)
                else:
                    pending.add(ticker)
    except Exception as exc:
        logger.warning(f"Could not read {path} for pending-position check: {exc}")
    return pending - filled


def _supersede_pending_signals(
    ticker: str,
    today_str: str,
    superseding_confidence: float,
    csv_path: Optional[Path] = None,
    lock_path: Optional[Path] = None,
) -> list[str]:
    """
    Cancel every still-pending row for `ticker`, marking it superseded by a
    newer qualifying signal. Returns the signal_dates actually cancelled.

    Re-checks pending status UNDER THE LOCK rather than trusting the caller's
    earlier snapshot. paper_updater.py can be mid-run while a scan is going,
    and it stamps fill_date onto a row the moment the entry zone trades — so
    a row that was pending when the guard looked can be genuinely filled by
    the time we get here. Cancelling it then would silently close a position
    that has real capital at risk. An empty return means "nothing was
    cancelled", and the caller must treat the ticker as still occupied.
    """
    path = csv_path if csv_path is not None else PAPER_TRADES_CSV
    lock = lock_path if lock_path is not None else PAPER_TRADES_LOCK_FILE
    if not path.exists():
        return []

    superseded: list[str] = []
    with exclusive_lock(lock, timeout=15.0):
        with open(path, newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))

        for row in rows:
            if row.get("ticker") != ticker:
                continue
            if (row.get("outcome") or "").strip():
                continue
            if (row.get("fill_date") or "").strip():
                # Filled between the guard's snapshot and now — real exposure.
                return []
            row["outcome"] = OUTCOME_SUPERSEDED
            row["exit_date"] = today_str
            note = (row.get("sizing_note") or "").strip()
            replacement = (
                f"superseded {today_str} — a newer qualifying signal "
                f"(confidence {superseding_confidence:.1f}) replaced this still-unfilled entry order"
            )
            row["sizing_note"] = f"{note} | {replacement}" if note else replacement
            superseded.append(row.get("signal_date", ""))

        if not superseded:
            return []

        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=_CSV_COLUMNS, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)

    return superseded


def _load_filled_open_positions_detail(sector_tickers: Optional[set[str]] = None) -> list[dict]:
    """
    Ticker/direction/entry/stop/risk_pct for real, FILLED open exposure —
    unlike _load_open_positions() (a bare ticker set used for the
    duplicate-signal guard), this carries enough detail for the Black Swan
    alert's per-position display and the cross-sector concentration check
    (portfolio-wide when sector_tickers is None, one sector's worth when
    given a filter — same underlying data, two different callers). Excludes
    pending-unfilled rows (blank fill_date): an order that hasn't filled yet
    has no real market exposure to warn about. Uses fill_price as the entry
    basis when available (the real price the position was actually
    established at — see the 2026-08-22 dollar-risk-basis-drift fix),
    falling back to the signal's entry_price for the rare pre-that-fix row
    still missing fill_price.
    """
    if not PAPER_TRADES_CSV.exists():
        return []
    positions: list[dict] = []
    try:
        with open(PAPER_TRADES_CSV, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if (row.get("outcome") or "").strip():
                    continue  # already closed
                if sector_tickers is not None and row.get("ticker") not in sector_tickers:
                    continue
                if not (row.get("fill_date") or "").strip():
                    continue  # never filled — no real exposure yet
                try:
                    entry = float(row.get("fill_price") or row.get("entry_price") or 0.0)
                    stop = float(row.get("stop_loss") or 0.0)
                    risk_pct = float(row.get("risk_pct") or 0.0)
                except ValueError:
                    entry = stop = risk_pct = 0.0
                positions.append({
                    "ticker": row.get("ticker", ""),
                    "direction": row.get("direction", "bullish"),
                    "entry_price": entry,
                    "stop_loss": stop,
                    "risk_pct": risk_pct,
                })
    except Exception as exc:
        logger.warning(f"Could not read paper_trades.csv for open-position detail: {exc}")
    return positions


def _append_row(row: dict, csv_path: Optional[Path] = None, lock_path: Optional[Path] = None) -> None:
    """
    Append one signal row to paper_trades.csv, creating header on first write.

    Lock-protected (same lock file as paper_updater.py's _save_trades) —
    without it, an append landing in the middle of paper_updater.py's
    multi-minute update run could be silently wiped out by that run's final
    full-file rewrite. The critical section here is brief either way, so
    this only ever waits for another brief append or for paper_updater.py's
    own (also brief, see its docstring) locked merge-and-write step.

    csv_path/lock_path (2026-08-24, rank-based parallel paper-trading
    track): default to PAPER_TRADES_CSV/PAPER_TRADES_LOCK_FILE (today's
    exact behavior) — pass RANK_TRADES_CSV/RANK_TRADES_LOCK_FILE to append
    to the rank track's own ledger instead.
    """
    path = csv_path if csv_path is not None else PAPER_TRADES_CSV
    lock = lock_path if lock_path is not None else PAPER_TRADES_LOCK_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    with exclusive_lock(lock, timeout=15.0):
        write_header = not path.exists()
        with open(path, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=_CSV_COLUMNS, extrasaction="ignore")
            if write_header:
                writer.writeheader()
            writer.writerow(row)


# ---------------------------------------------------------------------------
# App UI persistence — writes alongside the existing CSV/Discord behavior,
# never in place of it. Every call is wrapped so a DB failure (locked file,
# disk full) never breaks a scan the way it would if this were load-bearing.
# See App_UI_Scope.md §4 — "wrap instead of consolidate."
# ---------------------------------------------------------------------------

def _read_config_snapshot() -> str:
    try:
        return CONFIG_PATH.read_text(encoding="utf-8")
    except Exception as exc:
        logger.warning(f"Could not read {CONFIG_PATH} for config_snapshot: {exc}")
        return ""


def _db_create_scan_run_safe(scan_type: str, config_snapshot: str) -> Optional[int]:
    try:
        return app_db.create_scan_run(scan_type, config_snapshot)
    except Exception as exc:
        logger.warning(f"app_ui DB: could not create scan_run — {exc}")
        return None


def _db_insert_ticker_result_safe(
    run_id: Optional[int],
    ticker: str,
    category: str,
    composite_score: float,
    trade_structure: Optional[str] = None,
    expected_value: Optional[float] = None,
    event_gate_blocked: bool = False,
    event_gate_trigger: Optional[str] = None,
    sector: Optional[str] = None,
    structures_eligible_after_filters: Optional[int] = None,
    exclusion_summary: Optional[str] = None,
    ev_outlier_z: Optional[float] = None,
) -> Optional[int]:
    if run_id is None:
        return None
    try:
        return app_db.insert_ticker_result(
            run_id, ticker, category, composite_score,
            trade_structure=trade_structure, expected_value=expected_value,
            event_gate_blocked=event_gate_blocked, event_gate_trigger=event_gate_trigger,
            sector=sector,
            structures_eligible_after_filters=structures_eligible_after_filters,
            exclusion_summary=exclusion_summary,
            ev_outlier_z=ev_outlier_z,
        )
    except Exception as exc:
        logger.warning(f"app_ui DB: could not insert ticker_result for {ticker} — {exc}")
        return None


def _ev_outlier_z_safe(structure_name: str, ev_value: float) -> Optional[float]:
    """
    robust_z_score(ev_value, <trailing history of this structure's own
    expected_value>) — wrapped the same way every other DB read/write in this
    module is, so a locked/missing DB degrades this diagnostic rather than
    breaking the scan that doesn't depend on it.
    """
    try:
        history = app_db.get_expected_values_for_structure(structure_name)
        return robust_z_score(ev_value, history)
    except Exception as exc:
        logger.warning(f"app_ui DB: could not compute ev_outlier_z for {structure_name} — {exc}")
        return None


def _db_insert_layer_scores_safe(result_id: Optional[int], score: dict) -> None:
    if result_id is None:
        return
    try:
        for layer_name, score_key in _LAYER_SCORE_FIELDS.items():
            app_db.insert_layer_score(result_id, layer_name, score.get(score_key))
    except Exception as exc:
        logger.warning(f"app_ui DB: could not insert layer_scores — {exc}")


def _db_insert_notification_safe(
    run_id: Optional[int],
    ticker: Optional[str],
    alert_type: str,
    payload: dict,
    discord_sent: bool,
) -> None:
    try:
        app_db.insert_notification(
            alert_type, "sent" if discord_sent else "failed",
            run_id=run_id, ticker=ticker, payload=payload,
        )
    except Exception as exc:
        logger.warning(f"app_ui DB: could not insert notification ({alert_type}) — {exc}")


def run_paper_scan(scan_type: str = "post_close") -> int:
    """
    Run the full swing model pipeline and log qualifying signals to paper_trades.csv.
    Returns number of new signals logged this session.

    Guarded by a file lock (shared.utils.scan_lock) so an external scheduler
    relaunching this scan_type before a previous instance finished can't run
    two copies concurrently — see scan_lock.py's module docstring for the
    2026-08-04 incident this exists to stop (post-close restarted from
    scratch every ~5 minutes; retail-sector tickers, processed last in ticker
    order, never survived long enough to be scored, twice in a row). Returns
    0 without doing any work if another instance already holds the lock.
    """
    with acquire_scan_lock(scan_type) as acquired:
        if not acquired:
            logger.warning(
                f"{scan_type}: another instance appears to already be running this scan_type — "
                "skipping this invocation rather than duplicating work and doubling up on the same "
                "rate-limited APIs (see shared/utils/scan_lock.py)."
            )
            return 0
        return _run_paper_scan_locked(scan_type)


def _run_paper_scan_locked(scan_type: str = "post_close") -> int:
    """The actual scan body — see run_paper_scan() for the lock guard around this."""
    cfg = load_config()
    model_version = get_model_version()
    today_str = date.today().isoformat()
    already_logged = _load_logged_keys()
    open_positions = _load_open_positions()
    pending_positions = _load_pending_positions()

    # Rank-based parallel paper-trading track (2026-08-24) — collects every
    # ticker's already-computed scoring context as the main loop below runs,
    # for a second pass AFTER the loop that ranks within each sector and
    # logs the top N regardless of whether they clear CONFIDENCE_THRESHOLD.
    # Reuses this same scan's already-fetched data (StockTwits/Seeking
    # Alpha/news are NOT re-fetched) — see _run_rank_track's own docstring.
    # (open positions for this track are loaded inside _run_rank_track itself,
    # not here — this pass only needs to stash scoring context.)
    rank_track_candidates: list[dict] = []

    # app_ui DB — one scan_runs row per invocation; every ticker_result and
    # notification below is tagged with this run_id. run_id is None if the DB
    # write itself failed, in which case the _db_*_safe helpers all no-op.
    run_id = _db_create_scan_run_safe(scan_type, _read_config_snapshot())

    # Event Severity Gate state — shared with run_swing_model.py's live scans
    # (same real-world tickers, same blocks). See event_gate.expire_blocks for
    # why blocks created in this run must be excluded from this run's expiry.
    gate_state = load_gate_state()
    blocks_created_this_scan: set[str] = set()

    active_sectors = get_active_sectors(cfg)
    watchlist: list[str] = get_all_tickers(cfg)
    ticker_sector_map = get_ticker_sector_map(cfg)
    rr_cfg: dict = cfg.get("risk_reward", {})

    # --- Technical indicators, once per active sector (own benchmark each) ---
    indicators_by_ticker: dict = {}
    for sector_name, sector_cfg in active_sectors.items():
        sector_indicators = run_pipeline(
            sector_cfg.get("tickers", []),
            benchmark=sector_cfg.get("benchmark", "SMH"),
            scan_type=scan_type, cfg=cfg,
        )
        indicators_by_ticker.update(sector_indicators)

    # --- Shared market context (one batch fetch covering every sector benchmark) ---
    mkt = _fetch_market_context(cfg)
    vix_val = float(mkt["vix"]) if mkt["vix"] is not None else 15.0

    # D3 diagnostic (no scoring effect) — yfinance-vs-Seeking-Alpha daily-bar
    # comparison, gated by config price_source_comparison.enabled.
    log_price_source_comparison(mkt.get("ticker_ohlcv", {}), scan_type, cfg)

    # --- Black Swan check — advisory only, per sector (2026-08-23 full model
    # audit: this pipeline — the one actually running 3x/day — had NO crash
    # circuit breaker at all before this; run_swing_model.py had one but it
    # only ever runs there and was scoped to SMH regardless of which sectors
    # were active. See _check_black_swan_per_sector's docstring. ---
    black_swan_results = _check_black_swan_per_sector(active_sectors, mkt, cfg)
    for sector_name, bs_result in black_swan_results.items():
        if bs_result.pop("_newly_triggered", False):
            sector_tickers = set(get_sector_tickers(cfg, sector_name))
            open_positions_for_alert = _load_filled_open_positions_detail(sector_tickers)
            alert_msg = build_black_swan_alert(
                bs_result["trigger_type"], open_positions_for_alert,
                bs_result["smh_pct_change"], bs_result["vix_pct_change"],
            )
            _try_send_black_swan_alert(alert_msg)

    # Regime/rotation/macro/seasonality modifiers computed PER SECTOR — macro's
    # TNX/DXY/China rationale and seasonality's demand calendar are only
    # validated for semiconductors (see macro_overlay._SECTORS_WITH_VALIDATED_
    # MACRO_LOGIC / seasonality's equivalent), so any other sector resolves
    # neutral instead of applying semiconductor-specific logic backwards
    # (e.g. "hawkish rates are adverse" scoring regional banks wrong).
    regime_by_sector: dict[str, str] = {}
    regime_mod_by_sector: dict[str, float] = {}
    rotation_state_by_sector: dict[str, str] = {}
    rotation_mod_by_sector: dict[str, float] = {}
    for sector_name in active_sectors:
        bench_df = mkt["sector_benchmark_dfs"].get(sector_name)
        regime = _compute_regime_safe(mkt["vix"], bench_df)
        regime_by_sector[sector_name] = regime
        # Bullish-default values — the per-ticker loop below recomputes both
        # modifiers directly from regime/rotation_state once each ticker's real
        # direction is known (see scoring.py::determine_direction), same
        # pattern as run_swing_model.py.
        regime_mod_by_sector[sector_name] = get_regime_modifiers(regime, cfg).get("regime_modifier", 0.0)
        rotation_result = _compute_rotation_safe(bench_df, mkt["spy_df"], cfg=cfg)
        rotation_state_by_sector[sector_name] = rotation_result.get("rotation_state", ROTATION_NEUTRAL)
        rotation_mod_by_sector[sector_name] = rotation_result.get("confidence_modifier", 0.0)

    # Sector-wide hyperscaler capex context (semiconductors' AMZN/MSFT/GOOGL/
    # META) — fetched once per scan, reused for every ticker in that sector.
    sector_context_filings = _compute_sector_context_filings(active_sectors)

    china_keyword_count = _compute_china_tension_count(cfg) if "semiconductors" in active_sectors else 0

    macro_state_by_sector: dict[str, dict] = {}
    macro_mod_by_sector: dict[str, float] = {}
    for sector_name in active_sectors:
        result = _compute_macro_safe(
            mkt["tnx_series"], mkt["dxy_series"], china_keyword_count, cfg, sector=sector_name
        )
        macro_state_by_sector[sector_name] = result
        macro_mod_by_sector[sector_name] = result.get("confidence_modifier", 0.0)
    # Persist for observability (app UI, debugging) — computed fresh every run
    # regardless, this doesn't feed back into scoring itself. Best-effort: a
    # write failure here shouldn't abort the scan.
    try:
        save_macro_state({"by_sector": macro_state_by_sector})
    except Exception as exc:
        logger.warning(f"Failed to persist macro state — {exc}")

    # Discord visibility for adverse macro conditions (2026-08-24) — same
    # wiring as run_swing_model.py's live scans; send_macro_warning existed,
    # fully built, but nothing ever called it in either path.
    for sector_name, result in macro_state_by_sector.items():
        if result.get("macro_state") == MACRO_ADVERSE:
            try:
                from shared.utils.discord_alerts import send_macro_warning
                send_macro_warning(result, sector=sector_name)
            except Exception as exc:
                logger.warning(f"{sector_name}: macro warning Discord alert failed — {exc}")

    seasonality_mod_by_sector: dict[str, float] = {
        sector_name: get_seasonality_modifier(cfg=cfg, sector=sector_name).get("confidence_modifier", 0.0)
        for sector_name in active_sectors
    }

    # Global weights: non-None only once a real feedback-loop calibration has
    # passed holdout — see load_live_weights_if_calibrated's docstring. Always
    # None today (zero global calibrations run so far, per should_recalibrate's
    # own floor).
    # Per-sector weights: sectors with enough historical data and a fit that
    # passed real holdout validation get their own weights instead of the
    # global default (see backtesting/sector_weight_calibration.py and
    # config's feedback_loop.sector_calibration_enabled kill switch) —
    # computed once per active sector here, not per ticker, since it's the
    # same lookup for every ticker in that sector.
    # Each sector's lookup is direction-aware (bullish/bearish get independently
    # calibrated weights once enough bearish outcomes exist — see
    # backtesting/sector_weight_calibration.py); both are precomputed here since
    # a ticker's real direction isn't known until the per-ticker loop below.
    sector_calibration_enabled = bool(cfg.get("feedback_loop", {}).get("sector_calibration_enabled", True))
    live_weights_by_sector = {
        sector_name: {
            direction: load_live_weights_if_calibrated(
                sector=sector_name if sector_calibration_enabled else None, direction=direction
            )
            for direction in ("bullish", "bearish")
        }
        for sector_name in active_sectors
    }

    # Real backtest-derived (threshold -> win rate) points — see
    # win_probability_calibration.py's module docstring for why
    # confidence/100 alone was never a real probability. None when
    # data/processed/win_probability_calibration.json hasn't been generated
    # yet (backtesting.fit_win_probability_calibration), in which case
    # rank_trade_structures falls back to the old uncalibrated behavior and
    # flags it via win_prob_calibrated=False.
    win_probability_calibration = load_calibration()

    # Cross-ticker analysis, once per sector so pooling stays within-sector.
    cross_ticker: dict = {}
    for sector_name, sector_cfg in active_sectors.items():
        sector_tickers = sector_cfg.get("tickers", [])
        sector_indicators = {t: indicators_by_ticker[t] for t in sector_tickers if t in indicators_by_ticker}
        sector_ohlcv = {t: mkt["ticker_ohlcv"][t] for t in sector_tickers if t in mkt["ticker_ohlcv"]}
        cross_ticker.update(_compute_cross_ticker_safe(sector_indicators, sector_ohlcv, cfg))

    signals_logged = 0
    # One AV cross-reference per (sector, trigger) per scan, not one per ticker
    # — see run_swing_model._should_fetch_av_confirmation (v2.2.117).
    av_sector_confirmed: set[tuple[str, str]] = set()

    for ticker in watchlist:
        # Reset every iteration, before the try block, so a failure on THIS
        # ticker before line ~716 sets it can't leak a stale value from the
        # PREVIOUS ticker's iteration into the except block below (Python
        # doesn't block-scope loop-body variables) — None unambiguously means
        # "no score was computed for this ticker" versus a real 0.0 read.
        final_score = None
        try:
            indicators = indicators_by_ticker.get(ticker)
            if indicators is None:
                logger.debug(f"{ticker}: no indicators — skipped")
                continue


            # This ticker's sector — drives which regime/rotation/macro/
            # seasonality modifier applies.
            sector = ticker_sector_map.get(ticker)
            regime = regime_by_sector.get(sector, "choppy")
            macro_mod = macro_mod_by_sector.get(sector, 0.0)
            seasonality_mod = seasonality_mod_by_sector.get(sector, 0.0)

            # Sentiment — StockTwits crowd sentiment + Seeking Alpha engagement proxy.
            # StockTwits is fetched here (ahead of the rest of scoring below)
            # purely to classify dominant_sentiment — direction must be known
            # BEFORE Sentiment/News/Positioning run, since their bearish-mirrored
            # sub-formulas need it as an input. Full parity with run_swing_model.py.
            stocktwits_messages = _fetch_stocktwits_safe(ticker)
            dominant_sentiment = classify_dominant_sentiment(stocktwits_messages)["dominant_sentiment"]
            direction = determine_direction(indicators, {"dominant_sentiment": dominant_sentiment}, cfg)

            # macro_mod/seasonality_mod above were computed once per sector
            # (bullish-default) — flip sign for bearish now that direction is
            # known, equivalent to (and cheaper than) recomputing per ticker
            # with direction="bearish" (macro_overlay.py/seasonality.py's own
            # direction handling is a pure sign flip of the same underlying
            # state; see Signal Integrity Audit finding B.3).
            if direction == "bearish":
                macro_mod = -macro_mod
                seasonality_mod = -seasonality_mod

            regime_mod = get_regime_modifiers(regime, cfg, direction=direction).get("regime_modifier", 0.0)
            rotation_mod = dampen_rotation_penalty_for_leader(
                get_rotation_modifier(rotation_state_by_sector.get(sector, ROTATION_NEUTRAL), cfg, direction=direction),
                float(indicators.get("rs_zscore", 0.0)),
                direction=direction,
            )

            sa_engagement_items = _fetch_sa_engagement_safe(ticker)
            price_data = {
                "price_change_5d_pct": (
                    indicators.get("close", 1.0) / max(indicators.get("sma_20", 1.0), 0.01) - 1
                )
            }
            sentiment = compute_sentiment_score(
                stocktwits_messages, sa_engagement_items, ticker, price_data, cfg, direction=direction
            )

            # News — Yahoo + Finnhub + Seeking Alpha are the primary sources, on
            # every scan — all free. Alpha Vantage is a confirmation tool, not a
            # routine per-ticker fetch: it's only called when one of the free
            # sources already flagged a critical event for this ticker, to
            # cross-reference it against an independent source immediately
            # rather than scoring on free-source data alone.
            sa_news_articles = [
                {**item, "source": "seekingalpha.com"} for item in sa_engagement_items
            ]
            yahoo_articles = _fetch_yahoo_news_safe(ticker)
            finnhub_articles = _fetch_finnhub_news_safe(ticker)
            sec_edgar_filings = _fetch_sec_edgar_safe(ticker) + sector_context_filings.get(sector, [])
            free_source_articles = sa_news_articles + yahoo_articles + finnhub_articles + sec_edgar_filings
            fetch_av_now = _should_fetch_av_confirmation(
                free_source_articles, ticker, cfg, sector, gate_state, av_sector_confirmed
            )
            av_articles = _fetch_av_news_safe(ticker, scan_type=scan_type, cfg=cfg) if fetch_av_now else []
            news = compute_news_score(
                av_articles, yahoo_articles, ticker, cfg, finnhub_articles=finnhub_articles,
                sector=sector, seeking_alpha_articles=sa_news_articles,
                sec_edgar_filings=sec_edgar_filings, direction=direction,
            )
            # China-tension double-count fix — see macro_overlay.py's
            # dampen_news_china_theme_if_macro_confirmed docstring.
            news = dampen_news_china_theme_if_macro_confirmed(
                news, macro_state_by_sector.get(sector, {}).get("china_tension_level", "normal")
            )

            # Earnings + cross-ticker modifiers
            earnings_info = _fetch_earnings_safe(ticker)
            earnings_date = (earnings_info or {}).get("next_earnings_date")
            earnings_result = get_earnings_modifier(ticker, earnings_date, cfg=cfg)
            earnings_mod = earnings_result.get("confidence_modifier", 0.0)
            # Direction-aware — see run_swing_model.py's matching comment
            # (Signal Integrity Audit follow-up finding).
            ct_mod = get_cross_ticker_modifier_for_direction(cross_ticker.get(ticker, {}), direction, cfg)

            # Fundamental + Positioning (fetched inside run_pipeline, cached in *_state.json).
            # Positioning is pre-scored for both directions (cheap — same cached
            # raw data); select the one matching this ticker's real direction.
            fundamental = indicators.get("_fundamental_full") or {}
            positioning = indicators.get(
                "_positioning_full_bearish" if direction == "bearish" else "_positioning_full"
            ) or {}

            # Event Severity Gate — check for an existing block (from a prior
            # scan) before scoring. Full parity with run_swing_model.py: advisory
            # only, so the signal still surfaces on its own score merits, flagged
            # with event_gate_blocked/trigger for the paper trade log and alert.
            existing_gate_block = is_ticker_blocked(ticker, gate_state)
            event_gate_blocked = existing_gate_block is not None
            event_gate_trigger = existing_gate_block.get("trigger_match") if existing_gate_block else None

            # Full confidence score
            score = compute_confidence_score(
                technical=indicators,
                positioning=positioning,
                sentiment=sentiment,
                news=news,
                regime_modifier=regime_mod,
                sector_rotation_modifier=rotation_mod,
                earnings_modifier=earnings_mod,
                cross_ticker_modifier=ct_mod,
                seasonality_modifier=seasonality_mod,
                macro_modifier=macro_mod,
                cfg=cfg,
                live_weights=live_weights_by_sector.get(sector, {}).get(direction),
                news_weight_scale=get_news_weight_scale(cfg, sector),
                regime=regime,
                fundamental=fundamental,
                event_gate_blocked=event_gate_blocked,
                event_gate_trigger=event_gate_trigger,
                win_probability_calibration=win_probability_calibration,
                direction_override=direction,
            )

            final_score = float(score.get("final_score", 0.0))

            # Geopolitical risk penalty — TSM/ASML per config.geopolitical_risk_tickers.
            # Applied here before structure ranking/threshold check, so every
            # downstream consumer sees the real, penalized score.
            final_score, geo_note = apply_geopolitical_penalty(cfg, ticker, final_score)
            if geo_note:
                score["final_score"] = final_score
                logger.info(f"{ticker}: {geo_note}")

            # Event Severity Gate — process this scan's critical news for this
            # ticker (may block it before it's even logged as a paper signal).
            # Sector-wide triggers block unconditionally; ticker triggers block
            # only when thesis-opposed. Mirrors run_swing_model.py exactly,
            # including updating this scan's own score dict in place so a
            # same-scan critical event can't slip through before its own block
            # is created (see run_swing_model.py for the full rationale).
            for event in news.get("critical_events", []):
                event_scope = event["scope"]
                trigger = event["trigger_match"]

                if event_scope == SCOPE_SECTOR:
                    if not has_active_block_for_trigger(gate_state, trigger, SCOPE_SECTOR):
                        gate_state = add_block(
                            gate_state, tickers=get_sector_tickers(cfg, sector), scope=SCOPE_SECTOR,
                            trigger_headline=event["headline"], trigger_match=trigger,
                            source=event["source"], event_timestamp_utc=event["event_timestamp_utc"],
                        )
                        new_block = gate_state["blocks"][-1]
                        blocks_created_this_scan.add(new_block["id"])
                        gate_discord_sent = _try_send_event_gate_alert(new_block, model_version)
                        _db_insert_notification_safe(
                            run_id, None, "event_gate_triggered", new_block, gate_discord_sent,
                        )
                        _write_event_gate_audit(new_block, model_version, scan_type, triggered=True)
                        score["event_gate_blocked"] = True
                        score["event_gate_trigger"] = trigger
                else:
                    opposed = is_thesis_opposed(event.get("ner_sentiment"), direction)
                    if opposed and not is_ticker_blocked(ticker, gate_state):
                        gate_state = add_block(
                            gate_state, tickers=[ticker], scope=event_scope,
                            trigger_headline=event["headline"], trigger_match=trigger,
                            source=event["source"], event_timestamp_utc=event["event_timestamp_utc"],
                        )
                        new_block = gate_state["blocks"][-1]
                        blocks_created_this_scan.add(new_block["id"])
                        gate_discord_sent = _try_send_event_gate_alert(new_block, model_version)
                        _db_insert_notification_safe(
                            run_id, ticker, "event_gate_triggered", new_block, gate_discord_sent,
                        )
                        _write_event_gate_audit(new_block, model_version, scan_type, triggered=True)
                        score["event_gate_blocked"] = True
                        score["event_gate_trigger"] = trigger

                # Immediate alert for an open position hit by a critical event —
                # does not wait for the daily re-score. Matches run_swing_model.py's
                # equivalent check; previously present only there, not here — a
                # genuine gap, not an intentional live-only design choice (see
                # CHANGELOG). paper trading tracks open positions via its own CSV
                # ledger (_load_open_positions), not swing_model's dormant
                # state["positions"] pipeline — see that function's own docstring
                # for why the two are deliberately kept separate.
                # Fires once per (ticker, trigger, event timestamp), not once
                # per matching event per scan — a critical item lingers in the
                # feed for days, and the unguarded version re-alerted on every
                # one of the day's three scans (MU: ~9 identical 'tariff'
                # alerts/day, 2026-08-24/25). See was_critical_alert_sent.
                if ticker in open_positions and not was_critical_alert_sent(gate_state, ticker, event):
                    _handle_open_position_critical_event({"ticker": ticker}, event, model_version)
                    gate_state = record_critical_alert(gate_state, ticker, event)

            if score.get("event_gate_blocked"):
                logger.info(
                    f"{ticker}: ACTIVE EVENT (trigger='{score.get('event_gate_trigger')}') "
                    f"— signal still logged, flagged for review"
                )

            # Log every ticker's computed score regardless of qualification —
            # otherwise sub-threshold tickers leave no record of what they
            # actually scored, making it impossible to audit the scoring
            # layers on days with zero qualifying signals. Modifiers are
            # included since they're shared across the whole watchlist each
            # scan and are the natural explanation for a uniform day-over-day
            # move in every ticker's score at once.
            # technical_max/sentiment_max/news_max default to the nominal
            # 40/15/15 caps but shift when calibrated live_weights are active
            # (see scoring.py's compute_confidence_score) — showing the
            # nominal cap here even when a category's real ceiling has moved
            # would make a deliberate reweighted score (e.g. sentiment=21.3
            # under a 0.4 sentiment weight, real cap 28) look like a scoring
            # bug instead of the calibrated redistribution it actually is.
            logger.info(
                f"{ticker}: SCORE {final_score:.1f}/100 "
                f"(technical={score.get('technical_total', 0.0):.1f}/{score.get('technical_max', 40.0):.0f}, "
                f"positioning={score.get('positioning_total', 0.0):.1f}/20, "
                f"sentiment={score.get('sentiment_total', 0.0):.1f}/{score.get('sentiment_max', 15.0):.0f}, "
                f"news={score.get('news_total', 0.0):.1f}/{score.get('news_max', 15.0):.0f}, "
                f"fundamental={score.get('fundamental_score', 0.0):.1f}/10 "
                f"as_of={score.get('fundamental_data_as_of') or 'never'}) "
                f"modifiers(regime={score.get('regime_modifier', 0.0):+.1f}, "
                f"macro={score.get('macro_modifier', 0.0):+.1f}, "
                f"sector_rotation={score.get('sector_rotation_modifier', 0.0):+.1f}, "
                f"earnings={score.get('earnings_modifier', 0.0):+.1f}, "
                f"cross_ticker={score.get('cross_ticker_modifier', 0.0):+.1f}, "
                f"seasonality={score.get('seasonality_modifier', 0.0):+.1f}, "
                f"total={score.get('total_modifier', 0.0):+.1f}) "
                f"direction={direction} "
                f"qualifies={'yes' if final_score >= CONFIDENCE_THRESHOLD else 'no'}"
            )

            # regime_modifier and sector_rotation_modifier are both derived
            # from the same underlying SMH price action (regime: SMH vs. its
            # own SMA trend; sector_rotation: SMH return vs. SPY). scoring.py
            # already dedupes this — when the two agree in sign, total_modifier
            # uses whichever has the larger magnitude instead of summing both
            # (see regime_sector_rotation_combined). This log line is now
            # informational only, confirming the dedup fired; it used to warn
            # about an unfixed double-count, which stopped being true once
            # that dedup landed (v2.2.38-42).
            r_mod = score.get("regime_modifier", 0.0)
            sr_mod = score.get("sector_rotation_modifier", 0.0)
            if (r_mod < 0 and sr_mod < 0) or (r_mod > 0 and sr_mod > 0):
                logger.info(
                    f"{ticker}: NOTE — regime ({r_mod:+.1f}) and sector_rotation ({sr_mod:+.1f}) "
                    f"both reflect the same SMH move; deduped to "
                    f"{score.get('regime_sector_rotation_combined', 0.0):+.1f} in total_modifier "
                    f"(larger magnitude used, not summed)"
                )

            # Entry/stop/target + trade structure ranking — computed for any score
            # clearing STRUCTURE_EVAL_DIAGNOSTIC_THRESHOLD (60), not just real
            # qualifying signals (>=CONFIDENCE_THRESHOLD, currently 70). Below
            # threshold this is research data only: recorded on the
            # ticker_results DB row's trade_structure/expected_value columns,
            # never written to paper_trades.csv and never fires the real trade
            # alert — see STRUCTURE_EVAL_DIAGNOSTIC_THRESHOLD's own comment.
            entry_mid = stop_loss = target_px = None
            rr_ratio = 0.0
            structure_recommended = ""
            ev_per_dollar = ""
            structures_eligible = None
            exclusion_summary = None
            greeks_filter_status = None
            ev_outlier_z = None
            capital_required = None
            position_type = None
            structure_legs = ""
            structure_effective_days = ""
            structure_greeks_summary = ""
            structure_max_loss = ""
            structure_max_gain = ""
            structure_strikes = ""
            structure_expiration_date = ""
            alternative_structures = ""
            if final_score >= STRUCTURE_EVAL_DIAGNOSTIC_THRESHOLD:
                close_px = float(indicators.get("close", 0.0))
                atr = float(indicators.get("atr_14", close_px * 0.02))
                # Breakout (rolling high) anchors a bullish entry zone; breakdown
                # (rolling low) anchors a bearish one — see risk_reward.py's
                # module docstring for why bearish mirrors every formula here.
                level = float(indicators.get(
                    "rolling_low_20" if direction == "bearish" else "rolling_high_20", close_px
                ))

                entry_lower, entry_upper = compute_entry_zone(
                    close_px, level, atr,
                    rr_cfg.get("entry_zone_half_width_atr", 0.25),
                    direction=direction,
                )
                entry_mid = (entry_lower + entry_upper) / 2.0
                # high_volume_support/low_volume_area_above (bullish) and their
                # high_volume_resistance/low_volume_area_below mirrors (bearish)
                # come from the same volume-profile nodes technical_common.py
                # already computes for the volume_profile technical sub-signal —
                # anchoring both directions' stop/target to real support/
                # resistance instead of always falling back to the mechanical
                # ATR-multiple/min-R:R number (see risk_reward.py docstrings).
                stop_loss = compute_stop_loss(
                    entry_upper if direction == "bearish" else entry_lower, atr,
                    high_volume_support=indicators.get("high_volume_support"),
                    high_volume_resistance=indicators.get("high_volume_resistance"),
                    stop_atr_multiplier=rr_cfg.get("stop_atr_multiplier", 2.0),
                    min_stop_atr_multiple=rr_cfg.get("min_stop_atr_multiple", 1.0),
                    direction=direction,
                )
                target_px = compute_target(
                    entry_mid, stop_loss,
                    low_volume_area_above=indicators.get("low_volume_area_above"),
                    low_volume_area_below=indicators.get("low_volume_area_below"),
                    min_rr=rr_cfg.get("min_rr_ratio", 3.0), direction=direction,
                    atr_14=atr, holding_days=_TIME_STOP_DAY_DEFAULT,
                    max_target_atr_multiple=rr_cfg.get("max_target_atr_multiple", 2.5),
                )
                rr_ratio = compute_rr_ratio(entry_mid, stop_loss, target_px, direction=direction) if target_px else 0.0

                try:
                    force_defined_risk = earnings_result.get("force_defined_risk", False) or (regime == REGIME_HIGH_VOL)
                    options_raw = positioning.get("_options_raw") or {}
                    trade_result = rank_trade_structures(
                        {
                            "ticker": ticker,
                            "direction": direction,
                            "confidence": final_score,
                            "entry": entry_mid,
                            "entry_mid": entry_mid,
                            "stop_loss": stop_loss,
                            "target": target_px,
                            "atr_14": atr,
                            "force_defined_risk": force_defined_risk,
                        },
                        # Sourced from config, not a duplicated literal — paper trading has
                        # no live, updating account balance (every trade sizes off the same
                        # fixed starting_capital, not equity net of prior wins/losses). This at
                        # least keeps the diagnostic evaluator's starting figure in sync with
                        # config/swing_config.yaml's position_sizing.starting_capital instead
                        # of silently drifting from it if that config value is ever changed.
                        account_equity=float(cfg.get("position_sizing", {}).get("starting_capital", 15000.0)),
                        options_approval_level=int(cfg.get("options_approval_level", 2)),
                        iv_percentile=options_raw.get("iv_percentile", 50.0),
                        option_chain=options_raw.get("chain"),
                        dte=options_raw.get("dte"),
                        atm_iv=options_raw.get("atm_iv"),
                        cfg=cfg,
                        win_probability_calibration=win_probability_calibration,
                    )
                    ranked = trade_result.get("ranked_structures", [])
                    structures_eligible = trade_result.get("structures_eligible_after_filters")
                    exclusion_summary = trade_result.get("exclusion_summary") or None
                    # Surfaced in the Discord alert below so a human reviewing
                    # a recommendation can see when Filter 4 (Greeks) didn't
                    # run at all this scan (chain fetch failed) — previously
                    # only visible in the CSV's structures_eligible/
                    # exclusion_summary, which discord_alerts.py never reads
                    # (Signal Integrity Audit finding D.1).
                    greeks_filter_status = trade_result.get("greeks_filter_status")
                    if ranked:
                        # recommended=True, not ranked[0]: rank_trade_structures sorts
                        # ranked_structures by raw EV-per-day (diagnostic order,
                        # unchanged), but the actual pick can be a lower-ranked
                        # options structure preferred over a higher-ranked gap-risk-
                        # exposed stock structure (long_stock/short_stock/
                        # long_stock_trailing_stop) — see rank_trade_structures'
                        # recommended-selection step. Reading ranked[0] directly
                        # here would silently ignore that preference and always act
                        # on the top EV-per-day structure regardless of gap risk.
                        best = next((s for s in ranked if s.get("recommended")), ranked[0])
                        structure_recommended = best.get("name", "")
                        capital_required = best.get("capital_required")
                        position_type = best.get("position_type")
                        # ev_per_dollar_per_day, not the un-normalized ev_per_dollar_risked —
                        # trade_selector.py now ranks (and picks ranked[0]) on the
                        # per-day metric, so persisting the un-normalized figure here
                        # would silently disagree with which structure was actually
                        # recommended and why.
                        ev_per_dollar = f"{best.get('ev_per_dollar_per_day', 0.0):.5f}"
                        # Previously computed by rank_trade_structures() and immediately
                        # discarded once "best" was picked — only structure_recommended/
                        # ev_per_dollar/capital_required/position_type survived to the
                        # CSV row and Discord alert. legs/effective_days/Greeks are real,
                        # already-computed data (see trade_selector.py's ranked_structures
                        # dict) that a trader reviewing a recommendation has no way to see
                        # without this.
                        structure_legs = str(best.get("legs", "") or "")
                        structure_effective_days = str(best.get("effective_days", "") or "")
                        greeks = best.get("greeks")
                        if greeks and greeks.get("net_greeks"):
                            g = greeks["net_greeks"]
                            structure_greeks_summary = (
                                f"Δ{g.get('delta', 0.0):+.2f} "
                                f"Γ{g.get('gamma', 0.0):+.3f} "
                                f"Θ{g.get('theta', 0.0):+.3f} "
                                f"V{g.get('vega', 0.0):+.3f}"
                            )

                        # max_loss_dollars/max_gain_dollars/strikes: real
                        # dollar figures and the actual strikes this structure's
                        # EV was priced against — computed by
                        # resolve_structure_economics() (options_math.py) and,
                        # same as legs/Greeks above, previously discarded
                        # before reaching the CSV row/Discord alert. None
                        # means genuinely unbounded (never fabricated — see
                        # that function's own per-branch comments).
                        max_loss_val = best.get("max_loss_dollars")
                        max_gain_val = best.get("max_gain_dollars")
                        structure_max_loss = f"{float(max_loss_val):.2f}" if max_loss_val is not None else ""
                        structure_max_gain = f"{float(max_gain_val):.2f}" if max_gain_val is not None else ""
                        strikes_dict = best.get("strikes") or {}
                        structure_strikes = ", ".join(f"{k}={v:.2f}" for k, v in strikes_dict.items())
                        # Actual calendar date, not just a day count — computed
                        # here (not in options_math.py, which stays clock-free)
                        # since this module already has today_str available.
                        eff_days = best.get("effective_days")
                        structure_expiration_date = (
                            (date.today() + timedelta(days=round(eff_days))).isoformat()
                            if eff_days is not None else ""
                        )

                        # Alternatives: the top 2 remaining structures by
                        # ev_per_dollar_per_day (ranked already carries this
                        # order — best isn't always ranked[0], see the
                        # gap-risk-preference comment above, so filter it out
                        # by identity rather than re-sorting). Full ranking
                        # data already exists in-memory; only the winner ever
                        # reached the user before this — "why not #2" was
                        # collapsed into exclusion_summary's counts alone.
                        alternatives = [s for s in ranked if s is not best][:2]
                        alternative_structures = " | ".join(
                            f"{alt.get('name', '')} (${alt.get('ev_per_dollar_per_day', 0.0):.5f}/day, "
                            f"${alt.get('capital_required', 0.0):.2f})"
                            for alt in alternatives
                        )

                        # Statistical outlier check — is this reading in line with
                        # what this same structure has produced historically, or
                        # is it a MU-long_strangle-style anomaly (~8x AVGO/NVDA's
                        # reading on the same structure, same scan)? MAD-based
                        # rather than a fixed multiplier so the bar self-adjusts as
                        # more history accumulates instead of a hand-picked cutoff
                        # (see shared/utils/robust_stats.py).
                        ev_outlier_z = _ev_outlier_z_safe(structure_recommended, float(ev_per_dollar))
                        if ev_outlier_z is not None and abs(ev_outlier_z) >= DEFAULT_OUTLIER_THRESHOLD:
                            logger.info(
                                f"{ticker}: NOTE — {structure_recommended}'s ev_per_dollar_per_day "
                                f"({float(ev_per_dollar):.5f}) is a statistical outlier vs. this "
                                f"structure's own history (z={ev_outlier_z:+.2f}, threshold="
                                f"{DEFAULT_OUTLIER_THRESHOLD}) — worth checking the underlying "
                                f"inputs (ATR/price ratio, IV, dte) before trusting this ranking"
                            )
                except Exception as exc:
                    logger.warning(f"{ticker}: structure ranking failed — {exc}")

            # Moved up from the qualifying (>=70) branch below — computed
            # once, unconditionally, so both that branch AND the rank-track
            # stash right after it can use the same values (2026-08-24).
            news_count = len(av_articles) + len(yahoo_articles) + len(finnhub_articles) + len(sec_edgar_filings)
            dominant_theme = str(news.get("dominant_narrative_theme", "")) if isinstance(news, dict) else ""

            # Rank-based parallel paper-trading track (2026-08-24) — stash
            # this ticker's full computed context, regardless of whether it
            # qualifies/is a duplicate/etc. below. This is the single latest
            # point in the loop where every input pass 2 needs is in scope
            # for every ticker. Deliberately NOT stashing entry_mid/stop_loss/
            # target_px/structure_recommended/capital_required even when
            # already computed above (score >= STRUCTURE_EVAL_DIAGNOSTIC_
            # THRESHOLD, 60): that computation used get_risk_pct(confidence),
            # which returns 0.0 for anything below CONFIDENCE_THRESHOLD (70)
            # — i.e. even a 60-69 scorer's structure was picked with a $0
            # budget (falls through to the diagnostic-only path, not a real
            # budget-fitted pick). Pass 2 needs a DIFFERENT structure
            # selection, computed with the rank track's own flat 3.33%
            # risk_pct_override — reusing pass 1's would silently carry over
            # a structure that was never actually budget-checked. Recomputing
            # entry/stop/target/structure fresh costs nothing extra
            # externally (pure local math + rank_trade_structures, no new
            # API fetches) so there's no real cost to always doing it fresh.
            rank_track_candidates.append({
                "ticker": ticker, "sector": sector, "direction": direction, "regime": regime,
                "final_score": final_score, "score": score, "indicators": indicators,
                "vix_val": vix_val, "news_count": news_count, "dominant_theme": dominant_theme,
                "earnings_result": earnings_result, "positioning": positioning,
            })

            if (today_str, ticker) in already_logged:
                logger.info(
                    f"{ticker}: already logged to the threshold track today — "
                    f"no second threshold signal (still ranked for the rank track)"
                )
                continue

            # Threshold track's same-day dedup. Deliberately checked HERE,
            # immediately after the rank-track stash above, and not at the top
            # of the loop where it used to sit (2026-08-26, v2.2.102).
            #
            # Up there it `continue`d before the stash, so a ticker already
            # logged to paper_trades.csv earlier today never entered the rank
            # track's candidate pool at all — it couldn't be ranked, let alone
            # picked. That silently contradicted _run_rank_track's own
            # "fully independent ... never cross-checked against the threshold
            # track" contract, and it biased the rank track against precisely
            # the STRONGEST names in each sector: the ones good enough to have
            # already qualified outright. Confirmed live on 2026-08-25 — AMGN
            # qualified pre-market at 75.0, and is absent from the entire
            # 47-ticker post-close scoreboard, so healthcare's post-close rank
            # picks were MRK (72.6) and ABT (68.7) with the sector's highest
            # scorer silently ineligible. Gating the rank track to post_close
            # (v2.2.100) made this worse, not better: the rank track now always
            # runs last, which is exactly when the threshold ledger is most
            # populated.
            #
            # Cost of moving it: an already-logged ticker now re-runs this
            # loop's per-ticker fetches instead of short-circuiting. That is
            # unavoidable rather than incidental — a ticker cannot be ranked
            # without a score, and the score needs those fetches. It is also
            # small: only tickers that already produced a qualifying signal
            # TODAY reach here, typically 0-1 a day (2026-08-25: just AMGN),
            # against 47 tickers scanned. The AV fetch stays budget-guarded by
            # free_sources_flag_critical_event either way.
            #
            # Kept ABOVE the sub-threshold branch below rather than moved down
            # beside the duplicate-position guard: that branch fires a
            # near-miss Discord alert, and a ticker that already has a live
            # signal logged today shouldn't also generate a near-miss ping if
            # it happens to slip under 70 on a later scan.

            if final_score < CONFIDENCE_THRESHOLD:
                sub_threshold_category = (
                    app_db.CATEGORY_NEAR_MISS if final_score >= NEAR_MISS_THRESHOLD else app_db.CATEGORY_NO_SIGNAL
                )
                result_id = _db_insert_ticker_result_safe(
                    run_id, ticker, sub_threshold_category, final_score,
                    trade_structure=structure_recommended or None,
                    expected_value=float(ev_per_dollar) if ev_per_dollar else None,
                    event_gate_blocked=bool(score.get("event_gate_blocked", False)),
                    event_gate_trigger=score.get("event_gate_trigger"),
                    sector=sector,
                    structures_eligible_after_filters=structures_eligible,
                    exclusion_summary=exclusion_summary,
                    ev_outlier_z=ev_outlier_z,
                )
                _db_insert_layer_scores_safe(result_id, score)

                if final_score >= NEAR_MISS_THRESHOLD:
                    near_miss_payload = {
                        "ticker": ticker,
                        "confidence": final_score,
                        "direction": direction,
                        "regime": regime,
                        "technical_score": score.get("technical_total", 0.0),
                        "technical_max": score.get("technical_max", 40.0),
                        "positioning_score": score.get("positioning_total", 0.0),
                        "sentiment_score": score.get("sentiment_total", 0.0),
                        "sentiment_max": score.get("sentiment_max", 15.0),
                        "news_score": score.get("news_total", 0.0),
                        "news_max": score.get("news_max", 15.0),
                        "fundamental_score": score.get("fundamental_score", 0.0),
                        "total_modifier": score.get("total_modifier", 0.0),
                    }
                    near_miss_sent = False
                    try:
                        near_miss_sent = send_near_miss_alert(near_miss_payload, model_version=model_version)
                    except Exception as exc:
                        logger.warning(f"{ticker}: near-miss Discord alert failed — {exc}")
                    _db_insert_notification_safe(
                        run_id, ticker, "near_miss", near_miss_payload, near_miss_sent,
                    )
                continue

            # Duplicate-position guard — a ticker already carrying ANY open
            # position (same OR opposite direction) doesn't get a second one
            # logged on top of it. Checked here (not earlier, alongside
            # already_logged) because it only applies to real qualifying
            # signals — near-miss/no-signal rows above are informational
            # only and never touch paper_trades.csv.
            #
            # A PENDING row (logged, never filled) is the exception: it's a
            # stale opinion, not exposure. Its entry zone, stop and target were
            # computed from data that is now days old, and today's signal is
            # the same model's newer read on the same ticker. Cancel the
            # pending order and let the fresh one take its place, rather than
            # letting the stale one keep the slot until it expires.
            if ticker in open_positions:
                if ticker in pending_positions:
                    cancelled = _supersede_pending_signals(
                        ticker, today_str, final_score,
                    )
                    if cancelled:
                        logger.info(
                            f"{ticker}: qualifies ({final_score:.1f}) and had {len(cancelled)} "
                            f"pending (unfilled) signal(s) from {', '.join(cancelled)} — "
                            f"cancelled as superseded, logging the newer signal"
                        )
                        pending_positions.discard(ticker)
                        open_positions.discard(ticker)
                    else:
                        # Filled underneath us since the snapshot — real
                        # exposure now, so the guard applies after all.
                        logger.info(
                            f"{ticker}: qualifies ({final_score:.1f}) but its pending signal "
                            f"filled during this scan — skipped (duplicate-position guard)"
                        )
                        continue
                else:
                    logger.info(
                        f"{ticker}: qualifies ({final_score:.1f}) but already has a filled open "
                        f"position — skipped (duplicate-position guard)"
                    )
                    continue

            qualified_category = (
                app_db.CATEGORY_TRADE_RECOMMENDED if structure_recommended else app_db.CATEGORY_PASSED_NO_TRADE
            )
            result_id = _db_insert_ticker_result_safe(
                run_id, ticker, qualified_category, final_score,
                trade_structure=structure_recommended or None,
                expected_value=float(ev_per_dollar) if ev_per_dollar else None,
                event_gate_blocked=bool(score.get("event_gate_blocked", False)),
                event_gate_trigger=score.get("event_gate_trigger"),
                sector=sector,
                structures_eligible_after_filters=structures_eligible,
                exclusion_summary=exclusion_summary,
                ev_outlier_z=ev_outlier_z,
            )
            _db_insert_layer_scores_safe(result_id, score)

            # news_count/dominant_theme computed earlier now (2026-08-24) —
            # see the rank-track stash comment above the sub-threshold branch.

            # Position sizing, locked in now so it can't drift if config or the
            # structure ranking changes before this trade closes. Calls
            # position_sizer.compute_position_size() with circuit_breaker_
            # state="normal"/consecutive_losses=0 — no-op multipliers, since
            # paper trading deliberately has neither concept (see this
            # module's docstring: "does not enforce circuit breakers or
            # position size limits" — that's about not BLOCKING a signal from
            # being logged, unrelated to the capital cap below, which only
            # shrinks the size *of* a signal that's logged either way).
            # risk_per_unit (passed as capital_required) is capital_required
            # for an options structure (a defined-risk debit trade's max loss
            # == its premium) or the entry-to-stop distance for a bare equity
            # trade — both are "what one unit costs if the stop is hit."
            #
            # Risk-based sizing alone isn't enough: it only asks "how far to
            # my stop," so a tight-stop, low-volatility name can size to an
            # arbitrarily large capital commitment for the same dollar risk as
            # a wide-stop name (this is exactly what happened live — PFE's
            # $1.16 stop sized to $1,676 deployed, 11% of a $15k account, off
            # the same $75 risk budget that gave AMZN a $861 position). This
            # is why per_unit_cost (the full per-share/per-contract dollar
            # cost, not just the risk distance) is passed separately — see
            # compute_position_size's own docstring for the dual-cap formula.
            account_equity = float(cfg.get("position_sizing", {}).get("starting_capital", 15000.0))
            max_capital_pct = float(cfg.get("position_sizing", {}).get("max_capital_pct", 5000 / 15000))
            position_type, risk_per_unit, per_unit_cost = derive_sizing_inputs(
                position_type, capital_required, entry_mid, stop_loss
            )
            sizing = compute_position_size(
                confidence_score=final_score, account_equity=account_equity,
                circuit_breaker_state="normal", capital_required=risk_per_unit,
                max_capital_pct=max_capital_pct, consecutive_losses=0,
                per_unit_cost=per_unit_cost, position_type=position_type,
            )
            risk_pct = sizing["risk_pct"]
            dollar_risk = sizing["dollar_risk"]
            max_capital = sizing["max_capital"]
            position_size = sizing["contracts_or_shares"]
            capital_deployed = sizing["capital_deployed"]
            risk_based_size = sizing["risk_based_size"]
            capital_based_size = sizing["capital_based_size"]
            # Actual dollar risk of the position actually sized — distinct from
            # dollar_risk (the pre-cap tier budget) whenever the capital cap
            # binds tighter than the risk-based size. paper_updater.py uses
            # this, not dollar_risk, to compute pnl_dollars at exit — otherwise
            # a capital-capped trade's realized P&L is booked against a risk
            # budget larger than the position that was actually opened (e.g.
            # AMZN 2026-08-07: capital cap capped it to 2 shares/$43.14 real
            # risk, but pnl_dollars was booked against the full $75 budget).
            actual_dollar_risk = sizing["actual_dollar_risk"]

            # Cross-sector concentration check (2026-08-23 full model audit) —
            # advisory only, consistent with paper trading's deliberate
            # "log every qualifying signal, don't gate on portfolio limits"
            # design (see the position-sizing comment above): this NEVER skips
            # logging the signal, it only notes when doing so would push net
            # directional exposure — summed across ALL open positions in
            # EVERY active sector, not just this ticker's own — past the same
            # 10% advisory threshold portfolio_manager.py already enforces
            # (raised 2026-08-23 from 1.5%, in scale with the position-sizing
            # tier increase) for the (currently unused) live path. Reuses that module's own
            # get_portfolio_delta() rather than re-deriving the math.
            from swing_model.portfolio_manager import get_portfolio_delta, MAX_NET_DIRECTIONAL_DELTA
            _open_for_delta = _load_filled_open_positions_detail()
            _ephemeral_state = {"positions": [
                {"direction": p["direction"], "risk_pct": p["risk_pct"], "open": True}
                for p in _open_for_delta
            ]}
            _current_delta = get_portfolio_delta(_ephemeral_state)
            _new_dir_sign = 1.0 if direction == "bullish" else -1.0
            _projected_delta = _current_delta + risk_pct * _new_dir_sign
            _max_net_delta = float(cfg.get("portfolio", {}).get("max_net_directional_delta", MAX_NET_DIRECTIONAL_DELTA))
            concentration_note = ""
            if abs(_projected_delta) > _max_net_delta:
                concentration_note = (
                    f"cross-sector concentration — logging this brings net directional exposure "
                    f"to {_projected_delta:+.2%} of account risk budget across all open sectors, "
                    f"beyond the {_max_net_delta:.1%} advisory threshold (informational only, "
                    f"paper trading logs every qualifying signal regardless)"
                )

            # sizing_note: persisted to paper_trades.csv itself, not just logged —
            # a signal that qualifies but sizes to 0, or that had zero eligible
            # options structures at all, used to leave no trace of *why* in the
            # ledger (only in the transient app.log line below and the app UI's
            # separate SQLite history), which made a blank structure_recommended/
            # 0-share row look identical to a real data gap and took real
            # forensic effort to explain after the fact. Built once here and
            # reused for both the CSV field and the log line so they can't drift.
            sizing_note_parts = []
            if not structure_recommended and exclusion_summary:
                sizing_note_parts.append(f"no options structure eligible ({exclusion_summary})")
            if position_size == 0:
                binding = "risk budget" if risk_based_size == 0 else "capital cap"
                sizing_note_parts.append(
                    f"signal qualifies but sizes to 0 {position_type} at this account size "
                    f"({binding} was the binding constraint) — not practically tradeable at this account size"
                )
            elif capital_based_size < risk_based_size:
                sizing_note_parts.append(
                    f"capital cap (${max_capital:.2f}, {max_capital_pct:.0%} of account) capped this "
                    f"position at {position_size} {position_type} instead of the {risk_based_size} the "
                    f"${dollar_risk:.2f} risk budget alone would allow"
                )
            if concentration_note:
                sizing_note_parts.append(concentration_note)
            sizing_note = " | ".join(sizing_note_parts)
            if sizing_note:
                logger.info(f"{ticker}: NOTE — {sizing_note}")

            row: dict = {
                "signal_date": today_str,
                "ticker": ticker,
                "direction": direction,
                "confidence": f"{final_score:.1f}",
                "technical_score": f"{score.get('technical_total', 0.0):.1f}",
                "positioning_score": f"{score.get('positioning_total', 0.0):.1f}",
                "sentiment_score": f"{score.get('sentiment_total', 0.0):.1f}",
                "news_score": f"{score.get('news_total', 0.0):.1f}",
                "fundamental_score": f"{score.get('fundamental_score', 0.0):.1f}",
                # Defaults are the nominal caps — what these fields mean when
                # no calibration is active. See _CSV_COLUMNS for why storing
                # them matters.
                "technical_max": f"{float(score.get('technical_max', TECHNICAL_MAX)):.1f}",
                "sentiment_max": f"{float(score.get('sentiment_max', SENTIMENT_MAX)):.1f}",
                "news_max": f"{float(score.get('news_max', NEWS_MAX)):.1f}",
                "regime": regime,
                "vix_at_signal": f"{vix_val:.1f}",
                "rsi_14": f"{float(indicators.get('rsi_14', 0.0)):.1f}",
                "rs_zscore": f"{float(indicators.get('rs_zscore', 0.0)):.3f}",
                "mom_5d": f"{float(indicators.get('mom_5d', 0.0)):.4f}",
                "trend_intact": str(bool(indicators.get("trend_intact", False))),
                "entry_zone_lower": f"{entry_lower:.2f}",
                "entry_zone_upper": f"{entry_upper:.2f}",
                "entry_price": f"{entry_mid:.2f}",
                "stop_loss": f"{stop_loss:.2f}",
                "target": f"{target_px:.2f}" if target_px else "",
                "rr_ratio": f"{rr_ratio:.2f}",
                "news_article_count": str(news_count),
                "dominant_news_theme": dominant_theme,
                "fundamental_data_quality": str(score.get("fundamental_data_quality", "unavailable")),
                "structure_recommended": structure_recommended,
                "ev_per_dollar": ev_per_dollar,
                "capital_required": f"{float(capital_required):.2f}" if capital_required is not None else "",
                "structure_legs": structure_legs,
                "structure_effective_days": structure_effective_days,
                "structure_greeks_summary": structure_greeks_summary,
                "structure_max_loss": structure_max_loss,
                "structure_max_gain": structure_max_gain,
                "structure_strikes": structure_strikes,
                "structure_expiration_date": structure_expiration_date,
                "alternative_structures": alternative_structures,
                "greeks_filter_status": greeks_filter_status or "",
                "risk_pct": f"{risk_pct:.4f}",
                "dollar_risk": f"{dollar_risk:.2f}",
                "actual_dollar_risk": f"{actual_dollar_risk:.2f}",
                "position_type": position_type,
                "position_size": str(position_size),
                "capital_deployed": f"{capital_deployed:.2f}",
                "sizing_note": sizing_note,
                "event_gate_blocked": bool(score.get("event_gate_blocked", False)),
                "event_gate_trigger": score.get("event_gate_trigger", "") or "",
                # Outcome fields filled by paper_updater.py
                "outcome": "",
                "exit_date": "",
                "exit_price": "",
                "pnl_pct": "",
                "achieved_rr": "",
                "holding_days": "",
                "pnl_dollars": "",
            }

            _append_row(row)
            signals_logged += 1
            logger.info(f"{ticker}: PAPER signal logged — confidence {final_score:.1f}")

            # Paper-specific Discord alert (separate from live model alert)
            paper_alert_payload = {
                **row,
                "entry_zone_lower": entry_lower,
                "entry_zone_upper": entry_upper,
                "stop_loss": stop_loss,
                "target": float(target_px) if target_px else 0.0,
                "rr_ratio": rr_ratio,
                "technical_score": score.get("technical_total", 0.0),
                "technical_max": score.get("technical_max", 40.0),
                "positioning_score": score.get("positioning_total", 0.0),
                "sentiment_score": score.get("sentiment_total", 0.0),
                "sentiment_max": score.get("sentiment_max", 15.0),
                "news_score": score.get("news_total", 0.0),
                "news_max": score.get("news_max", 15.0),
                "fundamental_score": score.get("fundamental_score", 0.0),
                "greeks_filter_status": greeks_filter_status,
            }
            paper_alert_sent = False
            try:
                paper_alert_sent = send_paper_signal_alert(paper_alert_payload, model_version=model_version)
            except Exception as exc:
                logger.warning(f"{ticker}: paper Discord alert failed — {exc}")
            _db_insert_notification_safe(run_id, ticker, "trade", paper_alert_payload, paper_alert_sent)

        except Exception as exc:
            # 2026-08-24 full model audit: this catch-all previously left ZERO
            # trace of a failed ticker beyond this one log line — no
            # validation-log entry, no DB row, invisible in the same
            # dashboard every other outcome for the day shows up in. Both
            # additions below are best-effort and can't themselves take down
            # the scan (write_validation_entry/_db_insert_ticker_result_safe
            # already degrade gracefully on their own failure, same as every
            # other call site in this file). Re-deriving sector fresh here
            # rather than reading the loop-local `sector` variable — that
            # variable is only assigned partway through the try block (line
            # ~600), so on an exception before that point it would still hold
            # a PREVIOUS ticker's stale value, not simply be undefined.
            logger.error(f"{ticker}: paper_runner error — {exc}")
            write_validation_entry(
                ticker, "paper_runner_scan_error",
                f"{exc} (score computed before failure: {final_score if final_score is not None else 'none'})",
            )
            _db_insert_ticker_result_safe(
                run_id, ticker, app_db.CATEGORY_SCAN_ERROR, final_score if final_score is not None else 0.0,
                sector=ticker_sector_map.get(ticker),
            )

    # Rank-based parallel paper-trading track (2026-08-24) — pass 2, run
    # after the main loop above finishes so every ticker's score this scan
    # is known before ranking within each sector. See _run_rank_track's own
    # docstring for the full design.
    try:
        rank_signals_logged = _run_rank_track(
            rank_track_candidates, cfg, rr_cfg, model_version, today_str, win_probability_calibration,
            scan_type=scan_type,
        )
        if rank_signals_logged:
            logger.info(f"Rank track: {rank_signals_logged} new signal(s) logged to {RANK_TRADES_CSV}")
    except Exception as exc:
        logger.error(f"Rank track pass failed — {exc}")

    # Event Severity Gate — expire blocks whose cooling-off condition is met,
    # same rule as run_swing_model.py: a post_close scan completing after the
    # block's event timestamp, excluding blocks created earlier in this run.
    newly_expired_blocks = expire_blocks(
        gate_state, scan_type, datetime.now(timezone.utc), exclude_ids=blocks_created_this_scan,
    )
    save_gate_state(gate_state)
    for expired_block in newly_expired_blocks:
        expired_discord_sent = _try_send_event_gate_expired_alert(expired_block, model_version)
        _db_insert_notification_safe(
            run_id, None, "event_gate_expired", expired_block, expired_discord_sent,
        )
        _write_event_gate_audit(expired_block, model_version, scan_type, triggered=False)

    logger.info(f"Paper scan complete — {signals_logged} new signals logged to {PAPER_TRADES_CSV}")
    return signals_logged


# Flat risk_pct for every rank-track pick, regardless of its actual score —
# same $500-at-$15k figure as the threshold track's lowest real tier
# (70-89 confidence). Simplest, most defensible choice until there's real
# rank-track data to justify a confidence-scaled curve for a score range
# with zero win-rate track record yet (2026-08-24, confirmed with user).
# Holding window the target-feasibility ceiling is measured against — the
# day-10 time stop, not MAX_HOLDING_DAYS (15), because a trade with under
# 30% of the target captured is closed at day 10 (see paper_updater's
# signal_decay.time_stop_day). Sizing a target against 15 days it will
# rarely be given is what makes it unreachable in practice.
_TIME_STOP_DAY_DEFAULT = 10

_RANK_TRACK_RISK_PCT = 0.0333


def _run_rank_track(
    candidates: list[dict],
    cfg: dict,
    rr_cfg: dict,
    model_version: str,
    today_str: str,
    win_probability_calibration,
    scan_type: str = "post_close",
) -> int:
    """
    Rank-based parallel paper-trading track (2026-08-24 full model audit
    strategy pivot) — pass 2 of the scan, run after the main per-ticker loop
    (_run_paper_scan_locked) finishes. Ranks `candidates` (every ticker's
    already-computed scoring context this scan, stashed by the main loop
    regardless of qualification — see that loop's own stash comment) WITHIN
    each sector by final_score, and always logs the top
    rank_track.top_n_per_sector (config, default 2) to
    paper_trading/rank_trades.csv — regardless of whether they clear
    CONFIDENCE_THRESHOLD (70). Direct fix for the sample-size problem the
    70+ threshold makes structurally rare (~1 in 250 scored ticker-days —
    see CHANGELOG v2.2.96/v2.2.97): a guaranteed, steady flow of new trades
    to build a real, comparable dataset, instead of waiting on rare
    qualifying events that a full model audit found don't even grow with a
    bigger watchlist.

    top_n_per_sector is a budget for the DAY, not for each scan, and only the
    rank_track.scan_type scan (default post_close) competes for it — see the
    two blocks at the top of the body. Both rules exist because they fail
    differently: the scan gate picks WHICH scan ranks, the per-(day, sector)
    slot count stops any scan — including a manual re-run of the owning one —
    from logging past the budget.

    Runs alongside — never replaces — the main loop's threshold-based
    logging. Fully independent: own CSV, own duplicate-position guard
    (own RANK_TRADES_CSV, never cross-checked against the threshold track —
    a ticker can legitimately be open in both, even opposite directions),
    own Discord identity (track="rank", see discord_alerts.py's
    _TRACK_BRANDING), own simulated $15,000 capital pool (same
    position_sizing.starting_capital value the threshold track uses — a
    sizing anchor recomputed fresh per signal, not a shared decremented
    ledger balance, see position_sizer.py). Never inserts a
    ticker_results/layer_scores DB row (that table has no unique constraint
    per (run_id, ticker) — a same-run second insert would silently
    duplicate; CSV + Discord only for now, revisit once the track's proven
    out).

    Zero additional external API cost: `candidates` carries only what the
    main loop already fetched this scan (StockTwits/Seeking Alpha/news are
    NOT re-fetched here).

    Returns count of new rank-track signals logged this run.
    """
    rank_cfg = cfg.get("rank_track", {})
    top_n = int(rank_cfg.get("top_n_per_sector", 2))

    # One scan owns the day's slots (rank_track.scan_type, default post_close).
    # Before this gate the slots went to whichever scan ran first — pre_market,
    # ranking on the least information of the day's three scans — and the two
    # later scans then competed for whatever was left. post_close ranks on the
    # full session's data and costs nothing in timing, since entry is a
    # next-day breakout trigger either way. "any" restores every-scan
    # behaviour; the per-(day, sector) budget below still applies in that case,
    # and still applies here too — this gate is not a substitute for it, since
    # the owning scan can legitimately run twice (a manual re-run or a retry;
    # see data/logs/paper_runner_task_rerun.log).
    owning_scan = str(rank_cfg.get("scan_type", "post_close"))
    if owning_scan != "any" and scan_type != owning_scan:
        logger.info(
            f"Rank track: skipped for scan_type={scan_type} — "
            f"rank_track.scan_type is '{owning_scan}'"
        )
        return 0

    already_logged = _load_logged_keys(RANK_TRADES_CSV)
    open_positions = _load_open_positions(RANK_TRADES_CSV)
    pending_positions = _load_pending_positions(RANK_TRADES_CSV)

    # Slots already consumed today, per sector — the day's budget is top_n per
    # sector across ALL of the day's scans, not top_n per scan.
    #
    # `already_logged` is keyed (signal_date, ticker), which stops the same
    # ticker being logged twice in a day but never stopped a later scan from
    # walking further down the same sector's ranking and filling top_n fresh
    # slots. With three scans a day (pre-market/mid-session/post-close) that
    # logged 3 x top_n per sector — exactly 6 per sector, 24 rows, on
    # 2026-08-25 against a configured top_n of 2 — and scans 2 and 3 are
    # systematically the LOWER-ranked names, every one of them reported as
    # "rank #1"/"rank #2" in the log. That silently inflates and biases the
    # dataset this whole track exists to build (see the sample-size rationale
    # above), so it has to be counted per (day, sector), not per scan.
    #
    # Sector is resolved per ticker rather than read back from the CSV: the
    # rank-track ledger carries no sector column. THIS scan's candidates are
    # the authoritative source (they carry the same `sector` value the rows
    # were logged under), with config's watchlist map as the fallback for a
    # ticker that was logged earlier today but isn't in this scan's candidate
    # set (scan error, or removed from the watchlist mid-day).
    #
    # A ticker that resolves to NEITHER can't be attributed to a sector, so it
    # can't consume a slot — which would silently restore the exact
    # overcounting this block exists to stop. That's a quiet correctness
    # failure on a counter, so it's warned about rather than swallowed.
    ticker_sector_map = dict(get_ticker_sector_map(cfg))
    ticker_sector_map.update({c["ticker"]: c["sector"] for c in candidates})
    slots_used_today: dict[str, int] = {}
    unresolved_today: list[str] = []
    for logged_date, logged_ticker in already_logged:
        if logged_date != today_str:
            continue
        logged_sector = ticker_sector_map.get(logged_ticker)
        if logged_sector:
            slots_used_today[logged_sector] = slots_used_today.get(logged_sector, 0) + 1
        else:
            unresolved_today.append(logged_ticker)
    if unresolved_today:
        logger.warning(
            f"Rank track: {len(unresolved_today)} row(s) already logged for {today_str} "
            f"could not be mapped to a sector ({', '.join(sorted(unresolved_today))}) — "
            f"their slots are NOT counted against today's per-sector budget, so that "
            f"sector may over-log today. Check these tickers are still in the watchlist."
        )

    by_sector: dict[str, list[dict]] = {}
    for c in candidates:
        by_sector.setdefault(c["sector"], []).append(c)

    signals_logged = 0
    for sector, sector_candidates in by_sector.items():
        ranked = sorted(sector_candidates, key=lambda c: c["final_score"], reverse=True)
        picks = slots_used_today.get(sector, 0)
        if picks >= top_n:
            logger.info(
                f"{sector}: rank-track already filled its {top_n} slot(s) for {today_str} "
                f"in an earlier scan — no further picks today"
            )
            continue
        # enumerate for the ACTUAL within-sector rank of each candidate this
        # scan. `picks` is a slot counter, not a rank — reporting it as one is
        # what made every logged row read "rank #1"/"rank #2" regardless of
        # where the candidate really placed.
        for rank_in_sector, c in enumerate(ranked, start=1):
            if picks >= top_n:
                break
            ticker = c["ticker"]
            if (today_str, ticker) in already_logged:
                continue
            # Same pending-vs-filled split as the threshold track's guard —
            # a never-filled entry order is a stale opinion this scan's newer
            # ranking supersedes; a filled one is real exposure.
            if ticker in open_positions:
                if ticker in pending_positions and _supersede_pending_signals(
                    ticker, today_str, c["final_score"],
                    csv_path=RANK_TRADES_CSV, lock_path=RANK_TRADES_LOCK_FILE,
                ):
                    logger.info(
                        f"{ticker}: rank-track pick with a pending (unfilled) signal — "
                        f"cancelled as superseded, logging the newer signal"
                    )
                    pending_positions.discard(ticker)
                    open_positions.discard(ticker)
                else:
                    logger.info(
                        f"{ticker}: rank-track pick but already has a filled open "
                        f"rank-track position — skipped"
                    )
                    continue

            row = _build_rank_track_row(c, cfg, rr_cfg, today_str, win_probability_calibration)
            if row is None:
                # No valid entry/stop/target could be computed (e.g. no real
                # close price) — skip this candidate, don't leave the
                # sector short a pick; the loop just moves to the next-
                # ranked candidate without incrementing `picks`.
                continue

            _append_row(row, csv_path=RANK_TRADES_CSV, lock_path=RANK_TRADES_LOCK_FILE)
            signals_logged += 1
            picks += 1
            logger.info(
                f"{ticker}: RANK-TRACK signal logged — rank #{rank_in_sector} in {sector} "
                f"(slot {picks}/{top_n} for {today_str}), score {c['final_score']:.1f}"
            )

            rank_alert_payload = {
                **row,
                "entry_zone_lower": float(row["entry_zone_lower"]),
                "entry_zone_upper": float(row["entry_zone_upper"]),
                "stop_loss": float(row["stop_loss"]),
                "target": float(row["target"]) if row["target"] else 0.0,
                "rr_ratio": float(row["rr_ratio"]),
                "technical_score": c["score"].get("technical_total", 0.0),
                "technical_max": c["score"].get("technical_max", 40.0),
                "positioning_score": c["score"].get("positioning_total", 0.0),
                "sentiment_score": c["score"].get("sentiment_total", 0.0),
                "sentiment_max": c["score"].get("sentiment_max", 15.0),
                "news_score": c["score"].get("news_total", 0.0),
                "news_max": c["score"].get("news_max", 15.0),
                "fundamental_score": c["score"].get("fundamental_score", 0.0),
                "greeks_filter_status": row.get("greeks_filter_status"),
            }
            try:
                send_paper_signal_alert(rank_alert_payload, model_version=model_version, track="rank")
            except Exception as exc:
                logger.warning(f"{ticker}: rank-track Discord alert failed — {exc}")

    return signals_logged


def _build_rank_track_row(
    candidate: dict, cfg: dict, rr_cfg: dict, today_str: str, win_probability_calibration,
) -> Optional[dict]:
    """
    Compute entry/stop/target/structure/sizing fresh for one rank-track pick
    and build its paper_trades.csv-schema row.

    Always recomputes the structure via rank_trade_structures — never reuses
    whatever the main loop may have already computed for this ticker at
    STRUCTURE_EVAL_DIAGNOSTIC_THRESHOLD (60) and above. That earlier
    computation used get_risk_pct(confidence), which is 0.0 below
    CONFIDENCE_THRESHOLD (70) by design — so even a 60-69 scorer's structure
    there was never actually budget-checked (dollar_risk=0.0 there means
    _fits_tier_budget always fails, falling through to the diagnostic-only
    path). This track needs a structure picked against its own real flat
    3.33% budget instead, which only risk_pct_override provides.

    Returns None if there's no real close price to anchor an entry/stop/
    target to (should be rare — the main loop already required
    `indicators is not None` to stash this candidate at all).
    """
    ticker = candidate["ticker"]
    direction = candidate["direction"]
    final_score = candidate["final_score"]
    indicators = candidate["indicators"]
    score = candidate["score"]
    earnings_result = candidate["earnings_result"] or {}
    positioning = candidate["positioning"] or {}
    regime = candidate["regime"]

    close_px = float(indicators.get("close", 0.0))
    if close_px <= 0:
        return None
    atr = float(indicators.get("atr_14", close_px * 0.02))
    level = float(indicators.get("rolling_low_20" if direction == "bearish" else "rolling_high_20", close_px))

    entry_lower, entry_upper = compute_entry_zone(
        close_px, level, atr, rr_cfg.get("entry_zone_half_width_atr", 0.25), direction=direction,
    )
    entry_mid = (entry_lower + entry_upper) / 2.0
    stop_loss = compute_stop_loss(
        entry_upper if direction == "bearish" else entry_lower, atr,
        high_volume_support=indicators.get("high_volume_support"),
        high_volume_resistance=indicators.get("high_volume_resistance"),
        stop_atr_multiplier=rr_cfg.get("stop_atr_multiplier", 2.0),
        min_stop_atr_multiple=rr_cfg.get("min_stop_atr_multiple", 1.0),
        direction=direction,
    )
    target_px = compute_target(
        entry_mid, stop_loss,
        low_volume_area_above=indicators.get("low_volume_area_above"),
        low_volume_area_below=indicators.get("low_volume_area_below"),
        min_rr=rr_cfg.get("min_rr_ratio", 3.0), direction=direction,
        atr_14=atr, holding_days=_TIME_STOP_DAY_DEFAULT,
        max_target_atr_multiple=rr_cfg.get("max_target_atr_multiple", 2.5),
    )
    rr_ratio = compute_rr_ratio(entry_mid, stop_loss, target_px, direction=direction) if target_px else 0.0

    structure_recommended = ""
    ev_per_dollar = ""
    capital_required = None
    position_type = None
    greeks_filter_status = None
    try:
        force_defined_risk = earnings_result.get("force_defined_risk", False) or (regime == REGIME_HIGH_VOL)
        options_raw = positioning.get("_options_raw") or {}
        trade_result = rank_trade_structures(
            {
                "ticker": ticker, "direction": direction, "confidence": final_score,
                "entry": entry_mid, "entry_mid": entry_mid, "stop_loss": stop_loss,
                "target": target_px, "atr_14": atr, "force_defined_risk": force_defined_risk,
            },
            account_equity=float(cfg.get("position_sizing", {}).get("starting_capital", 15000.0)),
            options_approval_level=int(cfg.get("options_approval_level", 2)),
            iv_percentile=options_raw.get("iv_percentile", 50.0),
            option_chain=options_raw.get("chain"),
            dte=options_raw.get("dte"),
            atm_iv=options_raw.get("atm_iv"),
            cfg=cfg,
            win_probability_calibration=win_probability_calibration,
            risk_pct_override=_RANK_TRACK_RISK_PCT,
        )
        ranked = trade_result.get("ranked_structures", [])
        greeks_filter_status = trade_result.get("greeks_filter_status")
        if ranked:
            best = next((s for s in ranked if s.get("recommended")), ranked[0])
            structure_recommended = best.get("name", "")
            capital_required = best.get("capital_required")
            position_type = best.get("position_type")
            ev_per_dollar = f"{best.get('ev_per_dollar_per_day', 0.0):.5f}"
    except Exception as exc:
        logger.warning(f"{ticker}: rank-track structure ranking failed — {exc}")

    account_equity = float(cfg.get("position_sizing", {}).get("starting_capital", 15000.0))
    max_capital_pct = float(cfg.get("position_sizing", {}).get("max_capital_pct", 5000 / 15000))
    position_type, risk_per_unit, per_unit_cost = derive_sizing_inputs(
        position_type, capital_required, entry_mid, stop_loss
    )
    sizing = compute_position_size(
        confidence_score=final_score, account_equity=account_equity,
        circuit_breaker_state="normal", capital_required=risk_per_unit,
        max_capital_pct=max_capital_pct, consecutive_losses=0,
        per_unit_cost=per_unit_cost, position_type=position_type,
        risk_pct_override=_RANK_TRACK_RISK_PCT,
    )

    sizing_note = f"rank track — flat {_RANK_TRACK_RISK_PCT:.2%} risk regardless of score ({final_score:.1f}/100)"
    if sizing["contracts_or_shares"] == 0:
        sizing_note += " — sizes to 0 at this account size, not practically tradeable"

    return {
        "signal_date": today_str,
        "ticker": ticker,
        "direction": direction,
        "confidence": f"{final_score:.1f}",
        "technical_score": f"{score.get('technical_total', 0.0):.1f}",
        "positioning_score": f"{score.get('positioning_total', 0.0):.1f}",
        "sentiment_score": f"{score.get('sentiment_total', 0.0):.1f}",
        "news_score": f"{score.get('news_total', 0.0):.1f}",
        "fundamental_score": f"{score.get('fundamental_score', 0.0):.1f}",
        # Mirrors the threshold track's row above — the rank track runs the
        # same scoring.py engine and so is subject to the same calibrated
        # reweighting. See _CSV_COLUMNS.
        "technical_max": f"{float(score.get('technical_max', TECHNICAL_MAX)):.1f}",
        "sentiment_max": f"{float(score.get('sentiment_max', SENTIMENT_MAX)):.1f}",
        "news_max": f"{float(score.get('news_max', NEWS_MAX)):.1f}",
        "regime": regime,
        "vix_at_signal": f"{float(candidate['vix_val']):.1f}",
        "rsi_14": f"{float(indicators.get('rsi_14', 0.0)):.1f}",
        "rs_zscore": f"{float(indicators.get('rs_zscore', 0.0)):.3f}",
        "mom_5d": f"{float(indicators.get('mom_5d', 0.0)):.4f}",
        "trend_intact": str(bool(indicators.get("trend_intact", False))),
        "entry_zone_lower": f"{entry_lower:.2f}",
        "entry_zone_upper": f"{entry_upper:.2f}",
        "entry_price": f"{entry_mid:.2f}",
        "stop_loss": f"{stop_loss:.2f}",
        "target": f"{target_px:.2f}" if target_px else "",
        "rr_ratio": f"{rr_ratio:.2f}",
        "news_article_count": str(candidate["news_count"]),
        "dominant_news_theme": candidate["dominant_theme"],
        "fundamental_data_quality": str(score.get("fundamental_data_quality", "unavailable")),
        "structure_recommended": structure_recommended,
        "ev_per_dollar": ev_per_dollar,
        "capital_required": f"{float(capital_required):.2f}" if capital_required is not None else "",
        "structure_legs": "",
        "structure_effective_days": "",
        "structure_greeks_summary": "",
        "structure_max_loss": "",
        "structure_max_gain": "",
        "structure_strikes": "",
        "structure_expiration_date": "",
        "alternative_structures": "",
        "greeks_filter_status": greeks_filter_status or "",
        "risk_pct": f"{sizing['risk_pct']:.4f}",
        "dollar_risk": f"{sizing['dollar_risk']:.2f}",
        "actual_dollar_risk": f"{sizing['actual_dollar_risk']:.2f}",
        "position_type": position_type,
        "position_size": str(sizing["contracts_or_shares"]),
        "capital_deployed": f"{sizing['capital_deployed']:.2f}",
        "sizing_note": sizing_note,
        "event_gate_blocked": bool(score.get("event_gate_blocked", False)),
        "event_gate_trigger": score.get("event_gate_trigger", "") or "",
        "outcome": "",
        "exit_date": "",
        "exit_price": "",
        "pnl_pct": "",
        "achieved_rr": "",
        "holding_days": "",
        "pnl_dollars": "",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Paper trading signal runner")
    parser.add_argument(
        "--scan-type",
        choices=["pre_market", "mid_session", "post_close"],
        default="post_close",
        help="Which scan window (default: post_close)",
    )
    args = parser.parse_args()
    count = run_paper_scan(scan_type=args.scan_type)
    print(f"Done — {count} paper signal(s) logged.")
    sys.exit(0)
