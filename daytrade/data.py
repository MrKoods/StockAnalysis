"""Download and archive intraday bars from yfinance.

yfinance only serves ~30 calendar days of 1m bars (8 days per request) and ~60
trading days of 5m bars. Each `fetch` merges what's available into a local
parquet archive per ticker, so running it at least every few weeks builds an
ever-longer 1m history for free.
"""

from __future__ import annotations

import logging
from datetime import datetime, time, timedelta

import pandas as pd
import yfinance as yf

from .config import DATA_DIR, TZ, UNIVERSE

log = logging.getLogger(__name__)

COLS = ["open", "high", "low", "close", "volume"]
RTH_START, RTH_END = time(9, 30), time(15, 59)


def _path(ticker: str, interval: str):
    return DATA_DIR / interval / f"{ticker}.parquet"


def _normalize(df: pd.DataFrame) -> pd.DataFrame:
    """Lower-case OHLCV, NY time, regular-hours bars only, no empty rows."""
    df = df.rename(columns=str.lower)[COLS].dropna(subset=["open", "high", "low", "close"])
    df.index = pd.DatetimeIndex(df.index).tz_convert(TZ)
    df.index.name = "ts"
    t = df.index.time
    return df[(t >= RTH_START) & (t <= RTH_END)]


def _drop_incomplete_today(df: pd.DataFrame) -> pd.DataFrame:
    now = pd.Timestamp.now(tz=TZ)
    if now.time() < time(16, 5):
        df = df[df.index.date < now.date()]
    return df


def _split(raw: pd.DataFrame, tickers: list[str]) -> dict[str, pd.DataFrame]:
    out = {}
    for t in tickers:
        if isinstance(raw.columns, pd.MultiIndex):
            if t not in raw.columns.get_level_values(0):
                continue
            sub = raw[t]
        else:
            sub = raw
        sub = _normalize(sub)
        if len(sub):
            out[t] = sub
    return out


def _merge_into_archive(ticker: str, interval: str, new: pd.DataFrame) -> int:
    path = _path(ticker, interval)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        old = pd.read_parquet(path)
        new = pd.concat([old, new])
    new = new[~new.index.duplicated(keep="last")].sort_index()
    new.to_parquet(path)
    return len(new)


def _download(tickers: list[str], **kw) -> pd.DataFrame:
    return yf.download(
        tickers, group_by="ticker", prepost=False, auto_adjust=False,
        progress=False, threads=True, **kw,
    )


def fetch(tickers: list[str] | None = None) -> dict[str, dict[str, int]]:
    """Pull all available 1m + 5m bars and merge them into the archive."""
    tickers = tickers or UNIVERSE
    frames: dict[str, dict[str, list[pd.DataFrame]]] = {t: {"1m": [], "5m": []} for t in tickers}

    # 1m: Yahoo serves the last 30 days, max 8 days per request, and rejects a
    # whole request that reaches past day 30 -- so step forward from day 29.
    logging.getLogger("yfinance").setLevel(logging.CRITICAL)
    today = datetime.now().date()
    start = today - timedelta(days=29)
    first = True
    while start <= today:
        end = start + timedelta(days=7)
        raw = _download(tickers, interval="1m", start=start, end=end)
        got = _split(raw, tickers) if len(raw) else {}
        if first and not got and start < today - timedelta(days=24):
            start += timedelta(days=1)  # oldest window past Yahoo's cutoff; nudge forward
            continue
        first = False
        for t, df in got.items():
            frames[t]["1m"].append(df)
        log.info("1m %s -> %s: %d tickers", start, end, len(got))
        start = end

    fetch_daily(tickers)
    raw = _download(tickers, interval="5m", period="60d")
    for t, df in _split(raw, tickers).items():
        frames[t]["5m"].append(df)

    summary = {}
    for t, by_iv in frames.items():
        summary[t] = {}
        for iv, parts in by_iv.items():
            if not parts:
                continue
            df = _drop_incomplete_today(pd.concat(parts))
            summary[t][iv] = _merge_into_archive(t, iv, df)
    return summary


def fetch_daily(tickers: list[str] | None = None) -> None:
    """2 years of daily bars (for ATR / trend context; Yahoo keeps these indefinitely)."""
    tickers = tickers or UNIVERSE
    raw = _download(tickers, interval="1d", period="2y")
    for t in tickers:
        if t not in raw.columns.get_level_values(0):
            continue
        df = raw[t].rename(columns=str.lower)[COLS].dropna(subset=["close"])
        df.index = pd.DatetimeIndex(df.index).tz_localize(None)
        _merge_into_archive(t, "1d", df)


def load(ticker: str, interval: str) -> pd.DataFrame:
    path = _path(ticker, interval)
    if not path.exists():
        return pd.DataFrame(columns=COLS)
    df = pd.read_parquet(path)
    if interval != "1d":
        df.index = pd.DatetimeIndex(df.index).tz_convert(TZ)
    return df
