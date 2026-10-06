"""python -m daytrade.research.families2_scan [families2|families3] -> Stage 1 (search)."""

import importlib
import pickle
import sys
import time

import numpy as np
import pandas as pd

from ..config import OUTPUT_DIR
from .families2 import FILTERS, build
from .hourly import HOLDOUT_START, tickers


def main():
    mod = sys.argv[1] if len(sys.argv) > 1 else "families2"
    fam = importlib.import_module(f"daytrade.research.{mod}")
    grid, run = fam.grid, fam.run
    t0 = time.time()
    X = build(tickers())
    sessions = [d for d in X.days if d < HOLDOUT_START]
    s_ix = {d: i for i, d in enumerate(sessions)}
    print(f"{len(X.tickers)} tickers, {len(sessions)} search sessions, {time.time() - t0:.0f}s", flush=True)
    cfgs = list(grid())
    metas, sums = [], []
    for ci, cfg in enumerate(cfgs):
        d = run(X, cfg)
        if d is None:
            continue
        keep = np.array([x < HOLDOUT_START for x in d["day"]]) & ~np.isnan(d["bps"])
        d = {k: v[keep] for k, v in d.items()}
        di = np.array([s_ix[x] for x in d["day"]])
        for fk, f in FILTERS.items():
            m = f(d)
            n = int(m.sum())
            if n < 500:
                continue
            sums.append(np.bincount(di[m], weights=d["bps"][m], minlength=len(sessions)).astype(np.float32))
            metas.append({"cfg_i": ci, "family": cfg.family, "params": repr(cfg.p), "filter": fk,
                          "n": n, "mean_bps": float(d["bps"][m].mean())})
        if ci % 40 == 0:
            print(f"cfg {ci + 1}/{len(cfgs)} configs={len(metas)} {time.time() - t0:.0f}s", flush=True)
    out = OUTPUT_DIR / "research"
    np.savez_compressed(out / f"{mod}_search.npz", M=np.vstack(sums))
    pd.DataFrame(metas).to_csv(out / f"{mod}_meta.csv", index=False)
    pickle.dump({"cfgs": cfgs, "sessions": sessions}, open(out / f"{mod}_grid.pkl", "wb"))
    print(f"{mod.upper()} DONE", len(cfgs), "strategies", len(metas), "configs", flush=True)


if __name__ == "__main__":
    main()
