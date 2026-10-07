"""python -m daytrade.research.daily_validate -> PROTOCOL8 Stages 2-4, applied mechanically.

Ambiguity resolved here (protocol is silent): a CAL config that passes Stage 3 has no confirmation
t, so for the final ranking its Stage-3 t stands in for it.
"""

import json
import pickle
from datetime import date

import numpy as np
import pandas as pd

from ..config import OUTPUT_DIR, ROOT
from .daily import CAL_FILTERS, FILTERS, DCfg, cal_hedge, load, max_lag, nw_t, run
from .families2_validate import t_luck
from .mass import pbo_cscv

RES = ROOT / "research_results"
HOLD = (date(2018, 1, 1), date(2026, 10, 6))
SPLIT = date(2022, 1, 1)


def evaluate(P, cfg, fname, lo, hi):
    d = run(P, cfg)
    m = np.array([lo <= x < hi for x in d["day"]])
    if cfg.family == "CAL":
        d["hedged"] = cal_hedge(P, d, m)
    f = (CAL_FILTERS if cfg.family == "CAL" else FILTERS)[fname]
    m &= f(d) & ~np.isnan(d["hedged"])
    day, h, s = d["day"][m], d["hedged"][m], d["sign"][m]
    early = np.array([x < SPLIT for x in day])
    return {"n": int(m.sum()), "mean": float(h.mean()) if m.any() else np.nan,
            "raw": float(d["raw"][m].mean()) if m.any() else np.nan,
            "t": nw_t(day, h, max_lag(cfg)),
            "early": float(h[early].mean()) if early.any() else np.nan,
            "late": float(h[~early].mean()) if (~early).any() else np.nan,
            "long": float(h[s > 0].mean()) if (s > 0).any() else np.nan,
            "short": float(h[s < 0].mean()) if (s < 0).any() else np.nan}


def main():
    out = OUTPUT_DIR / "research"
    M = np.load(out / "daily_search.npz")["M"].astype(float)
    meta = pd.read_csv(out / "daily_meta.csv")
    cfgs = pickle.load(open(out / "daily_grid.pkl", "rb"))["cfgs"]
    T = M.shape[1]

    print("=== Stage 1: search summary per family (hedged net bps) ===")
    summary = {}
    for fam in meta.family.unique():
        idx = np.flatnonzero(meta.family == fam)
        m = meta.iloc[idx]
        obs, p = t_luck(M[idx], T)
        pbo = pbo_cscv(M[idx], S=10)
        summary[fam] = {"configs": len(m), "median_bps": float(m.mean_bps.median()),
                        "best_t_nw": float(m.t_nw.max()), "luck_p": p, "pbo": pbo["pbo"],
                        "IS_best_pos_OOS": pbo["share_IS_best_positive_OOS"]}
        print(fam, json.dumps({k: round(v, 3) if isinstance(v, float) else v for k, v in summary[fam].items()}))
        print(m.sort_values("t_nw", ascending=False)[["params", "filter", "n", "mean_bps", "raw_bps", "t_nw"]]
              .head(5).round(2).to_string(index=False))

    print("\n=== Stage 2: shortlist ===")
    short = []
    for fam in meta.family.unique():
        m = meta[(meta.family == fam) & (meta.n >= (200 if fam == "CAL" else 2000))]
        m = m.sort_values("t_nw", ascending=False).drop_duplicates(subset=["n", "mean_bps"])
        if m.empty:
            continue
        short.append(m.iloc[0])
        nxt = m[m.params != m.iloc[0].params]
        if len(nxt):
            short.append(nxt.iloc[0])
    short = pd.DataFrame(short)
    print(short[["family", "params", "filter", "n", "mean_bps", "t_nw"]].round(2).to_string(index=False))

    print("\n=== Stage 3: S&P 500 holdout 2018-2026 (once) ===")
    sp500, etf = load("sp500"), load("etf")
    rows = []
    for _, r in short.iterrows():
        cfg = cfgs[int(r.cfg_i)]
        P = etf if cfg.family == "CAL" else sp500
        s = evaluate(P, cfg, r["filter"], *HOLD)
        twin_ok, twin_mean = True, np.nan
        if cfg.family in ("REV", "MRV", "BRK") and cfg.p[-1] == "close":
            tw = evaluate(P, DCfg(cfg.family, cfg.p[:-1] + ("open",)), r["filter"], *HOLD)
            twin_mean = tw["mean"]
            twin_ok = twin_mean > 0
        sides_ok = all(np.isnan(v) or v > 0 for v in (s["long"], s["short"]))
        ok = s["mean"] > 0 and s["t"] >= 2.7 and s["early"] > 0 and s["late"] > 0 and sides_ok and twin_ok
        rows.append({"family": cfg.family, "params": r.params, "filter": r["filter"], "search_t": round(r.t_nw, 2),
                     **{f"ho_{k}": round(v, 2) for k, v in s.items()}, "twin_mean": round(twin_mean, 2),
                     "stage3": "PASS" if ok else "fail", "cfg_i": int(r.cfg_i)})
        print(rows[-1], flush=True)
    st = pd.DataFrame(rows)

    print("\n=== Stage 4: S&P 400 / S&P 600, 2018-2026 (once each) ===")
    st["t400"] = st["t600"] = st["bps400"] = st["bps600"] = np.nan
    todo = st[(st.stage3 == "PASS") & (st.family != "CAL")]
    if len(todo):
        conf = {"400": load("sp400"), "600": load("sp600")}
        for i, r in todo.iterrows():
            for k, P in conf.items():
                s = evaluate(P, cfgs[int(r.cfg_i)], r["filter"], *HOLD)
                st.loc[i, f"t{k}"], st.loc[i, f"bps{k}"] = round(s["t"], 2), round(s["mean"], 2)
    conf_ok = (st.t400 >= 2.0) & (st.t600 >= 2.0) & (st.bps400 > 0) & (st.bps600 > 0)
    st["stage4"] = np.where((st.family == "CAL") & (st.stage3 == "PASS"), "n/a (CAL)",
                            np.where(conf_ok, "PASS", "-"))
    st["rank_t"] = np.where(st.family == "CAL", st.ho_t, st[["t400", "t600"]].min(axis=1))
    elig = st[(st.stage4 == "PASS") | (st.stage4 == "n/a (CAL)")]
    sel = elig.sort_values("rank_t", ascending=False).drop_duplicates("family").head(3)
    st["selected"] = st.index.isin(sel.index)
    st.to_csv(RES / "daily_validation.csv", index=False)
    json.dump(summary, open(RES / "daily_search_summary.json", "w"), indent=2)
    print(st.drop(columns=["cfg_i"]).to_string(index=False))
    print("\nSELECTED:", sel[["family", "params", "filter"]].to_dict("records"))


if __name__ == "__main__":
    main()
