"""
Tracks open positions; reads/writes data/processed/position_state.json on every run.
Enforces simultaneous position limits (max 2); manages circuit breaker state;
calculates portfolio delta; fires circuit breaker Discord alerts; PDT tracking;
entry confirmation handling (Clarification: "entered" / "skipped" replies).
"""

import csv
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

from shared.utils.atomic_io import atomic_write_json

_POSITION_STATE_FILE = Path("data/processed/position_state.json")
_OVERRIDE_LOG_FILE = Path("data/logs/override_log.csv")

_EMPTY_STATE = {
    "positions": [],
    "account_equity": 15000.0,
    "peak_equity": 15000.0,
    "circuit_breaker_state": "normal",     # normal | yellow | orange | red
    "day_trades_rolling_5d": [],           # list of dates of day trades in last 5 trading days
    "consecutive_losses": 0,
    "black_swan_mode": False,
    "black_swan_normal_days": 0,
    "last_scan_timestamp_utc": None,
    "model_version": "v1.0.0",
}

MAX_OPEN_POSITIONS = 2
MAX_TOTAL_RISK_PCT = 0.03  # 3% total portfolio risk across all open positions
MAX_TOTAL_OPEN_POSITIONS = 2

# Fallback defaults — used when cfg lacks a portfolio.sectors block (or cfg is
# None), so behavior is unchanged for callers that haven't migrated their
# config yet. Real values normally come from config/swing_config.yaml's
# portfolio.sectors.<name>.max_open_positions/correlated_groups.
# Correlated GROUPS (generalized from the original 2-element pairs) — treat
# same-direction exposure to 2+ tickers from the same group as concentration risk.
_CORRELATED_GROUPS = [
    {"NVDA", "AMD"},
    {"NVDA", "AVGO"},
    {"AMD", "AVGO"},
    {"MU", "NVDA"},
    {"TSM", "NVDA"},
    {"TSM", "ASML"},
]


def load_position_state() -> dict:
    """Load position state from JSON. Returns empty state if file doesn't exist."""
    if _POSITION_STATE_FILE.exists():
        return json.loads(_POSITION_STATE_FILE.read_text())
    return _EMPTY_STATE.copy()


def save_position_state(state: dict) -> None:
    """Persist position state to data/processed/position_state.json (atomic write)."""
    atomic_write_json(_POSITION_STATE_FILE, state)


def add_position(state: dict, position: dict) -> dict:
    """
    Add a new open position to state.
    Validates: max 2 open positions; max simultaneous risk 3%; correlated pair rule.
    Raises ValueError if any constraint is violated.
    Updates PDT counter.
    """
    allowed, reason = can_open_new_position(state, position)
    if not allowed:
        raise ValueError(f"Cannot open position: {reason}")

    now_utc = datetime.now(timezone.utc).isoformat()
    entry = float(position.get("entry_price", position.get("entry_mid", 0.0)))

    new_pos = {
        "ticker": position.get("ticker", ""),
        "direction": position.get("direction", "bullish"),
        "entry_price": entry,
        "stop_loss": float(position.get("stop_loss", 0.0)),
        "target": float(position.get("target", 0.0)),
        "risk_pct": float(position.get("risk_pct", 0.01)),
        "structure": position.get("structure", "long_stock"),
        "confidence": float(position.get("confidence", 90.0)),
        "opened_at_utc": now_utc,
        "holding_day": 0,
        "highest_close_since_entry": entry,
        "lowest_close_since_entry": entry,
        "open": True,
    }

    state["positions"].append(new_pos)
    return state


def close_position(state: dict, ticker: str, exit_price: float, reason: str) -> dict:
    """
    Close a position and update realized P&L, consecutive loss count, and equity.
    Logs outcome to data/logs/trade_outcomes.csv.
    Returns updated state.
    """
    positions = state.get("positions", [])
    closed_pos = None
    remaining = []

    for pos in positions:
        if pos.get("ticker") == ticker and pos.get("open", True) and closed_pos is None:
            closed_pos = pos
        else:
            remaining.append(pos)

    if closed_pos is None:
        raise ValueError(f"No open position found for {ticker}")

    entry = float(closed_pos.get("entry_price", 0.0))
    direction = closed_pos.get("direction", "bullish")
    if direction == "bullish":
        pnl_pct = (exit_price - entry) / entry if entry > 0 else 0.0
    else:
        pnl_pct = (entry - exit_price) / entry if entry > 0 else 0.0

    equity = float(state.get("account_equity", 15000.0))
    risk_pct = float(closed_pos.get("risk_pct", 0.01))
    stop = float(closed_pos.get("stop_loss", 0.0))
    risk_distance = abs(entry - stop) / entry if entry > 0 and stop > 0 else risk_pct
    pnl_dollars = equity * risk_pct * (pnl_pct / risk_distance) if risk_distance > 0 else 0.0

    new_equity = equity + pnl_dollars
    state["account_equity"] = round(new_equity, 2)

    if new_equity > float(state.get("peak_equity", equity)):
        state["peak_equity"] = round(new_equity, 2)

    state["consecutive_losses"] = 0 if pnl_dollars >= 0 else state.get("consecutive_losses", 0) + 1

    # PDT: record day trade if opened and closed on same day
    opened_at = closed_pos.get("opened_at_utc", "")
    opened_date = opened_at[:10] if len(opened_at) >= 10 else ""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if opened_date == today:
        state.setdefault("day_trades_rolling_5d", []).append(today)

    closed_pos.update({
        "open": False,
        "exit_price": exit_price,
        "exit_reason": reason,
        "pnl_dollars": round(pnl_dollars, 2),
        "pnl_pct": round(pnl_pct * 100, 2),
        "closed_at_utc": datetime.now(timezone.utc).isoformat(),
    })

    remaining.append(closed_pos)
    state["positions"] = remaining
    _log_trade_outcome(closed_pos)
    return state


def update_circuit_breaker(state: dict, cfg: Optional[dict] = None) -> dict:
    """
    Check drawdown from peak equity and update circuit breaker state.
    Yellow: 5% drawdown; Orange: 10%; Red: 15%.
    Fires Discord alert when state changes.
    Returns updated state.
    """
    if cfg is None:
        cfg = {}

    equity = float(state.get("account_equity", 15000.0))
    peak = float(state.get("peak_equity", equity))
    if peak <= 0:
        return state

    drawdown_pct = (peak - equity) / peak
    prev_state = state.get("circuit_breaker_state", "normal")
    cb_cfg = cfg.get("circuit_breakers", {})

    red_thr = float(cb_cfg.get("red", {}).get("drawdown_pct", 0.15))
    orange_thr = float(cb_cfg.get("orange", {}).get("drawdown_pct", 0.10))
    yellow_thr = float(cb_cfg.get("yellow", {}).get("drawdown_pct", 0.05))

    if drawdown_pct >= red_thr:
        new_state = "red"
    elif drawdown_pct >= orange_thr:
        new_state = "orange"
    elif drawdown_pct >= yellow_thr:
        new_state = "yellow"
    else:
        new_state = "normal"

    state["circuit_breaker_state"] = new_state

    if new_state != prev_state:
        # Alert fires via discord_alerts.py in run_swing_model.py
        state["_cb_state_changed"] = {
            "from": prev_state,
            "to": new_state,
            "drawdown_pct": round(drawdown_pct * 100, 2),
            "equity": equity,
            "peak": peak,
        }

    return state


def can_open_new_position(
    state: dict,
    new_position: dict,
    cfg: Optional[dict] = None,
) -> tuple[bool, str]:
    """
    Check all portfolio constraints before allowing a new position.
    Returns (allowed: bool, reason: str).
    Constraints: per-sector position cap + a global total-position ceiling,
    max simultaneous risk %, correlated-group limit (scoped to the new
    ticker's own sector), circuit breaker state (Orange/Red → no new positions).

    Position caps are per-sector (e.g. 2 semis + 2 banks), not one shared
    pool — the point of a second sector is diversification, and a shared cap
    would let one sector's setups routinely crowd out the other's. The
    max_simultaneous_risk_pct cap remains the real dollar-risk backstop,
    independent of how many sector slots exist.
    """
    cfg = cfg or {}
    portfolio_cfg = cfg.get("portfolio", {})

    cb_state = state.get("circuit_breaker_state", "normal")
    if cb_state in ("orange", "red"):
        return False, f"circuit_breaker_{cb_state}_no_new_positions"

    from shared.utils.sector_config import get_ticker_sector_map, get_sector_tickers
    new_ticker = new_position.get("ticker", "")
    new_dir = new_position.get("direction", "bullish")
    sector = get_ticker_sector_map(cfg).get(new_ticker)
    sector_cfg = portfolio_cfg.get("sectors", {}).get(sector, {}) if sector else {}

    total_max_positions = int(portfolio_cfg.get("max_total_open_positions", MAX_TOTAL_OPEN_POSITIONS))
    sector_max_positions = int(sector_cfg.get("max_open_positions", MAX_OPEN_POSITIONS))
    max_risk_pct = float(portfolio_cfg.get("max_simultaneous_risk_pct", MAX_TOTAL_RISK_PCT))
    correlated_groups = [set(g) for g in sector_cfg.get("correlated_groups", [])] or _CORRELATED_GROUPS

    open_positions = [p for p in state.get("positions", []) if p.get("open", True)]

    if len(open_positions) >= total_max_positions:
        return False, f"max_total_positions_reached_{total_max_positions}"

    if sector is not None:
        sector_tickers = set(get_sector_tickers(cfg, sector))
        same_sector_open = [p for p in open_positions if p.get("ticker", "") in sector_tickers]
        if len(same_sector_open) >= sector_max_positions:
            return False, f"max_positions_reached_sector_{sector}_{sector_max_positions}"

    new_risk = float(new_position.get("risk_pct", 0.01))
    existing_risk = sum(float(p.get("risk_pct", 0.01)) for p in open_positions)
    if existing_risk + new_risk > max_risk_pct:
        return False, f"total_risk_exceeds_{round(max_risk_pct*100)}pct_{round((existing_risk + new_risk)*100, 1)}pct"

    # Same-ticker rule — no second same-direction position on a ticker that
    # already has one open. {new_ticker, open_ticker} collapses to a 1-element
    # set when they're equal, which never matches any correlated group below
    # (groups always have 2+ distinct tickers), so that check alone couldn't
    # catch this case — sector slots could otherwise concentrate in one name.
    for open_pos in open_positions:
        if new_ticker == open_pos.get("ticker", "") and new_dir == open_pos.get("direction", "bullish"):
            return False, f"duplicate_position_{new_ticker}_same_direction"

    # Correlated-group rule — no same-direction exposure to 2+ tickers from
    # the same group. correlated_groups is scoped to the NEW ticker's own
    # sector, so a bank ticker is only ever checked against bank groups.
    for open_pos in open_positions:
        open_ticker = open_pos.get("ticker", "")
        if new_dir == open_pos.get("direction", "bullish"):
            pair = {new_ticker, open_ticker}
            for corr_group in correlated_groups:
                if pair.issubset(corr_group):
                    return False, f"correlated_group_{open_ticker}_{new_ticker}_same_direction"

    # Yellow CB: only allow confidence >= 95
    if cb_state == "yellow":
        confidence = float(new_position.get("confidence", 90.0))
        if confidence < 95:
            return False, "yellow_cb_requires_confidence_95_plus"

    return True, "ok"


def handle_entry_confirmation(
    state: dict,
    ticker: str,
    confirmation: str,  # 'entered' | 'skipped'
    position_details: Optional[dict] = None,
) -> dict:
    """
    Process user's "entered" or "skipped" reply to a trade alert.
    "entered": add position to state, update portfolio delta, decrement slot count.
    "skipped": log to override_log.csv, free the signal slot.
    No reply after 2 hours: defaults to "skipped".
    Returns updated state.
    """
    if confirmation == "entered":
        if position_details is None:
            raise ValueError("position_details required when confirmation='entered'")
        state = add_position(state, position_details)
    elif confirmation == "skipped":
        _log_override(ticker, "user_skipped", position_details)
    else:
        _log_override(ticker, f"unknown_response_{confirmation}", position_details)

    return state


def get_portfolio_delta(state: dict, current_prices: dict[str, float]) -> float:
    """
    Calculate net portfolio delta across all open positions.
    Net directional exposure must not exceed 1.5% of account per 1% broad market move.
    Returns net delta (positive = net long, negative = net short).
    """
    open_positions = [p for p in state.get("positions", []) if p.get("open", True)]
    net_delta = 0.0

    for pos in open_positions:
        direction = 1.0 if pos.get("direction", "bullish") == "bullish" else -1.0
        risk_pct = float(pos.get("risk_pct", 0.01))
        net_delta += risk_pct * direction

    return round(net_delta, 4)


def count_day_trades(state: dict) -> int:
    """Count day trades in the rolling 5-trading-day window."""
    day_trades = state.get("day_trades_rolling_5d", [])
    if not day_trades:
        return 0

    # Keep only trades within ~7 calendar days (5 trading days approximate)
    cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")
    recent = [d for d in day_trades if d >= cutoff]
    state["day_trades_rolling_5d"] = recent
    return len(recent)


def is_pdt_warning(state: dict, threshold: int = 2) -> bool:
    """Return True if day trade count is at or above warning threshold."""
    return count_day_trades(state) >= threshold


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _log_trade_outcome(closed_pos: dict) -> None:
    """
    Append closed trade to trade_outcomes.csv via feedback_loop.log_trade_outcome —
    the single source of truth for that file's schema (also updates
    signal_win_rates.json for Phase 14 calibration). technical_total /
    sentiment_total / news_total / signal_key are left blank here: this
    position record only captures entry/exit/P&L, not the entry-time signal
    component scores those fields need.
    """
    from swing_model.feedback_loop import log_trade_outcome

    opened_at = str(closed_pos.get("opened_at_utc", ""))
    closed_at = str(closed_pos.get("closed_at_utc", ""))
    exit_reason = str(closed_pos.get("exit_reason", "")).lower()
    pnl_dollars = float(closed_pos.get("pnl_dollars", 0.0))

    if "target" in exit_reason or "profit" in exit_reason:
        outcome = "win"
    elif "time" in exit_reason:
        outcome = "time_stop"
    elif "stop" in exit_reason:
        outcome = "loss"
    else:
        outcome = "win" if pnl_dollars >= 0 else "loss"

    holding_days = ""
    if len(opened_at) >= 10 and len(closed_at) >= 10:
        try:
            opened_date = datetime.fromisoformat(opened_at.replace("Z", "+00:00")).date()
            closed_date = datetime.fromisoformat(closed_at.replace("Z", "+00:00")).date()
            holding_days = (closed_date - opened_date).days
        except ValueError:
            holding_days = ""

    log_trade_outcome({
        "timestamp_utc": closed_at,
        "ticker": closed_pos.get("ticker", ""),
        "entry_date": opened_at[:10] if len(opened_at) >= 10 else "",
        "exit_date": closed_at[:10] if len(closed_at) >= 10 else "",
        "entry_price": closed_pos.get("entry_price", ""),
        "exit_price": closed_pos.get("exit_price", ""),
        "direction": closed_pos.get("direction", ""),
        "structure": closed_pos.get("structure", ""),
        "confidence_score": closed_pos.get("confidence", ""),
        "holding_days": holding_days,
        "pnl_dollars": pnl_dollars,
        "pnl_pct": closed_pos.get("pnl_pct", ""),
        "outcome": outcome,
    })


def _log_override(ticker: str, reason: str, position_details: Optional[dict]) -> None:
    """Append override/skip to override_log.csv."""
    _OVERRIDE_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    write_header = not _OVERRIDE_LOG_FILE.exists()
    fieldnames = ["timestamp_utc", "ticker", "reason", "confidence"]
    with _OVERRIDE_LOG_FILE.open("a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if write_header:
            writer.writeheader()
        writer.writerow({
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "ticker": ticker,
            "reason": reason,
            "confidence": position_details.get("confidence", "") if position_details else "",
        })
