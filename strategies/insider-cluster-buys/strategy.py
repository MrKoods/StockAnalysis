"""insider-cluster-buys -- FROZEN paper rule = the pre-registered `chosen` config n2_h5_m75k:
long a S&P 500/400 stock when >= 2 distinct insiders (RPTOWNERCIK) each filed an open-market Form-4
purchase (TRANS_CODE 'P') of >= $25k within the trailing 5 calendar days (by FILING_DATE), qualifying
cluster total >= $75k, one trade per 5-day episode per ticker. Entry = next session open (the runner
enters at the session after the signal); exit = close 5 sessions later (spec hold_sessions=4).

*** DO NOT PROMOTE YET ***  The only insider source is SEC's QUARTERLY bulk Form-345 datasets, which
publish months after the quarter. A 3-5 day hold cannot be traded off data that lags a quarter, so a
live paper run would almost never fire on time and would be invalid. Live promotion needs a near-real-
time Form-4 feed the team does not have. This file encodes the frozen rule for the record only.
"""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pandas as pd

V3 = Path(r"C:\Users\user\Documents\Git\StockAnalysis-V3")
INSIDER_DIR = V3 / "data" / "events" / "insider"
UNI_FILES = {"sp500": "sp500_new.csv", "sp400": "sp400.csv"}

WINDOW_DAYS = 5
MIN_PER_INSIDER = 25_000.0
N_INS = 2
MIN_TOTAL = 75_000.0


def universe() -> list[str]:
    out: set[str] = set()
    for fn in UNI_FILES.values():
        try:
            df = pd.read_csv(V3 / "daytrade" / fn)
            out |= set(df.iloc[:, 0].astype(str).str.upper().str.strip())
        except Exception:
            continue
    return sorted(out)


def _load(asof: date) -> pd.DataFrame:
    """All Form-4 purchases filed on/before asof and at most ~40 days before it (enough for a 5-day
    window plus dedupe lookback). Empty frame if the archive is unavailable or lagging."""
    lo = asof - timedelta(days=40)
    frames = []
    for p in sorted(INSIDER_DIR.glob("*.parquet")):
        try:
            if int(p.stem[:4]) < lo.year:
                continue
            frames.append(pd.read_parquet(p))
        except Exception:
            continue
    if not frames:
        return pd.DataFrame()
    df = pd.concat(frames, ignore_index=True)
    df = df[df["DOCUMENT_TYPE"].isin(["4", "4/A"])].copy()
    df = df[df["TRANS_CODE"] == "P"]
    if "TRANS_ACQUIRED_DISP_CD" in df.columns:
        df = df[df["TRANS_ACQUIRED_DISP_CD"].astype(str).str.upper().str.startswith("A")]
    df["fdate"] = pd.to_datetime(df["FILING_DATE"], format="%d-%b-%Y", errors="coerce")
    df["val"] = (pd.to_numeric(df["TRANS_SHARES"], errors="coerce")
                 * pd.to_numeric(df["TRANS_PRICEPERSHARE"], errors="coerce"))
    df = df.dropna(subset=["fdate", "val", "RPTOWNERCIK"])
    asof_ts, lo_ts = pd.Timestamp(asof), pd.Timestamp(lo)
    df = df[(df["fdate"] <= asof_ts) & (df["fdate"] >= lo_ts)]   # no look-ahead
    df = df[df["val"] > 0]
    return df.drop_duplicates(["ACCESSION_NUMBER", "TRANS_DATE", "TRANS_SHARES", "TRANS_CODE"])


def signals(asof: date, bars: dict) -> list[dict]:
    df = _load(asof)
    if df.empty:
        return []
    df["sym"] = df["ISSUERTRADINGSYMBOL"].astype(str).str.upper().str.strip()
    uni = set(universe())
    df = df[df["sym"].isin(uni)]
    per = df.groupby(["sym", "RPTOWNERCIK", "fdate"], as_index=False)["val"].sum()
    win = pd.Timedelta(days=WINDOW_DAYS)
    asof_ts = pd.Timestamp(asof)
    out = []
    for sym, s in per.groupby("sym", sort=False):
        arr = s[["fdate", "RPTOWNERCIK", "val"]].to_numpy(object)
        last_fire = None
        fired_today = False
        for fd in sorted(set(s["fdate"])):
            tot: dict[object, float] = {}
            for f, owner, v in arr:
                if fd - win < f <= fd:
                    tot[owner] = tot.get(owner, 0.0) + float(v)
            qual = {o: t for o, t in tot.items() if t >= MIN_PER_INSIDER}
            if len(qual) < N_INS or sum(qual.values()) < MIN_TOTAL:
                continue
            if last_fire is not None and fd - last_fire < win:
                continue
            last_fire = fd
            fired_today = (fd == asof_ts)
        if fired_today:
            out.append({"ticker": sym, "side": "long"})
    return out
