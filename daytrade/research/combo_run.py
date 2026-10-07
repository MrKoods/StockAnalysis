"""python -m daytrade.research.combo_run -> PROTOCOL9, all stages, applied mechanically."""

import json
import time
from datetime import date

import numpy as np
import pandas as pd

from ..config import ROOT
from .combo import WINDOWS, prepare, random_models, ridge_beta, ridge_score, score_of, trades
from .families2 import build
from .hourly import HOLDOUT_START, tickers
from .mass import pbo_cscv

RES = ROOT / "research_results"
N_MODELS = 10_000


def tstat(day, bps):
    s = pd.Series(bps).groupby(np.asarray(day)).sum()
    sd = s.std(ddof=1)
    return float(s.mean() / (sd / np.sqrt(len(s)))) if len(s) > 2 and sd > 0 else float("nan")


def evaluate(P, score, window, q, side, mask):
    day, bps, sign = trades(P, score, window, q, side, mask)
    if not len(bps):
        return {"n": 0, "mean": np.nan, "t": np.nan, "h1": np.nan, "h2": np.nan, "long": np.nan, "short": np.nan}
    early = np.array([x < date(2026, 1, 1) for x in day])
    return {"n": len(bps), "mean": float(bps.mean()), "t": tstat(day, bps),
            "h1": float(bps[early].mean()) if early.any() else np.nan,
            "h2": float(bps[~early].mean()) if (~early).any() else np.nan,
            "long": float(bps[sign > 0].mean()) if (sign > 0).any() else np.nan,
            "short": float(bps[sign < 0].mean()) if (sign < 0).any() else np.nan}


def main():
    t0 = time.time()
    P5 = prepare(build(tickers()))
    search = np.array([d < HOLDOUT_START for d in P5.days])
    hold = ~search
    s_ix = {d: i for i, d in enumerate(P5.days[search])}
    print(f"prepared S&P 500: {len(P5.days)} sessions ({search.sum()} search) {time.time() - t0:.0f}s", flush=True)

    models = random_models(N_MODELS)
    rows, sums = [], []
    for i, m in enumerate(models):
        day, bps, _ = trades(P5, score_of(P5, m), m.window, m.q, m.side, search)
        di = np.array([s_ix[x] for x in day])
        sums.append(np.bincount(di, weights=bps, minlength=search.sum()).astype(np.float32))
        rows.append({"id": f"R{i:05d}", "window": m.window, "feats": "|".join(m.feats),
                     "weights": "|".join(f"{w:+g}" for w in m.weights), "q": m.q, "side": m.side,
                     "n": len(bps), "mean": float(bps.mean()), "t": tstat(day, bps)})
        if i % 1000 == 0:
            print(f"model {i}/{N_MODELS} {time.time() - t0:.0f}s", flush=True)
    meta = pd.DataFrame(rows)
    M = np.vstack(sums).astype(float)

    ridge = {}
    for w in WINDOWS:
        feats, beta = ridge_beta(P5, w, search)
        ridge[w] = (feats, beta)
        day, bps, _ = trades(P5, ridge_score(P5, feats, beta), w, 0.1, "both", search)
        meta.loc[len(meta)] = {"id": f"RIDGE_{w}", "window": w, "feats": "|".join(feats),
                               "weights": "|".join(f"{b:+.2e}" for b in beta), "q": 0.1, "side": "both",
                               "n": len(bps), "mean": float(bps.mean()), "t": tstat(day, bps)}

    rnd = meta[meta.id.str.startswith("R0") | meta.id.str.startswith("R1")].copy()
    T = M.shape[1]
    mu, sd = M.mean(1), M.std(1, ddof=1)
    sd = np.where(sd > 0, sd, np.inf)
    Z = (M - mu[:, None]) / sd[:, None]
    obs = float((mu / (sd / np.sqrt(T))).max())
    rng = np.random.default_rng(0)
    best = [((Z @ (np.bincount(rng.integers(0, T, T), minlength=T) / T)) * np.sqrt(T)).max() for _ in range(300)]
    luck = {"best_t": obs, "null_p95": float(np.percentile(best, 95)), "p": float(np.mean(np.array(best) >= obs))}
    pbo = pbo_cscv(M, S=10)
    print("\n=== Stage 1 ===")
    print("random models: median mean bps", round(rnd["mean"].median(), 2), "| 95% range",
          rnd["mean"].quantile([0.05, 0.95]).round(2).tolist())
    print("luck:", json.dumps({k: round(v, 3) for k, v in luck.items()}))
    print("PBO:", json.dumps({k: round(v, 3) for k, v in pbo.items()}))
    print("by window (median mean bps):", rnd.groupby("window")["mean"].median().round(2).to_dict())
    print(meta.sort_values("t", ascending=False).head(15).to_string(index=False))
    print(meta[meta.id.str.startswith("RIDGE")].to_string(index=False))

    short = (rnd[rnd.n >= 3000].sort_values("t", ascending=False)
             .drop_duplicates(subset=["n", "mean"]).head(10))
    short = pd.concat([short, meta[meta.id.str.startswith("RIDGE")]])

    def score_for(P, r):
        if r.id.startswith("RIDGE"):
            feats, beta = ridge[r.window]
            return ridge_score(P, feats, beta)
        m = models[int(r.id[1:])]
        return score_of(P, m)

    print("\n=== Stage 3: S&P 500 holdout (once) ===")
    out = []
    for _, r in short.iterrows():
        s = evaluate(P5, score_for(P5, r), r.window, r.q, r.side, hold)
        sides = [v for v, used in ((s["long"], r.side in ("both", "long")), (s["short"], r.side in ("both", "short"))) if used]
        ok = s["mean"] > 0 and s["t"] >= 2.9 and s["h1"] > 0 and s["h2"] > 0 and all(v > 0 for v in sides)
        out.append({"id": r.id, "window": r.window, "feats": r.feats, "weights": r.weights, "q": r.q, "side": r.side,
                    "search_t": round(r.t, 2), "search_bps": round(r["mean"], 2),
                    **{f"ho_{k}": round(v, 2) for k, v in s.items()}, "stage3": "PASS" if ok else "fail"})
        print(out[-1], flush=True)
    st = pd.DataFrame(out)

    print("\n=== Stage 4: S&P 400 / S&P 600 (once each) ===")
    st["t400"] = st["t600"] = st["bps400"] = st["bps600"] = np.nan
    passed = st[st.stage3 == "PASS"]
    if len(passed):
        conf = {k: prepare(build(pd.read_csv(ROOT / "daytrade" / f"sp{k}.csv")["ticker"].tolist()))
                for k in ("400", "600")}
        for i, r in passed.iterrows():
            rr = short[short.id == r.id].iloc[0]
            for k, P in conf.items():
                s = evaluate(P, score_for(P, rr), r.window, r.q, r.side, np.ones(len(P.days), bool))
                st.loc[i, f"t{k}"], st.loc[i, f"bps{k}"] = round(s["t"], 2), round(s["mean"], 2)
    st["stage4"] = np.where((st.t400 >= 2.0) & (st.t600 >= 2.0) & (st.bps400 > 0) & (st.bps600 > 0), "PASS", "-")
    st["conf_t"] = st[["t400", "t600"]].min(axis=1)
    sel = st[st.stage4 == "PASS"].sort_values("conf_t", ascending=False).drop_duplicates("window").head(3)
    st["selected"] = st.id.isin(sel.id)
    st.to_csv(RES / "combo10k_validation.csv", index=False)
    meta.to_csv(RES / "combo10k_search.csv", index=False)
    json.dump({"luck": luck, "pbo": pbo}, open(RES / "combo10k_summary.json", "w"), indent=2)
    print(st.to_string(index=False))
    print("\nSELECTED:", sel[["id", "window", "feats", "weights", "q", "side"]].to_dict("records"))
    print(f"COMBO DONE {time.time() - t0:.0f}s", flush=True)


if __name__ == "__main__":
    main()
