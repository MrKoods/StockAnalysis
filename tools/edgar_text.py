"""8-K text for the research archive (plain Python, zero Claude tokens) - added 2026-11-14.

    python tools/edgar_text.py backfill [--max N]   # resumable; item groups in ITEMS order, newest first
    python tools/edgar_text.py update               # daily (dispatcher): newest in-scope 8-Ks, capped
    python tools/edgar_text.py status

Why: data/edgar/filings.parquet holds only the INDEX of every 8-K (date, item codes, document name). Ideas that
need to know WHAT a filing says - buyback announced vs completed, officer departure vs appointment, special
dividend - were blocked (Director data request 2026-11-14). This stores the text.

Stored (data/edgar/text/part-*.parquet, git-ignored): accession, ticker, group (the filing's highest-priority
item), status, text = the 8-K body from its first "Item x.xx" heading (SEC cover page and hidden XBRL dropped),
exhibit = for item 8.01 whose body is only a cover note ("press release attached as Exhibit 99.1"), that press
release. Both cut at MAX_CHARS - the facts are at the top. Read them via research_data.filing_text().

Scope (ITEMS, download order): 8.01 other events, 5.02 officers/directors, 1.01/1.02 agreements, 2.01
acquisitions, 3.02 unregistered sales, 2.05 restructuring, 2.06 impairments, 3.01 delisting, 5.03 charter, 7.01
Reg FD. Not 2.02 (earnings releases, 115k filings) or 5.07 (vote results).
Rate: SEC allows 10 requests/s; WORKERS threads share one limiter at RATE, User-Agent = SEC_EDGAR_USER_AGENT.
"""
from __future__ import annotations

import html
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pandas as pd
import requests

import edgar
from common import TEAM, LockBusy, log, read_env, state_lock

OUT = TEAM / "data" / "edgar" / "text"
ITEMS = ["8.01", "5.02", "1.01", "1.02", "2.01", "3.02", "2.05", "2.06", "3.01", "5.03", "7.01"]
EX99_ITEMS = {"8.01"}                     # body is often a cover note; the facts are in the attached release
MAX_CHARS = 12_000
COVER_CHARS = 1_500                       # a body this short that points at Exhibit 99 = fetch the exhibit
PART_ROWS = 2_000
DAILY_CAP = 1_500                         # update(): a few minutes; the rest waits for tomorrow
RATE = 8.0                                # request starts per second, all threads together
WORKERS = 8                               # SEC answers in ~0.1-1 s, so one thread alone is too slow
ITEM_RX = re.compile(r"(?i)\bItem\s*\d\.\d\d")


class _Limiter:
    """Shared pacing for the worker threads: at most `rate` request starts per second."""

    def __init__(self, rate: float):
        self.gap, self.next, self.lock = 1.0 / rate, 0.0, threading.Lock()

    def wait(self) -> None:
        with self.lock:
            now = time.monotonic()
            at = max(now, self.next)
            self.next = at + self.gap
        if at > now:
            time.sleep(at - now)


_limit = _Limiter(RATE)
_local = threading.local()


def _get(url: str, tries: int = 5) -> requests.Response | None:
    """Thread-safe, rate-limited GET (one keep-alive session per thread). 404 -> None."""
    if not hasattr(_local, "s"):
        ua = read_env().get("SEC_EDGAR_USER_AGENT")
        if not ua:
            raise SystemExit("SEC_EDGAR_USER_AGENT missing from the V2 .env (SEC requires a contact User-Agent)")
        _local.s = requests.Session()
        _local.s.headers["User-Agent"] = ua
    for i in range(tries):
        _limit.wait()
        try:
            r = _local.s.get(url, timeout=30)
        except requests.RequestException:
            time.sleep(2 ** i)
            continue
        if r.status_code == 404:
            return None
        if r.status_code in (403, 429, 500, 502, 503, 504):
            time.sleep(2 ** (i + 1))        # 403/429 = SEC asking us to slow down
            continue
        r.raise_for_status()
        return r
    raise RuntimeError(f"EDGAR kept failing: {url}")


def to_text(raw: bytes | str) -> str:
    s = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else raw
    s = re.sub(r"(?is)<(script|style|head|ix:header)\b[^>]*>.*?</\1>", " ", s)
    s = re.sub(r"(?is)<div[^>]*display:\s*none[^>]*>.*?</div>", " ", s)
    s = re.sub(r"(?i)<br\s*/?>|</(p|div|tr|li|h\d)>", "\n", s)
    s = re.sub(r"(?s)<[^>]+>", " ", s)
    s = html.unescape(s).replace("\xa0", " ")
    s = re.sub(r"[ \t\r\f\v]+", " ", s)
    s = re.sub(r"\n\s*\n+", "\n", s)
    return s.strip()


def body_of(text: str) -> str:
    """Drop the SEC cover page: keep from the first 'Item x.xx' heading (text without one is kept whole)."""
    m = ITEM_RX.search(text)
    return text[m.start():] if m else text


def _url(cik: int, acc: str, name: str) -> str:
    return f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc.replace('-', '')}/{name}"


def _ex99(cik: int, acc: str) -> str | None:
    r = _get(_url(cik, acc, "index.json"))
    if r is None:
        return None
    names = [i["name"] for i in r.json().get("directory", {}).get("item", [])]
    return next((n for n in names if re.search(r"(?i)ex[-_]?99", n) and n.lower().endswith((".htm", ".html", ".txt"))),
                None)


def fetch(row) -> dict:
    """One filing -> text row. Errors are recorded (status), never raised: a bad document must not stop a backfill."""
    out = {"accession": row.accession, "ticker": row.ticker, "group": row.group, "status": "ok", "text": "",
           "exhibit": ""}
    try:
        r = _get(_url(row.cik, row.accession, row.primary_doc))
        if r is None:
            out["status"] = "missing"
            return out
        body = body_of(to_text(r.content))
        if row.group in EX99_ITEMS and len(body) < COVER_CHARS and re.search(r"(?i)exhibit\s*99", body):
            name = _ex99(row.cik, row.accession)
            ex = _get(_url(row.cik, row.accession, name)) if name else None
            if ex is not None:
                out["exhibit"] = to_text(ex.content)[:MAX_CHARS]
        out["text"] = body[:MAX_CHARS]
    except Exception as e:  # noqa: BLE001
        out["status"] = f"error: {str(e)[:80]}"
    return out


def _done() -> set[str]:
    acc: set[str] = set()
    for p in OUT.glob("part-*.parquet"):
        acc |= set(pd.read_parquet(p, columns=["accession"])["accession"])
    return acc


def todo() -> pd.DataFrame:
    """In-scope 8-Ks without text yet, in ITEMS order then newest first. Each filing counts once, under its
    highest-priority item."""
    f = pd.read_parquet(edgar.FILINGS)
    k = f[f["form"].isin(["8-K", "8-K/A"]) & f["items"].notna()].copy()
    rank = {it: i for i, it in enumerate(ITEMS)}
    k["prio"] = k["items"].map(lambda s: min((rank[x.strip()] for x in s.split(",") if x.strip() in rank),
                                            default=None))
    k = k[k["prio"].notna()]
    k["group"] = k["prio"].map(lambda i: ITEMS[int(i)])
    k = k[~k["accession"].isin(_done())]
    return k.sort_values(["prio", "filing_date"], ascending=[True, False]).drop_duplicates("accession")


def _write(rows: list[dict]) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    n = len(list(OUT.glob("part-*.parquet")))
    pd.DataFrame(rows).to_parquet(OUT / f"part-{n:05d}-{int(time.time())}.parquet", compression="zstd")


def _fetch_all(q: pd.DataFrame, progress: bool) -> int:
    rows, t0, n = [], time.time(), len(q)
    with ThreadPoolExecutor(WORKERS) as pool:
        for i, out in enumerate(pool.map(fetch, q.itertuples())):
            rows.append(out)
            if len(rows) >= PART_ROWS:
                _write(rows)
                rows = []
            if progress and (i + 1) % 1000 == 0:
                rate = (i + 1) / (time.time() - t0)
                log(f"edgar_text: {i + 1}/{n} ({out['group']}) {rate:.1f}/s, ~{(n - i - 1) / rate / 3600:.1f} h left",
                    "edgar_text")
    if rows:
        _write(rows)
    return n


def run(max_docs: int | None = None) -> str:
    """Backfill. Holds the edgar_text lock for its whole run (hours), so the daily update skips meanwhile: two
    fetchers at once would double SEC's rate and fetch the same filings twice."""
    try:
        with state_lock("edgar_text", wait_s=0, stale_s=24 * 3600):
            q = todo()
            t0 = time.time()
            n = _fetch_all(q.head(max_docs) if max_docs else q, progress=True)
            return f"edgar_text: fetched {n} filing(s) in {(time.time() - t0) / 60:.1f} min"
    except LockBusy as e:
        return f"edgar_text: another fetch is running ({e})"


def update() -> str:
    """Daily (dispatcher): the newest in-scope filings first, capped so the dispatch stays short; a backfill
    backlog drains a little each day too."""
    try:
        with state_lock("edgar_text", wait_s=0, stale_s=24 * 3600):
            q = todo().sort_values("filing_date", ascending=False)
            n = _fetch_all(q.head(DAILY_CAP), progress=False)
            return f"edgar_text update: {n} filing(s); backlog {max(len(q) - n, 0)}"
    except LockBusy:
        return "edgar_text update: skipped - the backfill is running (it covers new filings too)"


def status() -> str:
    parts = sorted(OUT.glob("part-*.parquet"))
    if not parts:
        return "edgar_text: nothing stored yet"
    d = pd.concat(pd.read_parquet(p, columns=["group", "status"]) for p in parts)
    by = d.groupby("group")["status"].agg(stored="size", ok=lambda s: int((s == "ok").sum()))
    return f"edgar_text: {len(d)} filings, {len(parts)} parts\n{by.to_string()}\nstill to fetch: {len(todo())}"


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    mx = int(sys.argv[sys.argv.index("--max") + 1]) if "--max" in sys.argv else None
    print({"backfill": lambda: run(mx), "update": update, "status": status}[cmd]())
