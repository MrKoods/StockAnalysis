"""
Runs hypothetical extreme scenarios against current portfolio and scoring system.
Scenarios: SMH -30% in one week, NVDA -40% gap down overnight, VIX -> 80,
Fed emergency rate hike, China export restriction affecting ASML + TSM simultaneously.
Results stored in backtesting/ and summarized in a Discord stress test alert.
Run quarterly and whenever a new model version is deployed.
"""

from typing import Optional


SCENARIOS = {
    "smh_30_pct_drop": {
        "description": "SMH drops -30% over one week",
        "smh_shock_pct": -0.30,
        "duration_days": 5,
    },
    "nvda_40_gap_down": {
        "description": "NVDA gaps down -40% overnight",
        "ticker": "NVDA",
        "shock_pct": -0.40,
        "duration_days": 1,
    },
    "vix_spike_80": {
        "description": "VIX spikes to 80 (2008/COVID-level)",
        "vix_level": 80,
        "smh_shock_pct": -0.20,
    },
    "fed_emergency_hike": {
        "description": "Emergency Fed rate hike +100bps",
        "tnx_rise_pct": 0.25,
        "broad_shock_pct": -0.10,
    },
    "china_export_restriction": {
        "description": "China export restriction on ASML + TSM",
        "affected_tickers": ["ASML", "TSM"],
        "shock_pct": -0.25,
    },
}

# Default assumptions: beta of semiconductor stocks vs SMH
_SECTOR_BETA = {"NVDA": 1.4, "AMD": 1.3, "AVGO": 1.1, "TSM": 1.0, "MU": 1.2, "ASML": 1.0}


def run_all_scenarios(
    open_positions: list[dict],
    account_equity: float,
    cfg: Optional[dict] = None,
) -> dict:
    """
    Run all defined stress scenarios against current portfolio state.

    Returns dict mapping scenario_name -> scenario_result:
    {
        pnl_by_position: {ticker: pnl_dollars},
        total_pnl: float,
        pct_of_equity: float,
        circuit_breaker_triggered: str,  # 'none' | 'yellow' | 'orange' | 'red'
        worst_structure: str,
        best_structure: str,
        max_possible_loss: float,
    }
    """
    results = {}
    for name, scenario in SCENARIOS.items():
        results[name] = run_scenario(scenario, open_positions, account_equity)
    return results


def run_scenario(
    scenario: dict,
    open_positions: list[dict],
    account_equity: float,
) -> dict:
    """Run a single stress scenario. Returns scenario_result dict."""
    pnl_by_position = {}
    total_pnl = 0.0
    worst_structure = ""
    worst_pnl = 0.0
    best_structure = ""
    best_pnl = float("-inf")

    for pos in open_positions:
        ticker = pos.get("ticker", "")
        direction = pos.get("direction", "bullish")
        entry = float(pos.get("entry_price", 0.0))
        stop = float(pos.get("stop_loss", 0.0))
        risk_pct = float(pos.get("risk_pct", 0.01))
        structure = pos.get("structure", "long_stock")

        # Determine shock magnitude for this ticker
        shock_pct = _compute_shock(scenario, ticker)

        # Price after shock
        shocked_price = entry * (1 + shock_pct)

        # P&L as fraction of risk
        if direction == "bullish":
            price_move_pct = (shocked_price - entry) / entry
        else:
            price_move_pct = (entry - shocked_price) / entry

        risk_dollars = account_equity * risk_pct
        risk_dist = abs(entry - stop) / entry if entry > 0 and stop > 0 else risk_pct
        pnl_dollars = risk_dollars * (price_move_pct / risk_dist) if risk_dist > 0 else 0.0

        # Cap loss at 2x risk for defined risk structures
        if structure not in {"naked_short_call", "naked_short_put", "short_straddle", "short_strangle"}:
            pnl_dollars = max(pnl_dollars, -risk_dollars * 2)

        pnl_by_position[ticker] = round(pnl_dollars, 2)
        total_pnl += pnl_dollars

        if pnl_dollars < worst_pnl or not worst_structure:
            worst_pnl = pnl_dollars
            worst_structure = f"{ticker} ({structure})"
        if pnl_dollars > best_pnl:
            best_pnl = pnl_dollars
            best_structure = f"{ticker} ({structure})"

    pct_of_equity = total_pnl / account_equity if account_equity > 0 else 0.0
    drawdown = abs(min(0, pct_of_equity))

    if drawdown >= 0.15:
        cb = "red"
    elif drawdown >= 0.10:
        cb = "orange"
    elif drawdown >= 0.05:
        cb = "yellow"
    else:
        cb = "none"

    return {
        "description": scenario.get("description", ""),
        "pnl_by_position": pnl_by_position,
        "total_pnl": round(total_pnl, 2),
        "pct_of_equity": round(pct_of_equity * 100, 2),
        "circuit_breaker_triggered": cb,
        "worst_structure": worst_structure,
        "best_structure": best_structure,
        "max_possible_loss": round(min(0, total_pnl), 2),
    }


def _compute_shock(scenario: dict, ticker: str) -> float:
    """Determine the price shock magnitude for a specific ticker in a scenario."""
    beta = _SECTOR_BETA.get(ticker, 1.0)

    # Ticker-specific shock
    if scenario.get("ticker") == ticker:
        return float(scenario.get("shock_pct", 0.0))

    # China restriction scenario: only affects specific tickers
    affected = scenario.get("affected_tickers", [])
    if affected:
        if ticker in affected:
            return float(scenario.get("shock_pct", 0.0))
        else:
            return float(scenario.get("shock_pct", 0.0)) * 0.3  # Contagion

    # Broad market shock
    smh_shock = float(scenario.get("smh_shock_pct", scenario.get("broad_shock_pct", 0.0)))
    return smh_shock * beta
