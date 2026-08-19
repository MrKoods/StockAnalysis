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
from swing_model.news_layer import compute_news_score, free_sources_flag_critical_event
from swing_model.scoring import compute_confidence_score, CONFIDENCE_THRESHOLD, determine_direction
from swing_model.feedback_loop import load_live_weights_if_calibrated
from swing_model.win_probability_calibration import load_calibration
from shared.utils.risk_reward import compute_entry_zone, compute_stop_loss, compute_target, compute_rr_ratio
from shared.utils.regime_detection import get_regime_modifiers
from shared.utils.position_sizer import compute_position_size
from shared.utils.sector_rotation import dampen_rotation_penalty_for_leader, get_rotation_modifier, ROTATION_NEUTRAL
from shared.utils.earnings_calendar import get_earnings_modifier
from shared.utils.seasonality import get_seasonality_modifier
from shared.utils.logger import get_logger
from shared.utils.discord_alerts import send_paper_signal_alert, send_near_miss_alert
from shared.utils.robust_stats import robust_z_score, DEFAULT_OUTLIER_THRESHOLD
from shared.utils.scan_lock import acquire_scan_lock
from shared.utils.atomic_io import exclusive_lock
from swing_model.trade_selector import rank_trade_structures
from shared.utils.regime_detection import REGIME_HIGH_VOL
from shared.utils.event_gate import (
    load_gate_state, save_gate_state, is_ticker_blocked, add_block,
    has_active_block_for_trigger, expire_blocks, is_thesis_opposed,
    SCOPE_SECTOR,
)
from shared.utils.sector_config import (
    get_active_sectors, get_all_tickers, get_ticker_sector_map, get_sector_tickers,
)
from shared.utils.macro_overlay import save_macro_state

# Reuse all pipeline helpers from run_swing_model to avoid duplication
from swing_model.run_swing_model import (
    _fetch_market_context,
    _compute_regime_safe,
    _compute_macro_safe,
    _compute_china_tension_count,
    _compute_rotation_safe,
    _compute_cross_ticker_safe,
    _fetch_stocktwits_safe,
    _fetch_sa_engagement_safe,
    _fetch_av_news_safe,
    _fetch_yahoo_news_safe,
    _fetch_finnhub_news_safe,
    _fetch_sec_edgar_safe,
    _compute_sector_context_filings,
    _fetch_earnings_safe,
    get_model_version,
    _try_send_event_gate_alert,
    _try_send_event_gate_expired_alert,
    _write_event_gate_audit,
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
    "regime", "vix_at_signal",
    "rsi_14", "rs_zscore", "mom_5d", "trend_intact",
    "entry_zone_lower", "entry_zone_upper", "entry_price", "stop_loss", "target", "rr_ratio",
    "news_article_count", "dominant_news_theme", "fundamental_data_quality",
    "structure_recommended", "ev_per_dollar",
    # capital_required is the winning structure's own theoretical dollar risk
    # from rank_trade_structures() — distinct from capital_deployed below,
    # which is that figure after position sizing/tier-budget rounding.
    # structure_legs/structure_effective_days/structure_greeks_summary were
    # already computed by trade_selector.py but discarded before reaching
    # this row until now — see the comment where they're extracted above.
    "capital_required", "structure_legs", "structure_effective_days", "structure_greeks_summary",
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
    # Outcome fields — blank until paper_updater.py fills them in
    "outcome", "exit_date", "exit_price", "pnl_pct", "achieved_rr", "holding_days", "pnl_dollars",
]


def _load_logged_keys() -> set[tuple[str, str]]:
    """Return set of (signal_date, ticker) pairs already in paper_trades.csv."""
    if not PAPER_TRADES_CSV.exists():
        return set()
    seen: set[tuple[str, str]] = set()
    try:
        with open(PAPER_TRADES_CSV, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                seen.add((row.get("signal_date", ""), row.get("ticker", "")))
    except Exception as exc:
        logger.warning(f"Could not read paper_trades.csv: {exc}")
    return seen


def _load_open_positions() -> set[str]:
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
    """
    if not PAPER_TRADES_CSV.exists():
        return set()
    open_positions: set[str] = set()
    try:
        with open(PAPER_TRADES_CSV, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if not (row.get("outcome") or "").strip():
                    open_positions.add(row.get("ticker", ""))
    except Exception as exc:
        logger.warning(f"Could not read paper_trades.csv for open-position check: {exc}")
    return open_positions


def _append_row(row: dict) -> None:
    """
    Append one signal row to paper_trades.csv, creating header on first write.

    Lock-protected (same lock file as paper_updater.py's _save_trades) —
    without it, an append landing in the middle of paper_updater.py's
    multi-minute update run could be silently wiped out by that run's final
    full-file rewrite. The critical section here is brief either way, so
    this only ever waits for another brief append or for paper_updater.py's
    own (also brief, see its docstring) locked merge-and-write step.
    """
    PAPER_TRADES_CSV.parent.mkdir(parents=True, exist_ok=True)
    with exclusive_lock(PAPER_TRADES_LOCK_FILE, timeout=15.0):
        write_header = not PAPER_TRADES_CSV.exists()
        with open(PAPER_TRADES_CSV, "a", newline="", encoding="utf-8") as f:
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

    for ticker in watchlist:
        try:
            indicators = indicators_by_ticker.get(ticker)
            if indicators is None:
                logger.debug(f"{ticker}: no indicators — skipped")
                continue

            if (today_str, ticker) in already_logged:
                logger.info(f"{ticker}: already logged today — skipped")
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
            fetch_av_now = free_sources_flag_critical_event(
                free_source_articles, ticker, cfg, sector=sector
            )
            av_articles = _fetch_av_news_safe(ticker) if fetch_av_now else []
            news = compute_news_score(
                av_articles, yahoo_articles, ticker, cfg, finnhub_articles=finnhub_articles,
                sector=sector, seeking_alpha_articles=sa_news_articles,
                sec_edgar_filings=sec_edgar_filings, direction=direction,
            )

            # Earnings + cross-ticker modifiers
            earnings_info = _fetch_earnings_safe(ticker)
            earnings_date = (earnings_info or {}).get("next_earnings_date")
            earnings_result = get_earnings_modifier(ticker, earnings_date, cfg=cfg)
            earnings_mod = earnings_result.get("confidence_modifier", 0.0)
            ct_mod = cross_ticker.get(ticker, {}).get("confidence_modifier", 0.0)

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
                regime=regime,
                fundamental=fundamental,
                event_gate_blocked=event_gate_blocked,
                event_gate_trigger=event_gate_trigger,
                win_probability_calibration=win_probability_calibration,
                direction_override=direction,
            )

            final_score = float(score.get("final_score", 0.0))

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
                    direction=direction,
                )
                target_px = compute_target(
                    entry_mid, stop_loss,
                    low_volume_area_above=indicators.get("low_volume_area_above"),
                    low_volume_area_below=indicators.get("low_volume_area_below"),
                    min_rr=rr_cfg.get("min_rr_ratio", 3.0), direction=direction,
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
            if ticker in open_positions:
                logger.info(
                    f"{ticker}: qualifies ({final_score:.1f}) but already has an open "
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

            news_count = len(av_articles) + len(yahoo_articles) + len(finnhub_articles) + len(sec_edgar_filings)
            dominant_theme = str(news.get("dominant_narrative_theme", "")) if isinstance(news, dict) else ""

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
            max_capital_pct = float(cfg.get("position_sizing", {}).get("max_capital_pct", 0.05))
            # Branches on trade_selector.py's own position_type field rather
            # than a truthiness heuristic on structure_recommended/
            # capital_required — that heuristic used to mislabel long_stock/
            # short_stock as "options" (cost == risk == capital_required)
            # whenever one won the ranking, when a stock position genuinely
            # needs two separate numbers: capital_required is now real dollar
            # risk (stop distance, post the _estimate_capital_required fix)
            # for risk-based sizing, but entry_mid (full share price) is still
            # needed separately for the capital/concentration cap — conflating
            # them again here would silently reintroduce that bug.
            if position_type == "options" and capital_required:
                risk_per_unit = float(capital_required)
                per_unit_cost = risk_per_unit
            elif position_type == "shares" and capital_required:
                risk_per_unit = float(capital_required)
                per_unit_cost = entry_mid
            else:
                # No structure survived ranking at all (rare post-fix for
                # bullish; the only path for bearish until the bearish R:R
                # bug is fixed — see CHANGELOG). Defensive fallback, not the
                # normal path: size shares directly off the shared entry/stop.
                position_type = "shares"
                # abs(): bearish stops sit above entry, not below — the
                # magnitude of the risk is what matters for sizing either way.
                risk_per_unit = abs(entry_mid - stop_loss)
                per_unit_cost = entry_mid
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
            logger.error(f"{ticker}: paper_runner error — {exc}")

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
