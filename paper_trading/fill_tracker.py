"""
Logs recommended price vs. actual fill price per trade.
Feeds slippage model calibration in options_math.py.
Quarterly recalibration: if actual slippage > 15% above modeled estimates,
fires Discord alert recommending review of structure liquidity thresholds.
"""

import csv
from datetime import datetime, timezone
from pathlib import Path


_FILL_LOG_FILE = Path("data/logs/fill_log.csv")

_FILL_LOG_COLUMNS = [
    "timestamp_utc", "ticker", "structure", "recommended_price",
    "actual_fill_price", "slippage_dollar", "slippage_pct",
    "num_legs", "notes",
]


def log_fill(
    ticker: str,
    structure: str,
    recommended_price: float,
    actual_fill_price: float,
    num_legs: int = 1,
    notes: str = "",
) -> None:
    """Append a fill record to data/logs/fill_log.csv."""
    slippage = actual_fill_price - recommended_price
    slippage_pct = (slippage / recommended_price) if recommended_price != 0 else 0.0

    path = _FILL_LOG_FILE
    write_header = not path.exists()
    with open(path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=_FILL_LOG_COLUMNS, extrasaction="ignore")
        if write_header:
            writer.writeheader()
        writer.writerow({
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "ticker": ticker,
            "structure": structure,
            "recommended_price": recommended_price,
            "actual_fill_price": actual_fill_price,
            "slippage_dollar": round(slippage, 4),
            "slippage_pct": round(slippage_pct, 4),
            "num_legs": num_legs,
            "notes": notes,
        })


def compute_avg_slippage() -> dict:
    """
    Compute average slippage from fill_log.csv for calibration.
    Returns {avg_slippage_pct, max_slippage_pct, total_fills, period}.
    """
    if not _FILL_LOG_FILE.exists():
        return {"avg_slippage_pct": 0.0, "max_slippage_pct": 0.0, "total_fills": 0, "period": ""}

    rows = []
    try:
        import csv as _csv
        with open(_FILL_LOG_FILE, newline="", encoding="utf-8") as f:
            reader = _csv.DictReader(f)
            rows = list(reader)
    except Exception:
        return {"avg_slippage_pct": 0.0, "max_slippage_pct": 0.0, "total_fills": 0, "period": ""}

    if not rows:
        return {"avg_slippage_pct": 0.0, "max_slippage_pct": 0.0, "total_fills": 0, "period": ""}

    slippages = [abs(float(r.get("slippage_pct", 0.0))) for r in rows]
    dates = [r.get("timestamp_utc", "") for r in rows if r.get("timestamp_utc")]
    period = f"{min(dates)[:10]} to {max(dates)[:10]}" if dates else ""

    return {
        "avg_slippage_pct": round(sum(slippages) / len(slippages), 6),
        "max_slippage_pct": round(max(slippages), 6),
        "total_fills": len(rows),
        "period": period,
    }


def check_slippage_threshold(
    avg_slippage_pct: float,
    modeled_slippage_pct: float,
    threshold: float = 0.15,
) -> bool:
    """
    Return True if actual slippage exceeds modeled by more than threshold (15%).
    Triggers Discord alert if True (caller handles alert).
    """
    if modeled_slippage_pct <= 0:
        return False
    excess = (avg_slippage_pct - modeled_slippage_pct) / modeled_slippage_pct
    return excess > threshold
