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
            "_fundamental_full": {}, "_positioning_full": {}, "_test_final_score": 85.0,
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
    config_path.write_text("watchlist:\n  tickers: [NVDA, AMD]\n", encoding="utf-8")
    db_path = tmp_path / "history.db"

    monkeypatch.setattr(pr, "CONFIG_PATH", config_path)
    monkeypatch.setattr(pr, "PAPER_TRADES_CSV", tmp_path / "paper_trades.csv")
    monkeypatch.setattr(app_db, "DEFAULT_DB_PATH", db_path)

    monkeypatch.setattr(pr, "load_config", lambda: {
        "watchlist": {"tickers": ["NVDA", "AMD"]}, "risk_reward": {}, "options_approval_level": 2,
    })
    monkeypatch.setattr(pr, "get_model_version", lambda: "v-test")
    monkeypatch.setattr(pr, "load_gate_state", lambda: {"blocks": []})
    monkeypatch.setattr(pr, "save_gate_state", lambda state: None)
    monkeypatch.setattr(pr, "is_ticker_blocked", lambda ticker, state: None)
    monkeypatch.setattr(pr, "expire_blocks", lambda *a, **k: [])

    monkeypatch.setattr(pr, "run_pipeline", lambda watchlist, benchmark=None, scan_type=None, cfg=None: _fake_indicators())
    monkeypatch.setattr(pr, "_fetch_market_context", lambda cfg: {
        "vix": 15.0, "sector_benchmark_dfs": {}, "spy_df": None, "tnx_series": None,
        "dxy_series": None, "ticker_ohlcv": {},
    })
    monkeypatch.setattr(pr, "_compute_regime_safe", lambda vix, benchmark_df: "trending_up")
    monkeypatch.setattr(pr, "_compute_macro_safe", lambda *a, **k: {"confidence_modifier": 0.0})
    monkeypatch.setattr(pr, "_compute_rotation_safe", lambda *a, **k: {"confidence_modifier": 0.0})
    monkeypatch.setattr(pr, "_compute_cross_ticker_safe", lambda *a, **k: {})
    monkeypatch.setattr(pr, "get_regime_modifiers", lambda regime, cfg: {"regime_modifier": 0.0})
    monkeypatch.setattr(pr, "get_seasonality_modifier", lambda cfg=None: {"confidence_modifier": 0.0})
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
    assert results["NVDA"]["expected_value"] == 0.03
    assert results["AMD"]["category"] == app_db.CATEGORY_NEAR_MISS
    assert results["AMD"]["composite_score"] == 85.0
    assert results["AMD"]["trade_structure"] is None

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
    monkeypatch.setattr(app_db, "DEFAULT_DB_PATH", db_path)

    monkeypatch.setattr(pr, "load_config", lambda: {
        "watchlist": {"tickers": ["NVDA"]}, "risk_reward": {}, "options_approval_level": 2,
    })
    monkeypatch.setattr(pr, "get_model_version", lambda: "v-test")
    monkeypatch.setattr(pr, "load_gate_state", lambda: {"blocks": []})
    monkeypatch.setattr(pr, "save_gate_state", lambda state: None)
    monkeypatch.setattr(pr, "is_ticker_blocked", lambda ticker, state: None)
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
    monkeypatch.setattr(pr, "_compute_rotation_safe", lambda *a, **k: {"confidence_modifier": 0.0})
    monkeypatch.setattr(pr, "_compute_cross_ticker_safe", lambda *a, **k: {})
    monkeypatch.setattr(pr, "get_regime_modifiers", lambda regime, cfg: {"regime_modifier": 0.0})
    monkeypatch.setattr(pr, "get_seasonality_modifier", lambda cfg=None: {"confidence_modifier": 0.0})
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
    monkeypatch.setattr(pr, "rank_trade_structures", lambda *a, **k: {"ranked_structures": []})
    monkeypatch.setattr(pr, "send_near_miss_alert", lambda payload, model_version: True)
    monkeypatch.setattr(pr, "send_paper_signal_alert", lambda payload, model_version: True)

    signals_logged = pr.run_paper_scan(scan_type="post_close")

    assert signals_logged == 1  # still appended to paper_trades.csv — CSV logic is unchanged
    run_id = app_db.get_latest_run_id(db_path=db_path)
    results = app_db.get_ticker_results(run_id, db_path=db_path)
    assert results[0]["category"] == app_db.CATEGORY_PASSED_NO_TRADE
    assert results[0]["trade_structure"] is None


def _run_av_cadence_scan(tmp_path, monkeypatch, scan_type: str) -> list:
    """Runs a single paper scan for NVDA with everything mocked except
    _fetch_av_news_safe (call-tracked), returning the list of tickers it was
    called for. Each call uses its own tmp_path so the "already logged today"
    dedup in run_paper_scan can't suppress a second scan_type's run."""
    config_path = tmp_path / "swing_config.yaml"
    config_path.write_text("watchlist:\n  tickers: [NVDA]\n", encoding="utf-8")
    db_path = tmp_path / "history.db"

    monkeypatch.setattr(pr, "CONFIG_PATH", config_path)
    monkeypatch.setattr(pr, "PAPER_TRADES_CSV", tmp_path / "paper_trades.csv")
    monkeypatch.setattr(app_db, "DEFAULT_DB_PATH", db_path)

    monkeypatch.setattr(pr, "load_config", lambda: {
        "watchlist": {"tickers": ["NVDA"]}, "risk_reward": {}, "options_approval_level": 2,
    })
    monkeypatch.setattr(pr, "get_model_version", lambda: "v-test")
    monkeypatch.setattr(pr, "load_gate_state", lambda: {"blocks": []})
    monkeypatch.setattr(pr, "save_gate_state", lambda state: None)
    monkeypatch.setattr(pr, "is_ticker_blocked", lambda ticker, state: None)
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
    monkeypatch.setattr(pr, "_compute_rotation_safe", lambda *a, **k: {"confidence_modifier": 0.0})
    monkeypatch.setattr(pr, "_compute_cross_ticker_safe", lambda *a, **k: {})
    monkeypatch.setattr(pr, "get_regime_modifiers", lambda regime, cfg: {"regime_modifier": 0.0})
    monkeypatch.setattr(pr, "get_seasonality_modifier", lambda cfg=None: {"confidence_modifier": 0.0})
    monkeypatch.setattr(
        pr, "get_earnings_modifier",
        lambda ticker, earnings_date, cfg=None: {"confidence_modifier": 0.0, "force_defined_risk": False},
    )
    monkeypatch.setattr(pr, "_fetch_stocktwits_safe", lambda ticker: [])
    monkeypatch.setattr(pr, "_fetch_sa_engagement_safe", lambda ticker: [])

    av_calls = []
    monkeypatch.setattr(pr, "_fetch_av_news_safe", lambda ticker: av_calls.append(ticker) or [{"title": "x"}])
    monkeypatch.setattr(pr, "_fetch_yahoo_news_safe", lambda ticker: [])
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


def test_av_news_skipped_for_pre_market(tmp_path, monkeypatch):
    av_calls = _run_av_cadence_scan(tmp_path, monkeypatch, "pre_market")
    assert av_calls == [], "AV news must be skipped for pre_market scans"


def test_av_news_fetched_for_post_close(tmp_path, monkeypatch):
    av_calls = _run_av_cadence_scan(tmp_path, monkeypatch, "post_close")
    assert av_calls == ["NVDA"], "AV news must still be fetched for post_close scans"
