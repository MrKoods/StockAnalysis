"""Build team/ref/fomc_dates.csv - every FOMC meeting and conference call since 2000 (added 2026-11-14).

    python tools/fomc_dates.py          # re-download from federalreserve.gov and rewrite the file (yearly is enough)

Source: federalreserve.gov - fomccalendars.htm (the last ~5 years + next year) and fomchistorical<YYYY>.htm
(older years). Public facts; the file is committed so every research run sees the same list.

Columns: start, date (the LAST day = the statement day), kind ('meeting' = on the published schedule,
'call' = conference call / unscheduled meeting - known only on the day), sep (Summary of Economic Projections with
it, marked * on the Fed's calendar, 2021+ only). Scheduled dates are published about a year ahead, so a strategy
may use them before they happen; a 'call' it may not. Read via research_data.fomc().
"""
from __future__ import annotations

import re
from datetime import date

import pandas as pd
import requests

from common import TEAM

OUT = TEAM / "team" / "ref" / "fomc_dates.csv"
BASE = "https://www.federalreserve.gov/monetarypolicy/"
FIRST_YEAR = 2000
MONTHS = {m: i for i, m in enumerate(["january", "february", "march", "april", "may", "june", "july", "august",
                                      "september", "october", "november", "december"], 1)}
MON3 = {k[:3]: v for k, v in MONTHS.items()}


def _page(name: str) -> str:
    r = requests.get(BASE + name, headers={"User-Agent": "StockAnalysis-Team research (FOMC calendar)"}, timeout=30)
    r.raise_for_status()
    return r.text


def _mon(s: str) -> int:
    return MON3[s.strip().lower()[:3]]


def _span(year: int, months: str, days: str) -> tuple[date, date]:
    """'April/May' + '30-1' -> (Apr 30, May 1); 'March' + '18-19' -> (Mar 18, Mar 19); 'March' + '15' -> same day."""
    ms = [_mon(m) for m in re.split(r"[/-]", months) if m.strip()]
    ds = [int(d) for d in re.findall(r"\d+", days)]
    start = date(year, ms[0], ds[0])
    end = date(year, ms[-1], ds[-1]) if len(ds) > 1 else start
    return start, end


TITLE_RX = re.compile(r"\s*([A-Za-z]+)(?:/([A-Za-z]+))?\s+(\d+)(?:\s*-\s*(?:([A-Za-z]+)\s+)?(\d+))?\s+"
                      r"(?:\((unscheduled|cancelled)\)\s+|(Unscheduled)\s+)?(Meeting|Conference Call)\s*-\s*(\d{4})",
                      re.I)
UNMATCHED: list[str] = []


def historical(year: int) -> list[dict]:
    """Title forms seen on the Fed's pages: 'January 29-30 Meeting - 2008', 'July 31-August 1 Meeting - 2012',
    'April/May 30-1 Meeting - 2013', 'March 15 (unscheduled) Meeting - 2020', 'March 17-18 (cancelled) Meeting -
    2020' (skipped), 'January 9 Conference Call - 2008'. A title that doesn't parse goes to UNMATCHED (reported)."""
    rows = []
    for title in re.findall(r"<h5[^>]*>([^<]+)</h5>", _page(f"fomchistorical{year}.htm")):
        m = TITLE_RX.match(title)
        if not m:
            if re.search(r"Meeting|Conference Call", title):
                UNMATCHED.append(title.strip())
            continue
        m1, slash, d1, m2, d2, paren, unsched, kind, yr = m.groups()
        if int(yr) != year or (paren or "").lower() == "cancelled":
            continue
        s = date(year, _mon(m1), int(d1))
        e = date(year, _mon(m2 or slash or m1), int(d2 or d1))
        unscheduled = bool(unsched) or (paren or "").lower() == "unscheduled"
        rows.append({"start": s, "date": e, "kind": "meeting" if kind.lower() == "meeting" and not unscheduled
                     else "call", "sep": ""})
    return rows


def current() -> list[dict]:
    """fomccalendars.htm: year sections '<YYYY> FOMC Meetings', each meeting = month div + date div."""
    s = _page("fomccalendars.htm")
    heads = [(m.start(), int(m.group(1))) for m in re.finditer(r"(\d{4}) FOMC Meetings", s)]
    rows = []
    for i, (pos, year) in enumerate(heads):
        seg = s[pos: heads[i + 1][0] if i + 1 < len(heads) else len(s)]
        months = re.findall(r"fomc-meeting__month[^>]*>\s*<strong>([^<]+)</strong>", seg)
        dates = re.findall(r"fomc-meeting__date[^>]*>([^<]+)<", seg)
        for mo, d in zip(months, dates):
            if not re.search(r"\d", d):
                continue
            st, en = _span(year, mo, d)
            unsched = bool(re.search(r"(?i)unscheduled|notation", d))
            rows.append({"start": st, "date": en, "kind": "call" if unsched else "meeting",
                         "sep": "yes" if "*" in d else "no"})
    return rows


def build() -> pd.DataFrame:
    cur = current()
    first_cur = min(r["date"].year for r in cur)
    rows = cur + [r for y in range(FIRST_YEAR, first_cur) for r in historical(y)]
    df = pd.DataFrame(rows).drop_duplicates(["date", "kind"]).sort_values("date").reset_index(drop=True)
    return df


def write() -> str:
    df = build()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT, index=False)
    per = df[df.kind == "meeting"].groupby(pd.to_datetime(df["date"]).dt.year).size()
    bad = f"; UNPARSED titles: {UNMATCHED}" if UNMATCHED else ""
    return (f"{OUT}: {len(df)} rows ({(df.kind == 'meeting').sum()} scheduled meetings, {(df.kind == 'call').sum()} "
            f"calls), {df['date'].min()} .. {df['date'].max()}; scheduled per year min {per.min()} max {per.max()}{bad}")


if __name__ == "__main__":
    print(write())
