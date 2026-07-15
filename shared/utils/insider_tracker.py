"""
SHARED: Fetches SEC Form 4 insider transactions via yfinance.
Flags unusual buying/selling clusters.
Insider buying = high-conviction bullish signal.
Insider selling cluster (multiple executives, short window) = bearish modifier.
Note: yfinance insider data has 1-2 business day delay — treat as confirmation only.
"""

from datetime import datetime, timezone, timedelta

import pandas as pd


def get_insider_signal(
    ticker: str,
    lookback_days: int = 30,
) -> dict:
    """
    Fetch and classify recent insider transactions.

    Returns dict:
    {
        signal: str,                   # 'buying', 'selling_cluster', 'neutral'
        confidence_modifier: float,    # -8 to +8
        transactions: list[dict],
        rationale: str,
    }

    Buying cluster: 2+ distinct insiders buying within 10 trading days → +8
    Selling cluster: 2+ distinct insiders selling within 10 trading days → -8
    Single large buy → +4; single large sell → -3 (asymmetric — insiders sell for many reasons)
    """
    from shared.api_clients.market_data_client import fetch_insider_transactions

    raw = fetch_insider_transactions(ticker)
    if raw is None or len(raw) == 0:
        return {
            "signal": "neutral",
            "confidence_modifier": 0.0,
            "transactions": [],
            "rationale": "No insider transaction data available.",
        }

    # Filter to lookback window
    cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)
    recent = []
    for tx in raw:
        ts = tx.get("date") or tx.get("startdate")
        if ts is None:
            continue
        if isinstance(ts, str):
            try:
                ts = datetime.fromisoformat(ts)
            except ValueError:
                continue
        if isinstance(ts, pd.Timestamp):
            ts = ts.to_pydatetime()
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        if ts >= cutoff:
            recent.append({**tx, "_parsed_date": ts})

    if not recent:
        return {
            "signal": "neutral",
            "confidence_modifier": 0.0,
            "transactions": [],
            "rationale": f"No insider activity in last {lookback_days} days.",
        }

    signal = classify_transactions(recent, window_days=10)
    modifier = _signal_to_modifier(signal, recent)

    return {
        "signal": signal,
        "confidence_modifier": modifier,
        "transactions": recent,
        "rationale": _build_rationale(signal, recent),
    }


def classify_transactions(transactions: list[dict], window_days: int = 10) -> str:
    """
    Classify a list of insider transactions as 'buying', 'selling_cluster', or 'neutral'.
    Cluster: 2+ distinct insiders transacting in same direction within window_days.
    """
    if not transactions:
        return "neutral"

    buy_insiders = set()
    sell_insiders = set()

    cutoff_relative = timedelta(days=window_days)
    if not transactions:
        return "neutral"

    # Find most-recent transaction date as anchor
    dates = []
    for tx in transactions:
        d = tx.get("_parsed_date")
        if d:
            dates.append(d)
    if not dates:
        return "neutral"
    anchor = max(dates)

    for tx in transactions:
        d = tx.get("_parsed_date")
        if d is None or (anchor - d) > cutoff_relative:
            continue
        insider_id = tx.get("insider") or tx.get("name") or tx.get("filerName", "unknown")
        # yfinance uses "Shares" for buy quantity, negative for sells
        shares = tx.get("shares") or tx.get("Shares") or 0
        transaction_type = str(tx.get("transaction") or tx.get("Transaction") or "").lower()
        if "sale" in transaction_type or "sell" in transaction_type or float(shares) < 0:
            sell_insiders.add(insider_id)
        elif "purchase" in transaction_type or "buy" in transaction_type or float(shares) > 0:
            buy_insiders.add(insider_id)

    if len(buy_insiders) >= 2:
        return "buying"
    if len(sell_insiders) >= 2:
        return "selling_cluster"
    if len(buy_insiders) == 1:
        return "buying"  # Single buyer still flagged as buying signal
    return "neutral"


def _signal_to_modifier(signal: str, transactions: list[dict]) -> float:
    """Convert classified signal to confidence modifier (-8 to +8)."""
    if signal == "buying":
        # 2+ distinct buyers → +8; single buyer → +4
        buyers = set(tx.get("insider") or tx.get("name", "x") for tx in transactions
                     if "purchase" in str(tx.get("transaction", "")).lower()
                     or "buy" in str(tx.get("transaction", "")).lower())
        return 8.0 if len(buyers) >= 2 else 4.0
    if signal == "selling_cluster":
        return -8.0
    return 0.0


def _build_rationale(signal: str, transactions: list[dict]) -> str:
    n = len(transactions)
    if signal == "buying":
        return f"{n} insider purchase(s) in lookback window — bullish signal."
    if signal == "selling_cluster":
        return f"{n} insider sale(s) in lookback window — bearish cluster signal."
    return "No significant insider activity pattern."
