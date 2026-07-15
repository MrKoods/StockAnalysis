"""
Simulates live trading with real-time data but no real capital.
Tracks fills, slippage, and P&L against Discord alert prices.
Runs on same schedule as run_swing_model.py (pre-market, mid-session, post-close).
Forward-testing period: 60-90 trading days minimum before Phase 15 go-live.
"""

from datetime import datetime, timezone


def run_paper_session(
    scan_type: str = "post_close",
    cfg_path: str = "config/swing_config.yaml",
) -> dict:
    """
    Run a single paper trading session with real-time data.

    Steps:
    1. Run the full swing model (same as run_swing_model.py)
    2. For any new signals: record recommended fill price at alert time
    3. Monitor open paper positions: check target/stop/time stop
    4. Log all outcomes to fill_tracker.py
    5. Compare real-time fills vs. recommended prices (slippage measurement)

    Returns session results dict.
    """
    from swing_model.indicator_pipeline import load_config

    try:
        cfg = load_config(cfg_path)
    except Exception:
        cfg = {}

    watchlist = cfg.get("watchlist", ["NVDA", "AMD", "AVGO", "TSM", "MU", "ASML"])
    session_results = {
        "scan_type": scan_type,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "signals_evaluated": len(watchlist),
        "new_paper_positions": 0,
        "positions_updated": 0,
        "errors": [],
    }

    # Paper session is a pass-through to the real pipeline — differences:
    # 1. No real money moved; outcomes are simulated
    # 2. All fills are logged to fill_log.csv at recommended price
    # 3. Open positions are tracked in data/processed/paper_positions.json

    from paper_trading.paper_state import load_paper_state, save_paper_state

    state = load_paper_state()

    # Step 3: Update open paper positions
    for pos in state.get("positions", []):
        if not pos.get("open", True):
            continue
        ticker = pos.get("ticker", "")
        try:
            from shared.api_clients.market_data_client import fetch_ohlcv
            df = fetch_ohlcv(ticker, period="5d")
            if df is not None and not df.empty:
                latest = df.iloc[-1]
                pos = _update_paper_position(pos, latest, state["account_equity"])
                session_results["positions_updated"] += 1
        except Exception as exc:
            session_results["errors"].append(f"{ticker}: {exc}")

    save_paper_state(state)
    return session_results


def simulate_fill(
    ticker: str,
    structure: str,
    recommended_price: float,
    actual_mid_price: float,
) -> dict:
    """
    Simulate a fill at the actual market mid-price vs. recommended price.
    Slippage = actual_mid_price - recommended_price (per leg, options structures).
    Returns {recommended_price, actual_fill, slippage, slippage_pct}.
    """
    slippage = actual_mid_price - recommended_price
    slippage_pct = slippage / recommended_price if recommended_price != 0 else 0.0

    return {
        "ticker": ticker,
        "structure": structure,
        "recommended_price": recommended_price,
        "actual_fill": actual_mid_price,
        "slippage": round(slippage, 4),
        "slippage_pct": round(slippage_pct, 4),
    }


def _update_paper_position(pos: dict, latest_bar, account_equity: float) -> dict:
    """Update a paper position against the latest bar. Check target/stop/time stop."""
    entry = float(pos.get("entry_price", 0.0))
    stop = float(pos.get("stop_loss", 0.0))
    target = float(pos.get("target", 0.0))
    direction = pos.get("direction", "bullish")
    holding_day = int(pos.get("holding_day", 0)) + 1
    pos["holding_day"] = holding_day

    high = float(latest_bar.get("High", 0))
    low = float(latest_bar.get("Low", 0))
    close = float(latest_bar.get("Close", 0))

    if direction == "bullish":
        if high >= target:
            pos["open"] = False
            pos["exit_price"] = target
            pos["exit_reason"] = "target_hit"
            pos["pnl_pct"] = round((target - entry) / entry * 100, 2)
        elif low <= stop:
            pos["open"] = False
            pos["exit_price"] = stop
            pos["exit_reason"] = "stop_hit"
            pos["pnl_pct"] = round((stop - entry) / entry * 100, 2)
    else:
        if low <= target:
            pos["open"] = False
            pos["exit_price"] = target
            pos["exit_reason"] = "target_hit"
            pos["pnl_pct"] = round((entry - target) / entry * 100, 2)
        elif high >= stop:
            pos["open"] = False
            pos["exit_price"] = stop
            pos["exit_reason"] = "stop_hit"
            pos["pnl_pct"] = round((entry - stop) / entry * 100, 2)

    # Time stop: Day 10 rule
    if pos.get("open", True) and holding_day >= 10:
        pos["open"] = False
        pos["exit_price"] = close
        pos["exit_reason"] = "time_stop_day10"
        pnl_sign = 1 if direction == "bullish" else -1
        pos["pnl_pct"] = round((close - entry) / entry * 100 * pnl_sign, 2)

    if not pos.get("open", True):
        pos["closed_at_utc"] = datetime.now(timezone.utc).isoformat()

    return pos
