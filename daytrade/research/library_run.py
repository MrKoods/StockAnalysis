"""PROTOCOL11, applied mechanically.

    python -m daytrade.research.library_run search    # Stages 1-3 (SEARCH instruments)
    python -m daytrade.research.library_run confirm   # Stage 4 (CONFIRMATION instruments)
"""

from __future__ import annotations

import json
import os
import pickle
import sys
import time
from datetime import date
from multiprocessing import Pool

import numpy as np
import pandas as pd

from ..config import OUTPUT_DIR, ROOT
from .library import FILTERS, grid, load, run
from .mass import pbo_cscv

RES = ROOT / "research_results"
OUT = OUTPUT_DIR / "research"
SEARCH_SYMS = ["SPY", "QQQ", "AAPL", "MSFT", "NVDA", "AMZN"]
CONFIRM_SYMS = ["DIA", "GOOGL", "TSLA", "AMD", "NFLX", "XOM", "IWM", "JPM", "BAC", "INTC", "GLD", "TLT", "XLF", "XLE"]
SEARCH = (date(2018, 1, 1), date(2023, 1, 1))
HOLD = (date(2023, 1, 1), date(2100, 1, 1))
FULL = (date(2018, 1, 1), date(2100, 1, 1))

_INST: dict = {}


def _init(syms):
    for s in list(syms) + ["SPY"]:
        if s not in _INST:
            I = load(s)
            if I is not None:
                _INST[s] = I


def drift(I, period):
    m = np.array([period[0] <= d < period[1] for d in I.days])
    return float(np.nanmean(I.C[m, -1] / I.O[m, 0] - 1) / 390) if m.any() else 0.0


def trades_for(cfg, syms):
    parts = []
    for s in syms:
        I = _INST.get(s)
        if I is None:
            continue
        t = run(I, cfg, _INST.get("SPY"))
        if t is not None and len(t["day"]):
            parts.append(t)
    if not parts:
        return None
    return {k: np.concatenate([p[k] for p in parts]) for k in parts[0]}


def score(t, period, mults=1.0):
    """-> (day, bps, sign, sym, mask-in-period) with drift removed and costs x mults."""
    m = np.array([period[0] <= d < period[1] for d in t["day"]])
    mu = np.array([drift(_INST[s], period) for s in t["sym"][m]]) if m.any() else np.array([])
    exc = t["ret"][m] - t["sign"][m] * mu * t["minutes"][m]
    bps = exc * 1e4 - 2 * mults * t["cost"][m]
    return t["day"][m], bps, t["sign"][m], t["sym"][m], m


def tstat(day, bps):
    s = pd.Series(bps).groupby(np.asarray(day)).sum()
    sd = s.std(ddof=1)
    return float(s.mean() / (sd / np.sqrt(len(s)))) if len(s) > 2 and sd > 0 else float("nan")


def _stage1_job(args):
    ci, cfg, sessions = args
    t = trades_for(cfg, SEARCH_SYMS)
    if t is None:
        return []
    day, bps, sign, sym, m = score(t, SEARCH)
    if not len(bps):
        return []
    feats = {k: t[k][m] for k in ("trend", "gap", "or30", "inside")}
    s_ix = {d: i for i, d in enumerate(sessions)}
    di = np.array([s_ix[d] for d in day])
    out = []
    for fk, f in FILTERS.items():
        mm = f(feats, sign)
        n = int(mm.sum())
        if n < 50:
            continue
        sums = np.bincount(di[mm], weights=bps[mm], minlength=len(sessions)).astype(np.float32)
        out.append(({"cfg_i": ci, "family": cfg.family, "params": repr(cfg.p), "filter": fk, "n": n,
                     "mean_bps": float(bps[mm].mean()), "t": tstat(day[mm], bps[mm])}, sums))
    return out


def search():
    t0 = time.time()
    _init(SEARCH_SYMS)
    missing = [s for s in SEARCH_SYMS if s not in _INST]
    assert not missing, f"missing search data: {missing}"
    sessions = sorted({d for s in SEARCH_SYMS for d in _INST[s].days if SEARCH[0] <= d < SEARCH[1]})
    cfgs = list(grid())
    print(f"{len(cfgs)} strategies x {len(FILTERS)} filters on {SEARCH_SYMS}; {len(sessions)} search sessions",
          flush=True)
    metas, sums = [], []
    with Pool(max(1, (os.cpu_count() or 2) - 1), initializer=_init, initargs=(SEARCH_SYMS,)) as pool:
        for i, res in enumerate(pool.imap(_stage1_job, [(ci, c, sessions) for ci, c in enumerate(cfgs)], chunksize=4)):
            for meta, s in res:
                metas.append(meta)
                sums.append(s)
            if i % 250 == 0:
                print(f"  {i}/{len(cfgs)} strategies, {len(metas)} configs, {time.time() - t0:.0f}s", flush=True)
    meta = pd.DataFrame(metas)
    M = np.vstack(sums).astype(float)
    np.savez_compressed(OUT / "library_search.npz", M=M)
    meta.to_csv(RES / "library_search.csv", index=False)
    pickle.dump({"cfgs": cfgs}, open(OUT / "library_grid.pkl", "wb"))

    print(f"\n=== Stage 1: {len(meta):,} configs (search: {SEARCH_SYMS}, 2018-2022) ===", flush=True)
    T = M.shape[1]
    fam_rows = []
    for fam in sorted(meta.family.unique()):
        idx = np.flatnonzero(meta.family == fam)
        X = M[idx]
        mu, sd = X.mean(1), X.std(1, ddof=1)
        sd = np.where(sd > 0, sd, np.inf)
        Z = (X - mu[:, None]) / sd[:, None]
        obs = float((mu / (sd / np.sqrt(T))).max())
        rng = np.random.default_rng(0)
        best = [((Z @ (np.bincount(rng.integers(0, T, T), minlength=T) / T)) * np.sqrt(T)).max() for _ in range(200)]
        pbo = pbo_cscv(X, S=10)
        m = meta.iloc[idx]
        fam_rows.append({"family": fam, "configs": len(m), "median_bps": round(m.mean_bps.median(), 2),
                         "best_t": round(obs, 2), "luck_p": round(float(np.mean(np.array(best) >= obs)), 3),
                         "pbo": round(pbo["pbo"], 2)})
        print(fam_rows[-1], flush=True)
    pd.DataFrame(fam_rows).to_csv(RES / "library_families.csv", index=False)

    short = []
    for fam in sorted(meta.family.unique()):
        m = meta[(meta.family == fam) & (meta.n >= 300)].sort_values("t", ascending=False)
        m = m.drop_duplicates(subset=["n", "mean_bps"])
        picked = []
        for r in m.itertuples():
            if len(picked) == 3:
                break
            if all(r.params != p.params for p in picked):
                picked.append(r)
        short += picked
    short = pd.DataFrame(short)
    print(f"\n=== Stage 2: shortlist ({len(short)}) ===")
    print(short[["family", "params", "filter", "n", "mean_bps", "t"]].round(2).to_string(index=False), flush=True)

    print("\n=== Stage 3: holdout 2023+ on the same six (once) ===", flush=True)
    rows = []
    for r in short.itertuples():
        cfg = cfgs[int(r.cfg_i)]
        t = trades_for(cfg, SEARCH_SYMS)
        day, bps, sign, sym, m = score(t, HOLD)
        feats = {k: t[k][m] for k in ("trend", "gap", "or30", "inside")}
        mm = FILTERS[r.filter](feats, sign)
        day, bps, sign, sym = day[mm], bps[mm], sign[mm], sym[mm]
        early = np.array([d < date(2025, 1, 1) for d in day])
        per = pd.Series(bps).groupby(sym).mean()
        sides = [bps[sign == s].mean() for s in (1, -1) if (sign == s).any()]
        tt = tstat(day, bps)
        ok = (len(bps) > 0 and bps.mean() > 0 and tt >= 3.1 and bps[early].mean() > 0 and bps[~early].mean() > 0
              and (per > 0).sum() >= 4 and all(v > 0 for v in sides))
        rows.append({"cfg_i": int(r.cfg_i), "family": r.family, "params": r.params, "filter": r.filter,
                     "search_n": r.n, "search_bps": round(r.mean_bps, 2), "search_t": round(r.t, 2),
                     "ho_n": len(bps), "ho_bps": round(float(bps.mean()), 2) if len(bps) else np.nan,
                     "ho_t": round(tt, 2), "ho_2023_24": round(float(bps[early].mean()), 2) if early.any() else np.nan,
                     "ho_2025_26": round(float(bps[~early].mean()), 2) if (~early).any() else np.nan,
                     "ho_insts_pos": int((per > 0).sum()), "stage3": "PASS" if ok else "fail"})
        print(rows[-1], flush=True)
    st = pd.DataFrame(rows)
    st.to_csv(RES / "library_stage3.csv", index=False)
    print("\nStage 3 passers:", st[st.stage3 == "PASS"][["family", "params", "filter"]].to_dict("records"))
    print(f"DONE {time.time() - t0:.0f}s")


def confirm():
    st = pd.read_csv(RES / "library_stage3.csv")
    cfgs = pickle.load(open(OUT / "library_grid.pkl", "rb"))["cfgs"]
    _init(CONFIRM_SYMS)
    have = [s for s in CONFIRM_SYMS if s in _INST]
    print("confirmation instruments:", have, flush=True)
    rows = []
    for r in st[st.stage3 == "PASS"].itertuples():
        cfg = cfgs[int(r.cfg_i)]
        t = trades_for(cfg, have)
        res = {}
        for mult in (1.0, 2.0):
            day, bps, sign, sym, m = score(t, FULL, mult)
            feats = {k: t[k][m] for k in ("trend", "gap", "or30", "inside")}
            mm = FILTERS[r.filter](feats, sign)
            res[mult] = (day[mm], bps[mm], sym[mm])
        day, bps, sym = res[1.0]
        per = pd.Series(bps).groupby(sym).mean()
        tt = tstat(day, bps)
        ok = bps.mean() > 0 and tt >= 2.0 and (per > 0).mean() >= 0.6 and res[2.0][1].mean() > 0
        months = (pd.Series(pd.to_datetime(pd.Series(day))).dt.to_period("M").nunique())
        rows.append({"family": r.family, "params": r.params, "filter": r.filter, "n": len(bps),
                     "bps": round(float(bps.mean()), 2), "bps_2x_cost": round(float(res[2.0][1].mean()), 2),
                     "t": round(tt, 2), "insts_pos_share": round(float((per > 0).mean()), 2),
                     "trades_per_month_per_inst": round(len(bps) / max(months, 1) / max(len(have), 1), 2),
                     "stage4": "PASS" if ok else "fail"})
        print(rows[-1], flush=True)
    out = pd.DataFrame(rows)
    if len(out):
        sel = out[out.stage4 == "PASS"].sort_values("t", ascending=False).drop_duplicates("family")
        out["paper_trade"] = out.index.isin(sel.index)
    out.to_csv(RES / "library_stage4.csv", index=False)
    print(json.dumps(out.to_dict("records"), indent=1, default=str))


if __name__ == "__main__":
    {"search": search, "confirm": confirm}[sys.argv[1]]()
