"""SEC EDGAR company events for the research archive (plain Python - zero Claude tokens).

    python tools/edgar.py backfill        # once: every filing (not Forms 3/4/5/144) for the universe, 1990s+
    python tools/edgar.py update          # daily (dispatcher): only companies that filed since the last update
    python tools/edgar.py splits          # weekly (dispatcher, Saturday): split dates/ratios + announcement dates
    python tools/edgar.py status

Output (data/edgar/, git-ignored, read by tools/research_data.py):
  filings.parquet  ticker cik form filing_date accepted(ET, naive) items accession primary_doc description
  splits.parquet   ticker ex_date ratio announced(ET, naive) announce_form announce_accession found_by

Efficiency: the backfill is ~1 request per company (+1 per 1,000 older filings). The daily update reads EDGAR's
one-file-per-day index and re-fetches only the companies in our universe that filed that day (~50-200), so a
day costs a couple of minutes at SEC's rate limit. Split announcements use full-text search once per split and
are cached - a split already matched is never searched again.

Look-ahead: `accepted` is SEC's acceptance timestamp. tools/research_data.py turns it into the first session
whose 09:30 ET open is after it - the earliest a strategy could have acted.
"""
from __future__ import annotations

import sys
import time
from datetime import date, timedelta

import pandas as pd
import requests

from common import TEAM, log, read_env, save_json, load_json

OUT = TEAM / "data" / "edgar"
FILINGS = OUT / "filings.parquet"
SPLITS = OUT / "splits.parquet"
STATE = OUT / "state.json"
DAILY_MAX = r"C:\Users\user\Documents\Git\StockAnalysis-V3\data\intraday\daily_max"
SKIP_FORMS = {"3", "4", "5", "3/A", "4/A", "5/A", "144", "144/A"}   # insider forms: tools/research_data.insider
COLS = ["ticker", "cik", "form", "filing_date", "accepted", "items", "accession", "primary_doc", "description"]
GAP = 0.125                                                       # SEC allows 10 requests/second; stay under

_last = [0.0]


def _get(url: str, params: dict | None = None, tries: int = 5, missing=(404,)) -> requests.Response | None:
    """Rate-limited GET with retries. A status in `missing` -> None (e.g. no daily index on a holiday)."""
    ua = read_env().get("SEC_EDGAR_USER_AGENT")
    if not ua:
        raise SystemExit("SEC_EDGAR_USER_AGENT missing from the V2 .env (SEC requires a contact User-Agent)")
    for i in range(tries):
        wait = GAP - (time.time() - _last[0])
        if wait > 0:
            time.sleep(wait)
        _last[0] = time.time()
        try:
            r = requests.get(url, params=params, headers={"User-Agent": ua}, timeout=30)
        except requests.RequestException:
            time.sleep(2 ** i)
            continue
        if r.status_code in missing:
            return None
        if r.status_code in (429, 500, 502, 503, 504) or (r.ok and '"errorType"' in r.text[:40]):
            time.sleep(2 ** i)                      # full-text search returns 200 + errorType when busy
            continue
        r.raise_for_status()
        return r
    raise RuntimeError(f"EDGAR kept failing: {url}")


def universe() -> list[str]:
    from pathlib import Path
    return sorted(p.stem for p in Path(DAILY_MAX).glob("*.parquet"))


def cik_map() -> dict[str, int]:
    """Our tickers -> CIK (SEC's current ticker file; BRK-B style matches SEC's BRK-B)."""
    rows = _get("https://www.sec.gov/files/company_tickers.json").json().values()
    sec = {r["ticker"].upper().replace(".", "-"): int(r["cik_str"]) for r in rows}
    return {t: sec[t] for t in universe() if t in sec}


def _frame(block: dict, ticker: str, cik: int) -> pd.DataFrame:
    df = pd.DataFrame({"ticker": ticker, "cik": cik, "form": block["form"], "filing_date": block["filingDate"],
                       "accepted": block["acceptanceDateTime"], "items": block.get("items", [""] * len(block["form"])),
                       "accession": block["accessionNumber"], "primary_doc": block["primaryDocument"],
                       "description": block.get("primaryDocDescription", [""] * len(block["form"]))})
    df = df[~df["form"].isin(SKIP_FORMS)]
    acc = pd.to_datetime(df["accepted"], utc=True, errors="coerce")
    df["accepted"] = acc.dt.tz_convert("America/New_York").dt.tz_localize(None)
    df["filing_date"] = pd.to_datetime(df["filing_date"], errors="coerce")
    return df[COLS]


def company(ticker: str, cik: int, full: bool) -> pd.DataFrame:
    r = _get(f"https://data.sec.gov/submissions/CIK{cik:010d}.json")
    if r is None:
        return pd.DataFrame(columns=COLS)
    s = r.json()
    parts = [_frame(s["filings"]["recent"], ticker, cik)]
    if full:
        for page in s["filings"].get("files", []):
            p = _get(f"https://data.sec.gov/submissions/{page['name']}")
            if p is not None:
                parts.append(_frame(p.json(), ticker, cik))
    return pd.concat(parts, ignore_index=True)


def _save(df: pd.DataFrame) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    df = df.drop_duplicates("accession" if "accession" in df else None).sort_values(["accepted", "ticker"])
    df.reset_index(drop=True).to_parquet(FILINGS.with_suffix(".tmp"))
    FILINGS.with_suffix(".tmp").replace(FILINGS)


def backfill() -> None:
    ciks = cik_map()
    missing = sorted(set(universe()) - set(ciks))
    log(f"edgar backfill: {len(ciks)} companies ({len(missing)} tickers not in SEC's map: {missing[:20]})", "edgar")
    parts, t0 = [], time.time()
    for i, (t, c) in enumerate(ciks.items(), 1):
        try:
            parts.append(company(t, c, full=True))
        except Exception as e:                       # one bad company must not lose the rest
            log(f"edgar backfill {t}: {e}", "edgar")
        if i % 100 == 0:
            log(f"edgar backfill {i}/{len(ciks)} ({time.time() - t0:.0f}s)", "edgar")
    df = pd.concat(parts, ignore_index=True)
    # A filing about two companies (e.g. a merger) is one accession per filer - keep one row per ticker+accession.
    df = df.drop_duplicates(["ticker", "accession"])
    OUT.mkdir(parents=True, exist_ok=True)
    df.sort_values(["accepted", "ticker"]).reset_index(drop=True).to_parquet(FILINGS)
    save_json(STATE, {"updated_through": str(date.today() - timedelta(days=1)), "unmapped": missing})
    log(f"edgar backfill done: {len(df):,} filings, {df['ticker'].nunique()} tickers", "edgar")


def update() -> str:
    """Daily: read EDGAR's daily index for each day since the last update; re-fetch only our filers."""
    if not FILINGS.exists():
        return "edgar: no archive yet - run `python tools/edgar.py backfill`"
    st = load_json(STATE, {})
    day = date.fromisoformat(st.get("updated_through", str(date.today() - timedelta(days=7)))) + timedelta(days=1)
    by_cik = {c: t for t, c in cik_map().items()}
    filers, last_ok = set(), None
    while day <= date.today():
        q = (day.month - 1) // 3 + 1
        # SEC answers 403 (not 404) for a daily index it hasn't published yet (e.g. today's, before ~10 PM ET).
        r = _get(f"https://www.sec.gov/Archives/edgar/daily-index/{day.year}/QTR{q}/master.{day:%Y%m%d}.idx",
                 missing=(403, 404))
        if r is not None:                             # None = weekend/holiday or not published yet
            for line in r.text.splitlines():
                p = line.split("|")
                if len(p) == 5 and p[0].isdigit() and int(p[0]) in by_cik and p[2] not in SKIP_FORMS:
                    filers.add(int(p[0]))
            last_ok = day
        day += timedelta(days=1)
    if not filers:
        if last_ok:
            save_json(STATE, {**st, "updated_through": str(last_ok)})
        return f"edgar: no new filings for our universe (through {last_ok or st.get('updated_through')})"
    new = pd.concat([company(by_cik[c], c, full=False) for c in sorted(filers)], ignore_index=True)
    old = pd.read_parquet(FILINGS)
    df = pd.concat([old, new], ignore_index=True).drop_duplicates(["ticker", "accession"], keep="last")
    OUT.mkdir(parents=True, exist_ok=True)
    df.sort_values(["accepted", "ticker"]).reset_index(drop=True).to_parquet(FILINGS)
    save_json(STATE, {**st, "updated_through": str(last_ok or st.get("updated_through"))})
    return f"edgar: {len(filers)} companies filed; archive now {len(df):,} filings (through {last_ok})"


def _announcement(cik: int, ex: pd.Timestamp, filings: pd.DataFrame) -> dict:
    """Earliest filing in the 120 days before the ex-date whose text says 'stock split' (full-text search,
    2001+). Its acceptance time comes from our own filings table, matched on the accession number."""
    if ex < pd.Timestamp("2001-03-01"):
        return {"found_by": "before_fts_coverage"}
    r = _get("https://efts.sec.gov/LATEST/search-index",
             {"q": '"stock split"', "ciks": f"{cik:010d}", "dateRange": "custom",
              "startdt": f"{ex - pd.Timedelta(days=120):%Y-%m-%d}", "enddt": f"{ex - pd.Timedelta(days=1):%Y-%m-%d}"})
    hits = (r.json().get("hits", {}).get("hits", []) if r is not None else [])
    # Only the 8-K body or a press release (EX-99.x) announces a split. Equity-plan exhibits (EX-10), 10-Qs and
    # proxies mention "stock split" as boilerplate - taking those would date the announcement too EARLY.
    hits = [h for h in hits if str(h["_source"].get("file_type", "")).upper().startswith(("8-K", "EX-99"))]
    accs = sorted({h["_id"].split(":")[0] for h in hits})
    rows = filings[filings["accession"].isin(accs)].sort_values("accepted")
    if not len(rows):
        return {"found_by": "not_found"}
    first = rows.iloc[0]
    return {"announced": first["accepted"], "announce_form": first["form"],
            "announce_accession": first["accession"], "found_by": "full_text_search"}


def splits() -> str:
    """Split ex-dates + ratios from yfinance; announcement dates from EDGAR (cached: only new splits searched)."""
    import yfinance as yf
    if not FILINGS.exists():
        return "edgar splits: no filings archive yet - run backfill first"
    filings = pd.read_parquet(FILINGS, columns=["ticker", "form", "accepted", "accession"])
    old = pd.read_parquet(SPLITS) if SPLITS.exists() else pd.DataFrame()
    if len(old):                                          # a failed search is retried, not cached
        old = old[old["found_by"] != "search_failed"]
    done = set(zip(old["ticker"], old["ex_date"])) if len(old) else set()
    ciks, rows = cik_map(), []
    for t in universe():
        try:
            s = yf.Ticker(t).splits
        except Exception:
            continue
        for ex, ratio in (s.items() if s is not None else []):
            ex = pd.Timestamp(ex).tz_localize(None).normalize() if pd.Timestamp(ex).tzinfo else pd.Timestamp(ex)
            if (t, ex) in done or t not in ciks:
                continue
            row = {"ticker": t, "ex_date": ex, "ratio": float(ratio)}
            try:
                row.update(_announcement(ciks[t], ex, filings[filings["ticker"] == t]))
            except RuntimeError:                          # SEC search busy: keep going, retry next run
                row["found_by"] = "search_failed"
            rows.append(row)
    new = pd.DataFrame(rows)
    df = pd.concat([old, new], ignore_index=True) if len(new) else old
    if len(df):
        OUT.mkdir(parents=True, exist_ok=True)
        df.sort_values(["ex_date", "ticker"]).reset_index(drop=True).to_parquet(SPLITS)
    failed = int((df["found_by"] == "search_failed").sum()) if len(df) else 0
    return f"edgar splits: {len(new)} new splits; {len(df)} total" + (f"; {failed} searches to retry" if failed else "")


def status() -> str:
    if not FILINGS.exists():
        return "edgar: no archive"
    df = pd.read_parquet(FILINGS, columns=["ticker", "form", "accepted"])
    sp = pd.read_parquet(SPLITS) if SPLITS.exists() else pd.DataFrame()
    return (f"edgar: {len(df):,} filings, {df['ticker'].nunique()} tickers, {df['accepted'].min():%Y-%m-%d} .. "
            f"{df['accepted'].max():%Y-%m-%d}; 8-Ks {int(df['form'].str.startswith('8-K').sum()):,}; "
            f"splits {len(sp)} ({int(sp['announced'].notna().sum()) if len(sp) and 'announced' in sp else 0} with announcement)")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    print({"backfill": backfill, "update": update, "splits": splits, "status": status}[cmd]() or "done")
