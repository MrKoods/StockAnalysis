"""python -m daytrade.research.families_scan -> per-session sums for every family config (search period only)."""

import pickle
import time

import numpy as np
import pandas as pd

from ..config import OUTPUT_DIR
from .families import FILTERS, grid, run_cfg
from .hourly import HOLDOUT_START, load_panel, tickers


def main():
    t0 = time.time()
    panels = [p for p in (load_panel(t) for t in tickers()) if p is not None]
    sessions = sorted({d for p in panels for d in p.days if d < HOLDOUT_START})
    s_ix = {d: i for i, d in enumerate(sessions)}
    cfgs = list(grid())
    metas, sums = [], []
    for ci, cfg in enumerate(cfgs):
        parts = [run_cfg(p, cfg) for p in panels]
        parts = [x for x in parts if x is not None]
        if not parts:
            continue
        d = {k: np.concatenate([x[k] for x in parts]) for k in parts[0]}
        keep = np.array([day < HOLDOUT_START for day in d["day"]]) & ~np.isnan(d["r"])
        d = {k: v[keep] for k, v in d.items()}
        di = np.array([s_ix[x] for x in d["day"]])
        for fk, f in FILTERS.items():
            m = f(d)
            n = int(m.sum())
            if n < 300:
                continue
            sums.append(np.bincount(di[m], weights=d["r"][m], minlength=len(sessions)).astype(np.float32))
            metas.append({"cfg_i": ci, "family": cfg.family, "params": repr(cfg.p), "filter": fk,
                          "n": n, "mean_atr": float(d["r"][m].mean())})
        if ci % 50 == 0:
            print(f"cfg {ci + 1}/{len(cfgs)} configs={len(metas)} {time.time() - t0:.0f}s", flush=True)
    out = OUTPUT_DIR / "research"
    np.savez_compressed(out / "families_search.npz", M=np.vstack(sums))
    pd.DataFrame(metas).to_csv(out / "families_meta.csv", index=False)
    pickle.dump({"cfgs": cfgs, "sessions": sessions}, open(out / "families_grid.pkl", "wb"))
    print("FAMILIES DONE", len(metas), flush=True)


if __name__ == "__main__":
    main()
