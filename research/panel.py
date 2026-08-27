"""
Phase 1 — data assembly.

Builds a date x ticker panel of split/dividend-adjusted daily bars, cached to
disk so every later phase reads the same immutable dataset instead of
re-downloading (and silently re-deriving) its own. See the Storage section
below for why the cache format is pickle rather than parquet.

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

_PRICE_PANEL = config.PANEL_DIR / "prices.pkl"
_VOLUME_PANEL = config.PANEL_DIR / "dollar_volume.pkl"
_CONTEXT_PANEL = config.PANEL_DIR / "context.pkl"
_UNIVERSE_FILE = config.PANEL_DIR / "universe.csv"

_WIKI_SP500 = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"


# --------------------------------------------------------------------------
# Storage
#
# Pickle rather than parquet, for an environment reason rather than a
# preference: on this machine a Windows Application Control policy blocks
# pyarrow's native DLL ("DLL load failed while importing _fs"), and fastparquet
# fails the same way, so pandas has no usable parquet engine. Measured at full
# panel scale (5500 dates x 500 tickers, ~22 MB), uncompressed pickle writes and
# reads in ~0.01s; gzip would cut it to 4 MB but costs 23s per write.
#
# Pickle's usual objections do not apply here: the file is generated locally by
# this module, never shipped or received, and gitignored. Its real weakness is
# version fragility across pandas releases — acceptable because the cache is
# fully regenerable with `--download` and is not a source of truth.
#
# These two helpers are the only place the format is named, so swapping back to
# parquet if the policy changes is a two-line edit.
# --------------------------------------------------------------------------

def _write_frame(frame: pd.DataFrame, path) -> None:
    frame.to_pickle(path)


def _read_frame(path) -> pd.DataFrame:
    return pd.read_pickle(path)


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
            frame = _extract_symbol(raw, symbol)
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

    # Context tickers come out of BOTH panels, not just prices. Dropping them
    # from one and leaving them in the other means prices.columns and
    # dollar_volume.columns disagree, and any later `prices[volumes.columns]`
    # style alignment silently pulls SPY/^VIX into the tradeable universe.
    # (^VIX also reports a nonsense volume, being an index rather than a
    # security, so its "dollar volume" is meaningless if it survives here.)
    context_cols = [c for c in config.CONTEXT_TICKERS if c in price_panel.columns]
    context_panel = price_panel[context_cols].copy()
    price_panel = price_panel.drop(columns=context_cols, errors="ignore")
    volume_panel = volume_panel.drop(columns=config.CONTEXT_TICKERS, errors="ignore")

    config.PANEL_DIR.mkdir(parents=True, exist_ok=True)
    _write_frame(price_panel, _PRICE_PANEL)
    _write_frame(volume_panel, _VOLUME_PANEL)
    _write_frame(context_panel, _CONTEXT_PANEL)

    logger.info(
        "Cached panel: %d dates x %d tickers (%s to %s), context: %s",
        len(price_panel), price_panel.shape[1],
        price_panel.index.min().date(), price_panel.index.max().date(),
        list(context_panel.columns),
    )


def _extract_symbol(raw: pd.DataFrame, symbol: str) -> pd.DataFrame | None:
    """
    Normalize a yfinance response to a plain OHLCV frame for one symbol.

    Do not special-case a single-symbol batch: with group_by="ticker", yfinance
    returns MultiIndex columns even for a batch of one (verified against
    yfinance 1.4.1), so a "len(batch) == 1 means flat columns" shortcut hands
    back a frame whose ["Close"] raises KeyError. Branch on the actual column
    structure instead of on the batch size.
    """
    if isinstance(raw.columns, pd.MultiIndex):
        if symbol not in raw.columns.get_level_values(0):
            return None
        return raw[symbol]
    return raw


# --------------------------------------------------------------------------
# Load
# --------------------------------------------------------------------------

def load_panel(sample: str = "in", apply_exclusions: bool = True) -> dict[str, pd.DataFrame]:
    """
    Load the cached panel, sliced to a named sample window.

    sample: "in" (2005-2018) | "out" (2019-2026) | "full".

    The default is deliberately "in", the SAFE option, not "full". Phases 1-5
    must never see out-of-sample data, and a default that quietly hands it over
    is precisely the kind of footgun that produced V2's four months of backtests
    graded against the wrong population. Reaching OOS data should require typing
    it out. "out" is opened once, in Phase 6, with the rules already locked.
    """
    if not _PRICE_PANEL.exists():
        raise FileNotFoundError(
            f"No cached panel at {_PRICE_PANEL}. Run: python -m research.panel --download"
        )

    prices = _read_frame(_PRICE_PANEL)
    volumes = _read_frame(_VOLUME_PANEL)
    context = _read_frame(_CONTEXT_PANEL)

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

    excluded: list[str] = []
    if apply_exclusions:
        excluded = sorted(set(config.EXCLUDED_TICKERS) & set(prices.columns))
        if excluded:
            prices = prices.drop(columns=excluded)
            volumes = volumes.drop(columns=excluded, errors="ignore")
            logger.info(
                "Excluded %d ticker(s) with unusable vendor data: %s",
                len(excluded), ", ".join(excluded),
            )

    return {
        "prices": prices,
        "dollar_volume": volumes,
        "context": context,
        "sample": sample,
        "signal_start": start,
        "signal_end": end,
        "excluded": excluded,
    }


def detect_adjustment_anomalies(
    prices: pd.DataFrame,
    move_threshold: float = 0.40,
    min_moves: int = 3,
) -> dict[str, dict]:
    """
    Find tickers whose price series oscillates between adjusted and unadjusted
    values — the failure mode that produced this project's MNST exclusion.

    The signature is specific, which is what makes it safe to act on. A real
    corporate event (a crisis, a bankruptcy, a buyout, a biotech readout)
    produces one or a few large moves. Broken adjustment produces repeated large
    moves whose signs ALTERNATE and whose price ratios cluster near a clean
    split factor (0.5/2.0, 1/3/3.0, 0.25/4.0), because the series keeps stepping
    between the two versions of itself.

    Requiring all three conditions together — enough moves, alternating signs,
    ratios near a split factor — is what keeps 2008's genuine bank collapses and
    2020-03-09's oil crash out of the results. Verified: on the 503-name S&P 500
    panel this flags exactly one ticker.

    Returns {ticker: {n_moves, n_alternations, n_near_split_ratios, first, last}}.
    """
    import numpy as np

    returns = prices.pct_change(fill_method=None)
    large = returns.abs() > move_threshold
    split_factors = (0.5, 2.0, 1 / 3, 3.0, 0.25, 4.0)
    findings: dict[str, dict] = {}

    for ticker in prices.columns:
        moves = returns[ticker][large[ticker]].dropna()
        if len(moves) < min_moves:
            continue
        signs = np.sign(moves.to_numpy())
        alternations = int((signs[:-1] != signs[1:]).sum())
        ratios = (1.0 + moves).to_numpy()
        near_split = int(sum(
            1 for r in ratios if any(abs(r - f) < 0.08 for f in split_factors)
        ))
        if alternations >= 2 and near_split >= 2:
            findings[ticker] = {
                "n_moves": len(moves),
                "n_alternations": alternations,
                "n_near_split_ratios": near_split,
                "first": str(moves.index.min().date()),
                "last": str(moves.index.max().date()),
            }

    return findings


# --------------------------------------------------------------------------
# Verification — the Phase 1 pass bar
# --------------------------------------------------------------------------

def verify_panel() -> dict:
    """
    Structural checks on the cached panel. Reports rather than asserts, so a
    failure is legible instead of a traceback.
    """
    # Verification reads the RAW cache, exclusions not applied: the point is to
    # see what the vendor actually returned, including the names research will
    # later drop. Otherwise an excluded ticker's corruption would become
    # invisible to the very check that is supposed to find it.
    panel = load_panel("full", apply_exclusions=False)
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

    # Index AND columns must agree. Checking only the index would let a
    # context ticker survive in one panel and not the other, which silently
    # widens the tradeable universe downstream.
    report["volume_panel_index_aligned"] = bool(volumes.index.equals(prices.index))
    report["volume_panel_columns_aligned"] = bool(
        set(volumes.columns) == set(prices.columns)
    )
    report["context_leaked_into_prices"] = sorted(
        set(config.CONTEXT_TICKERS) & set(prices.columns)
    )

    # Broken split adjustment. Anything flagged here that is NOT already in
    # config.EXCLUDED_TICKERS is a new problem needing a decision, which is why
    # the two are reported separately rather than netted off.
    anomalies = detect_adjustment_anomalies(prices)
    report["adjustment_anomalies"] = sorted(anomalies)
    report["unhandled_anomalies"] = sorted(set(anomalies) - set(config.EXCLUDED_TICKERS))
    report["excluded_by_config"] = sorted(
        set(config.EXCLUDED_TICKERS) & set(prices.columns)
    )

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
