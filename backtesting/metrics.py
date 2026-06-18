import math
from collections import defaultdict


def compute_win_rate(trades: list[dict]) -> float:
    """Return the fraction of trades that were profitable."""
    if not trades:
        return 0.0
    wins = sum(1 for t in trades if t.get("pnl_pct", 0.0) > 0)
    return wins / len(trades)


def compute_average_rr(trades: list[dict]) -> float:
    """Return the average realized reward-to-risk ratio across all closed trades."""
    realized = [t["realized_rr"] for t in trades if "realized_rr" in t]
    if not realized:
        return 0.0
    return sum(realized) / len(realized)


def compute_max_drawdown(equity_curve: list[float]) -> float:
    """Return the maximum peak-to-trough drawdown as a fraction of peak equity."""
    if len(equity_curve) < 2:
        return 0.0
    peak = equity_curve[0]
    max_dd = 0.0
    for val in equity_curve:
        if val > peak:
            peak = val
        dd = (peak - val) / peak
        if dd > max_dd:
            max_dd = dd
    return max_dd


def compute_profit_factor(trades: list[dict]) -> float:
    """Return gross winning P&L divided by gross losing P&L (absolute value).

    A value >1.0 means the strategy earns more on winners than it loses on losers.
    Infinity is returned when there are no losing trades.
    """
    gross_win = sum(t["pnl_pct"] for t in trades if t.get("pnl_pct", 0.0) > 0)
    gross_loss = abs(sum(t["pnl_pct"] for t in trades if t.get("pnl_pct", 0.0) < 0))
    if gross_loss == 0.0:
        return float("inf") if gross_win > 0 else 0.0
    return gross_win / gross_loss


def compute_risk_normalized_drawdown(trades: list[dict], risk_per_trade: float = 0.01) -> float:
    """Max drawdown on a fixed-fractional equity curve that risks `risk_per_trade` per trade.

    Each trade's P&L is scaled to realized_rr * risk_per_trade, so the curve reflects
    actual edge rather than raw dollar-move magnitude. Eliminates the high-IV artifact
    that inflates raw drawdown numbers on volatile semiconductors.
    """
    equity = 1.0
    curve = [equity]
    for t in sorted(trades, key=lambda x: x["entry_date"]):
        rr = t.get("realized_rr", 0.0)
        equity *= 1.0 + rr * risk_per_trade
        curve.append(equity)
    return compute_max_drawdown(curve)


def compute_sharpe_ratio(returns: list[float], risk_free_rate: float = 0.0) -> float:
    """Return the annualized Sharpe ratio for the given return series (assumed daily)."""
    if len(returns) < 2:
        return 0.0
    n = len(returns)
    mean_r = sum(returns) / n
    variance = sum((r - mean_r) ** 2 for r in returns) / (n - 1)
    std_r = math.sqrt(variance)
    if std_r == 0.0:
        return 0.0
    return ((mean_r - risk_free_rate) / std_r) * math.sqrt(252)


def compute_monthly_breakdown(trades: list[dict]) -> list[dict]:
    """Return per-calendar-month stats: trade count, wins, win rate, and avg P&L."""
    monthly: dict[str, list[dict]] = defaultdict(list)
    for t in trades:
        entry_date = t.get("entry_date")
        if entry_date is None:
            continue
        month_key = entry_date.strftime("%Y-%m") if hasattr(entry_date, "strftime") else str(entry_date)[:7]
        monthly[month_key].append(t)

    rows = []
    for month in sorted(monthly.keys()):
        month_trades = monthly[month]
        wins = sum(1 for t in month_trades if t.get("pnl_pct", 0.0) > 0)
        avg_pnl = sum(t.get("pnl_pct", 0.0) for t in month_trades) / len(month_trades)
        rows.append({
            "month": month,
            "trades": len(month_trades),
            "wins": wins,
            "win_rate": round(wins / len(month_trades), 4),
            "avg_pnl_pct": round(avg_pnl, 4),
        })
    return rows


def generate_report(trades: list[dict], equity_curve: list[float]) -> dict:
    """Aggregate all metrics into a single summary dict suitable for printing or writing to file."""
    if not trades:
        return {
            "total_trades": 0,
            "win_rate": 0.0,
            "profit_factor": 0.0,
            "risk_norm_drawdown": 0.0,
            "avg_rr": 0.0,
            "max_drawdown": 0.0,
            "sharpe_ratio": 0.0,
            "winning_trades": 0,
            "losing_trades": 0,
        }

    returns = [t.get("pnl_pct", 0.0) for t in trades]
    pf = compute_profit_factor(trades)

    return {
        "total_trades": len(trades),
        "win_rate": round(compute_win_rate(trades), 4),
        "profit_factor": round(pf, 4) if pf != float("inf") else pf,
        "risk_norm_drawdown": round(compute_risk_normalized_drawdown(trades), 4),
        "avg_rr": round(compute_average_rr(trades), 4),
        "max_drawdown": round(compute_max_drawdown(equity_curve), 4),
        "sharpe_ratio": round(compute_sharpe_ratio(returns), 4),
        "winning_trades": sum(1 for t in trades if t.get("pnl_pct", 0.0) > 0),
        "losing_trades": sum(1 for t in trades if t.get("pnl_pct", 0.0) <= 0),
    }
