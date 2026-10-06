"""python -m daytrade.research.run_mass {1m|5m} -> output/research/mass_<base>.npz + meta csv"""

import pickle
import sys

import numpy as np

from ..config import OUTPUT_DIR
from .mass import scan

base = sys.argv[1]
U, dets, exits, meta, sessions, M, C = scan(base, log=lambda m: print(m, flush=True))
out = OUTPUT_DIR / "research"
out.mkdir(parents=True, exist_ok=True)
np.savez_compressed(out / f"mass_{base}.npz", M=M, C=C)
meta.to_csv(out / f"mass_{base}_meta.csv", index=False)
with open(out / f"mass_{base}_grid.pkl", "wb") as f:
    pickle.dump({"dets": dets, "exits": exits, "sessions": sessions}, f)
print("DONE", base, M.shape, flush=True)
