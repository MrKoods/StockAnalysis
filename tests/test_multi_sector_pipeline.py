"""
Tests for multi-sector support added across sector_config.py, run_swing_model.py,
paper_runner.py, event_gate.py, and news_layer.py.

Covers the specific correctness properties the multi-sector refactor exists to
guarantee: each sector gets its own benchmark/regime/rotation data, event-gate
sector-wide blocks only cover the triggering sector's tickers (not the whole
multi-sector watchlist), and the real config file's watchlist still resolves
to a single active sector today (regional_banks stays inactive until the
live-activation phase).
"""

from unittest.mock import patch

import pandas as pd

from shared.utils.sector_config import get_active_sectors, get_all_tickers
from shared.utils.event_gate import add_block, is_ticker_blocked, SCOPE_SECTOR, SCOPE_TICKER
from swing_model.news_layer import compute_news_score, classify_severity as news_classify_severity


def _multi_sector_cfg() -> dict:
    return {
        "watchlist": {
            "sectors": {
                "semiconductors": {
                    "active": True, "benchmark": "SMH", "benchmark_alt": "SOXX",
                    "tickers": ["NVDA", "AMD"],
                },
                "regional_banks": {
                    "active": True, "benchmark": "KRE", "benchmark_alt": None,
                    "tickers": ["ZION", "KEY"],
                },
            },
        },
        "event_severity_gate": {
            "enabled": True,
            "sector_triggers": {
                "semiconductors": ["chip ban", "export restriction"],
                "regional_banks": ["bank failure", "FDIC receivership"],
            },
            "ticker_triggers": ["CEO resigns"],
            "principal_sources": [],
            "min_source_credibility": 0.0,
        },
    }


class TestRealConfigBothSectorsActive:
    """
    Sanity check on the real config file itself: as of v2.2.10 both sectors
    are active for paper trading (regional_banks flipped from false to true).
    This class exists to catch exactly this kind of drift — if it ever fails,
    someone changed watchlist.sectors.*.active without updating this test's
    expectations, which is worth noticing either way.
    """

    def test_real_config_has_both_sectors_active(self):
        import yaml
        cfg = yaml.safe_load(open("config/swing_config.yaml").read())
        active = get_active_sectors(cfg)
        assert set(active.keys()) == {"semiconductors", "regional_banks"}

    def test_real_config_watchlist_includes_both_sectors(self):
        import yaml
        cfg = yaml.safe_load(open("config/swing_config.yaml").read())
        tickers = get_all_tickers(cfg)
        assert tickers == ["NVDA", "AMD", "AVGO", "TSM", "MU", "ASML", "ZION", "KEY", "HBAN", "RF", "FITB"]


class TestFetchMarketContextPerSector:
    def test_fetches_every_active_sector_benchmark(self):
        from swing_model.run_swing_model import _fetch_market_context

        cfg = _multi_sector_cfg()
        smh_df = pd.DataFrame({"Close": [100.0, 101.0]})
        kre_df = pd.DataFrame({"Close": [50.0, 49.0]})
        spy_df = pd.DataFrame({"Close": [400.0, 401.0]})
        fake_ohlcv = {
            "NVDA": pd.DataFrame({"Close": [1.0]}), "AMD": pd.DataFrame({"Close": [1.0]}),
            "ZION": pd.DataFrame({"Close": [1.0]}), "KEY": pd.DataFrame({"Close": [1.0]}),
            "SMH": smh_df, "KRE": kre_df, "SPY": spy_df,
        }

        with patch("swing_model.run_swing_model.fetch_ohlcv_batch", return_value=fake_ohlcv), \
             patch("swing_model.run_swing_model.fetch_vix", return_value=15.0), \
             patch("swing_model.run_swing_model.fetch_treasury_yield", return_value=None), \
             patch("swing_model.run_swing_model.fetch_dxy", return_value=None):
            mkt = _fetch_market_context(cfg)

        assert set(mkt["sector_benchmark_dfs"].keys()) == {"semiconductors", "regional_banks"}
        assert mkt["sector_benchmark_dfs"]["semiconductors"] is smh_df
        assert mkt["sector_benchmark_dfs"]["regional_banks"] is kre_df
        assert mkt["spy_df"] is spy_df

    def test_single_sector_cfg_fetches_only_smh(self):
        from swing_model.run_swing_model import _fetch_market_context

        cfg = {"watchlist": {"tickers": ["NVDA"], "benchmark": "SMH"}}
        smh_df = pd.DataFrame({"Close": [100.0]})
        spy_df = pd.DataFrame({"Close": [400.0]})
        fake_ohlcv = {"NVDA": pd.DataFrame({"Close": [1.0]}), "SMH": smh_df, "SPY": spy_df}

        with patch("swing_model.run_swing_model.fetch_ohlcv_batch", return_value=fake_ohlcv), \
             patch("swing_model.run_swing_model.fetch_vix", return_value=15.0), \
             patch("swing_model.run_swing_model.fetch_treasury_yield", return_value=None), \
             patch("swing_model.run_swing_model.fetch_dxy", return_value=None):
            mkt = _fetch_market_context(cfg)

        assert set(mkt["sector_benchmark_dfs"].keys()) == {"semiconductors"}
        assert mkt["sector_benchmark_dfs"]["semiconductors"] is smh_df


class TestEventGateSectorIsolation:
    """The bug this session found: a sector-wide block must only cover its
    own sector's tickers, not every ticker across every sector."""

    def test_sector_wide_block_does_not_cover_other_sectors_tickers(self):
        state = {"blocks": []}
        state = add_block(
            state, tickers=["NVDA", "AMD"], scope=SCOPE_SECTOR,
            trigger_headline="chip ban announced", trigger_match="chip ban",
            source="Reuters", event_timestamp_utc="2026-01-01T00:00:00+00:00",
        )
        # Semiconductor tickers are blocked...
        assert is_ticker_blocked("NVDA", state) is not None
        assert is_ticker_blocked("AMD", state) is not None
        # ...but a bank ticker, not in this block's tickers list, must not be.
        assert is_ticker_blocked("ZION", state) is None
        assert is_ticker_blocked("KEY", state) is None

    def test_two_independent_sector_blocks_stay_isolated(self):
        state = {"blocks": []}
        state = add_block(
            state, tickers=["NVDA", "AMD"], scope=SCOPE_SECTOR,
            trigger_headline="chip ban", trigger_match="chip ban",
            source="Reuters", event_timestamp_utc="2026-01-01T00:00:00+00:00",
        )
        state = add_block(
            state, tickers=["ZION", "KEY"], scope=SCOPE_SECTOR,
            trigger_headline="regional bank contagion fears", trigger_match="bank failure",
            source="Reuters", event_timestamp_utc="2026-01-02T00:00:00+00:00",
        )
        semi_block = is_ticker_blocked("NVDA", state)
        bank_block = is_ticker_blocked("ZION", state)
        assert semi_block is not None and semi_block["trigger_match"] == "chip ban"
        assert bank_block is not None and bank_block["trigger_match"] == "bank failure"
        assert semi_block["id"] != bank_block["id"]


class TestNewsLayerSectorScopedTriggers:
    def test_chip_ban_headline_critical_for_semiconductor_sector(self):
        result = news_classify_severity(
            {"title": "New chip ban targets exports", "source_domain": "Reuters"},
            _multi_sector_cfg(), sector="semiconductors",
        )
        assert result["severity"] == "critical"
        assert result["scope"] == SCOPE_SECTOR

    def test_chip_ban_headline_not_critical_for_bank_sector(self):
        # Same headline, but scored for a bank ticker — must NOT trigger the
        # semiconductor-specific "chip ban" keyword.
        result = news_classify_severity(
            {"title": "New chip ban targets exports", "source_domain": "Reuters"},
            _multi_sector_cfg(), sector="regional_banks",
        )
        assert result["severity"] == "normal"

    def test_bank_failure_headline_critical_for_bank_sector_not_semis(self):
        cfg = _multi_sector_cfg()
        bank_result = news_classify_severity(
            {"title": "Regional bank failure sparks contagion fears", "source_domain": "Reuters"},
            cfg, sector="regional_banks",
        )
        semi_result = news_classify_severity(
            {"title": "Regional bank failure sparks contagion fears", "source_domain": "Reuters"},
            cfg, sector="semiconductors",
        )
        assert bank_result["severity"] == "critical"
        assert semi_result["severity"] == "normal"

    def test_compute_news_score_threads_sector_into_critical_events(self):
        import datetime
        now = datetime.datetime.now(datetime.timezone.utc)
        articles = [{
            "title": "New chip ban targets exports",
            "source_domain": "Reuters",
            "timestamp_utc": now.isoformat(),
        }]
        cfg = _multi_sector_cfg()
        # Scored as a semiconductor ticker: the chip-ban headline should
        # register as a sector-wide critical event.
        result = compute_news_score(articles, [], "NVDA", cfg, reference_date=now, sector="semiconductors")
        assert len(result["critical_events"]) == 1
        # Scored as a bank ticker: the same headline must not.
        result_bank = compute_news_score(articles, [], "ZION", cfg, reference_date=now, sector="regional_banks")
        assert len(result_bank["critical_events"]) == 0
