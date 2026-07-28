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
    monkeypatch.setattr(pr, "save_macro_state", lambda state: None)
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
