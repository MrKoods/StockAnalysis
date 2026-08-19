"""
Tests for Phase 9: data_validator and black_swan_detector.
No network calls, no disk writes tested here (write paths are covered by integration).
"""

import pandas as pd
from datetime import datetime, timezone, timedelta

from shared.utils.data_validator import (
    validate_ohlcv,
    validate_sentiment_data,
    validate_news_data,
    run_preflight_validation,
)
from shared.utils.black_swan_detector import (
    check_black_swan,
    build_black_swan_alert,
    should_resume_after_black_swan,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ohlcv(rows=5, bad_row=None):
    """Build a minimal valid OHLCV DataFrame."""
    data = {
        "Open":  [100.0] * rows,
        "High":  [105.0] * rows,
        "Low":   [98.0] * rows,
        "Close": [102.0] * rows,
        "Volume":[1_000_000] * rows,
    }
    idx = pd.date_range("2026-06-01", periods=rows, freq="B", tz="UTC")
    df = pd.DataFrame(data, index=idx)
    if bad_row is not None:
        for col, val in bad_row.items():
            df.iloc[-1, df.columns.get_loc(col)] = val
    return df


def _posts_valid(n=2):
    now = datetime.now(timezone.utc)
    return [{"sentiment": "bullish", "timestamp_utc": (now - timedelta(hours=i)).isoformat()} for i in range(n)]


def _articles_valid(n=2):
    now = datetime.now(timezone.utc)
    return [{"sentiment_score": 0.5, "timestamp_utc": (now - timedelta(hours=i)).isoformat()} for i in range(n)]


# ---------------------------------------------------------------------------
# validate_ohlcv
# ---------------------------------------------------------------------------

class TestValidateOHLCV:
    def test_valid_df_passes(self):
        ok, reasons = validate_ohlcv("NVDA", _ohlcv())
        assert ok is True
        assert reasons == []

    def test_empty_df_fails(self):
        ok, reasons = validate_ohlcv("NVDA", pd.DataFrame())
        assert ok is False
        assert any("empty" in r for r in reasons)

    def test_none_df_fails(self):
        ok, reasons = validate_ohlcv("NVDA", pd.DataFrame())
        assert ok is False

    def test_missing_columns_fails(self):
        df = _ohlcv().drop(columns=["Volume"])
        ok, reasons = validate_ohlcv("NVDA", df)
        assert ok is False
        assert any("missing_columns" in r for r in reasons)

    def test_high_less_than_low_fails(self):
        df = _ohlcv(bad_row={"High": 90.0, "Low": 98.0})
        ok, reasons = validate_ohlcv("NVDA", df)
        assert ok is False
        assert any("high_less_than_low" in r for r in reasons)

    def test_close_above_high_fails(self):
        df = _ohlcv(bad_row={"Close": 120.0, "High": 105.0})
        ok, reasons = validate_ohlcv("NVDA", df)
        assert ok is False
        assert any("close_out_of_range" in r for r in reasons)

    def test_zero_volume_fails(self):
        df = _ohlcv(bad_row={"Volume": 0})
        ok, reasons = validate_ohlcv("NVDA", df)
        assert ok is False
        assert any("volume" in r for r in reasons)

    def test_extreme_price_move_fails(self):
        df = _ohlcv()
        # Inject a 60% move on last bar
        df.iloc[-1, df.columns.get_loc("Close")] = df.iloc[-2]["Close"] * 1.60
        df.iloc[-1, df.columns.get_loc("High")] = df.iloc[-1]["Close"]
        ok, reasons = validate_ohlcv("NVDA", df, max_single_day_move_pct=0.50)
        assert ok is False
        assert any("extreme_single_day_move" in r for r in reasons)


# ---------------------------------------------------------------------------
# validate_sentiment_data
# ---------------------------------------------------------------------------

class TestValidateSentiment:
    def test_valid_posts_pass(self):
        ok, reasons = validate_sentiment_data("NVDA", _posts_valid())
        assert ok is True

    def test_empty_posts_pass(self):
        ok, reasons = validate_sentiment_data("NVDA", [])
        assert ok is True

    def test_unexpected_sentiment_value_fails(self):
        # Real StockTwits messages carry "sentiment" ('bullish'/'bearish'/None
        # from entities.sentiment.basic — see sentiment_client.py), not a
        # per-message "bullish_ratio" (that's an AGGREGATE sentiment_layer.py
        # computes from a batch of these, never a raw field — the old version
        # of this test/validator checked a field that could never actually be
        # present on real data).
        posts = [{"sentiment": "very_bullish", "timestamp_utc": datetime.now(timezone.utc).isoformat()}]
        ok, reasons = validate_sentiment_data("NVDA", posts)
        assert ok is False
        assert any("sentiment_unexpected_value" in r for r in reasons)

    def test_neutral_sentiment_none_passes(self):
        posts = [{"sentiment": None, "timestamp_utc": datetime.now(timezone.utc).isoformat()}]
        ok, reasons = validate_sentiment_data("NVDA", posts)
        assert ok is True

    def test_future_timestamp_fails(self):
        future = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
        posts = [{"sentiment": "bullish", "timestamp_utc": future}]
        ok, reasons = validate_sentiment_data("NVDA", posts)
        assert ok is False
        assert any("future_timestamp" in r for r in reasons)


# ---------------------------------------------------------------------------
# validate_news_data
# ---------------------------------------------------------------------------

class TestValidateNews:
    def test_valid_articles_pass(self):
        ok, reasons = validate_news_data("NVDA", _articles_valid())
        assert ok is True

    def test_empty_articles_pass(self):
        ok, reasons = validate_news_data("NVDA", [])
        assert ok is True

    def test_sentiment_score_out_of_range_fails(self):
        articles = [{"sentiment_score": 2.0, "timestamp_utc": datetime.now(timezone.utc).isoformat()}]
        ok, reasons = validate_news_data("NVDA", articles)
        assert ok is False
        assert any("out_of_range" in r for r in reasons)

    def test_future_news_timestamp_fails(self):
        future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        articles = [{"sentiment_score": 0.5, "timestamp_utc": future}]
        ok, reasons = validate_news_data("NVDA", articles)
        assert ok is False


# ---------------------------------------------------------------------------
# run_preflight_validation
# ---------------------------------------------------------------------------

class TestPreflightValidation:
    def test_all_valid_passes(self):
        result = run_preflight_validation("NVDA", _ohlcv(), _posts_valid(), _articles_valid())
        assert result["ticker_valid"] is True
        assert result["ohlcv_valid"] is True
        assert result["sentiment_valid"] is True
        assert result["news_valid"] is True

    def test_bad_ohlcv_fails_ticker(self):
        result = run_preflight_validation("NVDA", pd.DataFrame(), _posts_valid(), _articles_valid())
        assert result["ticker_valid"] is False
        assert result["ohlcv_valid"] is False

    def test_required_keys_present(self):
        result = run_preflight_validation("NVDA", _ohlcv(), [], [])
        for key in ("ticker_valid", "ohlcv_valid", "sentiment_valid", "news_valid", "failures"):
            assert key in result


# ---------------------------------------------------------------------------
# black_swan_detector
# ---------------------------------------------------------------------------

class TestBlackSwanDetector:
    def test_no_trigger_under_thresholds(self):
        result = check_black_swan(smh_current_pct_change=-0.03, vix_current_pct_change=0.10)
        assert result["black_swan_triggered"] is False
        assert result["trigger_type"] is None

    def test_smh_drop_triggers(self):
        result = check_black_swan(smh_current_pct_change=-0.08, vix_current_pct_change=0.10)
        assert result["black_swan_triggered"] is True
        assert result["trigger_type"] == "smh_drop"

    def test_vix_spike_triggers(self):
        result = check_black_swan(smh_current_pct_change=-0.02, vix_current_pct_change=0.45)
        assert result["black_swan_triggered"] is True
        assert result["trigger_type"] == "vix_spike"

    def test_exact_threshold_triggers(self):
        result = check_black_swan(smh_current_pct_change=-0.07, vix_current_pct_change=0.10)
        assert result["black_swan_triggered"] is True

    def test_result_required_keys(self):
        result = check_black_swan(-0.03, 0.10)
        for key in ("black_swan_triggered", "trigger_type", "smh_pct_change",
                    "vix_pct_change", "action_required"):
            assert key in result

    def test_alert_contains_ticker_info(self):
        positions = [{"ticker": "NVDA", "direction": "bullish", "entry_price": 500.0, "stop_loss": 480.0}]
        alert = build_black_swan_alert("smh_drop", positions, -0.08, 0.20)
        assert "NVDA" in alert
        assert "BLACK SWAN" in alert
        # Advisory only (product decision, see module docstring) — the alert
        # must not claim signals are suspended/blocked, since they aren't.
        assert "Advisory" in alert
        assert "SUSPEND" not in alert
        assert "BLOCKED" not in alert

    def test_alert_no_positions(self):
        alert = build_black_swan_alert("vix_spike", [], -0.03, 0.45)
        assert "No open positions" in alert

    def test_resume_requires_3_days(self):
        assert should_resume_after_black_swan(2) is False
        assert should_resume_after_black_swan(3) is True
        assert should_resume_after_black_swan(5) is True

    def test_custom_threshold_via_cfg(self):
        # config/swing_config.yaml's real key is "smh_drop_threshold_pct" —
        # the un-suffixed name below must NOT override the default (that was
        # the bug: this key was silently never read).
        cfg = {"black_swan": {"smh_drop_threshold_pct": -0.10}}
        # -8% should NOT trigger with -10% threshold
        result = check_black_swan(-0.08, 0.10, cfg=cfg)
        assert result["black_swan_triggered"] is False
