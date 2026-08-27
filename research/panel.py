"""
Phase 1 — data assembly.

Builds a date x ticker panel of split/dividend-adjusted daily bars, cached to
parquet so every later phase reads the same immutable dataset instead of
re-downloading (and silently re-deriving) its own.

Known, accepted limitation — survivorship bias. The universe is the *current*
S&P 500 membership, so names that were dropped from the index (usually after
poor performance) are absent from the whole history. This inflates any long-only
result, momentum included. It is accepted deliberately for the first read
because point-in-time membership data is slow to source and there is no point
paying for it before knowing whether the signal exists at all. It is a Phase 6
upgrade, and until then every result carries this caveat in RESEARCH_LOG.md.

Usage:
    python -m research.panel --download      # fetch and cache (slow, network)
    python -m research.panel --verify        # reconcile the cached panel
"""

from __future__ import annotations

import argparse
import io
import sys
import time

import pandas as pd

from research import config
from shared.utils.logger import get_logger

logger = get_logger(__name__)

_PRICE_PANEL = config.PANEL_DIR / "prices.parquet"
_VOLUME_PANEL = config.PANEL_DIR / "dollar_volume.parquet"
_CONTEXT_PANEL = config.PANEL_DIR / "context.parquet"
_UNIVERSE_FILE = config.PANEL_DIR / "universe.csv"

_WIKI_SP500 = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"


# --------------------------------------------------------------------------
# Universe
# --------------------------------------------------------------------------

def fetch_universe() -> list[str]:
    """
    Current S&P 500 constituents. Cached to universe.csv on first fetch so the
    panel is reproducible even if the index changes between runs — the cached
    file, not the live web page, is the dataset of record.
    """
    if _UNIVERSE_FILE.exists():
        tickers = pd.read_csv(_UNIVERSE_FILE)["ticker"].tolist()
        logger.info("Universe loaded from cache: %d tickers", len(tickers))
        return tickers

    import requests

    logger.info("Fetching S&P 500 constituents from Wikipedia")
    response = requests.get(_WIKI_SP500, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
    response.raise_for_status()
    table = pd.read_html(io.StringIO(response.text))[0]

    # yfinance uses '-' where the index uses '.' for share classes (BRK.B -> BRK-B).
    tickers = sorted(table["Symbol"].astype(str).str.replace(".", "-", regex=False).tolist())

    config.PANEL_DIR.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({"ticker": tickers}).to_csv(_UNIVERSE_FILE, index=False)
    logger.info("Universe cached: %d tickers", len(tickers))
    return tickers


# --------------------------------------------------------------------------
# Download
# --------------------------------------------------------------------------

def download_panel(tickers: list[str] | None = None, batch_size: int = 50) -> None:
    """
    Download adjusted daily bars for the universe plus context tickers, and
    cache three aligned frames: adjusted close, dollar volume, and context.

    auto_adjust=True gives split- and dividend-adjusted prices, which is what a
    total-return momentum calculation requires. Note this adjusts the *whole
    history* using all known corporate actions, which is correct for computing
    returns but means the price at a past date is not the price that was
    displayed on that date. Momentum is a function of returns, so this is fine;
    anything that keys off a price *level* (a round-number threshold, a dollar
    stop) would need unadjusted data.
    """
    import yfinance as yf

    tickers = tickers or fetch_universe()
    all_symbols = tickers + config.CONTEXT_TICKERS
    logger.info("Downloading %d symbols, %s to %s", len(all_symbols), config.DATA_START, config.OUT_OF_SAMPLE_END)

    closes: dict[str, pd.Series] = {}
    dollar_volumes: dict[str, pd.Series] = {}

    for start in range(0, len(all_symbols), batch_size):
        batch = all_symbols[start:start + batch_size]
        logger.info("Batch %d-%d of %d", start + 1, min(start + batch_size, len(all_symbols)), len(all_symbols))

        raw = yf.download(
            batch,
            start=config.DATA_START,
            end=config.OUT_OF_SAMPLE_END,
            interval="1d",
            auto_adjust=True,
            progress=False,
            group_by="ticker",
            threads=True,
        )
        if raw is None or raw.empty:
            logger.warning("Batch returned no data: %s", batch)
            continue

        for symbol in batch:
            frame = _extract_symbol(raw, symbol, len(batch))
            if frame is None or frame.empty:
                logger.warning("No data for %s", symbol)
                continue
            close = frame["Close"].dropna()
            if close.empty:
                continue
            closes[symbol] = close
            if "Volume" in frame:
                dollar_volumes[symbol] = (frame["Close"] * frame["Volume"]).dropna()

        time.sleep(1.0)  # be polite to the endpoint between batches

    if not closes:
        raise RuntimeError("Download produced no usable data — nothing cached.")

    price_panel = pd.DataFrame(closes).sort_index()
    volume_panel = pd.DataFrame(dollar_volumes).sort_index()

    context_cols = [c for c in config.CONTEXT_TICKERS if c in price_panel.columns]
    context_panel = price_panel[context_cols].copy()
    price_panel = price_panel.drop(columns=context_cols, errors="ignore")

    config.PANEL_DIR.mkdir(parents=True, exist_ok=True)
    price_panel.to_parquet(_PRICE_PANEL)
    volume_panel.to_parquet(_VOLUME_PANEL)
    context_panel.to_parquet(_CONTEXT_PANEL)

    logger.info(
        "Cached panel: %d dates x %d tickers (%s to %s), context: %s",
        len(price_panel), price_panel.shape[1],
        price_panel.index.min().date(), price_panel.index.max().date(),
        list(context_panel.columns),
    )


def _extract_symbol(raw: pd.DataFrame, symbol: str, batch_len: int) -> pd.DataFrame | None:
    """
    yfinance returns a flat frame for a single symbol and a MultiIndex-columned
    frame for several — normalize both to a plain OHLCV frame.
    """
    if batch_len == 1:
        return raw
    if isinstance(raw.columns, pd.MultiIndex):
        if symbol not in raw.columns.get_level_values(0):
            return None
        return raw[symbol]
    return raw


# --------------------------------------------------------------------------
# Load
# --------------------------------------------------------------------------

def load_panel(sample: str = "full") -> dict[str, pd.DataFrame]:
    """
    Load the cached panel, sliced to a named sample window.

    sample: "in" (2005-2018) | "out" (2019-2026) | "full".

    Phases 1-5 pass sample="in" and nothing else. "out" is opened once, in
    Phase 6, with the rules already locked.
    """
    if not _PRICE_PANEL.exists():
        raise FileNotFoundError(
            f"No cached panel at {_PRICE_PANEL}. Run: python -m research.panel --download"
        )

    prices = pd.read_parquet(_PRICE_PANEL)
    volumes = pd.read_parquet(_VOLUME_PANEL)
    context = pd.read_parquet(_CONTEXT_PANEL)

    if sample == "in":
        start, end = config.IN_SAMPLE_START, config.IN_SAMPLE_END
    elif sample == "out":
        start, end = config.OUT_OF_SAMPLE_START, config.OUT_OF_SAMPLE_END
    elif sample == "full":
        start, end = config.DATA_START, config.OUT_OF_SAMPLE_END
    else:
        raise ValueError(f"sample must be 'in', 'out' or 'full', got {sample!r}")

    # Formation windows need history from before the sample starts, so prices
    # are NOT truncated at the left edge here — callers slice signals, not
    # inputs. The right edge is a hard cut: no data after the sample end is
    # visible, which is what prevents look-ahead.
    prices = prices.loc[:end]
    volumes = volumes.loc[:end]
    context = context.loc[:end]

    return {
        "prices": prices,
        "dollar_volume": volumes,
        "context": context,
        "sample": sample,
        "signal_start": start,
        "signal_end": end,
    }


# --------------------------------------------------------------------------
# Verification — the Phase 1 pass bar
# --------------------------------------------------------------------------

def verify_panel() -> dict:
    """
    Structural checks on the cached panel. Reports rather than asserts, so a
    failure is legible instead of a traceback.
    """
    panel = load_panel("full")
    prices, volumes = panel["prices"], panel["dollar_volume"]
    report: dict = {}

    report["n_dates"] = len(prices)
    report["n_tickers"] = prices.shape[1]
    report["date_range"] = (str(prices.index.min().date()), str(prices.index.max().date()))
    report["context_tickers"] = list(panel["context"].columns)

    # Coverage: how much of the history each name actually has. Names added to
    # the index recently will legitimately be sparse; a *widespread* shortfall
    # means the download failed.
    coverage = prices.notna().sum() / len(prices)
    report["median_coverage"] = round(float(coverage.median()), 4)
    report["tickers_under_50pct_coverage"] = int((coverage < 0.5).sum())

    # A duplicated or unsorted index silently corrupts every rolling window.
    report["duplicate_dates"] = int(prices.index.duplicated().sum())
    report["index_monotonic"] = bool(prices.index.is_monotonic_increasing)

    # Non-positive prices break log returns and ratio math.
    report["non_positive_prices"] = int((prices <= 0).sum().sum())

    # Adjusted data should have no single-day move beyond roughly +/-50%. A
    # cluster of these usually means an unadjusted split slipped through.
    daily_returns = prices.pct_change(fill_method=None)
    report["extreme_daily_moves"] = int((daily_returns.abs() > 0.5).sum().sum())

    report["volume_panel_aligned"] = bool(volumes.index.equals(prices.index))

    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Phase 1 — build and verify the price panel")
    parser.add_argument("--download", action="store_true", help="fetch and cache the panel (slow)")
    parser.add_argument("--verify", action="store_true", help="run structural checks on the cached panel")
    args = parser.parse_args(argv)

    if not args.download and not args.verify:
        parser.print_help()
        return 1

    if args.download:
        download_panel()

    if args.verify:
        report = verify_panel()
        width = max(len(k) for k in report)
        print("\nPanel verification")
        print("-" * (width + 30))
        for key, value in report.items():
            print(f"{key:<{width}}  {value}")
        print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
