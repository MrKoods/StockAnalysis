"""
Integration test for the app_ui DB wiring added to paper_runner.py (see
App_UI_Scope.md §4 — "wrap instead of consolidate"). Every pipeline/Discord
dependency is mocked; this only verifies run_paper_scan() writes the right
scan_runs/ticker_results/layer_scores/notifications rows for a scan that
produces one trade-recommended ticker and one near-miss ticker.
"""

from app_ui import db as app_db
from paper_trading import paper_runner as pr


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
            "_fundamental_full": {}, "_positioning_full": {}, "_test_final_score": 68.0,
        },
        "MU": {
            "close": 80.0, "sma_20": 78.0, "atr_14": 1.5, "rolling_high_20": 81.0,
            "rsi_14": 50.0, "rs_zscore": 0.2, "mom_5d": 0.0, "trend_intact": True,
            "_fundamental_full": {}, "_positioning_full": {}, "_test_final_score": 55.0,
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


def test_run_paper_scan_persists_trade_and_near_miss_results(tmp_path, monkeypatch):
    config_path = tmp_path / "swing_config.yaml"
    config_path.write_text("watchlist:\n  tickers: [NVDA, AMD, MU]\n", encoding="utf-8")
    db_path = tmp_path / "history.db"

    monkeypatch.setattr(pr, "CONFIG_PATH", config_path)
    monkeypatch.setattr(pr, "PAPER_TRADES_CSV", tmp_path / "paper_trades.csv")
    # RANK_TRADES_CSV isolated too (2026-08-24) -- run_paper_scan now also
    # runs the rank track's own pass 2; without this it writes into the
    # REAL paper_trading/rank_trades.csv on every test run.
    monkeypatch.setattr(pr, "RANK_TRADES_CSV", tmp_path / "rank_trades.csv")
    monkeypatch.setattr(app_db, "DEFAULT_DB_PATH", db_path)

    monkeypatch.setattr(pr, "load_config", lambda: {
        "watchlist": {"tickers": ["NVDA", "AMD", "MU"]}, "risk_reward": {}, "options_approval_level": 2,
    })
    monkeypatch.setattr(pr, "get_model_version", lambda: "v-test")
    monkeypatch.setattr(pr, "load_gate_state", lambda: {"blocks": []})
    monkeypatch.setattr(pr, "save_gate_state", lambda state: None)
    monkeypatch.setattr(pr, "is_ticker_blocked", lambda ticker, state, direction=None: None)
    monkeypatch.setattr(pr, "expire_blocks", lambda *a, **k: [])

    monkeypatch.setattr(pr, "run_pipeline", lambda watchlist, benchmark=None, scan_type=None, cfg=None: _fake_indicators())
    monkeypatch.setattr(pr, "_fetch_market_context", lambda cfg: {
        "vix": 15.0, "sector_benchmark_dfs": {}, "spy_df": None, "tnx_series": None,
        "dxy_series": None, "ticker_ohlcv": {},
    })
    monkeypatch.setattr(pr, "_compute_regime_safe", lambda vix, benchmark_df: "trending_up")
    monkeypatch.setattr(pr, "_compute_macro_safe", lambda *a, **k: {"confidence_modifier": 0.0})
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
    monkeypatch.setattr(pr, "_fetch_av_news_safe", lambda ticker, **kw: [])
    monkeypatch.setattr(pr, "_fetch_yahoo_news_safe", lambda ticker: [])
    monkeypatch.setattr(pr, "_fetch_finnhub_news_safe", lambda ticker: [])
    monkeypatch.setattr(pr, "_fetch_earnings_safe", lambda ticker: None)
    monkeypatch.setattr(pr, "compute_sentiment_score", lambda *a, **k: {})
    monkeypatch.setattr(pr, "compute_news_score", lambda *a, **k: {"critical_events": [], "dominant_theme": ""})
    monkeypatch.setattr(pr, "compute_confidence_score", _fake_compute_confidence_score)
    monkeypatch.setattr(
        pr, "rank_trade_structures",
        lambda *a, **k: {"ranked_structures": [
            {"name": "bull_call_spread", "ev_per_dollar_risked": 0.03, "ev_per_dollar_per_day": 0.003},
        ]},
    )

    near_miss_calls = []
    trade_calls = []
    monkeypatch.setattr(pr, "send_near_miss_alert", lambda payload, model_version: near_miss_calls.append(payload) or True)
    monkeypatch.setattr(pr, "send_paper_signal_alert", lambda payload, model_version: trade_calls.append(payload) or True)

    signals_logged = pr.run_paper_scan(scan_type="post_close")

    assert signals_logged == 1  # only NVDA clears CONFIDENCE_THRESHOLD
    assert len(near_miss_calls) == 1 and near_miss_calls[0]["ticker"] == "AMD"
    assert len(trade_calls) == 1 and trade_calls[0]["ticker"] == "NVDA"

    runs = app_db.list_scan_runs(db_path=db_path)
    assert len(runs) == 1
    run_id = runs[0]["run_id"]
    assert runs[0]["scan_type"] == "post_close"
    run = app_db.get_scan_run(run_id, db_path=db_path)
    assert run["config_snapshot"] == config_path.read_text(encoding="utf-8")

    results = {r["ticker"]: r for r in app_db.get_ticker_results(run_id, db_path=db_path)}
    assert results["NVDA"]["category"] == app_db.CATEGORY_TRADE_RECOMMENDED
    assert results["NVDA"]["composite_score"] == 95.0
    assert results["NVDA"]["trade_structure"] == "bull_call_spread"
    # expected_value now persists ev_per_dollar_per_day, not ev_per_dollar_risked —
    # trade_selector.py ranks (and paper_runner.py reads ranked[0] from) the
    # per-day metric, so this must be whichever field actually drove the pick.
    assert results["NVDA"]["expected_value"] == 0.003
    assert results["AMD"]["category"] == app_db.CATEGORY_NEAR_MISS
    assert results["AMD"]["composite_score"] == 68.0
    # AMD (68) clears STRUCTURE_EVAL_DIAGNOSTIC_THRESHOLD (60) even though it's
    # below the real go-live gate (CONFIDENCE_THRESHOLD, 70) — trade_structure/
    # expected_value are recorded as research data on the near_miss row itself,
    # never surfaced as a real trade (see CHANGELOG's diagnostic-widening entry).
    assert results["AMD"]["trade_structure"] == "bull_call_spread"
    assert results["AMD"]["expected_value"] == 0.003
    # MU (55) is below even the diagnostic threshold — no structure ranking at all.
    assert results["MU"]["category"] == app_db.CATEGORY_NO_SIGNAL
    assert results["MU"]["composite_score"] == 55.0
    assert results["MU"]["trade_structure"] is None
    assert results["MU"]["expected_value"] is None

    nvda_layers = {
        s["layer_name"]: s["score"]
        for s in app_db.get_layer_scores(results["NVDA"]["result_id"], db_path=db_path)
    }
    assert set(nvda_layers) == set(pr._LAYER_SCORE_FIELDS)
    assert nvda_layers["technical"] == 30.0
    assert nvda_layers["fundamental"] == 5.0

    notifications = app_db.get_notifications(run_id=run_id, db_path=db_path)
    alert_types = {n["ticker"]: n["alert_type"] for n in notifications}
    assert alert_types["NVDA"] == "trade"
    assert alert_types["AMD"] == "near_miss"
    assert all(n["discord_status"] == "sent" for n in notifications)


def test_run_paper_scan_no_trade_when_structure_ranking_fails(tmp_path, monkeypatch):
    """A ticker that clears the threshold but finds no viable structure lands in
    passed_no_trade, not trade_recommended — and never reaches paper_trades.csv."""
    config_path = tmp_path / "swing_config.yaml"
    config_path.write_text("watchlist:\n  tickers: [NVDA]\n", encoding="utf-8")
    db_path = tmp_path / "history.db"

    monkeypatch.setattr(pr, "CONFIG_PATH", config_path)
    monkeypatch.setattr(pr, "PAPER_TRADES_CSV", tmp_path / "paper_trades.csv")
    # RANK_TRADES_CSV isolated too (2026-08-24) -- run_paper_scan now also
    # runs the rank track's own pass 2; without this it writes into the
    # REAL paper_trading/rank_trades.csv on every test run.
    monkeypatch.setattr(pr, "RANK_TRADES_CSV", tmp_path / "rank_trades.csv")
    monkeypatch.setattr(app_db, "DEFAULT_DB_PATH", db_path)

    monkeypatch.setattr(pr, "load_config", lambda: {
        "watchlist": {"tickers": ["NVDA"]}, "risk_reward": {}, "options_approval_level": 2,
    })
    monkeypatch.setattr(pr, "get_model_version", lambda: "v-test")
    monkeypatch.setattr(pr, "load_gate_state", lambda: {"blocks": []})
    monkeypatch.setattr(pr, "save_gate_state", lambda state: None)
    monkeypatch.setattr(pr, "is_ticker_blocked", lambda ticker, state, direction=None: None)
    monkeypatch.setattr(pr, "expire_blocks", lambda *a, **k: [])

    monkeypatch.setattr(pr, "run_pipeline", lambda watchlist, benchmark=None, scan_type=None, cfg=None: {
        "NVDA": _fake_indicators()["NVDA"],
    })
    monkeypatch.setattr(pr, "_fetch_market_context", lambda cfg: {
        "vix": 15.0, "sector_benchmark_dfs": {}, "spy_df": None, "tnx_series": None,
        "dxy_series": None, "ticker_ohlcv": {},
    })
    monkeypatch.setattr(pr, "_compute_regime_safe", lambda vix, benchmark_df: "trending_up")
    monkeypatch.setattr(pr, "_compute_macro_safe", lambda *a, **k: {"confidence_modifier": 0.0})
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
    monkeypatch.setattr(pr, "_fetch_av_news_safe", lambda ticker, **kw: [])
    monkeypatch.setattr(pr, "_fetch_yahoo_news_safe", lambda ticker: [])
    monkeypatch.setattr(pr, "_fetch_finnhub_news_safe", lambda ticker: [])
    monkeypatch.setattr(pr, "_fetch_earnings_safe", lambda ticker: None)
    monkeypatch.setattr(pr, "compute_sentiment_score", lambda *a, **k: {})
    monkeypatch.setattr(pr, "compute_news_score", lambda *a, **k: {"critical_events": [], "dominant_theme": ""})
    monkeypatch.setattr(pr, "compute_confidence_score", _fake_compute_confidence_score)
    monkeypatch.setattr(pr, "rank_trade_structures", lambda *a, **k: {"ranked_structures": []})
    monkeypatch.setattr(pr, "send_near_miss_alert", lambda payload, model_version: True)
    monkeypatch.setattr(pr, "send_paper_signal_alert", lambda payload, model_version: True)

    signals_logged = pr.run_paper_scan(scan_type="post_close")

    assert signals_logged == 1  # still appended to paper_trades.csv — CSV logic is unchanged
    run_id = app_db.get_latest_run_id(db_path=db_path)
    results = app_db.get_ticker_results(run_id, db_path=db_path)
    assert results[0]["category"] == app_db.CATEGORY_PASSED_NO_TRADE
    assert results[0]["trade_structure"] is None


def test_run_paper_scan_flags_ev_outlier_against_structure_history(tmp_path, monkeypatch, caplog):
    """
    Mirrors the actual MU long_strangle incident this fix exists for: seed
    long_strangle's trailing history with tightly-clustered readings (like
    AVGO/NVDA's), then have this scan's ticker come back with an EV/$/day far
    outside that cluster. paper_runner.py should compute a large ev_outlier_z,
    persist it, and log a NOTE — not silently accept the number.
    """
    import logging

    config_path = tmp_path / "swing_config.yaml"
    config_path.write_text("watchlist:\n  tickers: [NVDA]\n", encoding="utf-8")
    db_path = tmp_path / "history.db"

    monkeypatch.setattr(pr, "CONFIG_PATH", config_path)
    monkeypatch.setattr(pr, "PAPER_TRADES_CSV", tmp_path / "paper_trades.csv")
    # RANK_TRADES_CSV isolated too (2026-08-24) -- run_paper_scan now also
    # runs the rank track's own pass 2; without this it writes into the
    # REAL paper_trading/rank_trades.csv on every test run.
    monkeypatch.setattr(pr, "RANK_TRADES_CSV", tmp_path / "rank_trades.csv")
    monkeypatch.setattr(app_db, "DEFAULT_DB_PATH", db_path)

    # Seed history.db with a clean cluster of long_strangle readings from
    # "other tickers" before this scan runs — this is what a new outlier
    # reading gets compared against.
    seed_run = app_db.create_scan_run("pre_market", "cfg", db_path=db_path)
    for i, val in enumerate([1.5, 1.6, 1.7, 1.55, 1.65, 1.75, 1.62]):
        app_db.insert_ticker_result(
            seed_run, f"SEED{i}", app_db.CATEGORY_NO_SIGNAL,
            trade_structure="long_strangle", expected_value=val, db_path=db_path,
        )

    monkeypatch.setattr(pr, "load_config", lambda: {
        "watchlist": {"tickers": ["NVDA"]}, "risk_reward": {}, "options_approval_level": 2,
    })
    monkeypatch.setattr(pr, "get_model_version", lambda: "v-test")
    monkeypatch.setattr(pr, "load_gate_state", lambda: {"blocks": []})
    monkeypatch.setattr(pr, "save_gate_state", lambda state: None)
    monkeypatch.setattr(pr, "is_ticker_blocked", lambda ticker, state, direction=None: None)
    monkeypatch.setattr(pr, "expire_blocks", lambda *a, **k: [])

    monkeypatch.setattr(pr, "run_pipeline", lambda watchlist, benchmark=None, scan_type=None, cfg=None: {
        "NVDA": _fake_indicators()["NVDA"],
    })
    monkeypatch.setattr(pr, "_fetch_market_context", lambda cfg: {
        "vix": 15.0, "sector_benchmark_dfs": {}, "spy_df": None, "tnx_series": None,
        "dxy_series": None, "ticker_ohlcv": {},
    })
    monkeypatch.setattr(pr, "_compute_regime_safe", lambda vix, benchmark_df: "trending_up")
    monkeypatch.setattr(pr, "_compute_macro_safe", lambda *a, **k: {"confidence_modifier": 0.0})
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
    monkeypatch.setattr(pr, "_fetch_av_news_safe", lambda ticker, **kw: [])
    monkeypatch.setattr(pr, "_fetch_yahoo_news_safe", lambda ticker: [])
    monkeypatch.setattr(pr, "_fetch_finnhub_news_safe", lambda ticker: [])
    monkeypatch.setattr(pr, "_fetch_earnings_safe", lambda ticker: None)
    monkeypatch.setattr(pr, "compute_sentiment_score", lambda *a, **k: {})
    monkeypatch.setattr(pr, "compute_news_score", lambda *a, **k: {"critical_events": [], "dominant_theme": ""})
    monkeypatch.setattr(pr, "compute_confidence_score", _fake_compute_confidence_score)
    monkeypatch.setattr(
        pr, "rank_trade_structures",
        lambda *a, **k: {"ranked_structures": [
            # ~7x the seeded cluster — the MU-vs-AVGO/NVDA shape of anomaly.
            {"name": "long_strangle", "ev_per_dollar_risked": 12.0, "ev_per_dollar_per_day": 12.0},
        ]},
    )
    monkeypatch.setattr(pr, "send_near_miss_alert", lambda payload, model_version: True)
    monkeypatch.setattr(pr, "send_paper_signal_alert", lambda payload, model_version: True)

    with caplog.at_level(logging.INFO, logger="paper_trading.paper_runner"):
        pr.run_paper_scan(scan_type="post_close")

    run_id = app_db.get_latest_run_id(db_path=db_path)
    results = {r["ticker"]: r for r in app_db.get_ticker_results(run_id, db_path=db_path)}
    nvda = results["NVDA"]
    assert nvda["trade_structure"] == "long_strangle"
    assert nvda["ev_outlier_z"] is not None
    assert abs(nvda["ev_outlier_z"]) >= 3.5

    assert any("outlier" in record.message for record in caplog.records)


def _run_av_cadence_scan(tmp_path, monkeypatch, scan_type: str, cfg_extra: dict = None, yahoo_articles: list = None) -> list:
    """Runs a single paper scan for NVDA with everything mocked except
    _fetch_av_news_safe (call-tracked), returning the list of tickers it was
    called for. Each call uses its own tmp_path so the "already logged today"
    dedup in run_paper_scan can't suppress a second scan_type's run.

    `cfg_extra`: merged into the mocked cfg (e.g. an event_severity_gate block).
    `yahoo_articles`: overrides _fetch_yahoo_news_safe's return value — used to
    simulate a free source surfacing a headline that should trigger AV as a
    confirmation call.
    """
    config_path = tmp_path / "swing_config.yaml"
    config_path.write_text("watchlist:\n  tickers: [NVDA]\n", encoding="utf-8")
    db_path = tmp_path / "history.db"

    cfg = {
        "watchlist": {"tickers": ["NVDA"]}, "risk_reward": {}, "options_approval_level": 2,
        **(cfg_extra or {}),
    }

    monkeypatch.setattr(pr, "CONFIG_PATH", config_path)
    monkeypatch.setattr(pr, "PAPER_TRADES_CSV", tmp_path / "paper_trades.csv")
    # RANK_TRADES_CSV isolated too (2026-08-24) -- run_paper_scan now also
    # runs the rank track's own pass 2; without this it writes into the
    # REAL paper_trading/rank_trades.csv on every test run.
    monkeypatch.setattr(pr, "RANK_TRADES_CSV", tmp_path / "rank_trades.csv")
    monkeypatch.setattr(app_db, "DEFAULT_DB_PATH", db_path)

    monkeypatch.setattr(pr, "load_config", lambda: cfg)
    monkeypatch.setattr(pr, "get_model_version", lambda: "v-test")
    monkeypatch.setattr(pr, "load_gate_state", lambda: {"blocks": []})
    monkeypatch.setattr(pr, "save_gate_state", lambda state: None)
    monkeypatch.setattr(pr, "is_ticker_blocked", lambda ticker, state, direction=None: None)
    monkeypatch.setattr(pr, "expire_blocks", lambda *a, **k: [])

    monkeypatch.setattr(pr, "run_pipeline", lambda watchlist, benchmark=None, scan_type=None, cfg=None: {
        "NVDA": _fake_indicators()["NVDA"],
    })
    monkeypatch.setattr(pr, "_fetch_market_context", lambda cfg: {
        "vix": 15.0, "sector_benchmark_dfs": {}, "spy_df": None, "tnx_series": None,
        "dxy_series": None, "ticker_ohlcv": {},
    })
    monkeypatch.setattr(pr, "_compute_regime_safe", lambda vix, benchmark_df: "trending_up")
    monkeypatch.setattr(pr, "_compute_macro_safe", lambda *a, **k: {"confidence_modifier": 0.0})
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

    av_calls = []
    monkeypatch.setattr(pr, "_fetch_av_news_safe", lambda ticker, **kw: av_calls.append(ticker) or [{"title": "x"}])
    monkeypatch.setattr(pr, "_fetch_yahoo_news_safe", lambda ticker: yahoo_articles or [])
    monkeypatch.setattr(pr, "_fetch_finnhub_news_safe", lambda ticker: [])
    monkeypatch.setattr(pr, "_fetch_earnings_safe", lambda ticker: None)
    monkeypatch.setattr(pr, "compute_sentiment_score", lambda *a, **k: {})
    monkeypatch.setattr(pr, "compute_news_score", lambda *a, **k: {"critical_events": [], "dominant_theme": ""})
    monkeypatch.setattr(pr, "compute_confidence_score", _fake_compute_confidence_score)
    monkeypatch.setattr(pr, "rank_trade_structures", lambda *a, **k: {"ranked_structures": []})
    monkeypatch.setattr(pr, "send_near_miss_alert", lambda payload, model_version: True)
    monkeypatch.setattr(pr, "send_paper_signal_alert", lambda payload, model_version: True)

    pr.run_paper_scan(scan_type=scan_type)
    return av_calls


_GATE_CFG_EXTRA = {
    "event_severity_gate": {
        "enabled": True,
        "ticker_triggers": ["CEO resigns"],
        "sector_triggers": {},
        "principal_sources": [],
        "min_source_credibility": 0.0,
        "require_headline_match": True,
    },
}


def test_av_news_skipped_with_no_free_source_critical_event(tmp_path, monkeypatch):
    """AV is a confirmation tool, not a routine fetch — no scan type calls it
    absent a critical event flagged by Yahoo/Finnhub/Seeking Alpha."""
    for scan_type in ("pre_market", "post_close"):
        scan_dir = tmp_path / scan_type
        scan_dir.mkdir()
        av_calls = _run_av_cadence_scan(scan_dir, monkeypatch, scan_type, cfg_extra=_GATE_CFG_EXTRA)
        assert av_calls == [], f"AV news must be skipped for {scan_type} scans with no free-source trigger"


def test_av_news_fetched_when_free_source_flags_critical_event(tmp_path, monkeypatch):
    """AV fires as a confirmation call on ANY scan type once a free source
    (Yahoo here) surfaces a critical-severity headline — not gated by scan_type."""
    triggering_articles = [{"title": "NVDA CEO resigns amid controversy", "source_domain": "finance.yahoo.com"}]
    for scan_type in ("pre_market", "post_close"):
        scan_dir = tmp_path / scan_type
        scan_dir.mkdir()
        av_calls = _run_av_cadence_scan(
            scan_dir, monkeypatch, scan_type,
            cfg_extra=_GATE_CFG_EXTRA, yahoo_articles=triggering_articles,
        )
        assert av_calls == ["NVDA"], f"AV news must be fetched for {scan_type} scans when a free source flags a critical event"
