"""EPRE paper trading: Discord alerts + ledger (rules in RULES.md, fixed before the first trade).

    python -m epre signals     # weekdays ~15:40 ET: today's BUY-at-close and SELL-at-close lists
    python -m epre evaluate    # after the close: score trades whose exit close has happened
    add --dry-run to print instead of posting/writing

Every qualifying trade is logged and scored; Discord shows N_POSTED drawn at random (seeded by the date)
for manual paper trading - a random sample has the same expected result as the whole list.
"""

from __future__ import annotations

import logging
import os
from datetime import date, time

import numpy as np
import pandas as pd
import requests

from . import nyse
from .calendar import earnings_frame
from .config import CALENDAR, COST_BPS, HEDGE, LEDGER, N_POSTED, ROOT, TZ
from .rules import entry_session, reaction_session

log = logging.getLogger("epre.paper")
COLS = ["entry_day", "exit_day", "ticker", "index", "report_day", "bmo", "time_source", "posted",
        "entry_close", "exit_close", "ret_bps", "hedge_bps", "net_bps", "hedged_bps", "date_ok", "scored_on"]


# ------------------------------------------------------------------ discord
def _env(key: str) -> str | None:
    if os.environ.get(key):
        return os.environ[key]
    f = ROOT / ".env"
    if f.exists():
        for line in f.read_text(encoding="utf-8").splitlines():
            if line.startswith(key + "="):
                return line.split("=", 1)[1].strip().strip('"')
    return None


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


# ------------------------------------------------------------------ ledger
TEXT_COLS = ("entry_day", "exit_day", "report_day", "date_ok", "scored_on")


def load_ledger() -> pd.DataFrame:
    if LEDGER.exists():
        led = pd.read_csv(LEDGER, dtype={c: str for c in TEXT_COLS})
    else:
        led = pd.DataFrame(columns=COLS)
    for c in TEXT_COLS:      # all-empty columns read back as float; keep them text so True/dates fit
        led[c] = led[c].astype(object)
    return led


def save_ledger(led: pd.DataFrame) -> None:
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    led[COLS].to_csv(LEDGER, index=False)


# ------------------------------------------------------------------ signals
def entries_for(day: date, cal: pd.DataFrame, recheck: bool = True) -> pd.DataFrame:
    """Calendar events whose entry session is `day`. With recheck, each candidate's date and time are
    re-read from Yahoo right now and dropped if they no longer map to the same reaction session."""
    rows = []
    for r in cal.itertuples():
        d0 = reaction_session(date.fromisoformat(r.report_day), int(r.minute))
        if entry_session(d0) != day:
            continue
        rows.append({"ticker": r.ticker, "index": r.index, "report_day": r.report_day, "bmo": bool(r.bmo),
                     "time_source": r.time_source, "exit_day": str(d0), "minute": int(r.minute)})
    q = pd.DataFrame(rows)
    if q.empty or not recheck:
        return q
    keep = []
    for r in q.itertuples():
        try:
            f = earnings_frame(r.ticker, limit=4)
            fut = f[~f["reported"] & (f["ts"].dt.date >= day)]
            ok = len(fut) and str(fut.iloc[0]["ts"].date()) == r.report_day
        except Exception as exc:  # noqa: BLE001 - a failed recheck keeps the calendar's answer
            log.warning("recheck %s failed: %s", r.ticker, exc)
            ok = True
        if not ok:
            log.info("%s: report date moved since the calendar refresh - dropped", r.ticker)
        keep.append(bool(ok))
    return q[np.array(keep, bool)]


def _new_rows(day: date, q: pd.DataFrame) -> pd.DataFrame:
    rng = np.random.default_rng(int(day.strftime("%Y%m%d")))
    posted = np.zeros(len(q), bool)
    if len(q):
        posted[rng.choice(len(q), size=min(N_POSTED, len(q)), replace=False)] = True
    out = q.assign(entry_day=str(day), posted=posted)
    for c in COLS:
        if c not in out:
            out[c] = np.nan
    return out[COLS]


def _lines(day: date, buys: pd.DataFrame, sells: pd.DataFrame, label: str) -> list[str]:
    pb = buys[buys["posted"].astype(bool)]
    ps = sells[sells["posted"].astype(bool)]
    out = [f"**{label}** - BUY {len(pb)} of {len(buys)} qualifying | SELL {len(ps)} (posted ones exiting today)"]
    if len(pb):
        out += ["BUY at the close (market-on-close order before the cutoff). Hold through the earnings report.",
                "```"]
        out += [f"BUY  {r.ticker:6s} {r.index:5s} reports {r.report_day} {'before open' if r.bmo else 'after close'}"
                f"{'' if r.time_source == 'yahoo' else ' (time from company history)'}  -> sell {r.exit_day} close"
                for r in pb.sort_values("ticker").itertuples()]
        out.append("```")
    if len(ps):
        out += ["SELL at the close (market-on-close):", "```"]
        out += [f"SELL {r.ticker:6s} bought {r.entry_day}" for r in ps.sort_values("ticker").itertuples()]
        out.append("```")
    return out


def signals(dry: bool = False, day: date | None = None) -> None:
    now = pd.Timestamp.now(tz=TZ)
    today = day or now.date()
    if not nyse.covered(today):
        post("EPRE: the NYSE holiday table in epre/nyse.py ends - update it before trading further.", dry)
        return
    if not nyse.is_session(today):
        log.info("%s is not a session", today)
        return
    if not dry and today in nyse.EARLY_CLOSE:
        log.info("early close today - today's orders were posted yesterday")
        return
    if not dry and not (time(15, 30) <= now.time() <= time(15, 48)):
        log.info("skipping signals at %s ET (outside 15:30-15:48; MOC cutoff 15:50)", now.time())
        return
    cal = pd.read_csv(CALENDAR, dtype={"report_day": str})
    led = load_ledger()
    days = [today]
    nxt = nyse.next_session(today)
    if nxt in nyse.EARLY_CLOSE:
        days.append(nxt)          # tomorrow closes at 1 PM: post its orders today
    lines, new = [], []
    for d in days:
        rows = _new_rows(d, entries_for(d, cal, recheck=not dry or day is None))
        rows = rows[~rows["ticker"].isin(led.loc[led["entry_day"] == str(d), "ticker"])]
        new.append(rows)
        sells = pd.concat([led, rows])
        sells = sells[sells["exit_day"] == str(d)]
        label = f"EPRE paper trades {d}" + ("" if d == today else " (TOMORROW - early close 1 PM ET, "
                                                                  "MOC cutoff 12:50 PM ET)")
        lines += _lines(d, rows, sells, label)
    led = pd.concat([led, *new], ignore_index=True)
    if not dry:
        save_ledger(led)
    lines.append("_Paper only. Earnings announcement premium: passed the 2018-2026 holdout, unproven live._")
    post("\n".join(lines), dry)


# ------------------------------------------------------------------ evaluate
def _closes(tickers: list[str], start: date, end: date) -> dict[str, pd.Series]:
    import yfinance as yf
    raw = yf.download([t.replace(".", "-") for t in tickers], start=str(start), end=str(nyse.next_session(end)),
                      interval="1d", auto_adjust=True, group_by="ticker", progress=False, threads=True)
    out = {}
    for t in tickers:
        y = t.replace(".", "-")
        df = raw[y] if isinstance(raw.columns, pd.MultiIndex) and y in raw.columns.get_level_values(0) else (
            raw if not isinstance(raw.columns, pd.MultiIndex) else None)
        if df is not None and "Close" in df:
            s = df["Close"].dropna()
            s.index = pd.DatetimeIndex(s.index).date
            out[t] = s
    return out


def _date_ok(ticker: str, exit_day: str) -> bool | None:
    """Did the report actually land so that `exit_day` was its reaction session?"""
    try:
        f = earnings_frame(ticker, limit=6)
    except Exception:  # noqa: BLE001
        return None
    for r in f[f["reported"]].itertuples():
        if str(reaction_session(r.ts.date(), int(r.minute))) == exit_day:
            return True
    return False


def evaluate(dry: bool = False) -> None:
    now = pd.Timestamp.now(tz=TZ)
    led = load_ledger()
    if led.empty:
        log.info("empty ledger")
        return
    # an exit close is final once it is a past session, or today after 16:15 ET
    last_final = now.date() if now.time() >= time(16, 15) else nyse.prev_session(now.date())
    due = led["net_bps"].isna() & (pd.to_datetime(led["exit_day"]).dt.date <= last_final)
    if not due.any():
        log.info("nothing to score yet")
        return
    sub = led[due]
    start = min(date.fromisoformat(d) for d in sub["entry_day"])
    end = max(date.fromisoformat(d) for d in sub["exit_day"])
    px = _closes(sorted(set(sub["ticker"]) | set(HEDGE)), start, end)
    scored = []
    for i in np.flatnonzero(due.to_numpy()):
        t, ed, xd = led.at[i, "ticker"], date.fromisoformat(led.at[i, "entry_day"]), date.fromisoformat(led.at[i, "exit_day"])
        s = px.get(t)
        if s is None or ed not in s.index or xd not in s.index:
            continue
        hedge = [px[h].loc[xd] / px[h].loc[ed] - 1 for h in HEDGE if h in px and ed in px[h].index and xd in px[h].index]
        if len(hedge) < len(HEDGE):
            continue
        ret = s.loc[xd] / s.loc[ed] - 1
        cost = 2 * COST_BPS[led.at[i, "index"]]
        led.at[i, "entry_close"], led.at[i, "exit_close"] = round(float(s.loc[ed]), 4), round(float(s.loc[xd]), 4)
        led.at[i, "ret_bps"] = round(ret * 1e4, 1)
        led.at[i, "hedge_bps"] = round(float(np.mean(hedge)) * 1e4, 1)
        led.at[i, "net_bps"] = round(ret * 1e4 - cost, 1)
        led.at[i, "hedged_bps"] = round((ret - float(np.mean(hedge))) * 1e4 - cost, 1)
        ok = _date_ok(t, led.at[i, "exit_day"])
        led.at[i, "date_ok"] = "" if ok is None else str(ok)
        led.at[i, "scored_on"] = str(now.date())
        scored.append(i)
    if not scored:
        log.info("prices not available yet")
        return
    if not dry:
        save_ledger(led)
    new = led.loc[scored]
    lines = []
    for xd, g in new.groupby("exit_day"):
        p = g[g["posted"].astype(bool)]
        lines += [f"**EPRE paper results, sold at the {xd} close** ({len(g)} trades; net of costs, hedged vs SPY/IJH/IJR):"]
        if len(p):
            lines += ["```"] + [f"{r.ticker:6s} {r.net_bps:+8.1f} bps (hedged {r.hedged_bps:+8.1f})" for r in p.itertuples()] + ["```"]
        lines.append(f"Posted {len(p)}: {p['hedged_bps'].mean():+.1f} bps hedged | all {len(g)}: {g['hedged_bps'].mean():+.1f} bps hedged")
    lines.append(verdict(led))
    post("\n".join(lines), dry)


# ------------------------------------------------------------------ verdict (RULES.md)
def verdict(led: pd.DataFrame) -> str:
    x = led.dropna(subset=["hedged_bps"])
    n = len(x)
    if n == 0:
        return "Verdict: no closed trades yet."
    per_day = x.groupby("exit_day")["hedged_bps"].mean()
    sd = per_day.std(ddof=1)
    t = float(per_day.mean() / (sd / np.sqrt(len(per_day)))) if len(per_day) > 1 and sd > 0 else float("nan")
    m = float(x["hedged_bps"].mean())
    chk = x["date_ok"].dropna().astype(str).str.lower() == "true"
    acc = float(chk.mean()) if len(chk) else float("nan")
    head = (f"Running: {n} closed trades, {x['exit_day'].nunique()} exit days | hedged {m:+.1f} bps/trade "
            f"(net unhedged {x['net_bps'].mean():+.1f}) | day-t {t:.2f} | report-date accuracy {acc:.0%} | "
            f"backtest expectation ~ +19 bps.")
    if n < 1000:
        state = f"collecting ({n}/1,000 trades to checkpoint A)"
    elif n < 3000:
        state = ("FAIL at checkpoint A (mean < -20 bps) - stop" if m < -20
                 else f"checkpoint A passed; collecting ({n}/3,000 to checkpoint B)")
    elif n < 6000:
        if m < 0:
            state = "FAIL at checkpoint B (mean < 0) - stop"
        elif m >= 10 and t >= 1.0 and acc >= 0.90:
            state = "checkpoint B: SMALL REAL MONEY OK (mean >= +10, t >= 1, dates >= 90%); keep paper to 6,000"
        else:
            state = f"checkpoint B inconclusive; collecting ({n}/6,000 to checkpoint C)"
    else:
        state = ("PASS (mean >= +10 bps, t >= 2)" if m >= 10 and t >= 2 else "FAIL at checkpoint C")
    return head + "\nVerdict: " + state
