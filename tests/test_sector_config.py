"""
Tests for shared/utils/sector_config.py — centralized sector-aware config reads,
plus fallback to the legacy flat watchlist.tickers/watchlist.benchmark keys.
"""

from shared.utils.sector_config import (
    get_all_sectors,
    get_active_sectors,
    get_sector_tickers,
    get_sector_benchmark,
    get_all_tickers,
    get_ticker_sector_map,
    get_ticker_benchmark,
)


def _multi_sector_cfg() -> dict:
    return {
        "watchlist": {
            "tickers": ["NVDA", "AMD", "AVGO", "TSM", "MU", "ASML"],
            "benchmark": "SMH",
            "benchmark_alt": "SOXX",
            "sectors": {
                "semiconductors": {
                    "active": True,
                    "benchmark": "SMH",
                    "benchmark_alt": "SOXX",
                    "tickers": ["NVDA", "AMD", "AVGO", "TSM", "MU", "ASML"],
                },
                "regional_banks": {
                    "active": False,
                    "benchmark": "KRE",
                    "benchmark_alt": None,
                    "tickers": ["ZION", "KEY", "HBAN", "RF", "FITB"],
                },
            },
        }
    }


def _legacy_cfg() -> dict:
    return {
        "watchlist": {
            "tickers": ["NVDA", "AMD", "AVGO", "TSM", "MU", "ASML"],
            "benchmark": "SMH",
            "benchmark_alt": "SOXX",
        }
    }


class TestSectorsPresent:
    def test_get_all_sectors_returns_both(self):
        sectors = get_all_sectors(_multi_sector_cfg())
        assert set(sectors.keys()) == {"semiconductors", "regional_banks"}

    def test_get_active_sectors_excludes_inactive(self):
        active = get_active_sectors(_multi_sector_cfg())
        assert set(active.keys()) == {"semiconductors"}

    def test_get_sector_tickers(self):
        cfg = _multi_sector_cfg()
        assert get_sector_tickers(cfg, "semiconductors") == ["NVDA", "AMD", "AVGO", "TSM", "MU", "ASML"]
        assert get_sector_tickers(cfg, "regional_banks") == ["ZION", "KEY", "HBAN", "RF", "FITB"]

    def test_get_sector_tickers_unknown_sector_returns_empty(self):
        assert get_sector_tickers(_multi_sector_cfg(), "nonexistent") == []

    def test_get_sector_benchmark(self):
        cfg = _multi_sector_cfg()
        assert get_sector_benchmark(cfg, "semiconductors") == "SMH"
        assert get_sector_benchmark(cfg, "regional_banks") == "KRE"

    def test_get_all_tickers_only_includes_active_sectors(self):
        # regional_banks is inactive — its tickers must not appear
        tickers = get_all_tickers(_multi_sector_cfg())
        assert tickers == ["NVDA", "AMD", "AVGO", "TSM", "MU", "ASML"]
        assert "ZION" not in tickers

    def test_get_ticker_sector_map_only_active(self):
        mapping = get_ticker_sector_map(_multi_sector_cfg())
        assert mapping["NVDA"] == "semiconductors"
        assert "ZION" not in mapping

    def test_get_ticker_benchmark(self):
        assert get_ticker_benchmark(_multi_sector_cfg(), "NVDA") == "SMH"

    def test_get_ticker_benchmark_unknown_ticker_returns_none(self):
        assert get_ticker_benchmark(_multi_sector_cfg(), "UNKNOWN") is None

    def test_both_sectors_active(self):
        cfg = _multi_sector_cfg()
        cfg["watchlist"]["sectors"]["regional_banks"]["active"] = True
        active = get_active_sectors(cfg)
        assert set(active.keys()) == {"semiconductors", "regional_banks"}
        tickers = get_all_tickers(cfg)
        assert "NVDA" in tickers and "ZION" in tickers
        mapping = get_ticker_sector_map(cfg)
        assert mapping["ZION"] == "regional_banks"
        assert get_ticker_benchmark(cfg, "ZION") == "KRE"


class TestLegacyFallback:
    """No watchlist.sectors block at all — behave as a single implicit sector."""

    def test_get_all_sectors_synthesizes_one_sector(self):
        sectors = get_all_sectors(_legacy_cfg())
        assert list(sectors.keys()) == ["semiconductors"]
        assert sectors["semiconductors"]["active"] is True
        assert sectors["semiconductors"]["benchmark"] == "SMH"
        assert sectors["semiconductors"]["tickers"] == ["NVDA", "AMD", "AVGO", "TSM", "MU", "ASML"]

    def test_get_all_tickers_matches_legacy_flat_key(self):
        assert get_all_tickers(_legacy_cfg()) == ["NVDA", "AMD", "AVGO", "TSM", "MU", "ASML"]

    def test_get_ticker_benchmark_matches_legacy_flat_key(self):
        assert get_ticker_benchmark(_legacy_cfg(), "NVDA") == "SMH"

    def test_empty_cfg_uses_hardcoded_defaults(self):
        # No watchlist key at all
        tickers = get_all_tickers({})
        assert tickers == ["NVDA", "AMD", "AVGO", "TSM", "MU", "ASML"]
        assert get_ticker_benchmark({}, "NVDA") == "SMH"

    def test_none_cfg_does_not_raise(self):
        assert get_all_tickers(None) == ["NVDA", "AMD", "AVGO", "TSM", "MU", "ASML"]
