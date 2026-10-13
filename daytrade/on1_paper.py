"""ON1 paper-trading alerts + ledger (alerts go to the V2 Discord webhook, like g2_paper).

    python -m daytrade.on1_paper signals    # weekdays ~15:40 ET: rank, log picks, post 10 to buy at the close
    python -m daytrade.on1_paper evaluate   # weekdays after the 09:30 open: score every pending pick
    add --dry-run to print instead of posting/writing

ON1 rules: buy the 5% of stocks (ranked separately within the S&P 500 / 400 / 600) with the worst
return over the last part of the session, at the 16:00 close; sell at the next session's open. Long only.

The forward test (forward.update_on1) ranks on the 16:00 close itself and enters at that same close -
not doable live. Here the ranking uses the price at ~15:40 ET (vs the 14:30 close of the 13:30 hourly
bar, the same reference as the research), so picks can be sent as market-on-close orders before the
15:50 NYSE cutoff. The gap between this ledger and the forward test measures that timing cost.

ALL picks (~75/day) are logged and scored; the verdict uses all of them. Discord shows 10 drawn at
random (seeded by the date) for manual paper trading - a random sample has the same expected result.
"""

from __future__ import annotations

import logging
import sys
from datetime import date, time

import numpy as np
import pandas as pd
import yfinance as yf

from .config import ROOT, TZ
from .forward import INDEX_FILES, index_tickers
from .g2_paper import post

LEDGER = ROOT / "data" / "paper" / "on1_paper_ledger.csv"
N_POSTED = 10
QUANTILE = 0.05
COST_BPS = 2.0
REF = time(14, 30)             # close of the 13:30 hourly bar = research reference point
COLS = ["day", "ticker", "index", "posted", "rank_ret_bps", "rank_time", "close", "next_day", "next_open", "bps"]
log = logging.getLogger("on1paper")


def _intraday(tickers: list[str], day: date) -> dict[str, pd.DataFrame]:
    out = {}
    for i in range(0, len(tickers), 100):
        batch = tickers[i:i + 100]
        raw = yf.download(batch, period="5d", interval="5m", group_by="ticker",
                          prepost=False, auto_adjust=False, progress=False, threads=True)
        if not len(raw):
            continue
        for t in batch:
            if isinstance(raw.columns, pd.MultiIndex) and t not in raw.columns.get_level_values(0):
                continue
            df = (raw[t] if isinstance(raw.columns, pd.MultiIndex) else raw).dropna(subset=["Close"])
            df.index = pd.DatetimeIndex(df.index).tz_convert(TZ)
            df = df[df.index.date == day]
            if len(df):
                out[t] = df
    return out


def picks_for(today: date, rank_time: str) -> pd.DataFrame:
    """Worst-QUANTILE stocks per index by return since 14:30, using the latest 5m bar. Empty if no session."""
    picks = []
    for name in INDEX_FILES:
        tick = sorted(set(index_tickers(name)))
        bars = _intraday(tick, today)
        sig = {}
        for t, df in bars.items():
            # 5m bar starting 14:25 closes at 14:30
            ref = df[df.index.time <= time(14, 25)]
            if not len(ref) or ref.index[-1].time() < time(14, 0):
                continue
            sig[t] = float(df["Close"].iloc[-1]) / float(ref["Close"].iloc[-1]) - 1
        if not sig:
            continue
        s = pd.Series(sig)
        worst = s[s.rank(pct=True) <= QUANTILE].sort_values()
        log.info("%s: %d ranked, %d picks", name, len(s), len(worst))
        picks += [{"ticker": t, "index": name, "rank_ret_bps": round(r * 1e4, 1)} for t, r in worst.items()]
    if not picks:
        return pd.DataFrame(columns=COLS)
    q = pd.DataFrame(picks)
    rng = np.random.default_rng(int(today.strftime("%Y%m%d")))
    posted = np.zeros(len(q), bool)
    posted[rng.choice(len(q), size=min(N_POSTED, len(q)), replace=False)] = True
    q["posted"] = posted
    q["day"] = str(today)
    q["rank_time"] = rank_time
    for c in ("close", "next_day", "next_open", "bps"):
        q[c] = np.nan
    return q[COLS]


def signals(dry: bool = False, day: date | None = None) -> None:
    now = pd.Timestamp.now(tz=TZ)
    today = day or now.date()
    if not dry and not (time(15, 35) <= now.time() <= time(15, 50)):
        # the PC was asleep at the scheduled time: picks after the MOC cutoff can't be traded
        log.info("skipping signals at %s ET (outside 15:35-15:50)", now.time())
        return
    q = picks_for(today, now.strftime("%H:%M"))
    if q.empty:
        log.info("no session data for %s (holiday?)", today)
        return
    posted = q["posted"].to_numpy()
    if not dry:
        old = pd.read_csv(LEDGER) if LEDGER.exists() else pd.DataFrame(columns=COLS)
        led = pd.concat([old[old["day"] != str(today)], q[COLS]], ignore_index=True)
        LEDGER.parent.mkdir(parents=True, exist_ok=True)
        led.to_csv(LEDGER, index=False)
    lines = [f"**ON1 paper trades {today}** - {posted.sum()} drawn at random from {len(q)} picks "
             f"(paper only; unproven strategy)",
             "BUY at the close (market-on-close, before 3:50 PM ET). SELL at tomorrow's open. No stop.", "```"]
    for r in q[q["posted"]].sort_values("rank_ret_bps").itertuples():
        lines.append(f"BUY  {r.ticker:6s} {r.index:5s}  since 2:30 PM {r.rank_ret_bps / 100:+6.2f}%")
    lines.append("```")
    post("\n".join(lines), dry)


def _score(led: pd.DataFrame) -> pd.DataFrame:
    """Fill close/next_open/bps for pending rows whose next session has opened. Returns updated ledger."""
    led = led.copy()
    led["next_day"] = led["next_day"].astype(object)     # all-NaN on read -> float column
    pend = led["bps"].isna()
    if not pend.any():
        return led
    tick = sorted(led.loc[pend, "ticker"].unique())
    first = min(pd.to_datetime(led.loc[pend, "day"]))
    raw = yf.download(tick, start=(first - pd.Timedelta(days=3)).strftime("%Y-%m-%d"), interval="1d",
                      group_by="ticker", auto_adjust=False, progress=False, threads=True)
    for i in np.flatnonzero(pend.to_numpy()):
        t, d = led.at[i, "ticker"], date.fromisoformat(led.at[i, "day"])
        if isinstance(raw.columns, pd.MultiIndex) and t not in raw.columns.get_level_values(0):
            continue
        df = (raw[t] if isinstance(raw.columns, pd.MultiIndex) else raw).dropna(subset=["Open", "Close"])
        days = pd.DatetimeIndex(df.index).date
        on, after = df[days == d], df[days > d]
        if not len(on) or not len(after):
            continue
        c, o = float(on["Close"].iloc[0]), float(after["Open"].iloc[0])
        led.at[i, "close"], led.at[i, "next_open"] = round(c, 4), round(o, 4)
        led.at[i, "next_day"] = str(days[days > d][0])
        led.at[i, "bps"] = round((o / c - 1) * 1e4 - 2 * COST_BPS, 1)
    return led


def evaluate(dry: bool = False) -> None:
    if not LEDGER.exists():
        return
    old = pd.read_csv(LEDGER)
    led = _score(old)
    newly = led[old["bps"].isna() & led["bps"].notna()]
    if newly.empty:
        log.info("nothing to score yet")
        return
    if not dry:
        led.to_csv(LEDGER, index=False)
    x = led.dropna(subset=["bps"])
    lines = []
    for d, g in newly.groupby("day"):
        p = g[g["posted"].astype(bool)]
        lines += [f"**ON1 paper results {d}** (bought at the close, sold at the {g['next_day'].iloc[0]} open, "
                  f"net of {COST_BPS:g} bps/side):", "```"]
        lines += [f"BUY  {r.ticker:6s} {r.bps:+7.1f} bps" for r in p.itertuples()]
        lines += ["```", f"Posted 10: {p['bps'].mean():+.1f} bps/trade | all {len(g)} picks: {g['bps'].mean():+.1f} bps/trade"]
    lines += [f"Running (all picks): {x['bps'].mean():+.1f} bps/trade over {len(x)} trades, {x['day'].nunique()} day(s). "
              f"Backtest expectation ~ +9 bps.", verdict(x)]
    post("\n".join(lines), dry)


def verdict(x: pd.DataFrame) -> str:
    """Pass/fail rule, fixed 2026-10-13 BEFORE any live ON1 paper trade (all picks, ranked ~15:40 ET,
    close -> next open, net of costs): after >= 20 trading days: PASS if mean >= +5 bps/trade and
    day-clustered t >= 2; FAIL if mean < 0; otherwise keep collecting until 40 days, where the same
    PASS test applies and anything else FAILS."""
    days = x["day"].nunique()
    if days < 20:
        return f"Verdict: collecting ({days}/20 trading days)."
    per_day = x.groupby("day")["bps"].mean()
    t = per_day.mean() / (per_day.std(ddof=1) / np.sqrt(len(per_day))) if per_day.std(ddof=1) > 0 else 0.0
    m = x["bps"].mean()
    if m >= 5 and t >= 2:
        return f"Verdict: PASS ({m:+.1f} bps/trade, t {t:.2f}, {days} days) - worth considering small real size."
    if m < 0 or days >= 40:
        return f"Verdict: FAIL ({m:+.1f} bps/trade, t {t:.2f}, {days} days) - ON1 is not tradeable; shelve it."
    return f"Verdict: inconclusive ({m:+.1f} bps/trade, t {t:.2f}, {days}/40 days) - keep collecting."


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    logging.getLogger("yfinance").setLevel(logging.CRITICAL)
    dry = "--dry-run" in sys.argv
    day = next((date.fromisoformat(a[6:]) for a in sys.argv if a.startswith("--day=")), None)
    if sys.argv[1] == "signals":
        signals(dry, day if dry else None)       # --day=YYYY-MM-DD replays a past session (dry runs only)
    else:
        evaluate(dry)
