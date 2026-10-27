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
