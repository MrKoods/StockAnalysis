"""Today's SEC filings, captured BEFORE the close - what a day-0 strategy needs (plain Python, zero tokens; 2026-11-14).

    python tools/edgar_live.py capture [--date YYYY-MM-DD]   # normally run by the Scan Operator tick at ~12:40 PT
    python tools/edgar_live.py status

Why: data/edgar/filings.parquet comes from SEC's DAILY index, so a filing reaches it the next weekday. A day-0
strategy (buy at the close of the day the news came out - research_data's entry_session) has to know about the
filing before 16:00 ET. This reads SEC's real-time "current filings" feed at ~15:40 ET and saves our universe's
filings in the archive's own columns, so strategies treat both the same way (edgar_live.filings_asof()).

Look-ahead guard: a day-0 strategy may only use filings ACCEPTED before 15:30 ET (DAY0_CUTOFF - the same cutoff as
research_data.entry_session). The capture time is saved with every row (captured_at) as the proof the signal was
knowable before the close. In-scope 8-Ks also get their text (edgar_text.fetch), saved alongside.

Output: data/edgar/live/<date>.parquet (+ <date>-text.parquet). Git-ignored like the archive.
"""
from __future__ import annotations

import html
import re
import sys
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

import pandas as pd

import edgar
import edgar_text
from common import TEAM, load_json, log, now_pt, save_json

LIVE = TEAM / "data" / "edgar" / "live"
CIKS = LIVE / "cik_map.json"
ET = ZoneInfo("America/New_York")
DAY0_CUTOFF = time(15, 30)            # ET: a filing accepted later can't be traded at today's close
# SEC renamed SC 13D/13G to "SCHEDULE 13D/13G" in late 2024 - ask for both spellings.
FORMS = ["8-K", "SCHEDULE 13D", "SCHEDULE 13D/A", "SC 13D", "SC 13D/A", "SCHEDULE 13G", "SC TO-I", "SC TO-C",
         "SC TO-T", "10-Q", "10-K", "NT 10-Q", "NT 10-K", "S-3", "424B5", "DEF 14A", "DEFA14A", "25-NSE", "S-4"]
MAX_PAGES = 15                        # 1,500 filings of one form in a day is far above any real day
FEED = ("https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type={form}&company=&dateb=&owner=include"
        "&start={start}&count=100&output=atom")
CAPTURE_FROM = time(12, 40)           # PT: the Scan Operator tick that runs it (15:40 ET)
CAPTURE_UNTIL = time(12, 54)          # PT: later than this the 12:56 quote capture would miss the signals


def _cik_tickers() -> dict[int, str]:
    """CIK -> our ticker, refreshed weekly (SEC's ticker file)."""
    st = load_json(CIKS, {})
    if not st.get("map") or (date.today() - date.fromisoformat(st.get("date", "2000-01-01"))).days > 7:
        st = {"date": str(date.today()), "map": {str(c): t for t, c in edgar.cik_map().items()}}
        save_json(CIKS, st)
    return {int(c): t for c, t in st["map"].items()}


def parse(feed: str) -> list[dict]:
    rows = []
    for e in re.findall(r"<entry>(.*?)</entry>", feed, re.S):
        title = re.search(r"<title>([^<]*)</title>", e)
        summ = html.unescape(re.search(r"<summary[^>]*>(.*?)</summary>", e, re.S).group(1)) if "<summary" in e else ""
        acc = re.search(r"AccNo:</b>\s*([\d-]+)", summ)
        upd = re.search(r"<updated>([^<]+)</updated>", e)
        form = re.search(r'term="([^"]+)"', e)
        cik = re.search(r"\((\d{10})\)", title.group(1) if title else "")
        if not (acc and upd and form and cik):
            continue
        items = ",".join(re.findall(r"Item (\d\.\d\d)", summ))
        rows.append({"cik": int(cik.group(1)), "form": html.unescape(form.group(1)), "accession": acc.group(1),
                     "accepted": pd.Timestamp(upd.group(1)).tz_convert(ET).tz_localize(None), "items": items or None,
                     "filing_date": pd.Timestamp(re.search(r"Filed:</b>\s*([\d-]+)", summ).group(1))})
    return rows


def fetch_form(form: str, day: date) -> list[dict]:
    out = []
    for page in range(MAX_PAGES):
        r = edgar_text._get(FEED.format(form=form.replace(" ", "+"), start=page * 100))
        rows = parse(r.text) if r is not None else []
        out += [x for x in rows if x["accepted"].date() == day]
        if len(rows) < 100 or (rows and rows[-1]["accepted"].date() < day):
            break
    return out


def _primary_doc(cik: int, acc: str) -> str | None:
    r = edgar_text._get(edgar_text._url(cik, acc, "index.json"))
    if r is None:
        return None
    names = [i["name"] for i in r.json().get("directory", {}).get("item", [])]
    docs = [n for n in names if n.lower().endswith((".htm", ".html", ".txt")) and "index" not in n.lower()
            and not re.search(r"(?i)ex[-_]?\d", n) and not re.fullmatch(r"\d{10}-\d\d-\d{6}\.txt", n)]
    docs.sort(key=lambda n: not n.lower().endswith((".htm", ".html")))   # the 8-K itself, not a .txt copy
    return docs[0] if docs else None


def capture(day: date | None = None) -> str:
    day = day or now_pt().date()
    cmap = _cik_tickers()
    rows = []
    for form in FORMS:
        rows += [r | {"ticker": cmap[r["cik"]]} for r in fetch_form(form, day) if r["cik"] in cmap]
    df = pd.DataFrame(rows, columns=edgar.COLS)
    if rows:
        df = pd.DataFrame(rows).drop_duplicates("accession")
        df["primary_doc"], df["description"] = None, ""
        df = df[edgar.COLS]
    df["captured_at"] = pd.Timestamp(datetime.now(ET)).tz_localize(None)
    k8 = df[df["form"].str.startswith("8-K") & df["items"].notna()].copy()
    if len(k8):
        k8["primary_doc"] = [_primary_doc(c, a) for c, a in zip(k8["cik"], k8["accession"])]
        df.loc[k8.index, "primary_doc"] = k8["primary_doc"]
        rank = {it: i for i, it in enumerate(edgar_text.ITEMS)}
        k8["group"] = k8["items"].map(lambda s: next((x for x in sorted(s.split(","), key=lambda x: rank.get(x, 99))
                                                       if x in rank), None))
        scope = k8[k8["group"].notna() & k8["primary_doc"].notna()]
        txt = [edgar_text.fetch(r) for r in scope.itertuples()]
        if txt:
            pd.DataFrame(txt).to_parquet(LIVE / f"{day}-text.parquet", compression="zstd")
    LIVE.mkdir(parents=True, exist_ok=True)
    df.to_parquet(LIVE / f"{day}.parquet")
    before = int((df["accepted"].dt.time < DAY0_CUTOFF).sum()) if len(df) else 0
    return f"edgar_live {day}: {len(df)} universe filings ({before} accepted before 15:30 ET, tradeable day-0)"


def filings_asof(asof: date, cutoff_et: time | None = DAY0_CUTOFF) -> pd.DataFrame:
    """For strategies: the archive (filings.parquet) + today's live capture, without duplicates. Filings dated
    `asof` count only if accepted before `cutoff_et` (default 15:30 ET); pass None for the after-close view."""
    arch = pd.read_parquet(edgar.FILINGS)
    arch = arch[arch["accepted"].dt.date < asof]
    p = LIVE / f"{asof}.parquet"
    live = pd.read_parquet(p) if p.exists() else pd.DataFrame(columns=edgar.COLS)
    live = live[pd.to_datetime(live["accepted"]).dt.date == asof] if len(live) else live
    if cutoff_et is not None and len(live):
        live = live[pd.to_datetime(live["accepted"]).dt.time < cutoff_et]
    out = pd.concat([arch, live[edgar.COLS]], ignore_index=True) if len(live) else arch
    return out.drop_duplicates("accession", keep="first").reset_index(drop=True)


def text_asof(asof: date) -> pd.DataFrame:
    """Text rows (edgar_text format) for today's live 8-Ks - the archive's text for older filings is in
    data/edgar/text (research_data.filing_text)."""
    p = LIVE / f"{asof}-text.parquet"
    return pd.read_parquet(p) if p.exists() else pd.DataFrame(columns=["accession", "text", "exhibit"])


def due(now: datetime) -> bool:
    """The Scan Operator runs the capture on the first weekday tick in [12:40, 12:54] PT without one today."""
    if now.weekday() >= 5 or not (CAPTURE_FROM <= now.time() <= CAPTURE_UNTIL):
        return False
    return not (LIVE / f"{now.date()}.parquet").exists()


def status() -> str:
    files = sorted(p for p in LIVE.glob("*.parquet") if re.fullmatch(r"\d{4}-\d\d-\d\d", p.stem))
    if not files:
        return "edgar_live: no captures yet"
    last = pd.read_parquet(files[-1])
    return (f"edgar_live: {len(files)} capture day(s), last {files[-1].stem}: {len(last)} filings, captured "
            f"{last['captured_at'].max() if len(last) else '-'}")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    d = next((date.fromisoformat(a[7:]) for a in sys.argv if a.startswith("--date=")), None)
    print(capture(d) if cmd == "capture" else status())
