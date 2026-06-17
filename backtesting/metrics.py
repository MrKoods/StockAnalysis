# SHARED: Backtest performance metrics — the same calculations apply to both swing and day results.


def compute_win_rate(trades: list[dict]) -> float:
    """Return the fraction of trades that were profitable."""
    pass


def compute_average_rr(trades: list[dict]) -> float:
    """Return the average realized reward-to-risk ratio across all closed trades."""
    pass


def compute_max_drawdown(equity_curve: list[float]) -> float:
    """Return the maximum peak-to-trough drawdown as a fraction of peak equity."""
    pass


def compute_sharpe_ratio(returns: list[float], risk_free_rate: float = 0.0) -> float:
    """Return the annualized Sharpe ratio for the given return series."""
    pass


def generate_report(trades: list[dict], equity_curve: list[float]) -> dict:
    """Aggregate all metrics into a single summary dict suitable for printing or writing to file."""
    pass
