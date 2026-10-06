"""python -m daytrade.research.analyze_mass {1m|5m}"""

import json
import pickle
import sys

import numpy as np
import pandas as pd

from ..config import OUTPUT_DIR
from .mass import best_of_n_null, pbo_cscv

base = sys.argv[1]
out = OUTPUT_DIR / "research"
z = np.load(out / f"mass_{base}.npz")
M, C = z["M"].astype(np.float64), z["C"]
meta = pd.read_csv(out / f"mass_{base}_meta.csv")
grid = pickle.load(open(out / f"mass_{base}_grid.pkl", "rb"))
dets, exits, sessions = grid["dets"], grid["exits"], grid["sessions"]
T = M.shape[1]

min_n = 60 if base == "1m" else 150
keep = meta["n"].to_numpy() >= min_n
Mk, mk = M[keep], meta[keep].reset_index(drop=True)
mu = Mk.mean(axis=1)
sd = Mk.std(axis=1, ddof=1)
mk["daily_R"] = mu
mk["t_day"] = np.where(sd > 0, mu / (sd / np.sqrt(T)), 0)
mk["pos_days"] = (Mk > 0).mean(axis=1)

for col, src, attrs in [("det", dets, ["trigger", "zone", "reclaim_bars", "swing_n", "choch_window"]),
                        ("exit", exits, ["target", "target_r", "min_r", "be_at_r", "partial_at_r",
                                         "stop_buf_atr", "max_hold"])]:
    idx = mk["det_i" if col == "det" else "exit_i"]
    for a in attrs:
        mk[a] = [getattr(src[i], a) for i in idx]
mk["target"] = mk["target"] + "_" + mk["target_r"].astype(str) + "_" + mk["min_r"].astype(str)
mk["mgmt"] = np.where(mk["partial_at_r"].notna(), "partial1", np.where(mk["be_at_r"].notna(), "be1", "plain"))

print(f"== {base}: {len(meta):,} configs scanned, {keep.sum():,} with n >= {min_n}, {T} sessions ==")
print("\nTop 15 by day-clustered t:")
cols = ["trigger", "zone", "reclaim_bars", "swing_n", "choch_window", "target", "mgmt", "stop_buf_atr",
        "max_hold", "filter", "n", "mean_r", "daily_R", "t_day", "pos_days"]
print(mk.sort_values("t_day", ascending=False)[cols].head(15).round(3).to_string(index=False))

print("\nDistribution of mean R/trade over all eligible configs:")
print(mk["mean_r"].describe(percentiles=[.05, .25, .5, .75, .95]).round(3).to_string())

print("\nMarginal effect of each setting (median mean R/trade across all other settings):")
for a in ["trigger", "zone", "reclaim_bars", "swing_n", "choch_window", "target", "mgmt", "stop_buf_atr",
          "max_hold", "filter"]:
    g = mk.groupby(a, dropna=False)["mean_r"].median().round(3)
    print(f"  {a}: " + ", ".join(f"{k}={v:+.3f}" for k, v in g.items()))

S = 10 if base == "1m" else 8
pbo = pbo_cscv(Mk, S=S)
null = best_of_n_null(Mk)
print("\nOverfitting check (CSCV):", json.dumps({k: round(v, 3) for k, v in pbo.items()}))
print("Best-of-N luck baseline:", json.dumps({k: round(v, 4) for k, v in null.items()}))
mk.sort_values("t_day", ascending=False).head(200).to_csv(out / f"mass_{base}_top200.csv", index=False)
json.dump({"pbo": pbo, "null": null, "n_configs": int(len(meta)), "n_eligible": int(keep.sum())},
          open(out / f"mass_{base}_summary.json", "w"), indent=2)
