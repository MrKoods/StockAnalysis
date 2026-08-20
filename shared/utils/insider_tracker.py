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
    direction: str = "bullish",
) -> dict:
    """
    Fetch and classify recent insider transactions.

    Returns dict:
    {
        signal: str,                   # 'buying', 'selling_cluster', 'selling', 'neutral'
        confidence_modifier: float,    # -8 to +8
        transactions: list[dict],
        rationale: str,
    }

    Buying cluster: 2+ distinct insiders buying within 10 trading days → +8 (bullish)
    Selling cluster: 2+ distinct insiders selling within 10 trading days → -8 (bullish)
    Single large buy → +4; single large sell → -3 (asymmetric — insiders sell for many reasons)

    `direction="bearish"` sign-flips confidence_modifier (selling confirms a bearish
    thesis, buying opposes it), same convention as regime_detection/macro_overlay's
    modifiers. This function itself is currently unused — the real, wired-in insider
    signal is swing_model/positioning_layer.py's `_score_insider`, which has its own
    already-mirrored bearish ladder. Kept mirrored here too so this doesn't become an
    unmirrored bullish-only landmine if it's ever wired in as a standalone modifier.
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
    modifier = _signal_to_modifier(signal, recent, direction=direction)

    return {
        "signal": signal,
        "confidence_modifier": modifier,
        "transactions": recent,
        "rationale": _build_rationale(signal, recent),
    }


def count_distinct_traders(transactions: list[dict], window_days: int = 10) -> tuple[set, set]:
    """
    Return (buy_insiders, sell_insiders) — distinct insider ids transacting within
    window_days of the most recent transaction in the list. Single source of truth
    for buy/sell classification: a transaction counts as a buy/sell from either its
    text field ("purchase"/"buy"/"sale"/"sell") OR its shares sign (yfinance uses
    "Shares", negative for sells) — matching either is sufficient.

    Used by both classify_transactions (below) and swing_model/positioning_layer.py's
    _score_insider, which used to re-derive its own buyer count from only the text
    field and with no date window at all — diverging from classify_transactions
    whenever a transaction was classified via its shares sign, or was outside the
    window, giving inconsistent scoring for the same signal.
    """
    buy_insiders: set = set()
    sell_insiders: set = set()
    if not transactions:
        return buy_insiders, sell_insiders

    dates = [tx.get("_parsed_date") for tx in transactions if tx.get("_parsed_date")]
    if not dates:
        return buy_insiders, sell_insiders
    anchor = max(dates)
    cutoff_relative = timedelta(days=window_days)

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

    return buy_insiders, sell_insiders


def classify_transactions(transactions: list[dict], window_days: int = 10) -> str:
    """
    Classify a list of insider transactions as 'buying', 'selling_cluster',
    'selling', or 'neutral'. Cluster: 2+ distinct insiders transacting in
    same direction within window_days.

    A single seller used to fall through every branch to 'neutral' — this
    module's own docstring promises "single large sell -> -3 (asymmetric —
    insiders sell for many reasons)", but no code path produced that signal,
    so a lone insider sale (far more common than a same-window cluster of 2+
    sellers — routine 10b5-1 sales, tax-related sales, etc.) was invisible,
    scored identically to having zero insider data at all.
    """
    if not transactions:
        return "neutral"

    buy_insiders, sell_insiders = count_distinct_traders(transactions, window_days)

    if len(buy_insiders) >= 2:
        return "buying"
    if len(sell_insiders) >= 2:
        return "selling_cluster"
    if len(buy_insiders) == 1:
        return "buying"  # Single buyer still flagged as buying signal
    if len(sell_insiders) == 1:
        return "selling"  # Single seller — modest bearish signal, see _signal_to_modifier
    return "neutral"


def _signal_to_modifier(
    signal: str,
    transactions: list[dict],
    window_days: int = 10,
    direction: str = "bullish",
) -> float:
    """Convert classified signal to confidence modifier (-8 to +8).

    Bearish sign-flips the raw (bullish-shaped) value: insider selling confirms
    a bearish thesis (positive), insider buying opposes it (negative).
    """
    if signal == "buying":
        # 2+ distinct buyers → +8; single buyer → +4
        buy_insiders, _ = count_distinct_traders(transactions, window_days)
        raw = 8.0 if len(buy_insiders) >= 2 else 4.0
    elif signal == "selling_cluster":
        raw = -8.0
    elif signal == "selling":
        raw = -3.0
    else:
        raw = 0.0
    return -raw if direction == "bearish" else raw


def _build_rationale(signal: str, transactions: list[dict]) -> str:
    n = len(transactions)
    if signal == "buying":
        return f"{n} insider purchase(s) in lookback window — bullish signal."
    if signal == "selling_cluster":
        return f"{n} insider sale(s) in lookback window — bearish cluster signal."
    if signal == "selling":
        return f"{n} insider sale(s) in lookback window — single seller, modest bearish signal."
    return "No significant insider activity pattern."
