"""activist-13d-long-day0 -- paper rule for the pre-registered research `chosen` (e0_sp1500_h3).

LONG an S&P 1500 target at the DAY-0 close when an INITIAL Schedule 13D is accepted for it before 15:30 ET, held
3 sessions, exited at the close, judged real_hedged_bps (real Webull bid/ask, SPY-hedged by the runner).

Day-0 entry is reachable (built 2026-11-14): tools/edgar_live.py captures today's SEC filings ~12:40 PT and
paper_runner.run_day0 calls signals() BEFORE the close with bars up to YESTERDAY, logging a 'pending' signal for
TODAY so the 12:56 Quote Clerk prices it and the after-close run fills it at today's close (spec entry_at
"same_close"). edgar_live.filings_asof(asof) returns the archive + today's pre-15:30-ET filings in the archive's
own columns, so a filing accepted after the cutoff is dropped (no look-ahead).

A signal fires when an initial 13D's ENTRY_SESSION is today: accepted today before 15:30 ET, or accepted after
the cutoff on the prior session / a non-trading day / with no time stamp (-> the next session's close = today).
This mirrors research_data._entry_session exactly. Initial filings only (form_std == "SC 13D"): keeps both the
old 'SC 13D' and the post-2024 'SCHEDULE 13D' and drops /A amendments.
"""
from __future__ import annotations

import re
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

import edgar_live

V3 = Path(r"C:\Users\user\Documents\Git\StockAnalysis-V3") / "daytrade"
ENTRY_CUTOFF_SECS = 15.5 * 3600            # 15:30 ET -- same cutoff as research_data._entry_session


def _members() -> set:
    out: set = set()
    for name in ("sp500_new.csv", "sp400.csv", "sp600.csv"):
        try:
            df = pd.read_csv(V3 / name)
        except Exception:
            continue
        out |= set(df.iloc[:, 0].astype(str).str.upper().str.strip())
    return out


def universe() -> list[str]:
    return sorted(_members())


def _is_initial_13d(form) -> bool:
    f = re.sub(r"^SCHEDULE (13[DG])", r"SC \1", str(form).strip())   # post-2024 rename -> old name
    return f == "SC 13D"                                             # drops /A amendments


def _entry_session(accepted: pd.Timestamp, sessions: pd.DatetimeIndex):
    """First session whose close can still be bought after `accepted` (ET): the acceptance day when SEC accepted
    before 15:30 ET on a session day, else the next session. No time (00:00) = after the close. Mirrors
    research_data._entry_session."""
    day = accepted.normalize()
    secs = (accepted - day).total_seconds()
    before = 0 < secs < ENTRY_CUTOFF_SECS
    cand = day if before else day + timedelta(days=1)
    i = int(sessions.searchsorted(cand, side="left"))
    return sessions[i] if i < len(sessions) else None


def signals(asof: date, bars: dict) -> list[dict]:
    members = _members()
    spy = bars.get("SPY")
    if spy is None or not members:
        return []
    # bars run only to YESTERDAY in run_day0; asof is itself a trading session (the runner fires on trading days)
    hist = [pd.Timestamp(d) for d in spy.index if d < asof]
    sessions = pd.DatetimeIndex(sorted(set(hist) | {pd.Timestamp(asof)}))
    try:
        df = edgar_live.filings_asof(asof)                          # archive + today's pre-15:30-ET filings
    except Exception:
        return []
    if df.empty or "form" not in df.columns or "accepted" not in df.columns:
        return []
    tkr = df["ticker"].astype(str).str.upper().str.strip()
    keep = df["form"].map(_is_initial_13d) & tkr.isin(members)
    df = df[keep].copy()
    if df.empty:
        return []
    df["tkr"] = tkr[keep]
    df["accepted"] = pd.to_datetime(df["accepted"], errors="coerce")
    df = df[df["accepted"].notna()]
    today = pd.Timestamp(asof)
    out, seen = [], set()
    for t, a in zip(df["tkr"], df["accepted"]):
        if t in seen:
            continue
        if _entry_session(a, sessions) == today:                   # ENTRY_SESSION is today -> buy today's close
            seen.add(t)
            out.append({"ticker": t, "side": "long"})
    return out
