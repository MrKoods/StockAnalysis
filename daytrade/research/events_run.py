"""PROTOCOL12 runner.

  python -m daytrade.research.events_run check     # event-timing sanity checks (no P&L)
  python -m daytrade.research.events_run search    # Stage 1+2 (search period only) + luck baseline
  python -m daytrade.research.events_run holdout   # Stage 3, once, on the saved shortlist
"""

from __future__ import annotations

import json
import sys
import time

import numpy as np
import pandas as pd

from . import events as ev
from .daily import nw_t

OUT = ev.EDIR.parent.parent / "research_results"
SEARCH_START = {"ANL": pd.Timestamp("2012-01-01").date(), "INS": pd.Timestamp("2006-01-01").date()}


class Ctx:
    def __init__(self):
        t0 = time.time()
        self.P = ev.load_pooled()
        print(f"panel {len(self.P.tickers)} x {len(self.P.dates)} ({time.time() - t0:.0f}s)", flush=True)
        self._c = {}

    def get(self, k):
        if k not in self._c:
            t0 = time.time()
            self._c[k] = {"E": lambda: ev.load_earnings(self.P), "I": lambda: ev.load_insider(self.P),
                          "R": lambda: ev.load_ratings(self.P), "RRV": lambda: ev.rrv_prep(self.P),
                          "VIX": lambda: ev.load_vix(self.P)}[k]()
            print(f"loaded {k} ({time.time() - t0:.0f}s)", flush=True)
        return self._c[k]

    def run(self, cfg):
        f, P = cfg.family, self.P
        if f == "EGAP":
            return ev.egap(P, self.get("E"), cfg.p)
        if f == "ESUR":
            return ev.esur(P, self.get("E"), cfg.p)
        if f == "EPRE":
            return ev.epre(P, self.get("E"), cfg.p)
        if f == "INS":
            return ev.ins(P, self.get("I"), cfg.p)
        if f == "ANL":
            return ev.anl(P, self.get("R"), self.get("E"), cfg.p)
        if f == "RRV":
            return ev.rrv(P, self.get("RRV"), cfg.p)
        return ev.mac(P, self.get("VIX"), cfg.p)


def lfilter(d, lf):
    if lf == "liquid":
        return d["liquid"].astype(bool)
    if lf == "illiquid":
        return ~d["liquid"].astype(bool)
    return np.ones(len(d["raw"]), bool)


def period(d, cfg, which):
    day = d["day"]
    if which == "search":
        lo = SEARCH_START.get(cfg.family, pd.Timestamp("2000-01-01").date())
        return (day >= lo) & (day <= ev.SEARCH_END)
    return (day >= ev.HOLD_START) & (day <= ev.HOLD_END)


def is_daytrade(cfg):
    f, p = cfg.family, cfg.p
    return (f == "EGAP" and p[2] == "o0" and p[3] == 0) or (f in ("INS",) and p[5] == 1) or \
           (f == "ANL" and p[4] == 1)


def check():
    C = Ctx()
    P, E = C.P, C.get("E")
    ti, d0 = E.ti.to_numpy(), E.d0.to_numpy()
    print(f"earnings events {len(E)}  tickers {E.ti.nunique()}  from {P.dates[d0.min()]}")
    for off in (-2, -1, 0, 1, 2):
        d = d0 + off
        g = np.abs(P.O[ti, d] - P.C[ti, d - 1]) / P.atr[ti, d - 1]
        print(f"  offset {off:+d}: median |open gap|/ATR {np.nanmedian(g):.3f}")
    I = C.get("I")
    print(f"insider events {len(I)}  P {int((I.code == 'P').sum())}  S {int((I.code == 'S').sum())}")
    R = C.get("R")
    print(f"rating events {len(R)}  {R.act.value_counts().to_dict()}  from {P.dates[R.d_in.min()]}")
    for act in ("up", "down"):
        x = R[R.act == act]
        t2, d = x.ti.to_numpy(), x.d_in.to_numpy()
        for off, lab in ((-1, "prev session c-c"), (0, "entry session o-c")):
            r = (P.C[t2, d + off] / (P.C[t2, d + off - 1] if off < 0 else P.O[t2, d])) - 1
            print(f"  {act} {lab}: mean {np.nanmean(r) * 1e4:+.1f} bps")


def search():
    C = Ctx()
    cfgs = list(ev.grid())
    print(f"{len(cfgs)} configs", flush=True)
    rows, cache, holdl = [], {}, []
    t0 = time.time()
    for i, cfg in enumerate(cfgs):
        key = (cfg.family, cfg.p)
        if key not in cache:
            cache = {key: C.run(cfg)}          # configs are generated with the post-filter innermost
        d = cache[key]
        lag = ev.max_lag(cfg)
        m = period(d, cfg, "search") & lfilter(d, cfg.filt)
        s = ev.stats(d, m, lag)
        row = {"family": cfg.family, "p": json.dumps(cfg.p), "filt": cfg.filt, **s}
        if s["n"] >= 30:
            for side, sm in (("long", d["sign"] > 0), ("short", d["sign"] < 0)):
                ss = ev.stats(d, m & sm, lag)
                row[f"{side}_mean"], row[f"{side}_n"] = ss.get("mean"), ss["n"]
            sig = np.unique(d["sign"][m])
            row["sides"] = len(sig)
        if is_daytrade(cfg) and s["n"] >= 30 and cfg.family in ("EGAP", "INS", "ANL"):
            tw = ev.holdl_twin(C.P, {k: v[m] for k, v in d.items()})
            st = ev.stats(tw, np.ones(len(tw["raw"]), bool), 7)
            holdl.append({"family": cfg.family, "p": json.dumps(cfg.p), "filt": cfg.filt,
                          "day_n": s["n"], "day_mean": s["mean"], "day_raw": s["raw"], "day_t": s["t"],
                          "holdl_mean": st.get("mean"), "holdl_raw": st.get("raw"), "holdl_t": st.get("t"),
                          "holdl_win": st.get("win"), "day_win": s["win"]})
        rows.append(row)
        if i % 250 == 0:
            print(f"{i}/{len(cfgs)} {time.time() - t0:.0f}s", flush=True)
    S = pd.DataFrame(rows)
    S.to_csv(OUT / "events_search.csv", index=False)
    pd.DataFrame(holdl).to_csv(OUT / "events_holdl_search.csv", index=False)
    shortlist(C, S)


def _sig(d, m):
    return tuple(np.sort((d["ti"][m] * 100000 + d["p_in"][m]))[:200]) if "ti" in d else None


def shortlist(C, S):
    minn = lambda f: 60 if f == "MAC" else 300  # noqa: E731
    picks = []
    for fam, g in S.groupby("family"):
        g = g[g.n >= minn(fam)].sort_values("t", ascending=False)
        chosen, cores, sigs = [], set(), set()
        for _, r in g.iterrows():
            cfg = ev.ECfg(fam, tuple(json.loads(r.p)), r.filt)
            core = json.dumps(json.loads(r.p)[:2])
            if core in cores:
                continue
            d = C.run(cfg)
            m = period(d, cfg, "search") & lfilter(d, cfg.filt)
            sg = _sig(d, m)
            if sg in sigs:
                continue
            chosen.append(r)
            cores.add(core)
            sigs.add(sg)
            if len(chosen) == 3:
                break
        picks += chosen
        # luck baseline: random-sign shuffles of this family's best config's trades vs its search t,
        # max over the family's configs approximated by the best config's own null scaled by #configs
        if chosen:
            best = chosen[0]
            cfg = ev.ECfg(fam, tuple(json.loads(best.p)), best.filt)
            d = C.run(cfg)
            m = period(d, cfg, "search") & lfilter(d, cfg.filt)
            h = d["hedged"][m]
            cost = (d["sign"][m] * d["r"][m] * 1e4 - d["raw"][m]) if "r" in d else np.full(len(h), 2.0)
            gross = h + cost
            rng = np.random.default_rng(12)
            nulls = []
            for _ in range(200):
                s = rng.choice([-1.0, 1.0], len(h))
                nulls.append(nw_t(d["day"][m], s * gross - cost, ev.max_lag(cfg)))
            nulls = np.array(nulls)
            ncfg = int((S.family == fam).sum())
            # Sidak-style family-wise p: probability that the max of ncfg (correlated) nulls beats best t
            p1 = float((nulls >= best.t).mean())
            print(f"{fam}: best search t {best.t:.2f}  single-config null p {p1:.3f}  "
                  f"(family has {ncfg} configs; 95% of null |t| < {np.quantile(np.abs(nulls), .95):.2f})")
    L = pd.DataFrame(picks)
    L.to_csv(OUT / "events_shortlist.csv", index=False)
    print(L[["family", "p", "filt", "n", "mean", "raw", "t", "long_mean", "short_mean"]].to_string())


def holdout():
    C = Ctx()
    L = pd.read_csv(OUT / "events_shortlist.csv")
    res = []
    for _, r in L.iterrows():
        cfg = ev.ECfg(r.family, tuple(json.loads(r.p)), r.filt)
        d = C.run(cfg)
        lag = ev.max_lag(cfg)
        base = period(d, cfg, "holdout") & lfilter(d, cfg.filt)
        s = ev.stats(d, base, lag)
        row = {"family": r.family, "p": r.p, "filt": r.filt, "search_t": r.t, "search_mean": r["mean"],
               **{f"ho_{k}": v for k, v in s.items()}}
        yr = np.array([x.year for x in d["day"]])
        row["ho_2018_21"] = ev.stats(d, base & (yr <= 2021), lag).get("mean")
        row["ho_2022_26"] = ev.stats(d, base & (yr >= 2022), lag).get("mean")
        for u in ("sp500", "sp400", "sp600"):
            row[f"ho_{u}"] = ev.stats(d, base & (d["uni"] == u), lag).get("mean") if r.family != "MAC" else None
        for side, sm in (("long", d["sign"] > 0), ("short", d["sign"] < 0)):
            row[f"ho_{side}"] = ev.stats(d, base & sm, lag).get("mean")
        twin_ok = True
        p = list(json.loads(r.p))
        twin = None
        if r.family == "EGAP" and p[2] == "c0":
            twin = ev.ECfg("EGAP", (p[0], p[1], "o1", p[3], p[4]), r.filt)
        elif r.family == "ESUR" and p[2] == "c0":
            twin = ev.ECfg("ESUR", (p[0], p[1], "o1", p[3], p[4]), r.filt)
        elif r.family == "RRV" and p[3] == "close":
            twin = ev.ECfg("RRV", (p[0], p[1], p[2], "open", p[4]), r.filt)
        if twin is not None:
            dt = C.run(twin)
            tm = ev.stats(dt, period(dt, twin, "holdout") & lfilter(dt, twin.filt), lag).get("mean")
            row["ho_twin_mean"] = tm
            twin_ok = tm is not None and tm > 0
        sides = [row["ho_long"], row["ho_short"]]
        traded = [x for x, sm in zip(sides, (d["sign"] > 0, d["sign"] < 0)) if (base & sm).sum() >= 30]
        unis = [row[f"ho_{u}"] for u in ("sp500", "sp400", "sp600") if row.get(f"ho_{u}") is not None]
        row["PASS"] = bool(s.get("mean", -1) > 0 and (s.get("t") or 0) >= 3.0 and (row["ho_2018_21"] or -1) > 0
                           and (row["ho_2022_26"] or -1) > 0 and all(x > 0 for x in traded)
                           and all(x > 0 for x in unis) and s.get("raw", -1) > 0 and twin_ok)
        res.append(row)
        print(json.dumps({k: (round(v, 2) if isinstance(v, float) else v) for k, v in row.items()}), flush=True)
    pd.DataFrame(res).to_csv(OUT / "events_holdout.csv", index=False)


def portfolio(d, mask, slots=10, cost_mult=1.0, seed=3):
    """Capital split into `slots` equal slots; a trade occupies one slot from entry to exit; when more
    signals than free slots arrive on a day, a random subset is taken. Uses RAW (unhedged) P&L, i.e.
    what an account actually earns. Returns daily equity curve stats."""
    rng = np.random.default_rng(seed)
    idx = np.flatnonzero(mask)
    p_in, p_out = d["p_in"][idx], d["p_out"][idx]
    cost = d["sign"][idx] * d["r"][idx] * 1e4 - d["raw"][idx]
    pnl = (d["raw"][idx] - (cost_mult - 1) * cost) / 1e4
    order = np.lexsort((rng.random(len(idx)), p_in))
    busy_until, taken = [], []
    for k in order:
        busy_until = [b for b in busy_until if b > p_in[k]]
        if len(busy_until) < slots:
            busy_until.append(p_out[k])
            taken.append(k)
    taken = np.array(taken)
    exit_day = np.array(d["day"])[idx][taken]  # booked at entry date (close enough for monthly stats)
    s = pd.Series(pnl[taken] / slots, index=pd.to_datetime(exit_day)).groupby(level=0).sum()
    eq = (1 + s).cumprod()
    yrs = max((s.index[-1] - s.index[0]).days / 365.25, 0.1)
    mo = (1 + s).groupby(s.index.to_period("M")).prod() - 1
    return {"trades_taken": len(taken), "signals": len(idx), "cagr": float(eq.iloc[-1] ** (1 / yrs) - 1),
            "maxdd": float((eq / eq.cummax() - 1).min()), "worst_month": float(mo.min()),
            "pos_months": float((mo > 0).mean()), "trades_per_day": float(len(idx) / max(len(np.unique(exit_day)), 1))}


def economics():
    C = Ctx()
    H = pd.read_csv(OUT / "events_holdout.csv")
    for _, r in H.iterrows():
        cfg = ev.ECfg(r.family, tuple(json.loads(r.p)), r.filt)
        if cfg.family == "MAC":
            continue
        d = C.run(cfg)
        m = period(d, cfg, "holdout") & lfilter(d, cfg.filt)
        if m.sum() < 30:
            continue
        out = {"family": r.family, "p": r.p, "filt": r.filt, "PASS": r.PASS}
        for cm in (1.0, 2.0):
            e = portfolio(d, m, cost_mult=cm)
            out.update({f"{k}_c{cm:g}": round(v, 4) for k, v in e.items()})
        print(json.dumps(out), flush=True)


if __name__ == "__main__":
    {"check": check, "search": search, "holdout": holdout, "economics": economics}[sys.argv[1]]()
