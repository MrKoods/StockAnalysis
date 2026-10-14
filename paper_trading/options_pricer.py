"""
Real dollar pricing for the options structures the paper tracks recommend.

The paper ledgers record a structure name (long_strangle, diagonal_put, ...)
and a contract count, but their pnl_dollars is the STOCK trade's R-multiple x
planned dollar risk — the options were never priced. This module prices them.

Legs follow the exact strike/expiry conventions the model used to pick and
size each structure (shared/utils/options_math.resolve_structure_economics):
offsets are fractions of the stock price, the near expiration is the first
listed one at least positioning.min_dte days out (positioning_client.
_pick_expiration), and a diagonal/calendar's long leg is ~30 days further out.

Two modes:

  update_live(track)  — REAL quotes (yfinance, 15-min delayed). Called by the
      daily paper_updater run right after the outcome walk. A trade filled on
      or after PRICING_START is opened at the then-current quotes, marked every
      run, and closed on the first run after its stock trade closes. Any leg
      that expired before that is settled at intrinsic value on its expiry
      close. P&L is reported at mid AND at "natural" prices (pay the ask to
      buy, hit the bid to sell) — what a market order would really cost.
      Ledger: paper_trading/options_positions.csv.

  estimate(csv)       — Black-Scholes ESTIMATE for trades filled before
      PRICING_START, which have no stored quotes. Volatility = the median of
      the scans' own stored at-the-money IV readings for the ticker
      (positioning_state.json iv_history); no bid/ask spread charged. Label
      it as an estimate wherever it's shown.

Usage:
    python -m paper_trading.options_pricer estimate [rank|threshold|random]
    python -m paper_trading.options_pricer live     [rank|threshold|random]
"""

from __future__ import annotations

import csv
import json
import statistics
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd

from paper_trading.paper_runner import (
    PAPER_TRADES_CSV, PAPER_TRADES_LOCK_FILE, RANDOM_TRADES_CSV, RANDOM_TRADES_LOCK_FILE,
    RANK_TRADES_CSV, RANK_TRADES_LOCK_FILE,
)
from shared.api_clients.market_data_client import fetch_ohlcv_since
from shared.api_clients.option_quotes_client import fetch_quotes, fetch_spot, list_expirations
from shared.utils.atomic_io import exclusive_lock
from shared.utils.logger import get_logger
from shared.utils.options_math import black_scholes_price
from swing_model.indicator_pipeline import load_config

logger = get_logger(__name__)

TRACKS = {
    "threshold": (PAPER_TRADES_CSV, PAPER_TRADES_LOCK_FILE),
    "rank": (RANK_TRADES_CSV, RANK_TRADES_LOCK_FILE),
    "random": (RANDOM_TRADES_CSV, RANDOM_TRADES_LOCK_FILE),
}
POSITIONS_CSV = Path("paper_trading/options_positions.csv")
POSITIONS_LOCK = Path("paper_trading/options_positions.csv.lock")
POSITIONING_STATE = Path("data/processed/positioning_state.json")
# Fills before this date predate real-quote capture -> estimate() covers them.
PRICING_START = date(2026, 10, 14)
RISK_FREE = 0.04
FAR_LEG_EXTRA_DAYS = 30
# A quoted strike further than this from the convention's target strike (as a
# fraction of spot) means the chain doesn't really offer that leg.
MAX_STRIKE_MISS = 0.05

# structure -> legs as (option_type, qty per structure, strike offset vs spot, expiry "near"/"far").
# Mirrors resolve_structure_economics' branches one-for-one.
LEG_SPECS: dict[str, list[tuple[str, int, float, str]]] = {
    "long_call": [("call", 1, 0.0, "near")],
    "long_put": [("put", 1, 0.0, "near")],
    "deep_itm_call": [("call", 1, -0.15, "near")],
    "deep_itm_put": [("put", 1, 0.15, "near")],
    "bull_call_spread": [("call", 1, 0.0, "near"), ("call", -1, 0.12, "near")],
    "bear_put_spread": [("put", 1, 0.0, "near"), ("put", -1, -0.12, "near")],
    "diagonal_call": [("call", -1, 0.0, "near"), ("call", 1, 0.06, "far")],
    "diagonal_put": [("put", -1, 0.0, "near"), ("put", 1, -0.06, "far")],
    "calendar_call": [("call", -1, 0.0, "near"), ("call", 1, 0.0, "far")],
    "calendar_put": [("put", -1, 0.0, "near"), ("put", 1, 0.0, "far")],
    "long_butterfly_call": [("call", 1, -0.06, "near"), ("call", -2, 0.0, "near"), ("call", 1, 0.06, "near")],
    "long_straddle": [("call", 1, 0.0, "near"), ("put", 1, 0.0, "near")],
    "long_strangle": [("call", 1, 0.06, "near"), ("put", 1, -0.06, "near")],
}

POSITION_COLUMNS = [
    "track", "signal_date", "ticker", "direction", "structure", "contracts", "status",
    "open_date", "open_spot", "legs", "open_mid", "open_natural",
    "mark_date", "mark_mid", "close_date", "close_spot", "close_mid", "close_natural",
    "pnl_mid", "pnl_natural", "planned_risk", "stock_outcome", "stock_rr", "stock_pnl_dollars", "note",
]


# ---------------------------------------------------------------- helpers
def _min_dte(cfg: dict) -> int:
    return int(cfg.get("positioning", {}).get("min_dte", 5))


def _pick_expiries(expirations: list[str], today: date, min_dte: int) -> tuple[Optional[str], Optional[str]]:
    """(near, far) from listed expirations — same rule as positioning_client._pick_expiration."""
    dated = sorted(d for d in (_parse(e) for e in expirations) if d)
    near = next((d for d in dated if (d - today).days >= min_dte), dated[-1] if dated else None)
    if near is None:
        return None, None
    far_target = near + timedelta(days=FAR_LEG_EXTRA_DAYS)
    later = [d for d in dated if d > near]
    far = min(later, key=lambda d: abs((d - far_target).days)) if later else None
    return near.isoformat(), far.isoformat() if far else None


def _parse(s: str) -> Optional[date]:
    try:
        return datetime.strptime(str(s)[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _intrinsic(option_type: str, strike: float, spot: float) -> float:
    return max(0.0, spot - strike) if option_type == "call" else max(0.0, strike - spot)


def _close_on(ticker: str, day: date, cache: dict) -> Optional[float]:
    """Stock close on `day` (or the last session before it) — settles an expired leg."""
    if ticker not in cache:
        cache[ticker] = fetch_ohlcv_since(ticker, (day - timedelta(days=60)).isoformat())
    bars = cache[ticker]
    if bars is None or not len(bars):
        return None
    idx = pd.to_datetime(bars.index).tz_localize(None)
    s = pd.Series(bars["Close"].to_numpy(), index=idx)
    v = s.asof(pd.Timestamp(day))
    return None if pd.isna(v) else float(v)


def _value(legs: list[dict], key: str, buy_at_ask: Optional[bool]) -> float:
    """Structure value per unit. buy_at_ask None = mid; True = opening natural; False = closing natural."""
    total = 0.0
    for leg in legs:
        if leg.get("settled") is not None:
            px = leg["settled"]
        elif buy_at_ask is None:
            px = leg[f"{key}_mid"]
        elif buy_at_ask:
            px = leg[f"{key}_ask"] if leg["qty"] > 0 else leg[f"{key}_bid"]
        else:
            px = leg[f"{key}_bid"] if leg["qty"] > 0 else leg[f"{key}_ask"]
        total += leg["qty"] * px
    return total


# ---------------------------------------------------------------- live (real quotes)
class _Quotes:
    """Per-run cache of chains, so one run fetches each (ticker, expiry) once."""

    def __init__(self):
        self.chains: dict[tuple[str, str], Optional[pd.DataFrame]] = {}
        self.exps: dict[str, list[str]] = {}

    def expirations(self, ticker: str) -> list[str]:
        if ticker not in self.exps:
            self.exps[ticker] = list_expirations(ticker)
        return self.exps[ticker]

    def chain(self, ticker: str, expiry: str) -> Optional[pd.DataFrame]:
        if (ticker, expiry) not in self.chains:
            q = fetch_quotes(ticker, expiry)
            self.chains[(ticker, expiry)] = None if q is None else q[(q["bid"] > 0) & (q["ask"] > 0)]
        return self.chains[(ticker, expiry)]


def _open_legs(structure: str, ticker: str, spot: float, today: date, min_dte: int, quotes: _Quotes):
    near, far = _pick_expiries(quotes.expirations(ticker), today, min_dte)
    if near is None:
        return None, "no listed expirations"
    legs = []
    for option_type, qty, offset, which in LEG_SPECS[structure]:
        expiry = near if which == "near" else far
        if expiry is None:
            return None, "no far expiration listed"
        q = quotes.chain(ticker, expiry)
        if q is None or q.empty:
            return None, f"no two-sided quotes for {expiry}"
        side = q[q["option_type"] == option_type]
        target = spot * (1 + offset)
        if side.empty:
            return None, f"no {option_type} quotes for {expiry}"
        row = side.iloc[(side["strike"] - target).abs().argsort().iloc[0]]
        if abs(row["strike"] - target) / spot > MAX_STRIKE_MISS:
            return None, f"no {option_type} strike near {target:.2f} for {expiry}"
        legs.append({"type": option_type, "qty": qty, "strike": float(row["strike"]), "expiry": expiry,
                     "open_bid": float(row["bid"]), "open_ask": float(row["ask"]),
                     "open_mid": round((row["bid"] + row["ask"]) / 2, 4)})
    return legs, ""


def _quote_legs(legs: list[dict], ticker: str, spot: float, today: date, key: str,
                quotes: _Quotes, bar_cache: dict) -> bool:
    """Fill {key}_bid/ask/mid (or 'settled') on every leg. False if a live leg has no quote."""
    for leg in legs:
        exp = _parse(leg["expiry"])
        if exp < today:
            px = _close_on(ticker, exp, bar_cache)
            if px is None:
                return False
            leg["settled"] = round(_intrinsic(leg["type"], leg["strike"], px), 4)
            continue
        q = quotes.chain(ticker, leg["expiry"])
        hit = None if q is None else q[(q["option_type"] == leg["type"]) & (q["strike"] == leg["strike"])]
        if hit is None or hit.empty:
            if exp == today:
                leg["settled"] = round(_intrinsic(leg["type"], leg["strike"], spot), 4)
                continue
            return False
        leg[f"{key}_bid"], leg[f"{key}_ask"] = float(hit["bid"].iloc[0]), float(hit["ask"].iloc[0])
        leg[f"{key}_mid"] = round((leg[f"{key}_bid"] + leg[f"{key}_ask"]) / 2, 4)
    return True


def _load_positions() -> list[dict]:
    if not POSITIONS_CSV.exists():
        return []
    with open(POSITIONS_CSV, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _save_positions(rows: list[dict]) -> None:
    with open(POSITIONS_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=POSITION_COLUMNS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def update_live(track: str, today: Optional[date] = None, cfg: Optional[dict] = None) -> dict:
    """Open / mark / close real-quote options positions for one track. Returns counts."""
    today = today or date.today()
    cfg = cfg if cfg is not None else load_config()
    csv_path, _ = TRACKS[track]
    if not csv_path.exists():
        return {}
    trades = pd.read_csv(csv_path, dtype=str).fillna("")
    quotes, bar_cache, counts = _Quotes(), {}, {"opened": 0, "marked": 0, "closed": 0, "missed": 0}

    with exclusive_lock(POSITIONS_LOCK, timeout=30.0):
        positions = _load_positions()
        by_key = {(p["track"], p["signal_date"], p["ticker"]): p for p in positions}
        for t in trades.itertuples():
            if t.position_type != "options" or t.structure_recommended not in LEG_SPECS or not t.fill_date:
                continue
            fill = _parse(t.fill_date)
            if fill is None or fill < PRICING_START:
                continue
            key = (track, t.signal_date, t.ticker)
            p = by_key.get(key)
            if p is None:
                p = {"track": track, "signal_date": t.signal_date, "ticker": t.ticker, "direction": t.direction,
                     "structure": t.structure_recommended, "contracts": t.position_size or "0",
                     "planned_risk": t.actual_dollar_risk, "status": "pending"}
                by_key[key] = p
                positions.append(p)
            if p["status"] in ("closed", "missed"):
                continue
            if p["status"] == "pending":
                if t.outcome:
                    # Stock trade filled and closed between two runs — the options leg never got a quote.
                    p["status"], p["note"] = "missed", f"stock trade {t.outcome} before an options quote was taken"
                    counts["missed"] += 1
                    continue
                spot = fetch_spot(t.ticker)
                if not spot:
                    p["note"] = f"{today}: no spot price, retry next run"
                    continue
                legs, why = _open_legs(t.structure_recommended, t.ticker, spot, today, _min_dte(cfg), quotes)
                if legs is None:
                    p["note"] = f"{today}: {why}, retry next run"
                    continue
                p.update({"status": "open", "open_date": today.isoformat(), "open_spot": f"{spot:.2f}",
                          "legs": json.dumps(legs), "open_mid": f"{_value(legs, 'open', None):.4f}",
                          "open_natural": f"{_value(legs, 'open', True):.4f}", "note": ""})
                counts["opened"] += 1
                if not t.outcome:
                    continue
            legs = json.loads(p["legs"])
            spot = fetch_spot(t.ticker)
            if not spot or not _quote_legs(legs, t.ticker, spot, today, "close", quotes, bar_cache):
                p["note"] = f"{today}: missing quote, retry next run"
                continue
            n = float(p["contracts"] or 0)
            mid_now = _value(legs, "close", None)
            if t.outcome:
                nat_now = _value(legs, "close", False)
                p.update({"status": "closed", "close_date": today.isoformat(), "close_spot": f"{spot:.2f}",
                          "legs": json.dumps(legs), "close_mid": f"{mid_now:.4f}", "close_natural": f"{nat_now:.4f}",
                          "pnl_mid": f"{(mid_now - float(p['open_mid'])) * 100 * n:.2f}",
                          "pnl_natural": f"{(nat_now - float(p['open_natural'])) * 100 * n:.2f}",
                          "stock_outcome": t.outcome, "stock_rr": t.achieved_rr, "stock_pnl_dollars": t.pnl_dollars})
                counts["closed"] += 1
            else:
                p.update({"mark_date": today.isoformat(), "mark_mid": f"{mid_now:.4f}",
                          "pnl_mid": f"{(mid_now - float(p['open_mid'])) * 100 * n:.2f}"})
                counts["marked"] += 1
        _save_positions(positions)
    return counts


# ---------------------------------------------------------------- estimate (Black-Scholes)
def _iv_by_ticker() -> dict[str, float]:
    try:
        hist = json.loads(POSITIONING_STATE.read_text(encoding="utf-8")).get("iv_history", {})
    except (OSError, ValueError):
        return {}
    out = {}
    for t, vals in hist.items():
        good = [float(v) for v in vals if v is not None and 0.08 <= float(v) <= 1.5]
        if len(good) >= 5:
            out[t] = statistics.median(good)
    return out


def _synthetic_expiries(fill: date, weekly: bool, min_dte: int) -> tuple[date, date]:
    """Fridays (weekly) or third Fridays (monthly) — the listed calendar we can't fetch historically."""
    def fridays(start: date):
        d = start + timedelta(days=(4 - start.weekday()) % 7)
        while True:
            if weekly or 15 <= d.day <= 21:
                yield d
            d += timedelta(days=7)
    near = next(d for d in fridays(fill) if (d - fill).days >= min_dte)
    far_target = near + timedelta(days=FAR_LEG_EXTRA_DAYS)
    cands = [d for _, d in zip(range(30), fridays(near + timedelta(days=1)))]
    return near, min(cands, key=lambda d: abs((d - far_target).days))


def estimate(track: str = "rank", cfg: Optional[dict] = None) -> pd.DataFrame:
    """Black-Scholes estimate for every filled, closed-or-open options trade filled before PRICING_START."""
    cfg = cfg if cfg is not None else load_config()
    csv_path, _ = TRACKS[track]
    d = pd.read_csv(csv_path)
    d = d[(d.position_type == "options") & d.structure_recommended.isin(list(LEG_SPECS)) & d.fill_date.notna()]
    d = d[pd.to_datetime(d.fill_date).dt.date < PRICING_START]
    ivs, bar_cache, weekly_cache, rows = _iv_by_ticker(), {}, {}, []
    for t in d.itertuples():
        fill = _parse(t.fill_date)
        closed = isinstance(t.outcome, str) and t.outcome != ""
        end = _parse(t.exit_date) if closed else _parse(str(t.mark_date)) if isinstance(t.mark_date, str) else None
        s0 = float(t.fill_price)
        s1 = float(t.exit_price) if closed else float(t.mark_price) if pd.notna(t.mark_price) else None
        iv = ivs.get(t.ticker)
        if end is None or s1 is None or iv is None:
            continue
        if t.ticker not in weekly_cache:
            soon = [e for e in (_parse(x) for x in list_expirations(t.ticker)) if e and (e - date.today()).days <= 35]
            weekly_cache[t.ticker] = len(soon) >= 3
        near, far = _synthetic_expiries(fill, weekly_cache[t.ticker], _min_dte(cfg))
        v0 = v1 = 0.0
        expired_early = False
        for option_type, qty, offset, which in LEG_SPECS[t.structure_recommended]:
            exp = near if which == "near" else far
            k = s0 * (1 + offset)
            v0 += qty * black_scholes_price(s0, k, (exp - fill).days / 365, RISK_FREE, iv, option_type)
            if exp <= end:
                expired_early = expired_early or exp < end
                px = _close_on(t.ticker, exp, bar_cache)
                v1 += qty * _intrinsic(option_type, k, px if px is not None else s1)
            else:
                v1 += qty * black_scholes_price(s1, k, (exp - end).days / 365, RISK_FREE, iv, option_type)
        n = float(t.position_size or 0)
        rows.append({"signal_date": t.signal_date, "ticker": t.ticker, "direction": t.direction,
                     "structure": t.structure_recommended, "status": "closed" if closed else "open",
                     "contracts": n, "iv_used": round(iv, 3), "near_expiry": near.isoformat(),
                     "held_past_expiry": expired_early, "est_cost": round(v0 * 100 * n, 2),
                     "est_pnl": round((v1 - v0) * 100 * n, 2),
                     "planned_risk": float(t.actual_dollar_risk),
                     "stock_rr": float(t.achieved_rr) if closed else float(t.unrealized_rr) if pd.notna(t.unrealized_rr) else None,
                     "stock_pnl_dollars": float(t.pnl_dollars) if closed else float(t.unrealized_pnl_dollars) if pd.notna(t.unrealized_pnl_dollars) else None})
    return pd.DataFrame(rows)


def _print_estimate(track: str) -> None:
    e = estimate(track)
    if e.empty:
        print(f"[{track}] nothing to estimate")
        return
    out = Path(f"paper_trading/options_estimate_{track}.csv")
    e.to_csv(out, index=False)
    for status, g in e.groupby("status"):
        print(f"\n[{track}] {status} trades priced as options (Black-Scholes ESTIMATE, no bid/ask spread): {len(g)}")
        print(f"  options P&L  ${g.est_pnl.sum():+,.0f}   (avg ${g.est_pnl.mean():+,.0f}/trade, "
              f"{(g.est_pnl > 0).mean():.0%} profitable)")
        print(f"  stock-equivalent P&L in the ledger  ${g.stock_pnl_dollars.sum():+,.0f}")
        print(f"  options expired before the trade ended: {int(g.held_past_expiry.sum())}/{len(g)}")
        print(g.groupby("structure").agg(n=("est_pnl", "size"), options_pnl=("est_pnl", "sum"),
                                         stock_pnl=("stock_pnl_dollars", "sum")).round(0).to_string())
    print(f"\nper-trade detail: {out}")


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "estimate"
    which = sys.argv[2:] or ["rank"]
    for tr in which:
        if mode == "estimate":
            _print_estimate(tr)
        else:
            print(tr, update_live(tr))
