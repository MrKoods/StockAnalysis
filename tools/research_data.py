"""The ONLY data access research scripts may use. Every loader clips to TEAM_DATA_END (set by tools/jobs.py:
the plan's train_end for the train run, holdout_end for the one holdout run), so a train run cannot see the
holdout period. Earlier data than a window's start is allowed (indicator warm-up); scoring only counts trades
inside the window - the harness checks that.

Team archive (data/daily, tools/daily_bars.py - full re-download every Saturday):
  daily(tickers)    1999-01 .. last Friday   ~1,510 S&P 1500 names, split/dividend-adjusted OHLCV (yfinance)

Archives (read-only, from the V3 lab, refreshed by V3's daily tasks):
  hourly(tickers)   2023-11 .. today       ~1,510 names, America/New_York regular session bars
  five_min / one_min                       ~513 S&P 500 names, last few months only
  earnings(tickers) yfinance earnings dates + EPS estimate/actual/surprise, 2000+
  insider(start)    SEC Form 3/4/5 transactions, 2006+ (quarterly files)
  ratings(tickers)  analyst rating changes, 2012+
  universe(name)    'sp500' | 'sp400' | 'sp600' | 'all'

Team archive (data/edgar, from tools/edgar.py - updated by the dispatcher every run):
  filings(forms, items, tickers)  every SEC filing (not Forms 3/4/5/144) since the 1990s, with SEC's exact
                    acceptance time and 8-K item codes (codes exist from 2004-08; see EIGHT_K_ITEMS)
  splits(tickers)   stock splits: ex-date, ratio, and the first filing that said "stock split" (2001+)
  filing_text(df)   adds each 8-K's WORDS to filings() rows (body + attached press release for 8.01), 2026-11-14
  fomc()            FOMC meetings/calls since 2000 (scheduled dates usable in advance; calls only after)
  cboe(symbols)     CBOE daily closes (data/cboe, tools/cboe_history.py, 2026-11-23): VIX VIX9D VIX3M SKEW and the
                    option-strategy benchmarks PUT WPUT BXM CNDR BFLY (mid-price, BEFORE trading costs)
Both add `first_session` = the first session whose 09:30 ET open is after the event became public - the
earliest a strategy could have traded it. Use it, not the filing date, as the signal date.
And `entry_session` (2026-11-13) = the first session whose CLOSE can be bought after the event (SEC accepted it
before 15:30 ET that day). Buying at the close of entry_session catches the day-0 move that a buy at the close
AFTER first_session misses - most event edges are priced by then (decomposition, 2026-11-13 audit).
Hedge with the trade's own index fund: hedge_ticker('sp600') = IJR, 'sp400' = IJH, 'sp500' = SPY; index_of().
Survivorship (2026-11-13): an 'sp500' study MUST pass its events through pit_filter(df, date_col) - keeps only
rows dated while the stock was really in the S&P 500 (team/ref/sp500_membership.csv, 1996+). sp400/sp600/'all'
have no such list: their long results stay biased up (stocks that later fell out are missing entirely).
The full list of sources, their coverage and each family's used periods: state/data_catalog.md.
"""
from __future__ import annotations

import os
import re
import time
from pathlib import Path

import pandas as pd

V3 = Path(r"C:\Users\user\Documents\Git\StockAnalysis-V3")
INTRA = V3 / "data" / "intraday"
EVENTS = V3 / "data" / "events"
UNIVERSES = {"sp500": "sp500_new.csv", "sp400": "sp400.csv", "sp600": "sp600.csv"}
EDGAR = Path(__file__).resolve().parent.parent / "data" / "edgar"
DAILY = Path(__file__).resolve().parent.parent / "data" / "daily"   # tools/daily_bars.py
EIGHT_K_ITEMS = {
    "1.01": "entry into a material agreement", "1.02": "termination of a material agreement",
    "1.03": "bankruptcy or receivership", "2.01": "completed acquisition or disposition of assets",
    "2.02": "results of operations (earnings release)", "2.03": "new material debt obligation",
    "2.04": "debt acceleration trigger", "2.05": "exit or restructuring costs", "2.06": "material impairment",
    "3.01": "delisting notice / listing-rule failure", "3.02": "unregistered equity sale",
    "3.03": "change to shareholders' rights", "4.01": "auditor change",
    "4.02": "prior financials no longer reliable (restatement)", "5.01": "change in control",
    "5.02": "director/officer departure or appointment", "5.03": "charter or bylaw amendment (incl. splits)",
    "5.07": "shareholder vote results", "7.01": "Regulation FD disclosure", "8.01": "other events",
    "9.01": "financial statements and exhibits"}


def data_end() -> pd.Timestamp:
    """Last date a research script may see. Unset = refuse (only tools/jobs.py runs research)."""
    end = os.environ.get("TEAM_DATA_END")
    if not end:
        raise RuntimeError("TEAM_DATA_END not set - research scripts run only through tools/jobs.py")
    return pd.Timestamp(end)


def _read(path: Path) -> pd.DataFrame | None:
    # Smart App Control sometimes blocks pyarrow DLLs for a while; retry instead of failing the job.
    for i in range(4):
        try:
            return pd.read_parquet(path)
        except FileNotFoundError:
            return None
        except (ImportError, OSError):
            if i == 3:
                raise
            time.sleep(20)
    return None


def _clip_index(df: pd.DataFrame, end: pd.Timestamp) -> pd.DataFrame:
    idx = df.index
    if getattr(idx, "tz", None) is not None:
        cut = idx.tz_convert("America/New_York").normalize().tz_localize(None) <= end
    else:
        cut = pd.to_datetime(idx).normalize() <= end
    return df[cut]


def _bars(folder: str, tickers) -> dict[str, pd.DataFrame]:
    end = data_end()
    base = DAILY if folder == "daily" else INTRA / folder
    out = {}
    for t in tickers:
        df = _read(base / f"{t}.parquet")
        if df is not None and len(df):
            df = _clip_index(df.sort_index(), end)
            if len(df):
                out[t] = df
    return out


ETFS = {"SPY", "IWM", "IJR", "IJH", "MDY", "QQQ", "DIA", "VTI"}   # index/hedge funds in data/daily, not stocks
# Hedge each index's trades with ITS OWN index fund (added 2026-11-13): small-cap longs hedged with SPY carried
# the small-cap-vs-large-cap swing as noise - five sp600 longs in a row came out negative.
HEDGE = {"sp500": "SPY", "sp400": "IJH", "sp600": "IJR"}


def hedge_ticker(index: str) -> str:
    """The fund to hedge a trade from `index` ('sp500'|'sp400'|'sp600') with: SPY / IJH / IJR."""
    return HEDGE[index]


def index_of(tickers) -> dict[str, str]:
    """ticker -> 'sp500'|'sp400'|'sp600' (current membership - see universe()); others left out."""
    out = {}
    for name in ("sp600", "sp400", "sp500"):       # sp500 last: a ticker in two lists counts as the larger one
        for t in universe(name):
            out[t] = name
    wanted = set(tickers)
    return {t: i for t, i in out.items() if t in wanted}


def universe(name: str = "all") -> list[str]:
    """CURRENT index members (survivorship: names that left the index, or were added after a period, are not
    handled - a long test over many years is biased up; say so in PLAN.md and prefer recent train windows)."""
    if name == "all":
        return sorted(p.stem for p in DAILY.glob("*.parquet") if p.stem not in ETFS)
    df = pd.read_csv(V3 / "daytrade" / UNIVERSES[name])
    names = set(df.iloc[:, 0].astype(str).str.strip())
    if name == "sp500":
        # sp500_new.csv holds only the names V3 ADDED to its 50-ticker core (daytrade/config.py UNIVERSE), so the
        # 40 largest stocks were missing from "sp500" until 2026-11-13. They are the core's stocks.
        names |= SP500_CORE
    return sorted(names)


SP500_CORE = {"AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "AVGO", "AMD", "NFLX", "JPM", "BAC", "WFC",
              "C", "GS", "V", "MA", "XOM", "CVX", "UNH", "LLY", "JNJ", "PFE", "MRK", "ABBV", "KO", "PEP", "WMT",
              "COST", "HD", "DIS", "INTC", "MU", "QCOM", "ORCL", "CRM", "ADBE", "CSCO", "BA", "PLTR"}

# Point-in-time S&P 500 membership (tools/sp500_membership.py, added 2026-11-13). 280 of today's 503 members have
# price history from BEFORE they joined - usually a strong run that got them added - so an "sp500" test on
# universe("sp500") quietly buys future winners. pit_filter() keeps only rows dated while the stock was a member.
SP500_PIT = Path(__file__).resolve().parent.parent / "team" / "ref" / "sp500_membership.csv"


def _pit_spells() -> tuple[pd.DataFrame, pd.Timestamp]:
    with open(SP500_PIT, encoding="utf-8") as f:
        head = f.readline()
    src_end = pd.Timestamp(head.split("lists through ")[1][:10])
    spells = pd.read_csv(SP500_PIT, comment="#", parse_dates=["start", "end"])
    return spells, src_end


def sp500_member(tickers, dates) -> pd.Series:
    """Was tickers[i] in the S&P 500 on dates[i]? (bool Series, aligned with the inputs' order). After the source's
    last list (see the file header) membership = today's universe('sp500')."""
    d = pd.to_datetime(pd.Series(list(dates)))
    if d.dt.tz is not None:
        d = d.dt.tz_convert("America/New_York").dt.tz_localize(None)
    q = pd.DataFrame({"ticker": list(tickers), "date": d.dt.normalize().to_numpy()})
    q["_i"] = range(len(q))
    spells, src_end = _pit_spells()
    m = q.merge(spells, on="ticker", how="inner")
    hit = m[(m["start"] <= m["date"]) & (m["end"].isna() | (m["date"] < m["end"]))]["_i"]
    out = q["_i"].isin(hit)
    late = q["date"] > src_end
    out[late] = q.loc[late, "ticker"].isin(set(universe("sp500")))
    return pd.Series(out.to_numpy(), index=range(len(q)), name="sp500_member")


def pit_filter(df: pd.DataFrame, date_col: str = "entry_session", ticker_col: str = "ticker") -> pd.DataFrame:
    """Rows of an 'sp500' study whose stock was an S&P 500 member on its signal/entry date. REQUIRED for any
    universe('sp500') test (the Skeptic checks). Not for sp400/sp600/'all': a stock that later moved up to the S&P 500
    was usually in the 400/600 before, and no point-in-time list exists for those (that bias stays open)."""
    if df.empty:
        return df
    keep = sp500_member(df[ticker_col], df[date_col]).to_numpy()
    return df[keep]


def daily(tickers) -> dict[str, pd.DataFrame]:
    """Daily OHLCV (columns open high low close volume), index = date."""
    return _bars("daily", tickers)


def hourly(tickers) -> dict[str, pd.DataFrame]:
    return _bars("1h", tickers)


def five_min(tickers) -> dict[str, pd.DataFrame]:
    return _bars("5m", tickers)


def one_min(tickers) -> dict[str, pd.DataFrame]:
    return _bars("1m", tickers)


def earnings(tickers) -> dict[str, pd.DataFrame]:
    """Columns 'Earnings Date' (tz-aware), 'EPS Estimate', 'Reported EPS', 'Surprise(%)'. Rows after the
    cutoff are removed, and so are reported numbers for any report not yet out at the cutoff."""
    end = data_end()
    out = {}
    for t in tickers:
        df = _read(EVENTS / "earnings" / f"{t}.parquet")
        if df is None or not len(df):
            continue
        d = pd.to_datetime(df["Earnings Date"], utc=True).dt.tz_convert("America/New_York").dt.tz_localize(None)
        df = df[d.dt.normalize() <= end]
        if len(df):
            out[t] = df.reset_index(drop=True)
    return out


def insider(start: str = "2006-01-01") -> pd.DataFrame:
    """SEC insider transactions filed between `start` and the cutoff (FILING_DATE)."""
    end = data_end()
    frames = []
    for p in sorted((EVENTS / "insider").glob("*.parquet")):
        year = int(p.stem[:4])
        if year < pd.Timestamp(start).year or year > end.year:
            continue
        df = _read(p)
        if df is not None:
            frames.append(df)
    if not frames:
        return pd.DataFrame()
    df = pd.concat(frames, ignore_index=True)
    fd = pd.to_datetime(df["FILING_DATE"], errors="coerce")
    return df[(fd >= pd.Timestamp(start)) & (fd <= end)].reset_index(drop=True)


def _sessions(end: pd.Timestamp) -> pd.DatetimeIndex:
    """NYSE sessions up to the cutoff (SPY's daily bars)."""
    spy = _read(DAILY / "SPY.parquet")
    idx = pd.DatetimeIndex(pd.to_datetime(spy.index)).normalize().unique().sort_values()
    return idx[idx <= end]


def _first_session(ts: pd.Series, sessions: pd.DatetimeIndex) -> pd.Series:
    """First session whose 09:30 open is after `ts` (ET). A time of exactly 00:00 means SEC gave no time
    (old filings) - treated as after the close, so the next session."""
    day = ts.dt.normalize()
    secs = (ts - day).dt.total_seconds()
    same_day = (secs > 0) & (secs < 9.5 * 3600)
    i = sessions.searchsorted(day.where(same_day, day + pd.Timedelta(days=1)), side="left")
    out = pd.Series(pd.NaT, index=ts.index, dtype="datetime64[ns]")
    ok = (i < len(sessions)) & ts.notna().to_numpy()
    out[ok] = sessions[i[ok]]
    return out


ENTRY_CUTOFF_H = 15.5   # 15:30 ET: a filing SEC accepted by then can be bought at that session's close


def _entry_session(ts: pd.Series, sessions: pd.DatetimeIndex) -> pd.Series:
    """First session whose CLOSE can still be bought after the event: the acceptance day itself when SEC accepted
    it before 15:30 ET on a session day (overnight/pre-market filings included - their first_session), else the
    next session. No time (00:00, old filings) = after the close, as in _first_session. Paper-trading a strategy
    that enters here needs a live intraday EDGAR check (~12:45 PT) that is NOT built yet - the Director asks the
    user's session to build it when such a strategy passes its holdout (prompts/director.md)."""
    day = ts.dt.normalize()
    secs = (ts - day).dt.total_seconds()
    before = (secs > 0) & (secs < ENTRY_CUTOFF_H * 3600)
    i = sessions.searchsorted(day.where(before, day + pd.Timedelta(days=1)), side="left")
    out = pd.Series(pd.NaT, index=ts.index, dtype="datetime64[ns]")
    ok = (i < len(sessions)) & ts.notna().to_numpy()
    out[ok] = sessions[i[ok]]
    return out


def form_std(form: str) -> str:
    """SEC renamed 'SC 13D'/'SC 13G' to 'SCHEDULE 13D'/'SCHEDULE 13G' in late 2024 (2026 so far: 68 'SCHEDULE 13D',
    0 'SC 13D'). Map both to the old name, so a filter on 'SC 13D' keeps working across the change."""
    return re.sub(r"^SCHEDULE (13[DG])", lambda m: "SC " + m.group(1), str(form))


def filings(forms=None, items=None, tickers=None) -> pd.DataFrame:
    """SEC filings accepted up to the cutoff. forms: e.g. ['8-K'] (matches 8-K/A too); items: 8-K item codes,
    e.g. ['5.02'] (any match). 'SC 13D' also matches the post-2024 name 'SCHEDULE 13D' (form_std). Columns: ticker cik form filing_date accepted items accession primary_doc
    description first_session."""
    end = data_end()
    df = _read(EDGAR / "filings.parquet")
    if df is None:
        raise RuntimeError("no EDGAR archive - the dispatcher builds it (tools/edgar.py)")
    df = df[df["accepted"].dt.normalize() <= end]
    if forms:
        base = df["form"].map(form_std).str.replace("/A", "", regex=False)
        df = df[base.isin([form_std(f).replace("/A", "") for f in forms])]
    if items:
        codes = df["items"].fillna("").str.split(",")
        df = df[codes.apply(lambda c: any(x.strip() in items for x in c))]
    if tickers is not None:
        df = df[df["ticker"].isin(list(tickers))]
    df = df.copy()
    sessions = _sessions(end)
    df["first_session"] = _first_session(df["accepted"], sessions)
    df["entry_session"] = _entry_session(df["accepted"], sessions)
    return df.reset_index(drop=True)


TEXT = EDGAR / "text"                                    # tools/edgar_text.py
FOMC = Path(__file__).resolve().parent.parent / "team" / "ref" / "fomc_dates.csv"   # tools/fomc_dates.py


def filing_text(df: pd.DataFrame) -> pd.DataFrame:
    """Add the words of each 8-K to rows from filings() (added 2026-11-14). Columns added: text (the 8-K body from
    its first 'Item x.xx' heading), exhibit (for item 8.01 whose body is only a cover note, the attached press
    release - else ''), has_text (False = not downloaded: out of scope or the backfill hasn't reached it).
    In scope: items 8.01 5.02 1.01 1.02 2.01 3.02 2.05 2.06 3.01 5.03 7.01 (not 2.02 earnings, 5.07 votes).
    Use it to SPLIT an event by what it says (buyback authorized vs completed, CEO departs vs is appointed,
    special dividend), with simple, pre-registered keyword rules written in PLAN.md - a keyword list tuned on the
    train results is a variant like any other and counts in the luck bar.
    Coverage per item and period: state/data_catalog.md / `python tools/edgar_text.py status`."""
    out = df.copy()
    parts = sorted(TEXT.glob("part-*.parquet"))
    if not parts or out.empty:
        out["text"], out["exhibit"], out["has_text"] = "", "", False
        return out
    want = set(out["accession"])
    got = [t[t["accession"].isin(want)] for t in (_read(p) for p in parts) if t is not None]
    txt = pd.concat(got)[["accession", "text", "exhibit"]].drop_duplicates("accession") if got else pd.DataFrame(
        columns=["accession", "text", "exhibit"])
    out = out.merge(txt, on="accession", how="left")
    out["has_text"] = out["text"].notna()
    out[["text", "exhibit"]] = out[["text", "exhibit"]].fillna("")
    return out


def fomc() -> pd.DataFrame:
    """FOMC meetings and calls since 2000 (federalreserve.gov, added 2026-11-14): start, date (statement day; the
    statement comes at 14:00 ET), kind ('meeting' = scheduled, published ~a year ahead, so usable BEFORE it happens;
    'call' = conference call / unscheduled meeting, known only on the day - never use one before its date), sep
    (projections, 2021+). Rows after the cutoff are kept only for scheduled meetings (their dates were public)."""
    df = pd.read_csv(FOMC, parse_dates=["start", "date"])
    end = data_end()
    return df[(df["date"] <= end) | (df["kind"] == "meeting")].reset_index(drop=True)


CBOE = Path(__file__).resolve().parent.parent / "data" / "cboe"   # tools/cboe_history.py


def cboe(symbols=("VIX",)) -> pd.DataFrame:
    """CBOE index daily closes, one column per symbol, up to the cutoff. A value for day D is that day's close
    (known after 16:15 ET) - a rule may use it for a trade at D's close only if it uses an earlier proxy; the safe
    use is for trades from D+1 on. The strategy indexes (PUT, WPUT, BXM, CNDR, BFLY) are mid-price benchmarks:
    a test on them must charge real option spreads (paper/options, from 2026-11-23) - they are not tradeable."""
    if isinstance(symbols, str):
        symbols = [symbols]
    end = data_end()
    cols = {}
    for s in symbols:
        df = pd.read_csv(CBOE / f"{s}.csv", parse_dates=["date"])
        cols[s] = df.set_index("date")["close"]
    return pd.DataFrame(cols).loc[:end]


def splits(tickers=None) -> pd.DataFrame:
    """Splits known at the cutoff: announced by then, or (no announcement found) already effective by then.
    Columns: ticker ex_date ratio (>1 forward, <1 reverse) announced announce_form announce_accession found_by
    first_session (from `announced`; NaT when no announcement was found - then only ex_date is safe to use)."""
    end = data_end()
    df = _read(EDGAR / "splits.parquet")
    if df is None:
        raise RuntimeError("no splits archive - the dispatcher builds it (tools/edgar.py splits)")
    if "announced" not in df:
        df["announced"] = pd.NaT
    seen = df["announced"].dt.normalize() <= end
    df = df[seen | (df["announced"].isna() & (df["ex_date"] <= end))]
    if tickers is not None:
        df = df[df["ticker"].isin(list(tickers))]
    df = df.copy()
    sessions = _sessions(end)
    df["first_session"] = _first_session(df["announced"], sessions)
    df["entry_session"] = _entry_session(df["announced"], sessions)
    return df.reset_index(drop=True)


def ratings(tickers) -> dict[str, pd.DataFrame]:
    end = data_end()
    out = {}
    for t in tickers:
        df = _read(EVENTS / "ratings" / f"{t}.parquet")
        if df is None or not len(df):
            continue
        # Dated by the GradeDate column (the index is a plain row number) - clip on it, or nothing is clipped.
        when = pd.to_datetime(df["GradeDate"], errors="coerce")
        if getattr(when.dt, "tz", None) is not None:
            when = when.dt.tz_convert("America/New_York").dt.tz_localize(None)
        df = df[when.dt.normalize() <= end].sort_values("GradeDate")
        if len(df):
            out[t] = df.reset_index(drop=True)
    return out
