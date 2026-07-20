"""
SHARED: Centralizes every read of config/swing_config.yaml's watchlist structure
so sector-awareness lives in one place instead of being re-derived at each call site.

Reads the new `watchlist.sectors` block (sector name -> {active, benchmark,
benchmark_alt, tickers}) when present. Falls back to the legacy flat
`watchlist.tickers`/`watchlist.benchmark` keys (single implicit "semiconductors"
sector) when `watchlist.sectors` is absent, so configs and callers that haven't
been migrated yet keep working unchanged.
"""

from typing import Optional

_LEGACY_SECTOR_NAME = "semiconductors"
_LEGACY_DEFAULT_TICKERS = ["NVDA", "AMD", "AVGO", "TSM", "MU", "ASML"]
_LEGACY_DEFAULT_BENCHMARK = "SMH"


def _legacy_sectors(cfg: dict) -> dict:
    """Synthesize a single-sector `sectors` dict from the legacy flat keys."""
    wl = cfg.get("watchlist", {})
    return {
        _LEGACY_SECTOR_NAME: {
            "active": True,
            "benchmark": wl.get("benchmark", _LEGACY_DEFAULT_BENCHMARK),
            "benchmark_alt": wl.get("benchmark_alt"),
            "tickers": wl.get("tickers", list(_LEGACY_DEFAULT_TICKERS)),
        }
    }


def get_all_sectors(cfg: dict) -> dict:
    """
    Full sectors dict (active and inactive), from `watchlist.sectors` if present,
    else synthesized from the legacy flat keys.
    """
    if cfg is None:
        cfg = {}
    sectors = cfg.get("watchlist", {}).get("sectors")
    if sectors:
        return sectors
    return _legacy_sectors(cfg)


def get_active_sectors(cfg: dict) -> dict:
    """Sectors dict filtered to `active: true` only."""
    return {name: s for name, s in get_all_sectors(cfg).items() if s.get("active", False)}


def get_sector_tickers(cfg: dict, sector_name: str) -> list[str]:
    """Ticker list for one sector. Empty list if the sector doesn't exist."""
    return list(get_all_sectors(cfg).get(sector_name, {}).get("tickers", []))


def get_sector_benchmark(cfg: dict, sector_name: str) -> Optional[str]:
    """Benchmark ticker for one sector. None if the sector doesn't exist."""
    return get_all_sectors(cfg).get(sector_name, {}).get("benchmark")


def get_all_tickers(cfg: dict) -> list[str]:
    """Flattened ticker list across all ACTIVE sectors, in sector-definition order."""
    tickers: list[str] = []
    for sector in get_active_sectors(cfg).values():
        tickers.extend(sector.get("tickers", []))
    return tickers


def get_ticker_sector_map(cfg: dict) -> dict[str, str]:
    """{ticker: sector_name} across all ACTIVE sectors."""
    mapping: dict[str, str] = {}
    for name, sector in get_active_sectors(cfg).items():
        for ticker in sector.get("tickers", []):
            mapping[ticker] = name
    return mapping


def get_ticker_benchmark(cfg: dict, ticker: str) -> Optional[str]:
    """Benchmark ticker for whichever active sector `ticker` belongs to."""
    sector_name = get_ticker_sector_map(cfg).get(ticker)
    if sector_name is None:
        return None
    return get_sector_benchmark(cfg, sector_name)
