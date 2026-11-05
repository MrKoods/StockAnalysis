"""early-10q-drift -- FROZEN paper rule = pre-registered `chosen` = sp1500_t7_long:
LONG an S&P 1500 stock the session its 10-Q first becomes tradable, WHEN that 10-Q was accepted by SEC at
least 7 calendar days earlier (~5 trading days) than the SAME fiscal quarter's 10-Q one year prior. Enter
at that first tradable session's OPEN (the runner enters at the session after the signal), exit at the OPEN
3 sessions later (spec hold_sessions=3, exit_at=open). SPY-hedged, judged at real Webull quotes
(real_hedged_bps).

"Days early": among this ticker's prior 10-Qs find the one accepted 300-430 calendar days earlier (closest
to 365 = the same fiscal quarter a year ago), then days_early = (that acceptance date + 1 year) - this
acceptance date. Only the original 10-Q counts (form exactly "10-Q"; "10-Q/A" amendments ignored).

Promotability: 10-Qs are public the same day and data/edgar/filings.parquet (rebuilt by tools/edgar.py each
dispatcher run) carries SEC's exact acceptance time + the full 10-Q history needed for the prior-year match
-- so this CAN be traded live. NOTE: the SEC daily index reaches the parquet the next weekday, so a 10-Q
accepted the same session can slip one day in live paper (research uses the clean first_session); see
PLAN.md. Universe is CURRENT S&P 1500 membership (survivorship caveat in PLAN.md).

Signal timing (matches the research entry = first_session open): on `asof` we emit when the first tradable
session after SEC acceptance is the NEXT session (so the runner, which enters at the session after the
signal, enters exactly at first_session's open). A 10-Q accepted premarket (before 09:30, tradable at that
same day's open) is skipped -- the once-daily after-close runner would enter a day late.
"""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pandas as pd

FILINGS = Path(__file__).resolve().parents[2] / "data" / "edgar" / "filings.parquet"
V3 = Path(r"C:\Users\user\Documents\Git\StockAnalysis-V3") / "daytrade"
UNIV_CSVS = ("sp500_new.csv", "sp400.csv", "sp600.csv")
THRESHOLD_DAYS = 7
GAP_LO, GAP_HI = 300, 430


def _members() -> set:
    out = set()
    for name in UNIV_CSVS:
        try:
            df = pd.read_csv(V3 / name)
        except Exception:
            continue
        out |= set(df.iloc[:, 0].astype(str).str.upper().str.strip())
    return out


def _load() -> pd.DataFrame:
    try:
        return pd.read_parquet(FILINGS)
    except Exception:
        return pd.DataFrame()


def universe() -> list[str]:
    return sorted(_members())


def _days_early(acc_days: list, i: int) -> float | None:
    """days_early for the i-th (ascending) 10-Q acceptance day, or None if no prior-year match."""
    di = acc_days[i]
    best_j, best_err = None, None
    for j in range(i - 1, -1, -1):
        gap = (di - acc_days[j]).days
        if gap > GAP_HI:
            break
        if gap < GAP_LO:
            continue
        err = abs(gap - 365)
        if best_err is None or err < best_err:
            best_err, best_j = err, j
    if best_j is None:
        return None
    return ((acc_days[best_j] + pd.DateOffset(years=1)) - di).days


def signals(asof: date, bars: dict) -> list[dict]:
    members = _members()
    df = _load()
    if df.empty or not members or "accepted" not in df.columns or "form" not in df.columns:
        return []
    df = df[df["form"].astype(str) == "10-Q"].copy()
    df["tkr"] = df["ticker"].astype(str).str.upper().str.strip()
    df = df[df["tkr"].isin(members)]
    if df.empty:
        return []
    df["acc"] = pd.to_datetime(df["accepted"], errors="coerce")
    df = df[df["acc"].notna()].copy()
    df["acc_day"] = df["acc"].dt.normalize()
    df = df.drop_duplicates(["tkr", "acc_day"]).sort_values(["tkr", "acc_day"])

    spy = bars.get("SPY")
    if spy is None:
        return []
    sessions = sorted(d for d in spy.index if d <= asof)          # bars are indexed by date
    if not sessions:
        return []
    last = sessions[-1]
    recent_cut = pd.Timestamp(asof) - pd.Timedelta(days=10)

    out, seen = [], set()
    for t, g in df.groupby("tkr"):
        acc_days = list(g["acc_day"])
        accs = list(g["acc"])
        i = len(acc_days) - 1                                     # only the most recent 10-Q is a fresh signal
        if accs[i] < recent_cut:
            continue
        de = _days_early(acc_days, i)
        if de is None or de < THRESHOLD_DAYS:
            continue
        a = accs[i]
        day = a.normalize()
        secs = (a - day).total_seconds()
        same_day = 0 < secs < 9.5 * 3600                          # accepted premarket -> that day's open
        target = day.date() if same_day else day.date() + timedelta(days=1)
        if target > last and t not in seen:                       # first tradable session is the NEXT one
            seen.add(t)
            out.append({"ticker": t, "side": "long"})
    return out
