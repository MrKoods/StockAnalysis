"""
Slippage simulation for paper trading fills — compares the actual real-time market
price against the price a Discord alert recommended.

The actual paper-trading orchestration (running the full swing model, logging new
signals, tracking open positions to resolution) lives in paper_trading/paper_runner.py
(run_paper_scan, scheduled the same as run_swing_model.py) and paper_trading/paper_updater.py
(resolves open signals against target/stop/time-stop), both operating on
paper_trading/paper_trades.csv. An earlier, parallel orchestrator (run_paper_session,
tracking state in data/processed/paper_positions.json) was removed from this module:
nothing ever populated paper_positions.json with open positions, so it could never do
anything but no-op — paper_runner.py/paper_updater.py is the real, wired-up pathway.
"""


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
