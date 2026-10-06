"""python -m daytrade.research.fresh_test -> scores the pre-registered candidates on the 463
S&P 500 tickers that no search has touched (research_results/SHORTLIST2_fresh_tickers.md)."""

import pickle

import numpy as np
import pandas as pd

from ..config import OUTPUT_DIR, ROOT
from .engine import Det, Exit, Universe, detect, run, stats
from .mass import FILTERS

RES = ROOT / "research_results"


def _keep(fname):
    if fname == "none":
        return None
    f = FILTERS[fname]
    return lambda r: bool(f(pd.DataFrame([r]))[0])


def main():
    tickers = pd.read_csv(ROOT / "daytrade" / "sp500_new.csv")["ticker"].tolist()
    cands = [("C0", "1m", Det(), Exit(), "none"),
             ("C6", "5m", Det(base="5m", trigger="close_out"), Exit(target="R", target_r=2.0), "none")]
    grids = {b: pickle.load(open(OUTPUT_DIR / "research" / f"mass_{b}_grid.pkl", "rb")) for b in ("1m", "5m")}
    for r in pd.read_csv(RES / "fresh_ticker_candidates.csv").itertuples():
        g = grids[r.base]
        cands.append((r.id, r.base, g["dets"][int(r.det_i)], g["exits"][int(r.exit_i)], r.filter))

    rows = []
    for base in ("1m", "5m"):
        U = Universe(tickers=tickers, base=base)
        print(f"{base}: {len(U.days)} ticker-days, {len(U.sessions())} sessions", flush=True)
        cache = {}
        for cid, b, det, ex, fname in cands:
            if b != base:
                continue
            if det not in cache:
                cache[det] = detect(U, det)
            tr = run(U, cache[det], ex, _keep(fname))
            s = stats(tr)
            lo = tr[tr["direction"] == "long"]["r_net"].mean() if len(tr) else np.nan
            sh = tr[tr["direction"] == "short"]["r_net"].mean() if len(tr) else np.nan
            ok = (s["n"] >= 300 and s["mean"] >= 0.05 and s["t_day"] >= 3.0 and lo > 0 and sh > 0)
            rows.append({"id": cid, "base": b, "filter": fname, **{k: round(v, 3) for k, v in s.items()},
                         "long_mean": round(lo, 3), "short_mean": round(sh, 3),
                         "verdict": "PASS" if ok else "fail"})
            print(rows[-1], flush=True)
    out = pd.DataFrame(rows)
    out.to_csv(RES / "fresh_ticker_results.csv", index=False)
    print(out.to_string(index=False))


if __name__ == "__main__":
    main()
