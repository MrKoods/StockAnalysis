"""
Generates weekly Discord performance summary every Sunday at 6pm ET.
Covers: rolling win rate (last 10/20/50 trades), avg R:R vs. 1:3 target,
confidence score distribution, actual vs. theoretical EV per structure,
peak-to-trough drawdown.
Logs to data/logs/performance_log.csv.
Fires review alert if rolling 20-trade win rate drops below 70%.
"""

import csv
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


from shared.utils.logger import get_logger
from paper_trading.paper_trade_metrics import (
    evaluate_paper_trading_pass,
    load_paper_trade_gate_inputs,
    compute_signal_accuracy,
)

logger = get_logger(__name__)

_PERFORMANCE_LOG = Path("data/logs/performance_log.csv")
_REVIEW_TRIGGER_WIN_RATE = 0.70  # 20-trade rolling win rate below this triggers alert

_PERF_LOG_COLUMNS = [
    "timestamp_utc", "period_end",
    "win_rate_10", "win_rate_20", "win_rate_50",
    "avg_rr_20", "peak_to_trough_pct",
    "total_trades", "review_triggered",
]


def generate_weekly_summary(
    trade_outcomes_path: str = "data/logs/trade_outcomes.csv",
    cfg: Optional[dict] = None,
    paper_trades_path: Optional[Path] = None,
) -> dict:
    """
    Generate weekly performance summary and send to Discord.

    Covers:
    - Rolling win rate: last 10, 20, 50 trades
    - Average achieved R:R vs. 1:3 target
    - Confidence score distribution (histogram of surfaced scores)
    - Actual vs. theoretical EV per structure type
    - Peak-to-trough drawdown
    - Days since last review trigger

    Returns summary dict (including go_live_gate — see _compute_go_live_gate_summary)
    and logs to performance_log.csv.
    """
    # Independent of trade_outcomes_path/rows below — both the go-live gate
    # and the signal-accuracy view read paper_trading/paper_trades.csv (the
    # system that's actually running), not data/logs/trade_outcomes.csv (the
    # live/manual-confirmation path's file, unused since no version has gone
    # live) — see load_paper_trade_gate_inputs/compute_signal_accuracy.
    go_live_gate = _compute_go_live_gate_summary(paper_trades_path)
    signal_accuracy = _compute_signal_accuracy_summary(paper_trades_path)

    path = Path(trade_outcomes_path)
    if not path.exists():
        return {
            "status": "no_data",
            "win_rate_10": 0.0,
            "win_rate_20": 0.0,
            "win_rate_50": 0.0,
            "avg_rr_20": 0.0,
            "peak_to_trough_pct": 0.0,
            "total_trades": 0,
            "review_triggered": False,
            "go_live_gate": go_live_gate,
            "signal_accuracy": signal_accuracy,
        }

    try:
        with open(path, newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
    except OSError as exc:
        logger.warning(f"Cannot read trade outcomes: {exc}")
        return {"status": "error", "message": str(exc), "go_live_gate": go_live_gate, "signal_accuracy": signal_accuracy}

    if not rows:
        return {
            "status": "no_trades",
            "win_rate_10": 0.0, "win_rate_20": 0.0, "win_rate_50": 0.0,
            "avg_rr_20": 0.0, "peak_to_trough_pct": 0.0,
            "total_trades": 0, "review_triggered": False,
            "go_live_gate": go_live_gate,
            "signal_accuracy": signal_accuracy,
        }

    # Rolling win rates
    win_rate_10 = _rolling_win_rate(rows, 10)
    win_rate_20 = _rolling_win_rate(rows, 20)
    win_rate_50 = _rolling_win_rate(rows, 50)

    # Average R:R on last 20 wins
    last_20 = rows[-20:]
    win_rr_values = [float(r.get("achieved_rr", 0.0) or 0)
                     for r in last_20 if r.get("outcome") == "win"]
    avg_rr_20 = sum(win_rr_values) / len(win_rr_values) if win_rr_values else 0.0

    # Drawdown from equity curve
    pnl_values = [float(r.get("pnl_dollars", 0) or 0) for r in rows]
    peak_to_trough = _compute_peak_to_trough(pnl_values, starting_equity=15000.0)

    # Confidence score distribution
    confidence_scores = [float(r.get("confidence_score", 0) or 0) for r in rows if r.get("confidence_score")]
    conf_dist = _bucket_confidence(confidence_scores)

    # EV accuracy per structure
    ev_by_structure = _ev_accuracy_by_structure(rows)

    review_triggered = check_review_trigger(win_rate_20)

    summary = {
        "status": "ok",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_trades": len(rows),
        "win_rate_10": round(win_rate_10, 4),
        "win_rate_20": round(win_rate_20, 4),
        "win_rate_50": round(win_rate_50, 4),
        "avg_rr_20": round(avg_rr_20, 2),
        "peak_to_trough_pct": round(peak_to_trough * 100, 2),
        "confidence_distribution": conf_dist,
        "ev_accuracy_by_structure": ev_by_structure,
        "review_triggered": review_triggered,
        "go_live_gate": go_live_gate,
        "signal_accuracy": signal_accuracy,
    }

    log_performance_entry(summary)

    if review_triggered:
        logger.warning(
            f"PERFORMANCE REVIEW TRIGGERED: 20-trade win rate {win_rate_20:.1%} "
            f"< {_REVIEW_TRIGGER_WIN_RATE:.0%} threshold"
        )

    return summary


def check_review_trigger(rolling_20_win_rate: float) -> bool:
    """Return True if rolling 20-trade win rate dropped below review threshold (70%)."""
    return rolling_20_win_rate < _REVIEW_TRIGGER_WIN_RATE


def log_performance_entry(summary: dict) -> None:
    """Append performance summary to performance_log.csv."""
    path = _PERFORMANCE_LOG
    path.parent.mkdir(parents=True, exist_ok=True)
    write_header = not path.exists()

    row = {
        "timestamp_utc": summary.get("generated_at", datetime.now(timezone.utc).isoformat()),
        "period_end": summary.get("generated_at", "")[:10],
        "win_rate_10": summary.get("win_rate_10", 0.0),
        "win_rate_20": summary.get("win_rate_20", 0.0),
        "win_rate_50": summary.get("win_rate_50", 0.0),
        "avg_rr_20": summary.get("avg_rr_20", 0.0),
        "peak_to_trough_pct": summary.get("peak_to_trough_pct", 0.0),
        "total_trades": summary.get("total_trades", 0),
        "review_triggered": summary.get("review_triggered", False),
    }

    with open(path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=_PERF_LOG_COLUMNS, extrasaction="ignore")
        if write_header:
            writer.writeheader()
        writer.writerow(row)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _compute_go_live_gate_summary(paper_trades_path: Optional[Path] = None) -> dict:
    """
    Best-effort wrapper around evaluate_paper_trading_pass() for the weekly
    summary — a read failure here (missing file, malformed CSV row) shouldn't
    take down the rest of the performance report, so it degrades to an
    explicit error status rather than raising.
    """
    try:
        inputs = load_paper_trade_gate_inputs(paper_trades_path)
        return evaluate_paper_trading_pass(**inputs)
    except Exception as exc:
        logger.warning(f"Could not compute go-live gate: {exc}")
        return {"overall_pass": False, "data_status": "error", "failures": [str(exc)]}


def _compute_signal_accuracy_summary(paper_trades_path: Optional[Path] = None) -> dict:
    """
    Best-effort wrapper around compute_signal_accuracy() for the weekly
    summary — same reasoning as _compute_go_live_gate_summary: a read
    failure here shouldn't take down the rest of the performance report.
    """
    try:
        return compute_signal_accuracy(paper_trades_path)
    except Exception as exc:
        logger.warning(f"Could not compute signal accuracy: {exc}")
        return {"status": "error", "message": str(exc)}


def _rolling_win_rate(rows: list[dict], n: int) -> float:
    window = rows[-n:] if len(rows) >= n else rows
    if not window:
        return 0.0
    wins = sum(1 for r in window if r.get("outcome") == "win")
    return wins / len(window)


def _compute_peak_to_trough(pnl_values: list[float], starting_equity: float = 15000.0) -> float:
    """Compute peak-to-trough drawdown fraction from cumulative P&L."""
    if not pnl_values:
        return 0.0
    equity = starting_equity
    peak = equity
    max_dd = 0.0
    for pnl in pnl_values:
        equity += pnl
        if equity > peak:
            peak = equity
        if peak > 0:
            dd = (peak - equity) / peak
            max_dd = max(max_dd, dd)
    return max_dd


def _bucket_confidence(scores: list[float]) -> dict:
    """Group confidence scores into 5-point buckets."""
    buckets = {"85-89": 0, "90-92": 0, "93-95": 0, "96-98": 0, "99-100": 0}
    for s in scores:
        if 85 <= s < 90:
            buckets["85-89"] += 1
        elif 90 <= s <= 92:
            buckets["90-92"] += 1
        elif 93 <= s <= 95:
            buckets["93-95"] += 1
        elif 96 <= s <= 98:
            buckets["96-98"] += 1
        elif s >= 99:
            buckets["99-100"] += 1
    return buckets


def _ev_accuracy_by_structure(rows: list[dict]) -> dict:
    """Compute actual avg pnl vs theoretical EV per structure type."""
    by_structure: dict[str, dict] = {}
    for r in rows:
        structure = r.get("structure", "unknown")
        pnl = float(r.get("pnl_pct", 0) or 0)
        theoretical = float(r.get("theoretical_ev", 0) or 0)
        if structure not in by_structure:
            by_structure[structure] = {"pnl_sum": 0.0, "ev_sum": 0.0, "count": 0}
        by_structure[structure]["pnl_sum"] += pnl
        by_structure[structure]["ev_sum"] += theoretical
        by_structure[structure]["count"] += 1

    result = {}
    for s, d in by_structure.items():
        if d["count"] > 0:
            avg_pnl = d["pnl_sum"] / d["count"]
            avg_ev = d["ev_sum"] / d["count"]
            result[s] = {
                "avg_pnl_pct": round(avg_pnl, 4),
                "avg_theoretical_ev": round(avg_ev, 4),
                "accuracy_ratio": round(avg_pnl / avg_ev, 4) if avg_ev != 0 else 0.0,
                "count": d["count"],
            }
    return result


if __name__ == "__main__":
    # generate_weekly_summary() has no scheduled/cron caller yet (confirmed:
    # nothing outside tests calls it) — this lets the go-live gate status
    # (and the rest of the summary) actually be checked on demand rather than
    # only via test coverage.
    result = generate_weekly_summary()
    print(f"\nPerformance summary — status: {result.get('status')}\n")

    gate = result.get("go_live_gate", {})
    print(f"Go-live gate: overall_pass={gate.get('overall_pass')}  data_status={gate.get('data_status')}")
    if gate.get("failures"):
        print(f"  Failures: {', '.join(gate['failures'])}")

    if result.get("status") == "ok":
        print(f"\nWin rate (10/20/50): {result['win_rate_10']:.1%} / {result['win_rate_20']:.1%} / {result['win_rate_50']:.1%}")
        print(f"Avg R:R (last 20 wins): {result['avg_rr_20']:.2f}")
        print(f"Peak-to-trough drawdown: {result['peak_to_trough_pct']:.2f}%")
        print(f"Total trades: {result['total_trades']}")
        if result.get("review_triggered"):
            print("\n*** PERFORMANCE REVIEW TRIGGERED ***")
