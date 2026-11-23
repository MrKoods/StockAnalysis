"""Writes state/data_catalog.md - the one page the Scout/Researcher/Skeptic/Director read to know what data
exists, how far back it goes, and which periods each family has already used (plain Python, zero tokens).

    python tools/catalog.py
"""
from __future__ import annotations

import csv
import re
from collections import defaultdict

import pandas as pd

import research_data as rd
from common import STATE, TEAM, load_json, now_pt

OUT = STATE / "data_catalog.md"
TRIALS = TEAM / "registry" / "trials.csv"
NOT_AVAILABLE = [
    "options prices / implied volatility history", "short interest", "analyst consensus-estimate history "
    "(only EPS estimate vs actual per report)", "index add/remove ANNOUNCEMENT dates (S&P announces them; only "
    "companies that also filed an 8-K are visible)", "intraday bars before 2023-11", "companies no longer listed "
    "(the universe is today's S&P 1500 - every backtest has survivorship bias; say so)"]
# Can a paper test get this data on the day it trades? A "no" source can give a research verdict, never a paper
# test, until someone builds a live feed for it (the user decides). Keep in step with what actually refreshes.
LIVE = {
    "daily(tickers)": "yes - the paper runner downloads each day's bars",
    "cboe(symbols)": "yes - refreshed every dispatch (after 16:15 ET closes)",
    "hourly(tickers)": "yes - V3 fetch task, daily ~14:00 PT",
    "five_min / one_min": "yes - V3 fetch task, daily ~14:00 PT",
    "earnings(tickers)": "dates yes via Yahoo's calendar (as V4 EPRE does); this file is a 2026-10-23 copy",
    "insider(start)": "NO - 2026-10-23 copy, no Form 4 feed",
    "ratings(tickers)": "NO - 2026-10-23 copy, no ratings feed",
    "filings(forms, items, tickers)": "yes - SEC daily index each dispatch (a filing reaches it the next weekday)",
    "splits(tickers)": "weekly - refreshed Saturdays",
}


def _range(path, col=None) -> str:
    try:
        df = pd.read_parquet(path)
        s = pd.to_datetime(df[col] if col else df.index, utc=col is not None, errors="coerce")
        return f"{s.min():%Y-%m-%d} .. {s.max():%Y-%m-%d}"
    except Exception:
        return "?"


def sources() -> list[str]:
    n = lambda d: len(list(d.glob("*.parquet")))   # noqa: E731
    yrs = sorted(int(p.stem[:4]) for p in (rd.EVENTS / "insider").glob("*.parquet"))
    rows = [
        ("daily(tickers)", f"{n(rd.DAILY)} tickers", _range(rd.DAILY / "SPY.parquet"),
         "OHLCV, S&P 1500"),
        ("hourly(tickers)", f"{n(rd.INTRA / '1h')} tickers", _range(rd.INTRA / "1h" / "AAPL.parquet"), "regular session"),
        ("five_min / one_min", f"{n(rd.INTRA / '5m')} / {n(rd.INTRA / '1m')} tickers",
         _range(rd.INTRA / "5m" / "AAPL.parquet"), "S&P 500, recent months only"),
        ("earnings(tickers)", f"{n(rd.EVENTS / 'earnings')} tickers",
         _range(rd.EVENTS / "earnings" / "AAPL.parquet", "Earnings Date"), "dates + EPS estimate/actual/surprise"),
        ("insider(start)", "all filers", f"{yrs[0]} .. {yrs[-1]}" if yrs else "?", "Form 3/4/5 transactions"),
        ("ratings(tickers)", f"{n(rd.EVENTS / 'ratings')} tickers", _range(rd.EVENTS / "ratings" / "AAPL.parquet", "GradeDate"),
         "analyst rating changes"),
    ]
    lines = ["| loader | coverage | dates | what | live for paper? |", "|---|---|---|---|---|"]
    lines += [f"| `{a}` | {b} | {c} | {d} | {LIVE.get(a, '?')} |" for a, b, c, d in rows]
    f = rd.EDGAR / "filings.parquet"
    if f.exists():
        df = pd.read_parquet(f, columns=["ticker", "form", "accepted", "items"])
        st = load_json(rd.EDGAR / "state.json", {})
        lines.append(f"| `filings(forms, items, tickers)` | {df['ticker'].nunique()} tickers, {len(df):,} filings | "
                     f"{df['accepted'].min():%Y-%m-%d} .. {st.get('updated_through', '?')} | SEC filings + exact "
                     f"acceptance time; 8-K item codes from 2004-08 | {LIVE['filings(forms, items, tickers)']} |")
        k8 = df[df["form"].str.startswith("8-K") & (df["accepted"] >= "2004-08-23")]
        counts = k8["items"].fillna("").str.split(",").explode().str.strip().value_counts()
        item_lines = [f"- `{c}` {rd.EIGHT_K_ITEMS.get(c, '')}: {counts[c]:,} filings"
                      for c in sorted(counts.index) if c in rd.EIGHT_K_ITEMS]
        forms = df["form"].value_counts().head(12)
        form_line = ", ".join(f"{k} {v:,}" for k, v in forms.items())
    else:
        item_lines, form_line = ["- (EDGAR archive not built yet)"], ""
    s = rd.EDGAR / "splits.parquet"
    if s.exists():
        sp = pd.read_parquet(s)
        ann = int(sp["announced"].notna().sum()) if "announced" in sp else 0
        lines.append(f"| `splits(tickers)` | {len(sp)} splits ({int((sp['ratio'] > 1).sum())} forward, "
                     f"{int((sp['ratio'] < 1).sum())} reverse); announcement found for {ann} | "
                     f"{sp['ex_date'].min():%Y-%m-%d} .. {sp['ex_date'].max():%Y-%m-%d} | ex-date, ratio, first "
                     f"'stock split' filing (2001+) | {LIVE['splits(tickers)']} |")
    parts = sorted((rd.EDGAR / "text").glob("part-*.parquet"))
    if parts:
        t = pd.concat(pd.read_parquet(p, columns=["group", "status"]) for p in parts)
        by = t[t["status"] == "ok"].groupby("group").size()
        lines.append(f"| `filing_text(df)` | {len(t):,} 8-Ks with text (" + ", ".join(f"{g} {by[g]:,}" for g in by.index)
                     + ") | all years in filings() | 8-K body + attached press release (8.01) - split events by WHAT "
                     "they say | yes - edgar_text update each dispatch (newest first) |")
    if rd.FOMC.exists():
        fo = pd.read_csv(rd.FOMC)
        lines.append(f"| `fomc()` | {int((fo['kind'] == 'meeting').sum())} scheduled meetings, "
                     f"{int((fo['kind'] == 'call').sum())} calls | {fo['date'].min()} .. {fo['date'].max()} | "
                     "statement days (14:00 ET); scheduled dates known ~1 year ahead | yes - fixed calendar |")
    if (rd.CBOE / "VIX.csv").exists():
        files = sorted(rd.CBOE.glob("*.csv"))
        spans = []
        for p in files:
            d = pd.read_csv(p, usecols=["date"])["date"]
            spans.append(f"{p.stem} {d.iloc[0][:10]}+")
        lines.append(f"| `cboe(symbols)` | {', '.join(spans)} | .. {pd.read_csv(rd.CBOE / 'VIX.csv')['date'].iloc[-1]} | "
                     "VIX family + CBOE option-strategy indexes (mid-price, pre-cost; ETF daily bars for SPY/QQQ/IWM/"
                     f"IJR/IJH/MDY/DIA/TLT/GLD are in daily()) | {LIVE['cboe(symbols)']} |")
    lab_lines = []
    for p in sorted((TEAM / "tools" / "lab").glob("*.py")):
        doc = p.read_text(encoding="utf-8", errors="replace").split('"""')
        if p.stem != "__init__" and len(doc) >= 3:
            lab_lines.append(f"- `from lab import {p.stem}` - {(doc[1].strip().splitlines() or ['?'])[0]}")
    lines += ["", "### Research tools (tools/lab/, built by the Engineer on Director build requests)", ""] + (
        lab_lines or ["- none yet - the Director asks for one under '## Build requests' in its report"])
    return lines + ["", "### 8-K event types available (2004-08+, our universe) - each is a possible family", ""] + \
        item_lines + ([f"", f"Most common forms: {form_line}"] if form_line else [])


def families() -> list[str]:
    used = defaultdict(list)
    if TRIALS.exists():
        with open(TRIALS, newline="", encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                yrs = re.findall(r"(?:19|20)\d\d", r.get("data", ""))
                span = f"{yrs[0]}-{yrs[-1]}" if yrs else "?"
                used[r["family"]].append(f"{r['stage']} {span} ({r.get('verdict') or r.get('note', '')[:30]})")
    lines = ["| family | periods already used (search = train, holdout = the one clean look) |", "|---|---|"]
    lines += [f"| {f} | {'; '.join(v)} |" for f, v in sorted(used.items())]
    return lines


def write() -> str:
    text = "\n".join([
        f"# Data catalog - generated {now_pt():%Y-%m-%d %H:%M} by tools/catalog.py (do not edit)", "",
        "Everything research can use. Only these loaders exist (tools/research_data.py); an idea whose inputs",
        "are not here needs new data - list it under 'Needs data' in your notes, don't register it.",
        "`live for paper?` = can a paper test get the input on the day it trades. An idea resting on a NO source",
        "can only ever give a research verdict - not a paper test - so the Director does not queue it by default.", "",
        "## Sources", ""] + sources() + [
        "", "## Not available (needs new data - the user decides)", ""] + [f"- {x}" for x in NOT_AVAILABLE] + [
        "", "## Periods each family has used", "",
        "A family's holdout must be a period it has NOT used. A family not listed has its whole history clean.", ""]
        + families())
    OUT.write_text(text + "\n", encoding="utf-8")
    return f"catalog: {OUT.name} written"


if __name__ == "__main__":
    print(write())
