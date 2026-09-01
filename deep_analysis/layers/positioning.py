"""
Deep positioning view — options (put/call, IV skew, DTE), short interest and
its trend, insider transactions (net direction, notable names), institutional
ownership, recent 13D/13G/13F filings, and analyst-rating movement.

Feed: swing_model's positioning_client.fetch_all_positioning (one call, all
sub-sources), plus SEC ownership filings.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from shared.utils.logger import get_logger
from shared.api_clients.positioning_client import fetch_all_positioning
from shared.api_clients.sec_edgar_client import fetch_recent_ownership_filings

logger = get_logger(__name__)


def _num(v):
    return v if isinstance(v, (int, float)) else None


def _insider_view(transactions: Optional[list], mspr: Optional[list], form4: Optional[list]) -> dict:
    """
    Reconcile the three insider sources into one coherent block instead of three
    that contradict each other: yfinance transaction rows (often empty, no
    values), Finnhub MSPR (monthly -100..+100 buy/sell pressure), and the count
    of SEC Form 4 filings in the last ~120 days.
    """
    buys = sells = buy_val = sell_val = 0
    names = []
    cutoff = datetime.now(timezone.utc).timestamp() - 180 * 86400
    for tx in transactions or []:
        ttype = str(tx.get("transaction_type", "")).lower()
        val = _num(tx.get("value")) or 0
        date = tx.get("date")
        try:
            if date and hasattr(date, "timestamp") and date.timestamp() < cutoff:
                continue
        except Exception:  # noqa: BLE001
            pass
        if "purchase" in ttype or "buy" in ttype:
            buys += 1
            buy_val += val
            names.append(f"BUY {tx.get('insider_name', '?')} ({tx.get('position', '')})")
        elif "sale" in ttype or "sell" in ttype:
            sells += 1
            sell_val += val

    mspr_latest = None
    if isinstance(mspr, list) and mspr and isinstance(mspr[0], dict):
        mspr_latest = _num(mspr[0].get("mspr"))
    form4_count = len(form4 or [])

    txn_count = buys + sells
    if txn_count:
        read = "net buying" if buy_val > sell_val else "net selling" if sell_val > buy_val else "balanced"
    elif mspr_latest is not None:
        read = ("selling pressure" if mspr_latest <= -20
                else "buying pressure" if mspr_latest >= 20 else "roughly neutral")
    else:
        read = "no usable insider data"

    return {
        "transaction_rows": txn_count,
        "buys": buys, "sells": sells,
        "buy_value": round(buy_val, 0), "sell_value": round(sell_val, 0),
        "net_value": round(buy_val - sell_val, 0) if txn_count else None,
        "mspr_latest": mspr_latest,
        "form4_filings_120d": form4_count,
        "read": read,
        "notable": names[:5],
        "note": (
            "yfinance returned no transaction detail; read is from Finnhub MSPR"
            if not txn_count and mspr_latest is not None else None
        ),
    }


def _observations(d: dict) -> list[str]:
    obs: list[str] = []
    o = d.get("options") or {}
    if o.get("put_call_ratio") is not None:
        obs.append(f"Options put/call ratio {o['put_call_ratio']:.2f} at {o.get('dte')} DTE; "
                   f"IV skew {o.get('iv_skew')} (positive = puts richer).")
    si = d.get("short_interest") or {}
    if si.get("short_percent_of_float") is not None:
        obs.append(f"Short interest {si['short_percent_of_float'] * 100:.1f}% of float, "
                   f"{si.get('short_ratio')} days to cover, trend {si.get('trend')}.")
    ins = d.get("insider") or {}
    if ins.get("read") and ins["read"] != "no usable insider data":
        parts = [f"Insider signal: {ins['read']}"]
        if ins.get("transaction_rows"):
            parts.append(f"{ins.get('buys', 0)} buys / {ins.get('sells', 0)} sells last 6mo, "
                         f"net ${(ins.get('net_value') or 0) / 1e6:+.1f}M")
        if ins.get("mspr_latest") is not None:
            parts.append(f"Finnhub MSPR {ins['mspr_latest']:+.0f} (-100..+100)")
        if ins.get("form4_filings_120d"):
            parts.append(f"{ins['form4_filings_120d']} Form 4 filings in ~120d")
        line = "; ".join(parts) + "."
        if ins.get("note"):
            line += f" ({ins['note']}.)"
        if ins.get("notable"):
            line += f" Notable: {'; '.join(ins['notable'])}."
        obs.append(line)
    inst = d.get("institutional") or {}
    if inst.get("held_percent_institutions") is not None:
        top = ", ".join(h.get("holder", "") for h in (inst.get("top_holders") or [])[:3])
        obs.append(f"Institutions hold {inst['held_percent_institutions'] * 100:.0f}%. Top: {top}.")
    of = d.get("ownership_filings") or {}
    for key, label in (("activist_13d", "activist 13D"), ("passive_13g", "passive 13G"), ("institutional_13f", "13F")):
        if of.get(key):
            obs.append(f"{len(of[key])} recent {label} filing(s), latest {of[key][0].get('filingDate')}.")
    at = d.get("analyst_trend") or {}
    if at.get("net_action") and at["net_action"] != "none":
        obs.append(f"Analyst rating movement: {at['net_action']} "
                   f"({at.get('recent_upgrades', 0)} up / {at.get('recent_downgrades', 0)} down notches).")
    return obs


def analyze_positioning(ticker: str, *, current_price: Optional[float] = None, cfg: Optional[dict] = None) -> dict:
    """Deep positioning view for `ticker`."""
    try:
        raw = fetch_all_positioning(ticker, current_price, cfg=cfg) or {}
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"{ticker}: fetch_all_positioning failed — {exc}")
        raw = {}

    ownership_filings = {}
    try:
        ownership_filings = fetch_recent_ownership_filings(ticker) or {}
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"{ticker}: SEC ownership filings failed — {exc}")

    detail = {
        "options": raw.get("options") or {},
        "short_interest": raw.get("short_interest") or {},
        "insider": _insider_view(
            raw.get("insider_transactions"), raw.get("insider_mspr"),
            ownership_filings.get("insider_form4"),
        ),
        "institutional": raw.get("institutional") or {},
        "analyst_trend": raw.get("analyst_trend") or {},
        "ownership_filings": ownership_filings,
    }

    present = sum(
        1 for v in (
            detail["options"].get("put_call_ratio"),
            detail["short_interest"].get("short_percent_of_float"),
            detail["insider"].get("read") not in (None, "no usable insider data"),
            detail["institutional"].get("held_percent_institutions"),
            detail["analyst_trend"].get("net_action") not in (None, "none"),
        ) if v
    )
    dq = "complete" if present >= 4 else "partial" if present >= 1 else "unavailable"

    summary = {
        "put_call_ratio": detail["options"].get("put_call_ratio"),
        "iv_skew": detail["options"].get("iv_skew"),
        "short_pct_float": detail["short_interest"].get("short_percent_of_float"),
        "short_trend": detail["short_interest"].get("trend"),
        "insider_read": detail["insider"].get("read"),
        "insider_net_value": detail["insider"].get("net_value"),
        "institutional_pct": detail["institutional"].get("held_percent_institutions"),
        "analyst_movement": detail["analyst_trend"].get("net_action"),
    }

    return {
        "summary": summary,
        "detail": detail,
        "observations": _observations(detail),
        "data_quality": dq,
    }
