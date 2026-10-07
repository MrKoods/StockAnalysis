"""python -m daytrade.research.daily_scan -> PROTOCOL8 Stage 1 (S&P 500 stocks / ETFs, 2000-2017)."""

import pickle
import time
from datetime import date

import numpy as np
import pandas as pd

from ..config import OUTPUT_DIR
from .daily import CAL_FILTERS, FILTERS, cal_hedge, grid, load, max_lag, nw_t, run

SEARCH = (date(2000, 1, 1), date(2018, 1, 1))


def main():
    t0 = time.time()
    panels = {"stocks": load("sp500"), "etf": load("etf")}
    sessions = [d for d in panels["stocks"].dates if SEARCH[0] <= d < SEARCH[1]]
    s_ix = {d: i for i, d in enumerate(sessions)}
    print(f"loaded {time.time() - t0:.0f}s; {len(sessions)} search sessions", flush=True)
    cfgs = list(grid())
    metas, sums = [], []
    for ci, cfg in enumerate(cfgs):
        P = panels["etf" if cfg.family == "CAL" else "stocks"]
        d = run(P, cfg)
        insearch = np.array([SEARCH[0] <= x < SEARCH[1] for x in d["day"]])
        if cfg.family == "CAL":
            d["hedged"] = cal_hedge(P, d, insearch)
        filters = CAL_FILTERS if cfg.family == "CAL" else FILTERS
        for fk, f in filters.items():
            m = f(d) & insearch & ~np.isnan(d["hedged"])
            n = int(m.sum())
            if n < (100 if cfg.family == "CAL" else 500):
                continue
            di = np.array([s_ix[x] for x in d["day"][m]])
            sums.append(np.bincount(di, weights=d["hedged"][m], minlength=len(sessions)).astype(np.float32))
            metas.append({"cfg_i": ci, "family": cfg.family, "params": repr(cfg.p), "filter": fk, "n": n,
                          "mean_bps": float(d["hedged"][m].mean()), "raw_bps": float(d["raw"][m].mean()),
                          "t_nw": nw_t(d["day"][m], d["hedged"][m], max_lag(cfg))})
        if ci % 50 == 0:
            print(f"cfg {ci + 1}/{len(cfgs)} configs={len(metas)} {time.time() - t0:.0f}s", flush=True)
    out = OUTPUT_DIR / "research"
    np.savez_compressed(out / "daily_search.npz", M=np.vstack(sums))
    pd.DataFrame(metas).to_csv(out / "daily_meta.csv", index=False)
    pickle.dump({"cfgs": cfgs, "sessions": sessions}, open(out / "daily_grid.pkl", "wb"))
    print("DAILY DONE", len(cfgs), "strategies", len(metas), "configs", flush=True)


if __name__ == "__main__":
    main()
