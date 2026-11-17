"""special-dividend-drift-long -- paper rule for the pre-registered research `chosen` (all_sp1500_h20).

LONG an S&P 1500 filer at the DAY-0 close when an 8-K item 8.01 whose text matches the frozen
special-dividend regex is accepted for it before 15:30 ET (entry_session is today), held 20 sessions,
exited at the close, judged real_hedged_bps (real Webull bid/ask, SPY-hedged by the runner).

Day-0 entry is reachable (built 2026-11-14): tools/edgar_live.py captures today's SEC filings + in-scope
8-K text ~12:40 PT and paper_runner.run_day0 calls signals() BEFORE the close with bars up to YESTERDAY,
logging a 'pending' signal so the 12:56 Quote Clerk prices it and the after-close run fills it at today's
close (spec entry_at "same_close"). edgar_live.filings_asof(asof) returns the archive + today's
pre-15:30-ET filings (so a filing accepted after the cutoff is dropped -- no look-ahead);
edgar_live.text_asof(asof) has today's live 8-K text. For an 8-K accepted after 15:30 ET on the PRIOR
session whose entry_session is today, text is read from the archive text parts for just those few
accessions.

Signal, mirroring research_data/_entry_session + the frozen regex in research/test.py:
  - 8-K with item 8.01, filer in S&P 1500;
  - entry_session == today (accepted today before 15:30 ET, OR accepted after the cutoff on the prior
    session / a non-trading day / with no time stamp -> today's close);
  - its text (body + attached press release) matches SPECIAL_RE.
No cross-filing dedup (only one signal per ticker per day), to match research exactly.
"""
from __future__ import annotations

import re
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

import edgar_live

V3 = Path(r"C:\Users\user\Documents\Git\StockAnalysis-V3") / "daytrade"
TEXT = Path(__file__).resolve().parents[2] / "data" / "edgar" / "text"
ENTRY_CUTOFF_SECS = 15.5 * 3600            # 15:30 ET -- same cutoff as research_data._entry_session
SPECIAL_RE = re.compile(r"special\s+(?:cash\s+|one[-\s]?time\s+|year[-\s]?end\s+)?dividend", re.I)


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


def _has_801(items) -> bool:
    return "8.01" in [x.strip() for x in str(items or "").split(",")]


def _entry_session(accepted: pd.Timestamp, sessions: pd.DatetimeIndex):
    """First session whose close can still be bought after `accepted` (ET): the acceptance day when SEC
    accepted before 15:30 ET on a session day, else the next session. No time (00:00) = after the close.
    Mirrors research_data._entry_session."""
    day = accepted.normalize()
    secs = (accepted - day).total_seconds()
    before = 0 < secs < ENTRY_CUTOFF_SECS
    cand = day if before else day + timedelta(days=1)
    i = int(sessions.searchsorted(cand, side="left"))
    return sessions[i] if i < len(sessions) else None


def _text_for(accessions: set, asof: date) -> dict:
    """accession -> 'body + exhibit' text. Today's live 8-K text first (edgar_live), then the archive
    text parts for any still missing (rare: an 8-K accepted after 15:30 ET on the prior session)."""
    found: dict = {}
    try:
        live = edgar_live.text_asof(asof)
    except Exception:
        live = pd.DataFrame(columns=["accession", "text", "exhibit"])
    for a, t, x in zip(live.get("accession", []), live.get("text", []), live.get("exhibit", [])):
        if a in accessions:
            found[a] = f"{t or ''} {x or ''}"
    missing = accessions - set(found)
    if missing and TEXT.exists():
        for p in sorted(TEXT.glob("part-*.parquet")):
            try:
                df = pd.read_parquet(p, columns=["accession", "text", "exhibit"])
            except Exception:
                continue
            hit = df[df["accession"].isin(missing)]
            for a, t, x in zip(hit["accession"], hit["text"], hit["exhibit"]):
                found[a] = f"{t or ''} {x or ''}"
            missing -= set(hit["accession"])
            if not missing:
                break
    return found


def signals(asof: date, bars: dict) -> list[dict]:
    members = _members()
    spy = bars.get("SPY")
    if spy is None or not members:
        return []
    # bars run only to YESTERDAY in run_day0; asof is itself a trading session (the runner fires on them).
    hist = [pd.Timestamp(d) for d in spy.index if d < asof]
    sessions = pd.DatetimeIndex(sorted(set(hist) | {pd.Timestamp(asof)}))
    try:
        df = edgar_live.filings_asof(asof)                          # archive + today's pre-15:30-ET filings
    except Exception:
        return []
    if df.empty or "form" not in df.columns or "accepted" not in df.columns or "items" not in df.columns:
        return []
    form = df["form"].astype(str).str.replace("/A", "", regex=False).str.strip()
    tkr = df["ticker"].astype(str).str.upper().str.strip()
    keep = (form == "8-K") & df["items"].map(_has_801) & tkr.isin(members)
    df = df[keep].copy()
    if df.empty:
        return []
    df["tkr"] = tkr[keep]
    df["accepted"] = pd.to_datetime(df["accepted"], errors="coerce")
    df = df[df["accepted"].notna()]
    today = pd.Timestamp(asof)
    df = df[[_entry_session(a, sessions) == today for a in df["accepted"]]]   # entry_session is today
    if df.empty:
        return []
    text = _text_for(set(df["accession"].astype(str)), asof)
    out, seen = [], set()
    for t, acc in zip(df["tkr"], df["accession"].astype(str)):
        if t in seen:
            continue
        if SPECIAL_RE.search(text.get(acc, "")):
            seen.add(t)
            out.append({"ticker": t, "side": "long"})
    return out
