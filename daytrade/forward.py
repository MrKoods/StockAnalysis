"""Forward test of candidate C6 on sessions that did not exist during the search.

C6 (chosen 2026-10-06 after a 734-config search, see output/research/):
  * 5m base bars; sweep + reclaim on 15m bars (3 bars); PDH/PDL + 4H levels
  * CHoCH on 5m (swing_n 2, within 20 bars), first FVG in the leg else 62-79%
  * trigger: price trades into the zone, then any 5m close back out of it
    (candle color not required); enter at the next bar's open, before 15:30
  * stop: sweep extreme + 2 ticks; target: fixed 2R; flatten at 15:55
  * max 1 open trade and 2 trades per stock per day

Pass bar, fixed before any forward data exists: after >= 30 forward sessions,
PASS if mean net R >= +0.08 and day-clustered t >= 2.0 on forward trades only;
FAIL if mean net R < 0; otherwise keep collecting to 60 sessions.

Each run recomputes the ledger from the archive (deterministic, idempotent).
"""

from __future__ import annotations

from datetime import date

import pandas as pd

from .config import ROOT
from .research.engine import Det, Exit, Universe, detect, run, stats

FORWARD_START = date(2026, 10, 6)   # first session after the search data ended
C6_DET = Det(base="5m", trigger="close_out")
C6_EXIT = Exit(target="R", target_r=2.0)
LEDGER = ROOT / "data" / "forward" / "c6_forward_trades.csv"


def update() -> dict:
    U = Universe(base="5m")
    tr = run(U, detect(U, C6_DET), C6_EXIT)
    tr = tr[tr["day"] >= FORWARD_START] if len(tr) else tr
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    tr.to_csv(LEDGER, index=False)
    s = stats(tr)
    sessions = len({d for (_, d) in U.days if d >= FORWARD_START})
    s["sessions"] = sessions
    if sessions >= 30 and s["n"]:
        s["verdict"] = ("PASS" if s["mean"] >= 0.08 and s["t_day"] >= 2.0
                        else "FAIL" if s["mean"] < 0 else "keep collecting")
    else:
        s["verdict"] = f"collecting ({sessions}/30 sessions)"
    return s


def as_table(tr: pd.DataFrame) -> pd.DataFrame:
    return tr[["day", "ticker", "direction", "level", "reason", "r_net"]]
