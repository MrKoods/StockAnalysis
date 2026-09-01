"""Tests for the V3 deep-analysis pipeline (deep_analysis/)."""

from __future__ import annotations

import json
from contextlib import contextmanager

import pytest

from deep_analysis import collect as collect_mod
from deep_analysis.collect import collect_findings
from deep_analysis.prompts import build_user_prompt
from deep_analysis.render import DISCLAIMER, render_report
from deep_analysis.synthesize import SynthesisError, synthesize


# --------------------------------------------------------------------------- #
# Fakes                                                                        #
# --------------------------------------------------------------------------- #

_INDICATORS = {
    "close": 100.0, "sma_20": 95.0, "sma_50": 90.0, "rsi_14": 60.0, "atr_14": 2.0,
    "rs_zscore": 0.5, "trend_intact": True, "breakout_confirmed": False,
    "breakdown_confirmed": False, "downtrend_intact": False,
    "_fundamental_full": {"fundamental_score": 4.0, "data_quality": "complete", "data_as_of": "2026-08-28"},
    "_positioning_full": {"positioning_score_total": 11.0},
    "_positioning_full_bearish": {"positioning_score_total": 6.0},
}


@pytest.fixture
def patched_feeds(monkeypatch):
    """Patch every external fetch in deep_analysis.collect with canned data."""
    monkeypatch.setattr(collect_mod, "run_pipeline", lambda *a, **k: {"NVDA": dict(_INDICATORS)})
    monkeypatch.setattr(collect_mod, "fetch_stocktwits", lambda *a, **k: [{"sentiment": "bullish"}] * 40)
    monkeypatch.setattr(collect_mod, "fetch_seeking_alpha_engagement", lambda *a, **k: [])
    monkeypatch.setattr(collect_mod, "fetch_news_yahoo", lambda *a, **k: [
        {"title": "Chipmaker beats on revenue", "source": "yahoo", "timestamp_utc": "2026-08-30T12:00:00Z"},
    ])
    monkeypatch.setattr(collect_mod, "fetch_news_finnhub", lambda *a, **k: [])
    monkeypatch.setattr(collect_mod, "fetch_recent_8k_filings", lambda *a, **k: [])
    monkeypatch.setattr(collect_mod, "fetch_news_alpha_vantage", lambda *a, **k: [])
    monkeypatch.setattr(collect_mod, "fetch_ohlcv_batch", lambda *a, **k: {})
    monkeypatch.setattr(collect_mod, "fetch_vix_and_pct_change", lambda *a, **k: (18.0, -0.01))
    monkeypatch.setattr(collect_mod, "fetch_treasury_yield_10y", lambda *a, **k: None)
    monkeypatch.setattr(collect_mod, "fetch_usd_strength", lambda *a, **k: None)
    monkeypatch.setattr(collect_mod, "fetch_earnings_calendar", lambda *a, **k: {"next_earnings_date": "2026-11-19"})


class _FakeBlock:
    def __init__(self, text):
        self.type = "text"
        self.text = text


class _FakeMessage:
    def __init__(self, text="## Snapshot\nA briefing.", stop_reason="end_turn"):
        self.content = [_FakeBlock(text)] if text else []
        self.stop_reason = stop_reason
        self.stop_details = "policy" if stop_reason == "refusal" else None
        self.model = "claude-opus-5"
        self.usage = type("U", (), {"input_tokens": 1234, "output_tokens": 5678})()


class _FakeClient:
    def __init__(self, message):
        self._message = message
        self.captured = {}
        outer = self

        class _Messages:
            @contextmanager
            def stream(self, **kwargs):
                outer.captured = kwargs
                yield type("S", (), {"get_final_message": lambda _self: outer._message})()

        self.messages = _Messages()


# --------------------------------------------------------------------------- #
# collect                                                                      #
# --------------------------------------------------------------------------- #

def test_collect_findings_shape(patched_feeds):
    f = collect_findings("nvda", benchmark="SMH", sector="semiconductors", deep=False)

    assert f["ticker"] == "NVDA"
    assert f["direction"] in ("bullish", "bearish")
    assert f["benchmark"] == "SMH"
    assert set(["technical", "fundamental", "positioning", "sentiment", "news", "macro", "score"]).issubset(f)
    assert f["sentiment"]["stocktwits_message_count"] == 40
    assert f["news"]["source_counts"]["yahoo"] == 1
    assert any(h["title"] == "Chipmaker beats on revenue" for h in f["news"]["headlines"])
    # macro series were both None -> layer flagged as not on real data
    assert f["data_quality"]["layers_on_real_data"]["macro"] is False
    assert f["data_quality"]["layers_on_real_data"]["technical"] is True
    assert f["earnings"]["next_earnings_date"].startswith("2026-11-19")
    # whole bundle must be JSON-serializable with the default=str fallback
    json.dumps(f, default=str)


def test_collect_findings_records_feed_failure(patched_feeds, monkeypatch):
    def _boom(*a, **k):
        raise OSError("connection reset")

    monkeypatch.setattr(collect_mod, "fetch_news_yahoo", _boom)
    f = collect_findings("NVDA", benchmark="SMH", sector="semiconductors", deep=False)
    assert any("Yahoo news" in d for d in f["data_quality"]["degraded"])


def test_collect_findings_deep_wiring(patched_feeds, monkeypatch):
    """With deep=True, collect calls each analyze_* and nests the result."""
    def _fake(name):
        return lambda *a, **k: {"summary": {"n": name}, "detail": {}, "observations": [f"{name} obs"],
                                "data_quality": "complete"}

    monkeypatch.setattr(collect_mod, "load_price_frames", lambda *a, **k: {"ticker_daily": None})
    for layer in ("technical", "fundamental", "sentiment", "news", "positioning", "macro"):
        monkeypatch.setattr(collect_mod, f"analyze_{layer}", _fake(layer))

    f = collect_findings("NVDA", benchmark="SMH", sector="semiconductors", deep=True)
    assert set(f["deep"]) == {"technical", "fundamental", "sentiment", "news", "positioning", "macro"}
    assert f["deep"]["technical"]["observations"] == ["technical obs"]
    assert f["data_quality"]["deep_layer_quality"]["macro"] == "complete"


def test_analyze_technical_synthetic():
    import numpy as np
    import pandas as pd

    from deep_analysis.layers._prices import to_weekly
    from deep_analysis.layers.technical import analyze_technical

    idx = pd.date_range("2024-01-01", periods=400, freq="B", tz="UTC")
    rng = np.random.default_rng(7)
    close = np.abs(100 + np.cumsum(rng.normal(0.05, 1.0, len(idx)))) + 10
    df = pd.DataFrame(
        {"Open": close * 0.99, "High": close * 1.02, "Low": close * 0.98, "Close": close,
         "Volume": rng.integers(1_000_000, 5_000_000, len(idx))},
        index=idx,
    )
    bench = df.assign(Close=50 + np.cumsum(rng.normal(0.02, 0.5, len(idx))))
    frames = {"ticker_daily": df, "ticker_weekly": to_weekly(df), "benchmark_daily": bench, "spy_daily": bench}

    res = analyze_technical("TEST", "SMH", frames=frames)
    assert res["data_quality"] in ("complete", "partial")
    assert res["summary"]["rsi_14"] is not None
    assert res["detail"]["ma_stack"]["alignment"] in ("bullish", "bearish", "mixed")
    assert res["detail"]["structure"]["nearest_support"] is not None
    assert len(res["observations"]) >= 5


def test_fundamental_pick_stitches_by_recency():
    from deep_analysis.layers.fundamental import _pick

    facts = {
        "Revenues": [  # retired tag — deep history, stops in 2020
            {"start": "2019-01-01", "end": "2019-03-31", "val": 100.0, "duration_days": 89},
            {"start": "2020-01-01", "end": "2020-03-31", "val": 110.0, "duration_days": 90},
        ],
        "RevenueFromContractWithCustomerExcludingAssessedTax": [  # current tag
            {"start": "2025-01-01", "end": "2025-03-31", "val": 900.0, "duration_days": 89},
            {"start": "2026-01-01", "end": "2026-03-31", "val": 1200.0, "duration_days": 89},
        ],
    }
    merged = _pick(facts, ["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues"])
    assert merged[0]["end"] == "2019-03-31"   # old history kept
    assert merged[-1]["end"] == "2026-03-31"  # current tag wins the tail
    assert merged[-1]["val"] == 1200.0


def test_fundamental_yoy_date_matched_across_gap():
    from deep_analysis.layers.fundamental import _yoy

    # Q4 stub missing between 2025-10 and 2026-04 — a fixed 4-back offset would
    # compare the wrong quarters; date-matching lands on ~1 year earlier.
    series = [
        {"end": "2025-04-26", "val": 26.0},
        {"end": "2025-07-27", "val": 30.0},
        {"end": "2025-10-26", "val": 35.0},
        {"end": "2026-04-26", "val": 44.0},
        {"end": "2026-07-26", "val": 46.0},
    ]
    # latest 2026-07-26 vs ~2025-07-27 (val 30) -> (46-30)/30
    assert _yoy(series) == pytest.approx((46 - 30) / 30, abs=1e-3)


def test_positioning_insider_view_reconciles_sources():
    from deep_analysis.layers.positioning import _insider_view

    # yfinance empty, Finnhub MSPR strongly negative, 24 Form 4 filings
    v = _insider_view([], [{"mspr": -100.0}], [{"form": "4"}] * 24)
    assert v["transaction_rows"] == 0
    assert v["net_value"] is None            # not a fake $0
    assert v["mspr_latest"] == -100.0
    assert v["form4_filings_120d"] == 24
    assert "selling pressure" in v["read"]
    assert v["note"] is not None


def test_macro_uses_passed_in_rotation_state(monkeypatch):
    import deep_analysis.layers.macro as macro_mod

    for fn in ("fetch_treasury_yield_10y", "fetch_usd_strength", "fetch_federal_funds_rate", "fetch_cpi"):
        monkeypatch.setattr(macro_mod, fn, lambda *a, **k: None)
    monkeypatch.setattr(macro_mod, "fetch_vix_and_pct_change", lambda *a, **k: (14.0, 0.01))
    monkeypatch.setattr(macro_mod, "get_seasonality_modifier", lambda **k: {"seasonality_state": "neutral", "confidence_modifier": 0.0})

    import numpy as np
    import pandas as pd
    idx = pd.date_range("2024-01-01", periods=300, freq="B", tz="UTC")
    bench = pd.DataFrame({"Open": 1, "High": np.arange(300) + 10.0, "Low": 1,
                          "Close": np.arange(300) + 10.0, "Volume": 1}, index=idx)
    frames = {"benchmark_daily": bench, "spy_daily": bench}

    res = macro_mod.analyze_macro(
        "NVDA", "semiconductors", benchmark="SMH", frames=frames,
        rotation={"rotation_state": "outflow", "confidence_modifier": -5.0},
    )
    assert res["detail"]["sector"]["rotation_state"] == "outflow"
    assert res["summary"]["rotation_state"] == "outflow"


def test_analyze_technical_insufficient_history():
    import pandas as pd

    from deep_analysis.layers.technical import analyze_technical

    idx = pd.date_range("2026-01-01", periods=10, freq="B", tz="UTC")
    df = pd.DataFrame({"Open": 1, "High": 1, "Low": 1, "Close": 1, "Volume": 1}, index=idx)
    res = analyze_technical("TEST", "SMH", frames={"ticker_daily": df})
    assert res["data_quality"] == "unavailable"


# --------------------------------------------------------------------------- #
# prompts / render                                                             #
# --------------------------------------------------------------------------- #

def test_build_user_prompt_contains_ticker_and_json():
    prompt = build_user_prompt({"ticker": "AMD", "as_of_utc": "2026-08-31", "score": {"final_score": 40}})
    assert "AMD" in prompt
    assert "```json" in prompt
    assert '"final_score": 40' in prompt


def test_render_report_with_synthesis():
    findings = {
        "ticker": "AMD", "as_of_utc": "2026-08-31T00:00:00Z", "sector": "semiconductors",
        "benchmark": "SMH", "direction": "bullish",
        "score": {"final_score": 58.0, "technical_total": 28, "technical_max": 40},
        "data_quality": {"layers_on_real_data": {"technical": True, "news": False}, "degraded": [], "errors": []},
    }
    synthesis = {"report_markdown": "## Snapshot\nThe body.", "model": "claude-opus-5",
                 "usage": {"input_tokens": 10, "output_tokens": 20}}
    md = render_report(findings, synthesis)
    assert "# AMD — Deep Analysis" in md
    assert "## Snapshot" in md
    assert "Appendix A — Quantitative snapshot" in md
    assert "58.00 / 100" in md
    assert DISCLAIMER in md


def test_render_report_without_synthesis():
    findings = {"ticker": "AMD", "score": {}, "data_quality": {}}
    md = render_report(findings, None)
    assert "Synthesis not run" in md
    assert DISCLAIMER in md


# --------------------------------------------------------------------------- #
# synthesize                                                                   #
# --------------------------------------------------------------------------- #

def test_synthesize_happy_path():
    client = _FakeClient(_FakeMessage(text="## Snapshot\nGenerated briefing."))
    out = synthesize({"ticker": "NVDA"}, client=client)
    assert out["report_markdown"] == "## Snapshot\nGenerated briefing."
    assert out["usage"]["output_tokens"] == 5678
    assert client.captured["model"] == "claude-opus-5"
    assert client.captured["thinking"] == {"type": "adaptive"}
    assert client.captured["output_config"] == {"effort": "high"}


def test_synthesize_refusal_raises():
    client = _FakeClient(_FakeMessage(text="", stop_reason="refusal"))
    with pytest.raises(SynthesisError, match="refusal"):
        synthesize({"ticker": "NVDA"}, client=client)


def test_synthesize_empty_response_raises():
    client = _FakeClient(_FakeMessage(text="", stop_reason="end_turn"))
    with pytest.raises(SynthesisError, match="no text"):
        synthesize({"ticker": "NVDA"}, client=client)


def test_synthesize_missing_package_message():
    # _make_client() path: no client injected, anthropic not installed
    pytest.importorskip  # noqa: B018 - keep ref; explicit check below
    try:
        import anthropic  # noqa: F401
    except ImportError:
        with pytest.raises(SynthesisError, match="anthropic"):
            synthesize({"ticker": "NVDA"})
