"""Forward test of candidate C6 on sessions that did not exist during the search.

C6 (chosen 2026-10-06 after a 734-config search, see output/research/):
  * 5m base bars; sweep + reclaim on 15m bars (3 bars); PDH/PDL + 4H levels
  * CHoCH on 5m (swing_n 2, within 20 bars), first FVG in the leg else 62-79%
  * trigger: price trades into the zone, then any 5m close back out of it
    (candle color not required); enter at the next bar's open, before 15:30
  * stop: sweep extreme + 2 ticks; target: fixed 2R; flatten at 15:55
  * max 1 open trade and 2 trades per stock per day

Pass bar, fixed before any forward data exists: after >= 30 forward sessions,
PASS if mean net R >= +0.08 and day-clustered t >= 2.0 on forward trades only;
FAIL if mean net R < 0; otherwise keep collecting to 60 sessions.

Each run recomputes the ledger from the archive (deterministic, idempotent).
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from .config import ROOT, UNIVERSE
from .research.engine import Det, Exit, Universe, detect, run, stats
from .research.families import FILTERS as FAM_FILTERS
from .research.families import Cfg, run_cfg
from .research.hourly import load_panel

FORWARD_START = date(2026, 10, 6)   # first session after the search data ended
C6_DET = Det(base="5m", trigger="close_out")
C6_EXIT = Exit(target="R", target_r=2.0)
LEDGER = ROOT / "data" / "forward" / "c6_forward_trades.csv"


def update() -> dict:
    U = Universe(base="5m")
    tr = run(U, detect(U, C6_DET), C6_EXIT)
    tr = tr[tr["day"] >= FORWARD_START] if len(tr) else tr
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    tr.to_csv(LEDGER, index=False)
    s = stats(tr)
    sessions = len({d for (_, d) in U.days if d >= FORWARD_START})
    s["sessions"] = sessions
    if sessions >= 30 and s["n"]:
        s["verdict"] = ("PASS" if s["mean"] >= 0.08 and s["t_day"] >= 2.0
                        else "FAIL" if s["mean"] < 0 else "keep collecting")
    else:
        s["verdict"] = f"collecting ({sessions}/30 sessions)"
    return s


# ---------------- G2: gap fade (added 2026-10-06 after the family search) ----------------
# Exact config: fade an opening gap >= 0.25 daily ATR (open vs prev close) at the 09:30 open,
# target = previous close, no stop, exit at the close of the 12:30 hourly bar (~13:30 ET), only
# when the trade direction agrees with the 20-day trend. Universe: S&P 500 + S&P 400 + the core 50.
# Evidence before forward: S&P 500 search t 3.1, S&P 500 holdout +0.028 ATR (t 2.37, short of the
# 2.6 bar), S&P 400 midcaps (untouched, pre-registered) +0.045 ATR, t 4.7, PASS.
# Forward PASS bar, fixed before any forward data: after >= 40 forward sessions, mean net R > 0
# (ATR units, 1c/side) with day-clustered t >= 2.0; FAIL if mean < 0.
G2 = Cfg("GAP", (0.25, "fade", "open", "pc", 0.0, 2))
G2_LEDGER = ROOT / "data" / "forward" / "g2_forward_trades.csv"


def g2_tickers() -> list[str]:
    extra = [ROOT / "daytrade" / f for f in ("sp500_new.csv", "sp400.csv")]
    return UNIVERSE + [t for f in extra if f.exists() for t in pd.read_csv(f)["ticker"]]


def update_g2() -> dict:
    rows = []
    for t in g2_tickers():
        P = load_panel(t)
        if P is None:
            continue
        x = run_cfg(P, G2)
        if x is None:
            continue
        m = FAM_FILTERS["with_trend"](x) & ~np.isnan(x["r"]) & (x["day"] >= FORWARD_START)
        for i in np.flatnonzero(m):
            rows.append({"day": x["day"][i], "ticker": t, "direction": "long" if x["sign"][i] > 0 else "short",
                         "r_atr": float(x["r"][i])})
    tr = pd.DataFrame(rows, columns=["day", "ticker", "direction", "r_atr"])
    G2_LEDGER.parent.mkdir(parents=True, exist_ok=True)
    tr.to_csv(G2_LEDGER, index=False)
    sessions = tr["day"].nunique()
    s = {"n": len(tr), "sessions": int(sessions)}
    if len(tr):
        per_day = tr.groupby("day")["r_atr"].sum()
        sd = per_day.std(ddof=1)
        s["mean_atr"] = float(tr["r_atr"].mean())
        s["t_day"] = float(per_day.mean() / (sd / np.sqrt(len(per_day)))) if len(per_day) > 1 and sd > 0 else float("nan")
    if sessions >= 40:
        s["verdict"] = ("PASS" if s["mean_atr"] > 0 and s["t_day"] >= 2.0
                        else "FAIL" if s["mean_atr"] < 0 else "keep collecting")
    else:
        s["verdict"] = f"collecting ({sessions}/40 sessions)"
    return s


# ---------------- ON1: overnight last-hour reversal (SECONDARY: did NOT pass its confirmation) ----------------
# Each day buy the 5% of stocks with the worst last-hour return (13:30 bar close -> 16:00 close) at the
# close; sell at the next open. Long only. Ranked within each index (S&P 500 / 400 / 600), pooled.
# Evidence: S&P 500 search +9.9 bps t 2.07; holdout +11.1 bps t 2.24 (< 2.6 bar); midcaps +7.2 bps
# t 1.89 (< 2.0 bar, FAIL); small caps +9.0 bps t 2.38. Tracked because every slice was positive.
# Forward PASS bar, fixed before any forward data: >= 40 forward sessions, mean net bps > 0 (2 bps/side)
# with day-clustered t >= 2.0; FAIL if mean < 0.
ON1_LEDGER = ROOT / "data" / "forward" / "on1_forward_trades.csv"
INDEX_FILES = {"sp500": "sp500_new.csv", "sp400": "sp400.csv", "sp600": "sp600.csv"}


def index_tickers(name: str) -> list[str]:
    base = UNIVERSE if name == "sp500" else []
    f = ROOT / "daytrade" / INDEX_FILES[name]
    return base + (pd.read_csv(f)["ticker"].tolist() if f.exists() else [])


def update_on1() -> dict:
    from .research.families2 import Cfg2, build, run as run2
    cfg = Cfg2("ON", ("lasthour", "raw", 0.05, "rev"))
    parts = []
    for name in INDEX_FILES:
        X = build(index_tickers(name))
        d = run2(X, cfg)
        m = (d["sign"] > 0) & ~np.isnan(d["bps"]) & (d["day"] >= FORWARD_START)
        parts.append(pd.DataFrame({"day": d["day"][m], "index": name, "bps": d["bps"][m]}))
    tr = pd.concat(parts, ignore_index=True)
    ON1_LEDGER.parent.mkdir(parents=True, exist_ok=True)
    tr.to_csv(ON1_LEDGER, index=False)
    sessions = tr["day"].nunique()
    s = {"n": len(tr), "sessions": int(sessions)}
    if len(tr):
        per_day = tr.groupby("day")["bps"].sum()
        sd = per_day.std(ddof=1)
        s["mean_bps"] = float(tr["bps"].mean())
        s["t_day"] = float(per_day.mean() / (sd / np.sqrt(len(per_day)))) if len(per_day) > 1 and sd > 0 else float("nan")
    s["verdict"] = (("PASS" if s["mean_bps"] > 0 and s["t_day"] >= 2.0 else "FAIL" if s["mean_bps"] < 0
                     else "keep collecting") if sessions >= 40 else f"collecting ({sessions}/40 sessions)")
    return s


def as_table(tr: pd.DataFrame) -> pd.DataFrame:
    return tr[["day", "ticker", "direction", "level", "reason", "r_net"]]
