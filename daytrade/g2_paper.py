"""G2 paper-trading alerts + ledger (no broker keys needed; alerts go to the V2 Discord webhook).

    python -m daytrade.g2_paper signals    # weekdays ~09:34 ET: post today's 10 paper trades
    python -m daytrade.g2_paper evaluate   # weekdays after 13:30 ET: score them, post the result
    add --dry-run to print instead of posting

G2 rules: at the 09:30 open, a stock that gapped >= 0.25 x its 14-day ATR away from yesterday's close
is traded AGAINST the gap (buy gap-downs, short gap-ups) only when that direction agrees with the
20-day trend (yesterday's close vs its 20-day average). Target = yesterday's close; no stop; exit at
13:30 ET if the target was not reached.

The full strategy takes ~165 trades/day. A manual paper account cannot, so each day 10 qualifying
trades are drawn AT RANDOM (seeded by the date) - a random sample has the same expected result as the
whole strategy. NOT the most liquid 10: historically that slice lost money (-4.8 bps/trade), because
G2's edge sits in less liquid names - which is also where real opening costs are highest.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import date, time

import numpy as np
import pandas as pd
import requests
import yfinance as yf

from .config import ROOT, TZ
from .forward import g2_tickers

LEDGER = ROOT / "data" / "paper" / "g2_paper_ledger.csv"
TODAY_FILE = ROOT / "data" / "paper" / "g2_today.json"
N_TRADES = 10
COST_BPS = 2.0
EXIT = time(13, 29)            # exit at the close of the 13:29 minute (= 13:30)
log = logging.getLogger("g2paper")


def _env(name: str) -> str | None:
    from dotenv import dotenv_values
    return os.getenv(name) or dotenv_values(ROOT / ".env").get(name)


def post(text: str, dry: bool) -> None:
    if dry:
        print(text)
        return
    url = _env("DISCORD_WEBHOOK_URL")
    if not url:
        print("DISCORD_WEBHOOK_URL missing; message:\n" + text)
        return
    for chunk in [text[i:i + 1900] for i in range(0, len(text), 1900)]:
        requests.post(url, json={"content": chunk}, timeout=20).raise_for_status()


def _daily(tickers: list[str]) -> dict[str, pd.DataFrame]:
    out = {}
    for i in range(0, len(tickers), 100):
        raw = yf.download(tickers[i:i + 100], period="3mo", interval="1d", group_by="ticker",
                          auto_adjust=False, progress=False, threads=True)
        for t in tickers[i:i + 100]:
            if t in raw.columns.get_level_values(0):
                df = raw[t].dropna(subset=["Close"])
                if len(df) > 25:
                    out[t] = df
    return out


def _minutes(tickers: list[str], day: date) -> dict[str, pd.DataFrame]:
    out = {}
    for i in range(0, len(tickers), 100):
        raw = yf.download(tickers[i:i + 100], period="2d", interval="1m", group_by="ticker",
                          prepost=False, auto_adjust=False, progress=False, threads=True)
        if not len(raw):
            continue
        for t in tickers[i:i + 100]:
            if isinstance(raw.columns, pd.MultiIndex) and t not in raw.columns.get_level_values(0):
                continue
            df = (raw[t] if isinstance(raw.columns, pd.MultiIndex) else raw).dropna(subset=["Open"])
            df.index = pd.DatetimeIndex(df.index).tz_convert(TZ)
            df = df[df.index.date == day]
            if len(df):
                out[t] = df
    return out


def signals(dry: bool = False) -> None:
    now = pd.Timestamp.now(tz=TZ)
    today = now.date()
    if not dry and not (time(9, 31) <= now.time() <= time(10, 0)):
        # the PC was asleep at the scheduled time: a late "enter now" alert would be stale
        log.info("skipping signals at %s ET (outside 09:31-10:00)", now.time())
        return
    tick = sorted(set(g2_tickers()))
    daily = _daily(tick)
    rows = []
    mins = _minutes(list(daily), today)
    if not mins:
        log.info("no session data for %s (holiday?)", today)
        return
    for t, d in daily.items():
        hist = d[d.index.date < today]
        if len(hist) < 21 or t not in mins:
            continue
        o = float(mins[t]["Open"].iloc[0])                              # 09:30 open
        pc = float(hist["Close"].iloc[-1])
        hi, lo, cl = hist["High"], hist["Low"], hist["Close"]
        tr = pd.concat([hi - lo, (hi - cl.shift()).abs(), (lo - cl.shift()).abs()], axis=1).max(axis=1)
        atr = float(tr.iloc[-14:].mean())
        sma20 = float(cl.iloc[-20:].mean())
        gap = (o - pc) / atr
        if abs(gap) < 0.25:
            continue
        side = -np.sign(gap)
        if side * np.sign(pc - sma20) <= 0:
            continue
        rows.append({"ticker": t, "side": "BUY" if side > 0 else "SHORT", "open": round(o, 2),
                     "target": round(pc, 2), "gap_atr": round(gap, 2)})
    q = pd.DataFrame(rows)
    if q.empty:
        post(f"**G2 paper trades {today}**: no qualifying gaps today.", dry)
        return
    rng = np.random.default_rng(int(today.strftime("%Y%m%d")))
    pick = q.iloc[np.sort(rng.choice(len(q), size=min(N_TRADES, len(q)), replace=False))]
    TODAY_FILE.parent.mkdir(parents=True, exist_ok=True)
    TODAY_FILE.write_text(json.dumps({"day": str(today), "qualifying": len(q), "trades": pick.to_dict("records")}))
    lines = [f"**G2 paper trades {today}** - {len(pick)} drawn at random from {len(q)} qualifying "
             f"(paper only; unproven strategy)",
             "Enter now at market. Target = yesterday's close. No stop. Exit at 1:30 PM ET if not filled.", "```"]
    for r in pick.itertuples():
        lines.append(f"{r.side:5s} {r.ticker:6s} open {r.open:>9.2f}  target {r.target:>9.2f}  gap {r.gap_atr:+.2f} ATR")
    lines.append("```")
    post("\n".join(lines), dry)


def _score(df: pd.DataFrame, side: float, entry_i: int, target: float) -> float:
    """Net bps for a trade entered at the open of minute entry_i, target `target`, exit by 13:30."""
    df = df[df.index.time <= EXIT]
    if len(df) <= entry_i:
        return np.nan
    entry = float(df["Open"].iloc[entry_i])
    if (target - entry) * side <= 0:                  # already through the target at entry
        return np.nan
    after = df.iloc[entry_i:]
    hit = (after["High"] >= target) if side > 0 else (after["Low"] <= target)
    exitp = target if hit.any() else float(after["Close"].iloc[-1])
    return side * (exitp / entry - 1) * 1e4 - 2 * COST_BPS


def evaluate(dry: bool = False) -> None:
    if not TODAY_FILE.exists():
        return
    info = json.loads(TODAY_FILE.read_text())
    day = date.fromisoformat(info["day"])
    if day != pd.Timestamp.now(tz=TZ).date() and not dry:
        return
    mins = _minutes([t["ticker"] for t in info["trades"]], day)
    rows = []
    for t in info["trades"]:
        df = mins.get(t["ticker"])
        if df is None:
            continue
        side = 1.0 if t["side"] == "BUY" else -1.0
        rows.append({"day": str(day), "ticker": t["ticker"], "side": t["side"], "target": t["target"],
                     "bps_at_0930_open": round(_score(df, side, 0, t["target"]), 1),
                     "bps_at_0932_entry": round(_score(df, side, 2, t["target"]), 1)})
    new = pd.DataFrame(rows)
    old = pd.read_csv(LEDGER) if LEDGER.exists() else pd.DataFrame()
    led = pd.concat([old[old["day"] != str(day)] if len(old) else old, new], ignore_index=True)
    if not dry:                                       # dry runs never touch the real ledger
        LEDGER.parent.mkdir(parents=True, exist_ok=True)
        led.to_csv(LEDGER, index=False)
    d_mean = new["bps_at_0932_entry"].mean()
    all_mean = led["bps_at_0932_entry"].mean()
    days = led["day"].nunique()
    lines = [f"**G2 paper results {day}** (net of {COST_BPS:g} bps/side, entry 9:32):", "```"]
    for r in new.itertuples():
        lines.append(f"{r.side:5s} {r.ticker:6s} {r.bps_at_0932_entry:+7.1f} bps")
    lines += ["```", f"Today: {d_mean:+.1f} bps/trade | Running: {all_mean:+.1f} bps/trade over "
              f"{len(led)} trades, {days} day(s). Backtest expectation ~ +9.9 bps (likely optimistic on costs)."]
    post("\n".join(lines), dry)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    logging.getLogger("yfinance").setLevel(logging.CRITICAL)
    dry = "--dry-run" in sys.argv
    {"signals": signals, "evaluate": evaluate}[sys.argv[1]](dry)
