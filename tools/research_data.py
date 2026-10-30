"""The ONLY data access research scripts may use. Every loader clips to TEAM_DATA_END (set by tools/jobs.py:
the plan's train_end for the train run, holdout_end for the one holdout run), so a train run cannot see the
holdout period. Earlier data than a window's start is allowed (indicator warm-up); scoring only counts trades
inside the window - the harness checks that.

Archives (read-only, from the V3 lab, refreshed by V3's daily tasks):
  daily(tickers)    1999-01 .. ~2026-10   ~1,510 S&P 1500 names (daily_max), unadjusted-ish OHLCV
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
Both add `first_session` = the first session whose 09:30 ET open is after the event became public - the
earliest a strategy could have traded it. Use it, not the filing date, as the signal date.
The full list of sources, their coverage and each family's used periods: state/data_catalog.md.
"""
from __future__ import annotations

import os
import time
from pathlib import Path

import pandas as pd

V3 = Path(r"C:\Users\user\Documents\Git\StockAnalysis-V3")
INTRA = V3 / "data" / "intraday"
EVENTS = V3 / "data" / "events"
UNIVERSES = {"sp500": "sp500_new.csv", "sp400": "sp400.csv", "sp600": "sp600.csv"}
EDGAR = Path(__file__).resolve().parent.parent / "data" / "edgar"
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
    out = {}
    for t in tickers:
        df = _read(INTRA / folder / f"{t}.parquet")
        if df is not None and len(df):
            df = _clip_index(df.sort_index(), end)
            if len(df):
                out[t] = df
    return out


def universe(name: str = "all") -> list[str]:
    if name == "all":
        return sorted(p.stem for p in (INTRA / "daily_max").glob("*.parquet"))
    df = pd.read_csv(V3 / "daytrade" / UNIVERSES[name])
    return sorted(df.iloc[:, 0].astype(str).str.strip().tolist())


def daily(tickers) -> dict[str, pd.DataFrame]:
    """Daily OHLCV (columns open high low close volume), index = date."""
    return _bars("daily_max", tickers)


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
    spy = _read(INTRA / "daily_max" / "SPY.parquet")
    return pd.DatetimeIndex(pd.to_datetime(spy.index).normalize()).unique().sort_values()[lambda i: i <= end]


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


def filings(forms=None, items=None, tickers=None) -> pd.DataFrame:
    """SEC filings accepted up to the cutoff. forms: e.g. ['8-K'] (matches 8-K/A too); items: 8-K item codes,
    e.g. ['5.02'] (any match). Columns: ticker cik form filing_date accepted items accession primary_doc
    description first_session."""
    end = data_end()
    df = _read(EDGAR / "filings.parquet")
    if df is None:
        raise RuntimeError("no EDGAR archive - the dispatcher builds it (tools/edgar.py)")
    df = df[df["accepted"].dt.normalize() <= end]
    if forms:
        df = df[df["form"].str.replace("/A", "", regex=False).isin([f.replace("/A", "") for f in forms])]
    if items:
        codes = df["items"].fillna("").str.split(",")
        df = df[codes.apply(lambda c: any(x.strip() in items for x in c))]
    if tickers is not None:
        df = df[df["ticker"].isin(list(tickers))]
    df = df.copy()
    df["first_session"] = _first_session(df["accepted"], _sessions(end))
    return df.reset_index(drop=True)


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
    df["first_session"] = _first_session(df["announced"], _sessions(end))
    return df.reset_index(drop=True)


def ratings(tickers) -> dict[str, pd.DataFrame]:
    end = data_end()
    out = {}
    for t in tickers:
        df = _read(EVENTS / "ratings" / f"{t}.parquet")
        if df is None or not len(df):
            continue
        df = _clip_index(df.sort_index(), end) if isinstance(df.index, pd.DatetimeIndex) else df
        out[t] = df
    return out
