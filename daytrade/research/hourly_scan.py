"""python -m daytrade.research.hourly_scan -> per-session R sums for every hourly config,
SEARCH period only (holdout sessions are dropped before scoring)."""

import pickle
import time

import numpy as np
import pandas as pd

from ..config import OUTPUT_DIR
from .hourly import FILTERS, HOLDOUT_START, det_grid, events, exit_grid, exits, load_panel, tickers


def main():
    t0 = time.time()
    panels = [p for p in (load_panel(t) for t in tickers()) if p is not None]
    sessions = sorted({d for p in panels for d in p.days if d < HOLDOUT_START})
    s_ix = {d: i for i, d in enumerate(sessions)}
    print(f"{len(panels)} tickers, {len(sessions)} search sessions, {time.time() - t0:.0f}s", flush=True)
    dets, exs = list(det_grid()), list(exit_grid())
    metas, sums = [], []
    for di, det in enumerate(dets):
        parts = [events(p, det) for p in panels]
        parts = [x for x in parts if x is not None]
        ev = {k: np.concatenate([x[k] for x in parts]) for k in parts[0]}
        search = np.array([d < HOLDOUT_START for d in ev["day"]])
        ev = {k: v[search] for k, v in ev.items()}
        day_i = np.array([s_ix[d] for d in ev["day"]])
        fm = {k: f(ev) for k, f in FILTERS.items()}
        for xi, ex in enumerate(exs):
            r = exits(ev, ex)
            ok = ~np.isnan(r)
            for fk, m in fm.items():
                m = m & ok
                n = int(m.sum())
                if n < 200:
                    continue
                sums.append(np.bincount(day_i[m], weights=r[m], minlength=len(sessions)).astype(np.float32))
                metas.append({"det_i": di, "exit_i": xi, "filter": fk, "n": n, "mean_r": float(r[m].mean()),
                              **{f"d_{k}": v for k, v in det.__dict__.items()},
                              **{f"x_{k}": v for k, v in ex.__dict__.items()}})
        print(f"det {di + 1}/{len(dets)} events={len(day_i)} configs={len(metas)} {time.time() - t0:.0f}s", flush=True)
    out = OUTPUT_DIR / "research"
    np.savez_compressed(out / "hourly_search.npz", M=np.vstack(sums))
    pd.DataFrame(metas).to_csv(out / "hourly_meta.csv", index=False)
    pickle.dump({"dets": dets, "exits": exs, "sessions": sessions}, open(out / "hourly_grid.pkl", "wb"))
    print("HOURLY DONE", len(metas), flush=True)


if __name__ == "__main__":
    main()
