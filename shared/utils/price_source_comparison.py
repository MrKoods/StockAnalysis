"""
SHARED: One-scan accuracy check of the yfinance OHLCV the pipeline actually
uses against Seeking Alpha's get_daily_ohlcv (a keyed price source that is
built but not wired into scoring).

Decision D3 (2026-08 API re-architecture): yfinance is currently the single
point of failure for Technical scoring. Seeking Alpha's daily bars are the
obvious keyed backup, but before promoting SA to a co-source / failover its
bars need a real accuracy comparison against yfinance over ~1-2 trading weeks
— ideally spanning a corporate action (split / special dividend) to see
whether the two adjust the same way.

This appends one summary row per (scan, ticker) to
data/logs/price_source_comparison.csv. It has NO effect on scoring, indicators,
or signals — it only reads the OHLCV the caller already fetched and makes one
(cached ~8h) SA call per ticker. Gated by config price_source_comparison.enabled
so it can be switched off once the evaluation window is done. Never raises.
"""

import csv
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from shared.api_clients import seeking_alpha_client
from shared.utils.logger import get_logger

logger = get_logger(__name__)

# Referenced at call time (not baked into a signature) so tests monkeypatch it.
_CSV_PATH = Path("data/logs/price_source_comparison.csv")

_FIELDS = [
    "logged_at_utc", "scan_type", "ticker",
    "yf_first", "yf_last", "yf_bars",
    "sa_first", "sa_last", "sa_bars",
    "common_days", "sa_staleness_days",
    "close_pct_diff_last", "close_pct_diff_max", "close_pct_diff_mean",
    "adj_pct_diff_last", "adj_pct_diff_max",
    "last_common_date", "yf_close", "sa_close", "sa_adj",
    "yf_volume", "sa_volume", "volume_pct_diff_last",
    "ohlc_pct_diff_max_last", "note",
]


def _pct(a, b) -> Optional[float]:
    """(a - b) / |b| as a percentage, rounded; None if either side is missing
    or b is zero."""
    try:
        a = float(a)
        b = float(b)
    except (TypeError, ValueError):
        return None
    if b == 0.0:
        return None
    return round((a - b) / abs(b) * 100.0, 4)


def log_price_source_comparison(
    yf_ohlcv: dict, scan_type: str, cfg: Optional[dict] = None,
) -> None:
    """
    Compare each ticker's yfinance daily bars (already fetched by the caller)
    against Seeking Alpha's, and append the results to the comparison CSV.

    yf_ohlcv: {ticker: pd.DataFrame} exactly as _fetch_market_context returns
      in its "ticker_ohlcv" key — DatetimeIndex, columns Open/High/Low/Close/
      Volume, yfinance auto_adjust=True.
    No-op unless cfg["price_source_comparison"]["enabled"] is true.
    """
    if not ((cfg or {}).get("price_source_comparison") or {}).get("enabled", False):
        return
    try:
        rows = _build_rows(yf_ohlcv or {}, scan_type)
        _append_rows(rows)
        logger.info(f"price_source_comparison: logged {len(rows)} ticker row(s) ({scan_type})")
    except Exception as exc:  # never let a diagnostic break a scan
        logger.warning(f"price_source_comparison: skipped ({exc})")


def _build_rows(yf_ohlcv: dict, scan_type: str) -> list[dict]:
    import pandas as pd

    now = datetime.now(timezone.utc).isoformat()
    rows: list[dict] = []

    for ticker, yf_df in sorted(yf_ohlcv.items()):
        row = {f: "" for f in _FIELDS}
        row.update({"logged_at_utc": now, "scan_type": scan_type, "ticker": ticker})

        if yf_df is None or getattr(yf_df, "empty", True):
            row["note"] = "yf_missing"
            rows.append(row)
            continue

        yf_close = yf_df["Close"].dropna()
        if yf_close.empty:
            row["note"] = "yf_no_close"
            rows.append(row)
            continue
        yf_by_date = {ts.date().isoformat(): ts for ts in yf_close.index}
        yf_dates = sorted(yf_by_date)
        row["yf_first"], row["yf_last"], row["yf_bars"] = yf_dates[0], yf_dates[-1], len(yf_dates)

        sa_bars = seeking_alpha_client.get_daily_ohlcv(ticker, "1Y") or []
        sa_by_date = {b["date"]: b for b in sa_bars if b.get("date")}
        if not sa_by_date:
            row["note"] = "sa_empty"
            rows.append(row)
            continue
        sa_dates = sorted(sa_by_date)
        row["sa_first"], row["sa_last"], row["sa_bars"] = sa_dates[0], sa_dates[-1], len(sa_dates)
        row["sa_staleness_days"] = (pd.Timestamp(yf_dates[-1]) - pd.Timestamp(sa_dates[-1])).days

        common = sorted(set(yf_by_date) & set(sa_by_date))
        row["common_days"] = len(common)
        if not common:
            row["note"] = "no_common_days"
            rows.append(row)
            continue

        close_diffs, adj_diffs = [], []
        for d in common:
            yfc = float(yf_close.loc[yf_by_date[d]])
            cd = _pct(yfc, sa_by_date[d].get("close"))
            ad = _pct(yfc, sa_by_date[d].get("adj"))
            if cd is not None:
                close_diffs.append(abs(cd))
            if ad is not None:
                adj_diffs.append(abs(ad))

        last = common[-1]
        yf_row = yf_df.loc[yf_by_date[last]]
        sa_row = sa_by_date[last]
        yf_last_close = float(yf_close.loc[yf_by_date[last]])
        yf_vol = yf_row.get("Volume") if hasattr(yf_row, "get") else yf_row["Volume"]

        row["last_common_date"] = last
        row["yf_close"] = round(yf_last_close, 4)
        row["sa_close"] = sa_row.get("close")
        row["sa_adj"] = sa_row.get("adj")
        row["close_pct_diff_last"] = _pct(yf_last_close, sa_row.get("close"))
        row["adj_pct_diff_last"] = _pct(yf_last_close, sa_row.get("adj"))
        row["yf_volume"] = int(yf_vol) if pd.notna(yf_vol) else ""
        row["sa_volume"] = sa_row.get("volume")
        row["volume_pct_diff_last"] = _pct(yf_vol, sa_row.get("volume"))

        ohlc = [
            abs(x) for x in (
                _pct(yf_row["Open"], sa_row.get("open")),
                _pct(yf_row["High"], sa_row.get("high")),
                _pct(yf_row["Low"], sa_row.get("low")),
                _pct(yf_last_close, sa_row.get("close")),
            ) if x is not None
        ]
        row["ohlc_pct_diff_max_last"] = round(max(ohlc), 4) if ohlc else ""
        row["close_pct_diff_max"] = round(max(close_diffs), 4) if close_diffs else ""
        row["close_pct_diff_mean"] = round(sum(close_diffs) / len(close_diffs), 4) if close_diffs else ""
        row["adj_pct_diff_max"] = round(max(adj_diffs), 4) if adj_diffs else ""
        rows.append(row)

    return rows


def _append_rows(rows: list[dict]) -> None:
    if not rows:
        return
    _CSV_PATH.parent.mkdir(parents=True, exist_ok=True)
    write_header = not _CSV_PATH.exists()
    with open(_CSV_PATH, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=_FIELDS, extrasaction="ignore")
        if write_header:
            writer.writeheader()
        writer.writerows(rows)
