"""Hourly: run PROTOCOL10 stages automatically once the needed Dukascopy history is complete.

Stages 1-3 run once SPY and QQQ have every month 2018-01 .. last full month marked done.
Stage 4 runs once those Stage-3 results exist and every confirmation symbol is complete
(symbols Dukascopy does not serve - all months empty - are skipped).
"""

from datetime import date
import subprocess
import sys

from ..config import DATA_DIR, ROOT
from ..dukascopy import OUT

RES = ROOT / "research_results"
LOG = DATA_DIR / "minute_auto.log"


def months():
    t = date.today()
    y, m = 2018, 1
    while (y, m) < (t.year, t.month):
        yield y, m
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)


def complete(sym: str) -> bool:
    d = OUT / sym
    return d.exists() and all((d / f"{y}-{m:02d}.done").exists() for y, m in months())


def unserved(sym: str) -> bool:
    d = OUT / sym
    files = list(d.glob("*.parquet")) if d.exists() else []
    return len(files) >= 12 and all(f.stat().st_size < 3000 for f in files)


def run(stage: str):
    with open(LOG, "a") as f:
        f.write(f"\n=== {date.today()} running {stage} ===\n")
        f.flush()
        subprocess.run([sys.executable, "-m", "daytrade.research.minute_run", stage], cwd=ROOT,
                       stdout=f, stderr=subprocess.STDOUT, check=False)


def run_library(stage: str):
    with open(LOG, "a") as f:
        f.write(f"
=== {date.today()} library {stage} ===
")
        f.flush()
        subprocess.run([sys.executable, "-m", "daytrade.research.library_run", stage], cwd=ROOT,
                       stdout=f, stderr=subprocess.STDOUT, check=False)


if __name__ == "__main__":
    from .library_run import CONFIRM_SYMS
    from .minute_run import CONFIRM
    if not (RES / "minute_stage3.csv").exists():
        if complete("SPY") and complete("QQQ"):
            run("search")
    elif not (RES / "minute_stage4.csv").exists():
        if all(complete(s) or unserved(s) for s in CONFIRM):
            run("confirm")
    # PROTOCOL11 Stage 4 (day-trader library) once every confirmation symbol is in
    if (RES / "library_stage3.csv").exists() and not (RES / "library_stage4.csv").exists():
        if all(complete(s) or unserved(s) for s in CONFIRM_SYMS):
            run_library("confirm")
