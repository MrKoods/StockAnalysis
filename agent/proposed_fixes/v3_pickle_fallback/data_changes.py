"""
PROPOSED FIX: V3 daytrade/data.py - add pickle fallback for parquet archive reads/writes.

Root cause: pyarrow's _parquet DLL is blocked by Windows Application Control policy,
causing IntradayFetch to crash at fetch_daily() with:
  ImportError: DLL load failed while importing _parquet: An Application Control policy
  has blocked this file.

Impact of the crash: daily (1d) bar archive not updated; 1m/5m archives not updated;
forward-test C6/G2/ON1 stats ARE updated (the 'forward' subcommand runs before 'fetch').

Fix: wrap parquet read/write in try/except ImportError in _merge_into_archive() and
load(). When blocked, skip merging old history (yfinance downloads cover a rolling
window anyway) and write a .pkl fallback file. load() prefers .pkl if present.

Replace _merge_into_archive and load in StockAnalysis-V3/daytrade/data.py with these
two functions (all other functions in data.py are unchanged).
"""


def _merge_into_archive(ticker: str, interval: str, new) -> int:
    path = _path(ticker, interval)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        try:
            import pandas as pd
            old = pd.read_parquet(path)
            new = pd.concat([old, new])
        except ImportError:
            pass  # pyarrow DLL blocked; skip merge; rolling window re-covers history
    else:
        pkl_path = path.with_suffix(".pkl")
        if pkl_path.exists():
            import pandas as pd
            old = pd.read_pickle(pkl_path)
            new = pd.concat([old, new])
    new = new[~new.index.duplicated(keep="last")].sort_index()
    try:
        new.to_parquet(path)
    except ImportError:
        new.to_pickle(path.with_suffix(".pkl"))
    return len(new)


def load(ticker: str, interval: str):
    import pandas as pd
    path = _path(ticker, interval)
    pkl_path = path.with_suffix(".pkl")
    if pkl_path.exists():
        df = pd.read_pickle(pkl_path)
    elif path.exists():
        try:
            df = pd.read_parquet(path)
        except ImportError:
            return pd.DataFrame(columns=COLS)
    else:
        return pd.DataFrame(columns=COLS)
    if interval != "1d":
        df.index = pd.DatetimeIndex(df.index).tz_convert(TZ)
    return df
