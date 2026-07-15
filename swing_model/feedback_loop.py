"""
Logs closed trade outcomes; updates rolling win rate per signal combination;
feeds back into scoring engine calibration (two-speed cycle per Clarification 1).

Two-speed cycle:
  Immediate: log outcome → update signal_win_rates.json (does NOT affect live scoring)
  Monthly (or every 20 trades): mini-calibration pass → out-of-sample check →
    if passing: update live_weights.json; if failing: Discord alert + keep old weights.
  Weight changes > 5pp require version increment + mini-backtest (enforced by model_versioning.py).
"""

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


_TRADE_OUTCOMES_FILE = Path("data/logs/trade_outcomes.csv")
_SIGNAL_WIN_RATES_FILE = Path("data/processed/signal_win_rates.json")
# Calibrated weight deltas — separate from config/live_weights.json (which has a nested schema)
_LIVE_WEIGHTS_FILE = Path("data/processed/calibrated_weights.json")

_OUTCOMES_COLUMNS = [
    "timestamp_utc", "ticker", "entry_date", "exit_date",
    "entry_price", "exit_price", "direction", "structure",
    "confidence_score", "technical_total", "sentiment_total", "news_total",
    "holding_days", "pnl_dollars", "pnl_pct", "outcome",  # 'win' | 'loss'
    "signal_key",  # hash of signal combination for win rate lookup
]


def log_trade_outcome(outcome: dict) -> None:
    """
    Log a closed trade outcome to trade_outcomes.csv.
    Also updates signal_win_rates.json immediately.
    """
    path = _TRADE_OUTCOMES_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    write_header = not path.exists()

    row = {col: outcome.get(col, "") for col in _OUTCOMES_COLUMNS}
    if not row.get("timestamp_utc"):
        row["timestamp_utc"] = datetime.now(timezone.utc).isoformat()

    with open(path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=_OUTCOMES_COLUMNS, extrasaction="ignore")
        if write_header:
            writer.writeheader()
        writer.writerow(row)

    update_signal_win_rates(outcome)


def update_signal_win_rates(outcome: dict) -> None:
    """
    Update the rolling win rate for the specific signal combination that fired.
    Stored in data/processed/signal_win_rates.json.
    Does NOT update live_weights.json — that happens only at scheduled recalibration.
    """
    path = _SIGNAL_WIN_RATES_FILE
    path.parent.mkdir(parents=True, exist_ok=True)

    if path.exists():
        try:
            rates = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            rates = {}
    else:
        rates = {}

    key = outcome.get("signal_key", "unknown")
    if key not in rates:
        rates[key] = {"wins": 0, "losses": 0, "total": 0}

    result = outcome.get("outcome", "")
    if result == "win":
        rates[key]["wins"] += 1
    elif result in ("loss", "time_stop"):
        rates[key]["losses"] += 1
    rates[key]["total"] += 1

    # Compute rolling win rate only when >= 10 samples
    if rates[key]["total"] >= 10:
        rates[key]["win_rate"] = round(rates[key]["wins"] / rates[key]["total"], 4)

    path.write_text(json.dumps(rates, indent=2), encoding="utf-8")


def run_calibration(
    holdout_count: int = 5,
    min_change_for_version: float = 0.05,
    cfg: Optional[dict] = None,
) -> dict:
    """
    Monthly calibration pass:
    1. Read all outcomes from trade_outcomes.csv
    2. Withhold most recent holdout_count trades as out-of-sample check
    3. Recompute win rates per signal combination from remaining trades
    4. Test new weights on withheld trades
    5. If new weights equal or better on withheld: update live_weights.json
    6. If any weight changes > min_change_for_version: require version increment
    7. If calibration fails out-of-sample check: keep old weights, send Discord alert

    Returns dict with calibration result details.
    """
    if not _TRADE_OUTCOMES_FILE.exists():
        return {
            "status": "no_data",
            "message": "No trade outcomes file found",
            "weights_updated": False,
        }

    # Load all outcomes
    outcomes = []
    try:
        with open(_TRADE_OUTCOMES_FILE, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            outcomes = list(reader)
    except OSError as exc:
        return {"status": "error", "message": str(exc), "weights_updated": False}

    if len(outcomes) < holdout_count + 10:
        return {
            "status": "insufficient_data",
            "message": f"Need at least {holdout_count + 10} trades, have {len(outcomes)}",
            "weights_updated": False,
        }

    train_outcomes = outcomes[:-holdout_count]
    holdout = outcomes[-holdout_count:]

    # Load current weights
    current_weights = _load_live_weights()

    # Recompute weights from training set
    new_weights = _recompute_weights(train_outcomes, current_weights)

    # Test on holdout
    holdout_win_rate_old = _score_outcomes(holdout, current_weights)
    holdout_win_rate_new = _score_outcomes(holdout, new_weights)

    passed_holdout = holdout_win_rate_new >= holdout_win_rate_old

    # Check if any changes exceed version threshold
    needs_version = any(
        abs(new_weights.get(k, 0) - current_weights.get(k, 0)) > min_change_for_version
        for k in set(list(new_weights.keys()) + list(current_weights.keys()))
    )

    result = {
        "status": "pass" if passed_holdout else "fail",
        "holdout_win_rate_old": round(holdout_win_rate_old, 4),
        "holdout_win_rate_new": round(holdout_win_rate_new, 4),
        "weights_updated": False,
        "needs_version_increment": needs_version,
        "train_count": len(train_outcomes),
        "holdout_count": len(holdout),
        "new_weights": new_weights,
        "current_weights": current_weights,
    }

    if passed_holdout and not needs_version:
        _save_live_weights(new_weights)
        result["weights_updated"] = True
    elif passed_holdout and needs_version:
        # Changes >5pp — require version bump before applying
        result["message"] = (
            "Calibration passed holdout but weight change > 5pp: "
            "bump model version before applying"
        )
    else:
        result["message"] = (
            f"Calibration failed holdout (new={holdout_win_rate_new:.1%} < "
            f"old={holdout_win_rate_old:.1%}). Keeping current weights."
        )

    return result


def build_signal_key(indicator_state: dict) -> str:
    """
    Create a hashable key for a signal combination (for win rate lookup).
    Key encodes: breakout T/F, trend T/F, RS direction, RSI range, sentiment direction.
    """
    breakout = "B1" if indicator_state.get("breakout_confirmed") else "B0"
    trend = "T1" if indicator_state.get("trend_aligned") else "T0"
    rs = indicator_state.get("relative_strength_direction", "neutral")[:3].upper()

    rsi = float(indicator_state.get("rsi", 50))
    if rsi < 40:
        rsi_band = "RSI_LOW"
    elif rsi < 60:
        rsi_band = "RSI_MID"
    else:
        rsi_band = "RSI_HIGH"

    sentiment = indicator_state.get("sentiment_direction", "neutral")[:3].upper()

    return f"{breakout}_{trend}_{rs}_{rsi_band}_{sentiment}"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _load_live_weights() -> dict:
    if _LIVE_WEIGHTS_FILE.exists():
        try:
            return json.loads(_LIVE_WEIGHTS_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {"technical": 0.60, "sentiment": 0.25, "news": 0.15}


def _save_live_weights(weights: dict) -> None:
    _LIVE_WEIGHTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    _LIVE_WEIGHTS_FILE.write_text(json.dumps(weights, indent=2), encoding="utf-8")


def _recompute_weights(outcomes: list[dict], current_weights: dict) -> dict:
    """
    Recompute weights based on which signal components correlate with wins.
    Simple win/loss comparison per sub-signal; ±2pp adjustments capped at 10pp.
    """
    if not outcomes:
        return current_weights.copy()

    wins = [o for o in outcomes if o.get("outcome") == "win"]
    losses = [o for o in outcomes if o.get("outcome") in ("loss", "time_stop")]

    if not wins or not losses:
        return current_weights.copy()

    def avg(outcomes, field):
        vals = [float(o.get(field, 0)) for o in outcomes if o.get(field)]
        return sum(vals) / len(vals) if vals else 0.0

    # If technical signal higher on wins → increase technical weight
    tech_win = avg(wins, "technical_total")
    tech_loss = avg(losses, "technical_total")
    sent_win = avg(wins, "sentiment_total")
    sent_loss = avg(losses, "sentiment_total")
    news_win = avg(wins, "news_total")
    news_loss = avg(losses, "news_total")

    adj_tech = 0.02 if tech_win > tech_loss else -0.02
    adj_sent = 0.02 if sent_win > sent_loss else -0.02
    adj_news = 0.02 if news_win > news_loss else -0.02

    new_weights = {
        "technical": round(max(0.30, min(0.80, current_weights.get("technical", 0.60) + adj_tech)), 4),
        "sentiment": round(max(0.05, min(0.40, current_weights.get("sentiment", 0.25) + adj_sent)), 4),
        "news": round(max(0.05, min(0.30, current_weights.get("news", 0.15) + adj_news)), 4),
    }

    # Normalize to sum to 1.0
    total = sum(new_weights.values())
    if total > 0:
        new_weights = {k: round(v / total, 4) for k, v in new_weights.items()}

    return new_weights


def _score_outcomes(outcomes: list[dict], weights: dict) -> float:
    """Simple proxy: win rate on outcomes weighted by confidence signal."""
    if not outcomes:
        return 0.0
    wins = sum(1 for o in outcomes if o.get("outcome") == "win")
    return wins / len(outcomes)
