"""
End-to-end smoke test of the LIVE paper-trading pipeline (paper_runner.run_paper_scan)
with two active sectors, everything external mocked (no real API calls, no real
Discord sends). This is the thing backtesting can't verify — backtest_engine.py's
_simulate_test_signals() never calls run_pipeline()/_fetch_market_context() at all,
it's an independent simulation, so the only way to confirm the actual multi-sector
plumbing (sector loop, per-sector benchmark routing, DB sector tagging, portfolio
caps) works end to end is to run the real pipeline function with fakes standing in
for yfinance/StockTwits/Alpha Vantage/Discord.
"""

from app_ui import db as app_db
from paper_trading import paper_runner as pr


def _two_sector_cfg():
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
        "portfolio": {
            "max_simultaneous_risk_pct": 0.03,
            "max_total_open_positions": 4,
            "sectors": {
                "semiconductors": {"max_open_positions": 2, "correlated_groups": [["NVDA", "AMD"]]},
                "regional_banks": {"max_open_positions": 2, "correlated_groups": [["ZION", "KEY"]]},
            },
        },
        "risk_reward": {},
        "options_approval_level": 2,
    }


def _fake_indicators():
    return {
        "NVDA": {
            "close": 100.0, "sma_20": 95.0, "atr_14": 2.0, "rolling_high_20": 101.0,
            "rsi_14": 60.0, "rs_zscore": 1.0, "mom_5d": 0.02, "trend_intact": True,
            "_fundamental_full": {}, "_positioning_full": {}, "_test_final_score": 95.0,
        },
        "AMD": {
            "close": 50.0, "sma_20": 48.0, "atr_14": 1.0, "rolling_high_20": 51.0,
            "rsi_14": 55.0, "rs_zscore": 0.5, "mom_5d": 0.01, "trend_intact": True,
            "_fundamental_full": {}, "_positioning_full": {}, "_test_final_score": 40.0,
        },
        "ZION": {
            "close": 60.0, "sma_20": 58.0, "atr_14": 1.5, "rolling_high_20": 61.0,
            "rsi_14": 58.0, "rs_zscore": 0.8, "mom_5d": 0.015, "trend_intact": True,
            "_fundamental_full": {}, "_positioning_full": {}, "_test_final_score": 92.0,
        },
        "KEY": {
            "close": 20.0, "sma_20": 19.0, "atr_14": 0.5, "rolling_high_20": 20.5,
            "rsi_14": 50.0, "rs_zscore": 0.2, "mom_5d": 0.005, "trend_intact": True,
            "_fundamental_full": {}, "_positioning_full": {}, "_test_final_score": 30.0,
        },
    }


def _fake_compute_confidence_score(
    technical, positioning, sentiment, news,
    regime_modifier, sector_rotation_modifier, earnings_modifier, cross_ticker_modifier,
    seasonality_modifier, macro_modifier, cfg=None, regime=None, fundamental=None,
    event_gate_blocked=False, event_gate_trigger=None, **_kwargs,
):
    fs = technical.get("_test_final_score", 0.0)
    return {
        "final_score": fs, "direction": "bullish",
        "technical_total": 30.0, "positioning_total": 15.0, "sentiment_total": 10.0,
        "news_total": 10.0, "fundamental_score": 5.0,
        "regime_modifier": 0.0, "sector_rotation_modifier": 0.0, "earnings_modifier": 0.0,
        "cross_ticker_modifier": 0.0, "seasonality_modifier": 0.0, "macro_modifier": 0.0,
        "total_modifier": 0.0, "base_score": fs,
        "event_gate_blocked": event_gate_blocked, "event_gate_trigger": event_gate_trigger,
        "fundamental_data_quality": "ok",
    }


def test_two_sectors_flow_through_the_real_pipeline_and_tag_correctly(tmp_path, monkeypatch):
    """
    NVDA (semis) scores 95 -> trade recommended. ZION (banks) scores 92 -> trade
    recommended. AMD/KEY score below threshold -> no_signal/near_miss. Verifies:
    - run_pipeline() gets called once per sector with that sector's own tickers
    - every ticker_results row lands with the correct sector tag
    - a semis trade and a bank trade can coexist (portfolio caps are per-sector)
    """
    config_path = tmp_path / "swing_config.yaml"
    config_path.write_text("watchlist:\n  tickers: [NVDA, AMD, ZION, KEY]\n", encoding="utf-8")
    db_path = tmp_path / "history.db"

    monkeypatch.setattr(pr, "CONFIG_PATH", config_path)
    monkeypatch.setattr(pr, "PAPER_TRADES_CSV", tmp_path / "paper_trades.csv")
    # RANK_TRADES_CSV isolated too (2026-08-24) -- run_paper_scan now also
    # runs the rank track's own pass 2; without this it writes into the
    # REAL paper_trading/rank_trades.csv on every test run.
    monkeypatch.setattr(pr, "RANK_TRADES_CSV", tmp_path / "rank_trades.csv")
    monkeypatch.setattr(app_db, "DEFAULT_DB_PATH", db_path)

    cfg = _two_sector_cfg()
    monkeypatch.setattr(pr, "load_config", lambda: cfg)
    monkeypatch.setattr(pr, "get_model_version", lambda: "v-test")
    monkeypatch.setattr(pr, "load_gate_state", lambda: {"blocks": []})
    monkeypatch.setattr(pr, "save_gate_state", lambda state: None)
    monkeypatch.setattr(pr, "is_ticker_blocked", lambda ticker, state: None)
    monkeypatch.setattr(pr, "expire_blocks", lambda *a, **k: [])

    run_pipeline_calls = []

    def _fake_run_pipeline(tickers, benchmark=None, scan_type=None, cfg=None):
        run_pipeline_calls.append((tuple(tickers), benchmark))
        all_ind = _fake_indicators()
        return {t: all_ind[t] for t in tickers if t in all_ind}

    monkeypatch.setattr(pr, "run_pipeline", _fake_run_pipeline)
    monkeypatch.setattr(pr, "_fetch_market_context", lambda cfg: {
        "vix": 15.0,
        "sector_benchmark_dfs": {"semiconductors": None, "regional_banks": None},
        "spy_df": None, "tnx_series": None, "dxy_series": None, "ticker_ohlcv": {},
    })
    monkeypatch.setattr(pr, "_compute_regime_safe", lambda vix, benchmark_df: "trending_up")
    monkeypatch.setattr(pr, "_compute_macro_safe", lambda *a, **k: {"confidence_modifier": 0.0})
    # Avoids a real Yahoo News fetch — semiconductors is an active sector in
    # this test's cfg, so _compute_china_tension_count would otherwise run
    # for real (see run_swing_model.py's main()/paper_runner.py's equivalent).
    monkeypatch.setattr(pr, "_compute_china_tension_count", lambda cfg: 0)
    monkeypatch.setattr(pr, "save_macro_state", lambda state: None)
    monkeypatch.setattr(pr, "_compute_rotation_safe", lambda *a, **k: {"confidence_modifier": 0.0})
    monkeypatch.setattr(pr, "_compute_cross_ticker_safe", lambda *a, **k: {})
    monkeypatch.setattr(pr, "get_regime_modifiers", lambda regime, cfg, **k: {"regime_modifier": 0.0})
    monkeypatch.setattr(pr, "get_seasonality_modifier", lambda cfg=None, sector=None: {"confidence_modifier": 0.0})
    monkeypatch.setattr(
        pr, "get_earnings_modifier",
        lambda ticker, earnings_date, cfg=None: {"confidence_modifier": 0.0, "force_defined_risk": False},
    )
    monkeypatch.setattr(pr, "_fetch_stocktwits_safe", lambda ticker: [])
    monkeypatch.setattr(pr, "_fetch_sa_engagement_safe", lambda ticker: [])
    monkeypatch.setattr(pr, "_fetch_av_news_safe", lambda ticker: [])
    monkeypatch.setattr(pr, "_fetch_yahoo_news_safe", lambda ticker: [])
    monkeypatch.setattr(pr, "_fetch_finnhub_news_safe", lambda ticker: [])
    monkeypatch.setattr(pr, "_fetch_earnings_safe", lambda ticker: None)
    monkeypatch.setattr(pr, "compute_sentiment_score", lambda *a, **k: {})
    monkeypatch.setattr(pr, "compute_news_score", lambda *a, **k: {"critical_events": [], "dominant_theme": ""})
    monkeypatch.setattr(pr, "compute_confidence_score", _fake_compute_confidence_score)
    monkeypatch.setattr(
        pr, "rank_trade_structures",
        lambda *a, **k: {"ranked_structures": [{"name": "bull_call_spread", "ev_per_dollar_risked": 0.03}]},
    )
    monkeypatch.setattr(pr, "send_near_miss_alert", lambda payload, model_version: True)
    monkeypatch.setattr(pr, "send_paper_signal_alert", lambda payload, model_version: True)

    signals_logged = pr.run_paper_scan(scan_type="post_close")

    # --- run_pipeline was called once per sector, with that sector's own tickers/benchmark ---
    assert len(run_pipeline_calls) == 2
    calls_by_benchmark = {benchmark: tickers for tickers, benchmark in run_pipeline_calls}
    assert set(calls_by_benchmark["SMH"]) == {"NVDA", "AMD"}
    assert set(calls_by_benchmark["KRE"]) == {"ZION", "KEY"}

    # --- both sectors produced a qualifying trade ---
    assert signals_logged == 2

    # --- every ticker_results row is tagged with the correct sector ---
    run_id = app_db.get_latest_run_id(db_path=db_path)
    results = {r["ticker"]: r for r in app_db.get_ticker_results(run_id, db_path=db_path)}
    assert set(results.keys()) == {"NVDA", "AMD", "ZION", "KEY"}
    assert results["NVDA"]["sector"] == "semiconductors"
    assert results["AMD"]["sector"] == "semiconductors"
    assert results["ZION"]["sector"] == "regional_banks"
    assert results["KEY"]["sector"] == "regional_banks"

    # --- a semis trade and a bank trade coexisted (per-sector caps, not one shared pool) ---
    assert results["NVDA"]["category"] == app_db.CATEGORY_TRADE_RECOMMENDED
    assert results["ZION"]["category"] == app_db.CATEGORY_TRADE_RECOMMENDED


def _one_sector_cfg():
    return {
        "watchlist": {
            "sectors": {
                "semiconductors": {
                    "active": True, "benchmark": "SMH", "benchmark_alt": "SOXX",
                    "tickers": ["NVDA"],
                },
            },
        },
        "portfolio": {
            "max_simultaneous_risk_pct": 0.03,
            "max_total_open_positions": 2,
            "sectors": {"semiconductors": {"max_open_positions": 2, "correlated_groups": []}},
        },
        "risk_reward": {},
        "options_approval_level": 2,
    }


def test_open_position_critical_event_fires_immediate_alert(tmp_path, monkeypatch):
    """
    run_swing_model.py fires an immediate alert when a critical news event hits
    an already-open position, without waiting for the daily rescore —
    paper_runner.py had no equivalent at all until this fix (found while
    reviewing pipeline duplication between the two, 2026-08-19). Uses the same
    real-pipeline-with-fakes harness as the multi-sector test above, but with
    one ticker already open in paper_trades.csv and one critical event
    returned from the (faked) news layer.
    """
    config_path = tmp_path / "swing_config.yaml"
    config_path.write_text("watchlist:\n  tickers: [NVDA]\n", encoding="utf-8")
    db_path = tmp_path / "history.db"
    trades_csv = tmp_path / "paper_trades.csv"
    trades_csv.write_text("ticker,outcome\nNVDA,\n", encoding="utf-8")  # open (blank outcome)

    monkeypatch.setattr(pr, "CONFIG_PATH", config_path)
    monkeypatch.setattr(pr, "PAPER_TRADES_CSV", trades_csv)
    monkeypatch.setattr(pr, "RANK_TRADES_CSV", tmp_path / "rank_trades.csv")
    monkeypatch.setattr(app_db, "DEFAULT_DB_PATH", db_path)

    cfg = _one_sector_cfg()
    monkeypatch.setattr(pr, "load_config", lambda: cfg)
    monkeypatch.setattr(pr, "get_model_version", lambda: "v-test")
    monkeypatch.setattr(pr, "load_gate_state", lambda: {"blocks": []})
    monkeypatch.setattr(pr, "save_gate_state", lambda state: None)
    monkeypatch.setattr(pr, "is_ticker_blocked", lambda ticker, state: None)
    monkeypatch.setattr(pr, "expire_blocks", lambda *a, **k: [])

    monkeypatch.setattr(pr, "run_pipeline", lambda tickers, benchmark=None, scan_type=None, cfg=None: {
        "NVDA": _fake_indicators()["NVDA"],
    })
    monkeypatch.setattr(pr, "_fetch_market_context", lambda cfg: {
        "vix": 15.0, "sector_benchmark_dfs": {"semiconductors": None},
        "spy_df": None, "tnx_series": None, "dxy_series": None, "ticker_ohlcv": {},
    })
    monkeypatch.setattr(pr, "_compute_regime_safe", lambda vix, benchmark_df: "trending_up")
    monkeypatch.setattr(pr, "_compute_macro_safe", lambda *a, **k: {"confidence_modifier": 0.0})
    monkeypatch.setattr(pr, "_compute_china_tension_count", lambda cfg: 0)
    monkeypatch.setattr(pr, "save_macro_state", lambda state: None)
    monkeypatch.setattr(pr, "_compute_rotation_safe", lambda *a, **k: {"confidence_modifier": 0.0})
    monkeypatch.setattr(pr, "_compute_cross_ticker_safe", lambda *a, **k: {})
    monkeypatch.setattr(pr, "get_regime_modifiers", lambda regime, cfg, **k: {"regime_modifier": 0.0})
    monkeypatch.setattr(pr, "get_seasonality_modifier", lambda cfg=None, sector=None: {"confidence_modifier": 0.0})
    monkeypatch.setattr(
        pr, "get_earnings_modifier",
        lambda ticker, earnings_date, cfg=None: {"confidence_modifier": 0.0, "force_defined_risk": False},
    )
    monkeypatch.setattr(pr, "_fetch_stocktwits_safe", lambda ticker: [])
    monkeypatch.setattr(pr, "_fetch_sa_engagement_safe", lambda ticker: [])
    monkeypatch.setattr(pr, "_fetch_av_news_safe", lambda ticker: [])
    monkeypatch.setattr(pr, "_fetch_yahoo_news_safe", lambda ticker: [])
    monkeypatch.setattr(pr, "_fetch_finnhub_news_safe", lambda ticker: [])
    monkeypatch.setattr(pr, "_fetch_earnings_safe", lambda ticker: None)
    monkeypatch.setattr(pr, "compute_sentiment_score", lambda *a, **k: {})

    critical_event = {
        "headline": "NVDA CEO resigns amid controversy",
        "source": "reuters.com",
        "scope": "ticker",
        "trigger_match": "CEO resigns",
        "ner_sentiment": "bearish",
        "event_timestamp_utc": "2026-08-19T00:00:00+00:00",
    }
    monkeypatch.setattr(
        pr, "compute_news_score",
        lambda *a, **k: {"critical_events": [critical_event], "dominant_narrative_theme": "none"},
    )
    monkeypatch.setattr(pr, "compute_confidence_score", _fake_compute_confidence_score)
    monkeypatch.setattr(
        pr, "rank_trade_structures",
        lambda *a, **k: {"ranked_structures": [{"name": "bull_call_spread", "ev_per_dollar_risked": 0.03}]},
    )
    monkeypatch.setattr(pr, "send_near_miss_alert", lambda payload, model_version: True)
    monkeypatch.setattr(pr, "send_paper_signal_alert", lambda payload, model_version: True)

    alert_calls = []
    monkeypatch.setattr(
        pr, "_handle_open_position_critical_event",
        lambda position, event, model_version: alert_calls.append((position, event, model_version)),
    )

    pr.run_paper_scan(scan_type="post_close")

    assert len(alert_calls) == 1
    position, event, model_version = alert_calls[0]
    assert position["ticker"] == "NVDA"
    assert event["trigger_match"] == "CEO resigns"
    assert model_version == "v-test"


def test_greeks_filter_status_round_trips_into_paper_trades_csv(tmp_path, monkeypatch):
    """
    trade_selector.rank_trade_structures()'s own greeks_filter_status
    computation is well tested (tests/test_phase7_trade_math.py), but nothing
    previously confirmed the wiring that actually persists it: paper_runner.py
    reads it off the TOP-LEVEL rank_trade_structures() return dict (not
    nested inside a ranked structure) and writes it into paper_trades.csv.
    Every existing full-pipeline test mocks rank_trade_structures() without a
    top-level "greeks_filter_status" key at all, so trade_result.get(...)
    silently returns None -> "" in every one of them — a column-alignment or
    key-name regression in that specific wiring wouldn't be caught by any of
    them (2026-08-23 full model audit finding).
    """
    config_path = tmp_path / "swing_config.yaml"
    config_path.write_text("watchlist:\n  tickers: [NVDA]\n", encoding="utf-8")
    db_path = tmp_path / "history.db"
    trades_csv = tmp_path / "paper_trades.csv"

    monkeypatch.setattr(pr, "CONFIG_PATH", config_path)
    monkeypatch.setattr(pr, "PAPER_TRADES_CSV", trades_csv)
    monkeypatch.setattr(pr, "RANK_TRADES_CSV", tmp_path / "rank_trades.csv")
    monkeypatch.setattr(app_db, "DEFAULT_DB_PATH", db_path)

    cfg = _one_sector_cfg()
    monkeypatch.setattr(pr, "load_config", lambda: cfg)
    monkeypatch.setattr(pr, "get_model_version", lambda: "v-test")
    monkeypatch.setattr(pr, "load_gate_state", lambda: {"blocks": []})
    monkeypatch.setattr(pr, "save_gate_state", lambda state: None)
    monkeypatch.setattr(pr, "is_ticker_blocked", lambda ticker, state: None)
    monkeypatch.setattr(pr, "expire_blocks", lambda *a, **k: [])

    monkeypatch.setattr(pr, "run_pipeline", lambda tickers, benchmark=None, scan_type=None, cfg=None: {
        "NVDA": _fake_indicators()["NVDA"],
    })
    monkeypatch.setattr(pr, "_fetch_market_context", lambda cfg: {
        "vix": 15.0, "sector_benchmark_dfs": {"semiconductors": None},
        "spy_df": None, "tnx_series": None, "dxy_series": None, "ticker_ohlcv": {},
    })
    monkeypatch.setattr(pr, "_compute_regime_safe", lambda vix, benchmark_df: "trending_up")
    monkeypatch.setattr(pr, "_compute_macro_safe", lambda *a, **k: {"confidence_modifier": 0.0})
    monkeypatch.setattr(pr, "_compute_china_tension_count", lambda cfg: 0)
    monkeypatch.setattr(pr, "save_macro_state", lambda state: None)
    monkeypatch.setattr(pr, "_compute_rotation_safe", lambda *a, **k: {"confidence_modifier": 0.0})
    monkeypatch.setattr(pr, "_compute_cross_ticker_safe", lambda *a, **k: {})
    monkeypatch.setattr(pr, "get_regime_modifiers", lambda regime, cfg, **k: {"regime_modifier": 0.0})
    monkeypatch.setattr(pr, "get_seasonality_modifier", lambda cfg=None, sector=None: {"confidence_modifier": 0.0})
    monkeypatch.setattr(
        pr, "get_earnings_modifier",
        lambda ticker, earnings_date, cfg=None: {"confidence_modifier": 0.0, "force_defined_risk": False},
    )
    monkeypatch.setattr(pr, "_fetch_stocktwits_safe", lambda ticker: [])
    monkeypatch.setattr(pr, "_fetch_sa_engagement_safe", lambda ticker: [])
    monkeypatch.setattr(pr, "_fetch_av_news_safe", lambda ticker: [])
    monkeypatch.setattr(pr, "_fetch_yahoo_news_safe", lambda ticker: [])
    monkeypatch.setattr(pr, "_fetch_finnhub_news_safe", lambda ticker: [])
    monkeypatch.setattr(pr, "_fetch_earnings_safe", lambda ticker: None)
    monkeypatch.setattr(pr, "compute_sentiment_score", lambda *a, **k: {})
    monkeypatch.setattr(pr, "compute_news_score", lambda *a, **k: {"critical_events": [], "dominant_theme": ""})
    monkeypatch.setattr(pr, "compute_confidence_score", _fake_compute_confidence_score)
    monkeypatch.setattr(
        pr, "rank_trade_structures",
        lambda *a, **k: {
            "ranked_structures": [{"name": "long_call", "ev_per_dollar_risked": 0.05}],
            # The real field under test — a top-level key on the returned
            # dict, not nested inside a ranked structure (see
            # paper_runner.py's `trade_result.get("greeks_filter_status")`).
            "greeks_filter_status": "not_implemented_no_options_chain_data",
        },
    )
    monkeypatch.setattr(pr, "send_near_miss_alert", lambda payload, model_version: True)
    monkeypatch.setattr(pr, "send_paper_signal_alert", lambda payload, model_version: True)

    signals_logged = pr.run_paper_scan(scan_type="post_close")
    assert signals_logged == 1

    import csv
    with open(trades_csv, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 1
    assert rows[0]["ticker"] == "NVDA"
    assert rows[0]["greeks_filter_status"] == "not_implemented_no_options_chain_data"


def test_ticker_scan_error_is_visible_not_silent(tmp_path, monkeypatch):
    """
    2026-08-24 full model audit: an uncaught exception anywhere in one
    ticker's ~720-line per-ticker scoring block used to leave ZERO trace
    beyond a single logger.error() line — no validation-log entry, no DB
    row, invisible in the same dashboard every other ticker's outcome shows
    up in. Injects a real exception (compute_confidence_score raises for
    AMD, succeeds normally for NVDA — both in the same scan) and asserts
    the failure is now visible two ways without taking down the rest of the
    scan: a validation_log.csv-style entry (via write_validation_entry,
    monkeypatched here to capture calls directly rather than parsing a real
    CSV) and a CATEGORY_SCAN_ERROR ticker_results DB row — while NVDA is
    scored and logged completely normally, unaffected by AMD's failure.
    """
    config_path = tmp_path / "swing_config.yaml"
    config_path.write_text("watchlist:\n  tickers: [NVDA, AMD]\n", encoding="utf-8")
    db_path = tmp_path / "history.db"

    monkeypatch.setattr(pr, "CONFIG_PATH", config_path)
    monkeypatch.setattr(pr, "PAPER_TRADES_CSV", tmp_path / "paper_trades.csv")
    monkeypatch.setattr(pr, "RANK_TRADES_CSV", tmp_path / "rank_trades.csv")
    monkeypatch.setattr(app_db, "DEFAULT_DB_PATH", db_path)

    cfg = {
        "watchlist": {
            "sectors": {
                "semiconductors": {
                    "active": True, "benchmark": "SMH", "benchmark_alt": "SOXX",
                    "tickers": ["NVDA", "AMD"],
                },
            },
        },
        "portfolio": {
            "max_simultaneous_risk_pct": 0.03,
            "max_total_open_positions": 4,
            "sectors": {"semiconductors": {"max_open_positions": 2, "correlated_groups": []}},
        },
        "risk_reward": {},
        "options_approval_level": 2,
    }
    monkeypatch.setattr(pr, "load_config", lambda: cfg)
    monkeypatch.setattr(pr, "get_model_version", lambda: "v-test")
    monkeypatch.setattr(pr, "load_gate_state", lambda: {"blocks": []})
    monkeypatch.setattr(pr, "save_gate_state", lambda state: None)
    monkeypatch.setattr(pr, "is_ticker_blocked", lambda ticker, state: None)
    monkeypatch.setattr(pr, "expire_blocks", lambda *a, **k: [])

    monkeypatch.setattr(
        pr, "run_pipeline",
        lambda tickers, benchmark=None, scan_type=None, cfg=None: {
            t: v for t, v in _fake_indicators().items() if t in tickers
        },
    )
    monkeypatch.setattr(pr, "_fetch_market_context", lambda cfg: {
        "vix": 15.0, "sector_benchmark_dfs": {"semiconductors": None},
        "spy_df": None, "tnx_series": None, "dxy_series": None, "ticker_ohlcv": {},
    })
    monkeypatch.setattr(pr, "_compute_regime_safe", lambda vix, benchmark_df: "trending_up")
    monkeypatch.setattr(pr, "_compute_macro_safe", lambda *a, **k: {"confidence_modifier": 0.0})
    monkeypatch.setattr(pr, "_compute_china_tension_count", lambda cfg: 0)
    monkeypatch.setattr(pr, "save_macro_state", lambda state: None)
    monkeypatch.setattr(pr, "_compute_rotation_safe", lambda *a, **k: {"confidence_modifier": 0.0})
    monkeypatch.setattr(pr, "_compute_cross_ticker_safe", lambda *a, **k: {})
    monkeypatch.setattr(pr, "get_regime_modifiers", lambda regime, cfg, **k: {"regime_modifier": 0.0})
    monkeypatch.setattr(pr, "get_seasonality_modifier", lambda cfg=None, sector=None: {"confidence_modifier": 0.0})
    monkeypatch.setattr(
        pr, "get_earnings_modifier",
        lambda ticker, earnings_date, cfg=None: {"confidence_modifier": 0.0, "force_defined_risk": False},
    )
    monkeypatch.setattr(pr, "_fetch_stocktwits_safe", lambda ticker: [])
    monkeypatch.setattr(pr, "_fetch_sa_engagement_safe", lambda ticker: [])
    monkeypatch.setattr(pr, "_fetch_av_news_safe", lambda ticker: [])
    monkeypatch.setattr(pr, "_fetch_yahoo_news_safe", lambda ticker: [])
    monkeypatch.setattr(pr, "_fetch_finnhub_news_safe", lambda ticker: [])
    monkeypatch.setattr(pr, "_fetch_earnings_safe", lambda ticker: None)
    monkeypatch.setattr(pr, "compute_sentiment_score", lambda *a, **k: {})
    monkeypatch.setattr(pr, "compute_news_score", lambda *a, **k: {"critical_events": [], "dominant_theme": ""})

    def _raise_for_amd(technical, *a, **k):
        if technical.get("_test_final_score") == 40.0:  # AMD's fixture marker
            raise RuntimeError("injected scoring failure")
        return _fake_compute_confidence_score(technical, *a, **k)

    monkeypatch.setattr(pr, "compute_confidence_score", _raise_for_amd)
    monkeypatch.setattr(
        pr, "rank_trade_structures",
        lambda *a, **k: {"ranked_structures": [{"name": "bull_call_spread", "ev_per_dollar_risked": 0.03}]},
    )
    monkeypatch.setattr(pr, "send_near_miss_alert", lambda payload, model_version: True)
    monkeypatch.setattr(pr, "send_paper_signal_alert", lambda payload, model_version: True)

    validation_entries = []
    monkeypatch.setattr(
        pr, "write_validation_entry",
        lambda ticker, failure_type, detail: validation_entries.append((ticker, failure_type, detail)),
    )

    signals_logged = pr.run_paper_scan(scan_type="post_close")

    # --- NVDA (95, above threshold) unaffected by AMD's failure ---
    assert signals_logged == 1
    run_id = app_db.get_latest_run_id(db_path=db_path)
    results = {r["ticker"]: r for r in app_db.get_ticker_results(run_id, db_path=db_path)}
    assert results["NVDA"]["category"] == app_db.CATEGORY_TRADE_RECOMMENDED

    # --- AMD's failure is now visible two ways instead of vanishing silently ---
    assert len(validation_entries) == 1
    amd_ticker, failure_type, detail = validation_entries[0]
    assert amd_ticker == "AMD"
    assert failure_type == "paper_runner_scan_error"
    assert "injected scoring failure" in detail

    assert results["AMD"]["category"] == app_db.CATEGORY_SCAN_ERROR


def test_rank_track_picks_top_n_per_sector_regardless_of_threshold(tmp_path, monkeypatch):
    """
    Rank-based parallel paper-trading track (2026-08-24 full model audit
    strategy pivot) — end-to-end via the same real-pipeline-with-fakes
    harness as the tests above. Both tickers in the sector score well below
    CONFIDENCE_THRESHOLD (70) AND below STRUCTURE_EVAL_DIAGNOSTIC_THRESHOLD
    (60, so the main loop never computes a structure for either) — the
    whole point of this track is that it still produces a real, funded pick
    on a day like this. With top_n_per_sector=1, only the higher-scoring
    ticker (NVDA, 45) should be picked over the lower one (AMD, 30), logged
    to rank_trades.csv with a real (non-$0) capital_deployed and a computed
    entry/stop/target — never to paper_trades.csv (neither clears 70), and
    never as a ticker_results/layer_scores DB row (rank-track picks are
    CSV + Discord only, see _run_rank_track's own docstring).
    """
    config_path = tmp_path / "swing_config.yaml"
    config_path.write_text("watchlist:\n  tickers: [NVDA, AMD]\n", encoding="utf-8")
    db_path = tmp_path / "history.db"
    trades_csv = tmp_path / "paper_trades.csv"
    rank_csv = tmp_path / "rank_trades.csv"

    monkeypatch.setattr(pr, "CONFIG_PATH", config_path)
    monkeypatch.setattr(pr, "PAPER_TRADES_CSV", trades_csv)
    monkeypatch.setattr(pr, "RANK_TRADES_CSV", rank_csv)
    monkeypatch.setattr(app_db, "DEFAULT_DB_PATH", db_path)

    cfg = {
        "watchlist": {
            "sectors": {
                "semiconductors": {
                    "active": True, "benchmark": "SMH", "benchmark_alt": "SOXX",
                    "tickers": ["NVDA", "AMD"],
                },
            },
        },
        "portfolio": {
            "max_simultaneous_risk_pct": 0.03,
            "max_total_open_positions": 4,
            "sectors": {"semiconductors": {"max_open_positions": 2, "correlated_groups": []}},
        },
        "rank_track": {"top_n_per_sector": 1},
        "risk_reward": {},
        "options_approval_level": 2,
    }
    monkeypatch.setattr(pr, "load_config", lambda: cfg)
    monkeypatch.setattr(pr, "get_model_version", lambda: "v-test")
    monkeypatch.setattr(pr, "load_gate_state", lambda: {"blocks": []})
    monkeypatch.setattr(pr, "save_gate_state", lambda state: None)
    monkeypatch.setattr(pr, "is_ticker_blocked", lambda ticker, state: None)
    monkeypatch.setattr(pr, "expire_blocks", lambda *a, **k: [])

    def _low_score_indicators():
        base = _fake_indicators()
        base["NVDA"]["_test_final_score"] = 45.0
        base["AMD"]["_test_final_score"] = 30.0
        return base

    monkeypatch.setattr(
        pr, "run_pipeline",
        lambda tickers, benchmark=None, scan_type=None, cfg=None: {
            t: v for t, v in _low_score_indicators().items() if t in tickers
        },
    )
    monkeypatch.setattr(pr, "_fetch_market_context", lambda cfg: {
        "vix": 15.0, "sector_benchmark_dfs": {"semiconductors": None},
        "spy_df": None, "tnx_series": None, "dxy_series": None, "ticker_ohlcv": {},
    })
    monkeypatch.setattr(pr, "_compute_regime_safe", lambda vix, benchmark_df: "trending_up")
    monkeypatch.setattr(pr, "_compute_macro_safe", lambda *a, **k: {"confidence_modifier": 0.0})
    monkeypatch.setattr(pr, "_compute_china_tension_count", lambda cfg: 0)
    monkeypatch.setattr(pr, "save_macro_state", lambda state: None)
    monkeypatch.setattr(pr, "_compute_rotation_safe", lambda *a, **k: {"confidence_modifier": 0.0})
    monkeypatch.setattr(pr, "_compute_cross_ticker_safe", lambda *a, **k: {})
    monkeypatch.setattr(pr, "get_regime_modifiers", lambda regime, cfg, **k: {"regime_modifier": 0.0})
    monkeypatch.setattr(pr, "get_seasonality_modifier", lambda cfg=None, sector=None: {"confidence_modifier": 0.0})
    monkeypatch.setattr(
        pr, "get_earnings_modifier",
        lambda ticker, earnings_date, cfg=None: {"confidence_modifier": 0.0, "force_defined_risk": False},
    )
    monkeypatch.setattr(pr, "_fetch_stocktwits_safe", lambda ticker: [])
    monkeypatch.setattr(pr, "_fetch_sa_engagement_safe", lambda ticker: [])
    monkeypatch.setattr(pr, "_fetch_av_news_safe", lambda ticker: [])
    monkeypatch.setattr(pr, "_fetch_yahoo_news_safe", lambda ticker: [])
    monkeypatch.setattr(pr, "_fetch_finnhub_news_safe", lambda ticker: [])
    monkeypatch.setattr(pr, "_fetch_earnings_safe", lambda ticker: None)
    monkeypatch.setattr(pr, "compute_sentiment_score", lambda *a, **k: {})
    monkeypatch.setattr(pr, "compute_news_score", lambda *a, **k: {"critical_events": [], "dominant_theme": ""})
    monkeypatch.setattr(pr, "compute_confidence_score", _fake_compute_confidence_score)
    # Both below STRUCTURE_EVAL_DIAGNOSTIC_THRESHOLD (60) -> the main loop
    # never calls rank_trade_structures for either -> this fake is ONLY
    # ever exercised by the rank track's own _build_rank_track_row.
    monkeypatch.setattr(
        pr, "rank_trade_structures",
        lambda *a, **k: {
            "ranked_structures": [
                {"name": "long_call", "ev_per_dollar_per_day": 0.01, "recommended": True,
                 "capital_required": 100.0, "position_type": "options"},
            ],
            "greeks_filter_status": None,
        },
    )
    monkeypatch.setattr(pr, "send_near_miss_alert", lambda payload, model_version: True)
    monkeypatch.setattr(pr, "send_paper_signal_alert", lambda payload, model_version=None, track="threshold": True)

    signals_logged = pr.run_paper_scan(scan_type="post_close")

    # --- neither ticker cleared 70, so nothing hit the threshold track ---
    assert signals_logged == 0
    assert not trades_csv.exists()

    # --- rank track picked exactly 1 (top_n_per_sector=1): NVDA (45 > 30) ---
    assert rank_csv.exists()
    import csv as csv_module
    with open(rank_csv, newline="", encoding="utf-8") as f:
        rank_rows = list(csv_module.DictReader(f))
    assert len(rank_rows) == 1
    assert rank_rows[0]["ticker"] == "NVDA"
    assert rank_rows[0]["confidence"] == "45.0"

    # --- real, funded position -- not a $0 phantom row ---
    assert float(rank_rows[0]["capital_deployed"]) > 0.0
    assert float(rank_rows[0]["position_size"]) > 0
    assert rank_rows[0]["entry_price"] != ""
    assert rank_rows[0]["stop_loss"] != ""
    assert rank_rows[0]["structure_recommended"] == "long_call"

    # --- rank track never touched the app UI dashboard DB (CSV + Discord
    # only) -- NVDA (the rank-track pick) and AMD both still get their
    # normal sub-threshold DB row from the MAIN loop (both score below
    # NEAR_MISS_THRESHOLD=65 -> CATEGORY_NO_SIGNAL), completely unaffected
    # by the rank track; neither is CATEGORY_TRADE_RECOMMENDED, confirming
    # the rank-track pick didn't create or overwrite a "real trade" DB row.
    run_id = app_db.get_latest_run_id(db_path=db_path)
    results = {r["ticker"]: r for r in app_db.get_ticker_results(run_id, db_path=db_path)}
    assert results["NVDA"]["category"] == app_db.CATEGORY_NO_SIGNAL
    assert results["AMD"]["category"] == app_db.CATEGORY_NO_SIGNAL
