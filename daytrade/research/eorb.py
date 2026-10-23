"""EORB: 'stocks in play' first-hour breakout, hourly bars 2023-11..2026-10 (PROTOCOL12 addendum).

In play = earnings day 0, or first-hour volume >= k x its 14-day average first-hour volume.
Signal = direction of the 09:30-10:30 bar (needs |move| >= x ATR); entry 10:30, follow or fade;
exit 12:30 / 16:00 close / day+1 close / day+3 close; optional stop at the first-hour bar's far extreme.
Hedge = SPY over the same interval (beta 1). Search < 2025-07-01, holdout >= 2025-07-01 (once).

  python -m daytrade.research.eorb
"""

from __future__ import annotations

import itertools
import json

import numpy as np
import pandas as pd

from ..config import DATA_DIR
from .daily import nw_t, universe
from .events import COST, EDIR

HDIR = DATA_DIR / "1h"
SPLIT = pd.Timestamp("2025-07-01").date()
OUT = DATA_DIR.parent.parent / "research_results"


def build():
    uni = {}
    for name in ("sp500", "sp400", "sp600"):
        for t in universe(name):
            uni.setdefault(t, name)
    spy = pd.read_parquet(HDIR / "SPY.parquet")
    spy_day = spy.groupby(spy.index.date)
    spy_px = {d: g["open"].tolist() + [g["close"].iloc[-1]] for d, g in spy_day if len(g) == 7}
    rows = []
    for t, u in uni.items():
        f = HDIR / f"{t}.parquet"
        if not f.exists():
            continue
        h = pd.read_parquet(f)
        g = {d: x for d, x in h.groupby(h.index.date) if len(x) == 7}
        days = sorted(g)
        if len(days) < 40:
            continue
        o1 = np.array([g[d]["open"].iloc[0] for d in days])
        c1 = np.array([g[d]["close"].iloc[0] for d in days])
        hi1 = np.array([g[d]["high"].iloc[0] for d in days])
        lo1 = np.array([g[d]["low"].iloc[0] for d in days])
        v1 = np.array([g[d]["volume"].iloc[0] for d in days], float)
        dc = np.array([g[d]["close"].iloc[-1] for d in days])
        dh = np.array([g[d]["high"].max() for d in days])
        dl = np.array([g[d]["low"].min() for d in days])
        p1230 = np.array([g[d]["open"].iloc[3] for d in days])
        # remaining-bar extremes after entry (bars 10:30..15:30) for the stop check
        rh = np.array([g[d]["high"].iloc[1:].max() for d in days])
        rl = np.array([g[d]["low"].iloc[1:].min() for d in days])
        rh_noon = np.array([g[d]["high"].iloc[1:3].max() for d in days])
        rl_noon = np.array([g[d]["low"].iloc[1:3].min() for d in days])
        prev_c = np.r_[np.nan, dc[:-1]]
        tr = np.fmax(dh - dl, np.fmax(np.abs(dh - prev_c), np.abs(dl - prev_c)))
        atr = pd.Series(tr).rolling(14, min_periods=10).mean().shift(1).to_numpy()   # through d-1
        rv = v1 / pd.Series(v1).rolling(14, min_periods=10).mean().shift(1).to_numpy()
        earn = set()
        ef = EDIR / "earnings" / f"{t}.parquet"
        if ef.exists():
            e = pd.read_parquet(ef)
            if not e.empty:
                ts = pd.to_datetime(e["Earnings Date"], utc=True).dt.tz_convert("America/New_York")
                hm = ts.dt.hour * 60 + ts.dt.minute
                darr = np.array(days, dtype="datetime64[D]")
                for dd, m in zip(ts.dt.date, hm):
                    if m == 0:
                        continue
                    k = np.searchsorted(darr, np.datetime64(dd), side="left")
                    if k < len(days) and m >= 570 and days[k] == dd:
                        k += 1
                    if k < len(days):
                        earn.add(k)
        for i in range(15, len(days)):
            d = days[i]
            if d not in spy_px or not np.isfinite(atr[i]):
                continue
            sp = spy_px[d]
            rows.append((t, u, d, i in earn, rv[i], (c1[i] - o1[i]) / atr[i], np.sign(o1[i] - prev_c[i]),
                         c1[i], hi1[i], lo1[i], p1230[i], dc[i], rh[i], rl[i], rh_noon[i], rl_noon[i],
                         dc[i + 1] if i + 1 < len(days) else np.nan, dc[i + 3] if i + 3 < len(days) else np.nan,
                         sp[1], sp[3], sp[7]))
    cols = ["t", "uni", "day", "earn", "rv", "mv", "gapsign", "entry", "hi1", "lo1", "p1230", "dc", "rh", "rl",
            "rhn", "rln", "dc1", "dc3", "s_in", "s_1230", "s_close"]
    return pd.DataFrame(rows, columns=cols)


def evaluate(D, p):
    play, x, mode, exit_, stop, gapf, lf = p
    m = np.array(D.earn.to_numpy() if play == "earn" else (D.rv.to_numpy() >= float(play[2:])), dtype=bool)
    mv = D.mv.to_numpy()
    m &= np.abs(mv) >= x
    m &= mv != 0
    sign = np.sign(mv) * (1 if mode == "follow" else -1)
    if gapf:
        m &= D.gapsign.to_numpy() == np.sign(mv)
    if lf != "none":
        big = D.uni.to_numpy() == "sp500"
        m &= big if lf == "sp500" else ~big
    d = D[m]
    sign = sign[m]
    entry = d.entry.to_numpy()
    xp = {"1230": d.p1230, "c0": d.dc, "c1": d.dc1, "c3": d.dc3}[exit_].to_numpy()
    if stop:
        # stop at the far side of the first-hour bar (long: its low; short: its high), checked over the
        # bars after entry through the exit (intraday only; multi-day exits use the same-day check)
        sp = np.where(sign > 0, d.lo1, d.hi1)
        ext_h = (d.rhn if exit_ == "1230" else d.rh).to_numpy()
        ext_l = (d.rln if exit_ == "1230" else d.rl).to_numpy()
        hit = np.where(sign > 0, ext_l <= sp, ext_h >= sp)
        xp = np.where(hit, sp, xp)
    r = xp / entry - 1
    sref = {"1230": d.s_1230, "c0": d.s_close, "c1": d.s_close, "c3": d.s_close}[exit_].to_numpy()
    rs = sref / d.s_in.to_numpy() - 1
    cost = 2 * d.uni.map(COST).to_numpy()
    ok = np.isfinite(r)
    hedged = sign * (r - rs) * 1e4 - cost
    raw = sign * r * 1e4 - cost
    return pd.DataFrame({"day": d.day.to_numpy(), "hedged": hedged, "raw": raw, "sign": sign})[ok]


def grid():
    return itertools.product(["earn", "rv3", "rv5"], [0.0, 0.25, 0.5], ["follow", "fade"],
                             ["1230", "c0", "c1", "c3"], [False, True], [False, True],
                             ["none", "sp500", "small"])


def st(x, lag):
    if len(x) < 30:
        return {"n": len(x)}
    return {"n": len(x), "mean": float(x.hedged.mean()), "raw": float(x.raw.mean()),
            "t": nw_t(x.day.to_numpy(), x.hedged.to_numpy(), lag),
            "long": float(x.hedged[x.sign > 0].mean()) if (x.sign > 0).sum() else None,
            "short": float(x.hedged[x.sign < 0].mean()) if (x.sign < 0).sum() else None}


def main():
    pf = EDIR / "eorb_panel.parquet"
    if pf.exists():
        D = pd.read_parquet(pf)
    else:
        D = build()
        D.to_parquet(pf)
    print(f"panel rows {len(D)}  earnings-day rows {int(D.earn.sum())}", flush=True)
    rows = []
    for p in grid():
        if p[4] and p[3] in ("c1", "c3"):
            continue
        x = evaluate(D, p)
        lag = {"1230": 1, "c0": 1, "c1": 2, "c3": 4}[p[3]]
        rows.append({"p": json.dumps(p), **st(x[x.day < SPLIT], lag)})
    S = pd.DataFrame(rows)
    S.to_csv(OUT / "eorb_search.csv", index=False)
    print(f"{len(S)} configs; search t quantiles {S.t.quantile([.05, .5, .95]).round(2).tolist()}")
    S["core"] = S.p.map(lambda s: json.dumps(json.loads(s)[:4]))
    L = S[S.n >= 200].sort_values("t", ascending=False).drop_duplicates("core").head(6)
    res = []
    for _, r in L.iterrows():
        p = tuple(json.loads(r.p))
        x = evaluate(D, p)
        lag = {"1230": 1, "c0": 1, "c1": 2, "c3": 4}[p[3]]
        h = st(x[x.day >= SPLIT], lag)
        sides = [v for v in (h.get("long"), h.get("short")) if v is not None]
        ok = h.get("mean", -1) > 0 and (h.get("t") or 0) >= 2.6 and h.get("raw", -1) > 0 and all(v > 0 for v in sides)
        res.append({"p": r.p, "search_n": r.n, "search_mean": r["mean"], "search_t": r.t,
                    **{f"ho_{k}": v for k, v in h.items()}, "PASS": ok})
        print(json.dumps({k: (round(v, 2) if isinstance(v, float) else v) for k, v in res[-1].items()}))
    pd.DataFrame(res).to_csv(OUT / "eorb_holdout.csv", index=False)


if __name__ == "__main__":
    main()
