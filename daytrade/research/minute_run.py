"""PROTOCOL10, applied mechanically.

    python -m daytrade.research.minute_run search    # Stages 1-3 (needs SPY + QQQ)
    python -m daytrade.research.minute_run confirm   # Stage 4 (needs DIA + stocks)
"""

from __future__ import annotations

import json
import pickle
import sys
from datetime import date
from unittest import mock

import numpy as np
import pandas as pd

from .. import dukascopy
from ..config import OUTPUT_DIR, ROOT
from .mass import pbo_cscv
from .minute import drift_per_minute, grid, load_inst, run, score

RES = ROOT / "research_results"
OUT = OUTPUT_DIR / "research"
SEARCH = (date(2018, 1, 1), date(2023, 1, 1))
HOLD = (date(2023, 1, 1), date(2100, 1, 1))
FULL = (date(2018, 1, 1), date(2100, 1, 1))
CONFIRM = ["DIA", "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "TSLA", "AMD", "NFLX", "XOM", "IWM", "JPM", "BAC", "INTC"]


def tstat(day, bps):
    s = pd.Series(bps).groupby(np.asarray(day)).sum()
    sd = s.std(ddof=1)
    return float(s.mean() / (sd / np.sqrt(len(s)))) if len(s) > 2 and sd > 0 else float("nan")


# ---------------- the user's LSR rules (locked) and C6 on Dukascopy minutes ----------------
def lsr_trades(sym: str, variant: str) -> dict:
    m1 = dukascopy.load(sym)
    cost = 1.0 if sym in ("SPY", "QQQ", "DIA", "IWM") else 2.0
    if variant == "LSR_1m":
        from ..backtest import _apply_limits
        from ..config import DEFAULT
        from ..levels import build_5m, day_levels
        from ..strategy import scan_day
        lv = day_levels(build_5m(m1, pd.DataFrame(columns=m1.columns)))
        rows = []
        for day, g in m1.groupby(m1.index.date):
            if day not in lv:
                continue
            setups = scan_day(sym, day, g, lv[day], DEFAULT)
            _apply_limits(setups, DEFAULT)
            for s in setups:
                if s.status == "traded":
                    sign = 1.0 if s.direction == "long" else -1.0
                    rows.append((day, sign, sign * (s.exit / s.entry - 1),
                                 (s.exit_ts - s.entry_ts).total_seconds() / 60 + 1))
    else:  # C6: 5m base / 15m sweep / close-out trigger / fixed 2R
        from . import engine
        from .engine import Det, Exit, Universe, detect

        def fake_load(t, interval):
            return m1 if interval == "1m" and t == sym else pd.DataFrame(columns=["open", "high", "low", "close", "volume"])

        with mock.patch.object(engine.data, "load", fake_load):
            U = Universe(tickers=[sym], base="5m")
        tr = engine.run(U, detect(U, Det(base="5m", trigger="close_out")), Exit(target="R", target_r=2.0))
        rows = [(r.day, 1.0 if r.direction == "long" else -1.0, r.r_gross * r.risk_pct / 100,
                 (r.exit_bar - r.entry_bar + 1) * 5.0) for r in tr.itertuples()]
    if not rows:
        return {k: np.array([]) for k in ("day", "sym", "sign", "ret", "minutes", "cost")}
    day, sign, ret, mins = (np.array(c) for c in zip(*rows))
    return {"day": day, "sym": np.full(len(day), sym), "sign": sign.astype(float), "ret": ret.astype(float),
            "minutes": mins.astype(float), "cost": np.full(len(day), cost)}


def _concat(parts):
    parts = [p for p in parts if p is not None and len(p["day"])]
    return {k: np.concatenate([p[k] for p in parts]) for k in parts[0]} if parts else None


def evaluate(trades, insts, period):
    drift = {I.sym: drift_per_minute(I, *period) for I in insts}
    day, bps, sign, sym = score(trades, *period, drift)
    return day, bps, sign, sym


def search():
    insts = [load_inst(s) for s in ("SPY", "QQQ")]
    assert all(insts), "SPY/QQQ not downloaded yet"
    sessions = sorted({d for I in insts for d in I.days if SEARCH[0] <= d < SEARCH[1]})
    s_ix = {d: i for i, d in enumerate(sessions)}
    print({I.sym: (len(I.days), str(I.days[0]), str(I.days[-1])) for I in insts}, flush=True)
    cfgs = list(grid())
    metas, sums, trades_cache = [], [], {}
    for ci, cfg in enumerate(cfgs):
        tr = _concat([run(I, cfg) for I in insts])
        if tr is None:
            continue
        trades_cache[ci] = tr
        day, bps, _, _ = evaluate(tr, insts, SEARCH)
        if len(bps) < 50:
            continue
        di = np.array([s_ix[d] for d in day])
        sums.append(np.bincount(di, weights=bps, minlength=len(sessions)).astype(np.float32))
        metas.append({"cfg_i": ci, "family": cfg.family, "params": repr(cfg.p), "n": len(bps),
                      "mean_bps": float(bps.mean()), "t": tstat(day, bps)})
    meta = pd.DataFrame(metas)
    M = np.vstack(sums).astype(float)

    print("=== Stage 1 (search: SPY+QQQ 2018-2022) ===")
    for fam in meta.family.unique():
        idx = np.flatnonzero(meta.family == fam)
        m = meta.iloc[idx]
        pbo = pbo_cscv(M[idx], S=10) if len(idx) > 2 else {"pbo": np.nan}
        print(fam, f"configs={len(m)} median={m.mean_bps.median():+.2f} bps best_t={m.t.max():.2f} pbo={pbo['pbo']:.2f}")
        print(m.sort_values("t", ascending=False).head(5).round(2).to_string(index=False))

    print("\n=== Stage 2 shortlist ===")
    short = []
    for fam in meta.family.unique():
        m = meta[(meta.family == fam) & (meta.n >= 300)].sort_values("t", ascending=False)
        m = m.drop_duplicates(subset=["n", "mean_bps"])
        if m.empty:
            continue
        short.append(m.iloc[0])
        nxt = m[m.params != m.iloc[0].params]
        if len(nxt):
            short.append(nxt.iloc[0])
    short = pd.DataFrame(short)
    print(short.round(2).to_string(index=False))

    print("\n=== Stage 3 holdout (SPY+QQQ 2023+, once) + LSR locked variants ===")
    rows = []
    cands = [(r.family, r.params, trades_cache[int(r.cfg_i)], round(r.t, 2), int(r.cfg_i)) for r in short.itertuples()]
    for v in ("LSR_1m", "C6_5m"):
        cands.append((v, "locked", _concat([lsr_trades(s, v) for s in ("SPY", "QQQ")]), np.nan, -1))
    for fam, params, tr, st, ci in cands:
        if tr is None:
            rows.append({"family": fam, "params": params, "n": 0, "stage3": "fail (no trades)"})
            continue
        day, bps, sign, sym = evaluate(tr, insts, HOLD)
        early = np.array([d < date(2025, 1, 1) for d in day])
        by_sym = {s: float(bps[sym == s].mean()) for s in ("SPY", "QQQ") if (sym == s).any()}
        t = tstat(day, bps)
        ok = (bps.mean() > 0 and t >= 2.8 and bps[early].mean() > 0 and bps[~early].mean() > 0
              and len(by_sym) == 2 and min(by_sym.values()) > 0)
        sday, sbps, _, _ = evaluate(tr, insts, SEARCH)
        rows.append({"family": fam, "params": params, "cfg_i": ci, "search_n": len(sbps),
                     "search_bps": round(float(sbps.mean()), 2) if len(sbps) else np.nan,
                     "search_t": round(tstat(sday, sbps), 2) if len(sbps) else np.nan,
                     "n": len(bps), "mean_bps": round(float(bps.mean()), 2), "t": round(t, 2),
                     "2023-24": round(float(bps[early].mean()), 2), "2025-26": round(float(bps[~early].mean()), 2),
                     **{f"{k}_bps": round(v, 2) for k, v in by_sym.items()}, "stage3": "PASS" if ok else "fail"})
        print(rows[-1], flush=True)
    st = pd.DataFrame(rows)
    st.to_csv(RES / "minute_stage3.csv", index=False)
    pickle.dump({"cfgs": cfgs}, open(OUT / "minute_grid.pkl", "wb"))
    meta.to_csv(RES / "minute_search.csv", index=False)
    print("\nStage 3 passers:", st[st.stage3 == "PASS"][["family", "params"]].to_dict("records"))


def confirm():
    st = pd.read_csv(RES / "minute_stage3.csv")
    cfgs = pickle.load(open(OUT / "minute_grid.pkl", "rb"))["cfgs"]
    insts = [I for I in (load_inst(s) for s in CONFIRM) if I is not None]
    print("confirmation instruments:", [I.sym for I in insts], flush=True)
    rows = []
    for r in st[st.stage3 == "PASS"].itertuples():
        if r.family in ("LSR_1m", "C6_5m"):
            tr = _concat([lsr_trades(I.sym, r.family) for I in insts])
        else:
            tr = _concat([run(I, cfgs[int(r.cfg_i)]) for I in insts])
        day, bps, sign, sym = evaluate(tr, insts, FULL)
        per = pd.Series(bps).groupby(sym).mean()
        t = tstat(day, bps)
        ok = bps.mean() > 0 and t >= 2.0 and (per > 0).mean() >= 0.6
        rows.append({"family": r.family, "params": r.params, "n": len(bps), "mean_bps": round(float(bps.mean()), 2),
                     "t": round(t, 2), "share_instruments_positive": round(float((per > 0).mean()), 2),
                     "stage4": "PASS" if ok else "fail"})
        print(rows[-1], flush=True)
    out = pd.DataFrame(rows)
    if len(out):
        sel = out[out.stage4 == "PASS"].sort_values("t", ascending=False).drop_duplicates("family").head(3)
        out["selected"] = out.index.isin(sel.index)
    out.to_csv(RES / "minute_stage4.csv", index=False)
    print(json.dumps(out.to_dict("records"), default=str, indent=1))


if __name__ == "__main__":
    {"search": search, "confirm": confirm}[sys.argv[1]]()
