"""Search harness: every config tried is logged, with its score on the search split only.

Split (fixed before searching, 2026-10-06):
  1m data   search = 2026-09-08..2026-09-23 (12 sessions)
            holdout = 2026-09-24..2026-10-05 (8 sessions) -- shortlist only
  5m data   search = sessions before 2026-08-24, holdout = 2026-08-24..2026-10-05
"""

from __future__ import annotations

import itertools
from datetime import date
from pathlib import Path

import pandas as pd

from ..config import OUTPUT_DIR
from .engine import Det, Exit, Universe, detect, run, stats

SPLIT_1M = date(2026, 9, 24)
SPLIT_5M = date(2026, 8, 24)
LOG = OUTPUT_DIR / "research" / "configs_tried.csv"


class Searcher:
    def __init__(self, base: str = "1m"):
        self.U = Universe(base=base)
        self.split = SPLIT_1M if base == "1m" else SPLIT_5M
        self._entries: dict = {}
        LOG.parent.mkdir(parents=True, exist_ok=True)

    def entries(self, det: Det):
        if det not in self._entries:
            self._entries[det] = detect(self.U, det)
        return self._entries[det]

    def trades(self, det: Det, ex: Exit, keep=None, part: str = "search") -> pd.DataFrame:
        tr = run(self.U, self.entries(det), ex, keep)
        if tr.empty:
            return tr
        if part == "search":
            return tr[tr["day"] < self.split]
        if part == "holdout":
            return tr[tr["day"] >= self.split]
        return tr

    def score(self, family: str, det: Det, ex: Exit, keep=None, keep_name: str = "-") -> dict:
        s = stats(self.trades(det, ex, keep, "search"))
        row = {"family": family, "det": repr(det), "exit": repr(ex), "filter": keep_name, **s}
        pd.DataFrame([row]).to_csv(LOG, mode="a", header=not Path(LOG).exists(), index=False)
        return row


def exit_grid():
    targets = [("level", 2.0, 1.5), ("level", 2.0, 1.0), ("R", 1.0, 0), ("R", 1.5, 0), ("R", 2.0, 0),
               ("R", 3.0, 0), ("level_cap", 2.0, 0), ("level_cap", 3.0, 0), ("none", 0, 0)]
    for (tg, tr, mr), be, part, hold, buf in itertools.product(
            targets, [None, 1.0], [None, 1.0], [None, 30, 60], [0.0, 0.05]):
        if be is not None and part is not None:
            continue  # partial already moves the stop to breakeven
        yield Exit(target=tg, target_r=tr, min_r=mr or 1.5, be_at_r=be, partial_at_r=part,
                   max_hold=hold, stop_buf_atr=buf)
