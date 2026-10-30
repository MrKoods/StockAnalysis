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
        ("daily(tickers)", f"{n(rd.INTRA / 'daily_max')} tickers", _range(rd.INTRA / "daily_max" / "SPY.parquet"),
         "OHLCV, S&P 1500"),
        ("hourly(tickers)", f"{n(rd.INTRA / '1h')} tickers", _range(rd.INTRA / "1h" / "AAPL.parquet"), "regular session"),
        ("five_min / one_min", f"{n(rd.INTRA / '5m')} / {n(rd.INTRA / '1m')} tickers",
         _range(rd.INTRA / "5m" / "AAPL.parquet"), "S&P 500, recent months only"),
        ("earnings(tickers)", f"{n(rd.EVENTS / 'earnings')} tickers",
         _range(rd.EVENTS / "earnings" / "AAPL.parquet", "Earnings Date"), "dates + EPS estimate/actual/surprise"),
        ("insider(start)", "all filers", f"{yrs[0]} .. {yrs[-1]}" if yrs else "?", "Form 3/4/5 transactions"),
        ("ratings(tickers)", f"{n(rd.EVENTS / 'ratings')} tickers", _range(rd.EVENTS / "ratings" / "AAPL.parquet"),
         "analyst rating changes"),
    ]
    lines = ["| loader | coverage | dates | what |", "|---|---|---|---|"]
    lines += [f"| `{a}` | {b} | {c} | {d} |" for a, b, c, d in rows]
    f = rd.EDGAR / "filings.parquet"
    if f.exists():
        df = pd.read_parquet(f, columns=["ticker", "form", "accepted", "items"])
        st = load_json(rd.EDGAR / "state.json", {})
        lines.append(f"| `filings(forms, items, tickers)` | {df['ticker'].nunique()} tickers, {len(df):,} filings | "
                     f"{df['accepted'].min():%Y-%m-%d} .. {st.get('updated_through', '?')} | SEC filings + exact "
                     f"acceptance time; 8-K item codes from 2004-08 |")
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
                     f"'stock split' filing (2001+) |")
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
        "are not here needs new data - list it under 'Needs data' in your notes, don't register it.", "",
        "## Sources", ""] + sources() + [
        "", "## Not available (needs new data - the user decides)", ""] + [f"- {x}" for x in NOT_AVAILABLE] + [
        "", "## Periods each family has used", "",
        "A family's holdout must be a period it has NOT used. A family not listed has its whole history clean.", ""]
        + families())
    OUT.write_text(text + "\n", encoding="utf-8")
    return f"catalog: {OUT.name} written"


if __name__ == "__main__":
    print(write())
