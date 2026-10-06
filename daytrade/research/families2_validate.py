"""python -m daytrade.research.families2_validate [families2|families3] -> Stages 2-4, applied mechanically.

families2 = PROTOCOL5; families3 = PROTOCOL7 (adds: skip candidates whose search trades duplicate an
earlier pick)."""

import importlib
import json
import pickle
import sys
from datetime import date

import numpy as np
import pandas as pd

from ..config import OUTPUT_DIR, ROOT
from .families2 import FILTERS, build
from .hourly import HOLDOUT_START, tickers
from .mass import pbo_cscv

MOD = sys.argv[1] if len(sys.argv) > 1 else "families2"
run = importlib.import_module(f"daytrade.research.{MOD}").run
DEDUPE = MOD != "families2"

RES = ROOT / "research_results"


def tstat(day, bps):
    s = pd.Series(bps).groupby(np.asarray(day)).sum()
    sd = s.std(ddof=1)
    return float(s.mean() / (sd / np.sqrt(len(s)))) if len(s) > 1 and sd > 0 else float("nan")


def t_luck(X, T, n_boot=300, seed=0):
    mu, sd = X.mean(1), X.std(1, ddof=1)
    sd = np.where(sd > 0, sd, np.inf)
    Z = (X - mu[:, None]) / sd[:, None]
    obs = (mu / (sd / np.sqrt(T))).max()
    rng = np.random.default_rng(seed)
    best = [((Z @ (np.bincount(rng.integers(0, T, T), minlength=T) / T)) * np.sqrt(T)).max() for _ in range(n_boot)]
    return float(obs), float(np.mean(np.array(best) >= obs))


def evaluate(X, cfg, fname, lo=None, hi=None):
    d = run(X, cfg)
    if d is None:
        return None
    m = FILTERS[fname](d) & ~np.isnan(d["bps"])
    days = d["day"]
    if lo is not None:
        m &= np.array([x >= lo for x in days])
    if hi is not None:
        m &= np.array([x < hi for x in days])
    day, bps, sign = days[m], d["bps"][m], d["sign"][m]
    out = {"n": int(m.sum()), "mean_bps": float(bps.mean()) if m.any() else np.nan, "t": tstat(day, bps),
           "long": float(bps[sign > 0].mean()) if (sign > 0).any() else np.nan,
           "short": float(bps[sign < 0].mean()) if (sign < 0).any() else np.nan}
    return out, day, bps


def main():
    out = OUTPUT_DIR / "research"
    M = np.load(out / f"{MOD}_search.npz")["M"].astype(float)
    meta = pd.read_csv(out / f"{MOD}_meta.csv")
    cfgs = pickle.load(open(out / f"{MOD}_grid.pkl", "rb"))["cfgs"]
    T = M.shape[1]
    mu, sd = M.mean(1), M.std(1, ddof=1)
    meta["t"] = mu / (sd / np.sqrt(T))

    print("=== Stage 1: search summary per family ===")
    fam_stats = {}
    for fam in meta["family"].unique():
        idx = np.flatnonzero(meta["family"] == fam)
        m = meta.iloc[idx]
        obs, p = t_luck(M[idx], T)
        pbo = pbo_cscv(M[idx], S=10)
        fam_stats[fam] = {"configs": len(m), "median_bps": float(m.mean_bps.median()), "best_t": obs,
                          "luck_p": p, "pbo": pbo["pbo"], "IS_best_pos_OOS": pbo["share_IS_best_positive_OOS"]}
        print(fam, json.dumps({k: round(v, 3) if isinstance(v, float) else v for k, v in fam_stats[fam].items()}))
        print(m.sort_values("t", ascending=False)[["params", "filter", "n", "mean_bps", "t"]].head(5).round(3)
              .to_string(index=False))

    print("\n=== Stage 2: shortlist (top by t, n >= 2000, + next-best with different core params) ===")
    short = []
    for fam in meta["family"].unique():
        m = meta[(meta.family == fam) & (meta.n >= 2000)].sort_values("t", ascending=False)
        if m.empty:
            continue
        if DEDUPE:
            seen = {(int(x.n), round(float(x.mean_bps), 6)) for x in short}
            m = m[[(int(a), round(float(b), 6)) not in seen for a, b in zip(m.n, m.mean_bps)]]
            m = m.drop_duplicates(subset=["n", "mean_bps"])
            if m.empty:
                continue
        first = m.iloc[0]
        short.append(first)
        nxt = m[m.params != first.params]
        if len(nxt):
            short.append(nxt.iloc[0])
    short = pd.DataFrame(short)
    print(short[["family", "params", "filter", "n", "mean_bps", "t"]].round(3).to_string(index=False))

    print("\n=== Stage 3: S&P 500 holdout (once) ===")
    X5 = build(tickers())
    rows = []
    for _, r in short.iterrows():
        cfg = cfgs[int(r.cfg_i)]
        res = evaluate(X5, cfg, r["filter"], lo=HOLDOUT_START)
        s, day, bps = res
        h1 = bps[np.array([x < date(2026, 1, 1) for x in day])].mean()
        h2 = bps[np.array([x >= date(2026, 1, 1) for x in day])].mean()
        both = all(np.isnan(v) or v > 0 for v in (s["long"], s["short"]))
        ok = s["mean_bps"] > 0 and s["t"] >= 2.6 and h1 > 0 and h2 > 0 and both
        rows.append({"family": r.family, "params": r.params, "filter": r["filter"], "search_t": round(r.t, 2),
                     **{f"ho_{k}": round(v, 3) for k, v in s.items()}, "ho_2025H2": round(h1, 3),
                     "ho_2026": round(h2, 3), "stage3": "PASS" if ok else "fail", "cfg_i": int(r.cfg_i)})
        print(rows[-1], flush=True)
    st = pd.DataFrame(rows)

    print("\n=== Stage 4: confirmation on S&P 400 and S&P 600 (once each) ===")
    passed = st[st.stage3 == "PASS"]
    conf = {}
    for name in ("sp400", "sp600"):
        if len(passed):
            conf[name] = build(pd.read_csv(ROOT / "daytrade" / f"{name}.csv")["ticker"].tolist())
    st["t400"] = np.nan
    st["t600"] = np.nan
    st["bps400"] = np.nan
    st["bps600"] = np.nan
    for i, r in passed.iterrows():
        for name, col in (("sp400", "400"), ("sp600", "600")):
            s, _, _ = evaluate(conf[name], cfgs[int(r.cfg_i)], r["filter"])
            st.loc[i, f"t{col}"] = round(s["t"], 2)
            st.loc[i, f"bps{col}"] = round(s["mean_bps"], 3)
    st["stage4"] = np.where((st.t400 >= 2.0) & (st.t600 >= 2.0) & (st.bps400 > 0) & (st.bps600 > 0), "PASS", "-")
    st["conf_min_t"] = st[["t400", "t600"]].min(axis=1)
    sel = (st[st.stage4 == "PASS"].sort_values("conf_min_t", ascending=False)
           .drop_duplicates("family").head(3))
    st["selected"] = st.index.isin(sel.index)
    st.to_csv(RES / f"{MOD}_validation.csv", index=False)
    json.dump(fam_stats, open(RES / f"{MOD}_search_summary.json", "w"), indent=2)
    print(st.drop(columns=["cfg_i"]).to_string(index=False))
    print("\nSELECTED:", sel[["family", "params", "filter"]].to_dict("records"))


if __name__ == "__main__":
    main()
