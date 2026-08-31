"""Tests for shared/utils/price_source_comparison.py — the D3 yfinance-vs-SA
daily-bar diagnostic. No scoring effect; it only reads OHLCV and appends a CSV."""

import csv

import pandas as pd
import pytest

import shared.utils.price_source_comparison as psc


def _yf_df(dates, closes, *, opens=None, highs=None, lows=None, vols=None):
    idx = pd.to_datetime(dates).tz_localize("UTC")
    n = len(dates)
    return pd.DataFrame(
        {
            "Open": opens or closes,
            "High": highs or closes,
            "Low": lows or closes,
            "Close": closes,
            "Volume": vols or [1_000_000] * n,
        },
        index=idx,
    )


def _sa_bars(dates, closes, *, adj=None, vols=None):
    adj = adj or closes
    vols = vols or [1_000_000] * len(dates)
    return [
        {"date": d, "open": c, "high": c, "low": c, "close": c, "adj": a, "volume": v}
        for d, c, a, v in zip(dates, closes, adj, vols)
    ]


@pytest.fixture
def _cfg_on():
    return {"price_source_comparison": {"enabled": True}}


def _read_rows(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def test_disabled_is_a_noop(monkeypatch, tmp_path):
    called = []
    monkeypatch.setattr(psc.seeking_alpha_client, "get_daily_ohlcv", lambda *a, **k: called.append(1) or [])
    psc.log_price_source_comparison({"NVDA": _yf_df(["2026-08-27"], [100.0])}, "post_close", {})
    assert not psc._CSV_PATH.exists()
    assert called == []


def test_matching_bars_log_small_diffs(monkeypatch, _cfg_on):
    dates = ["2026-08-25", "2026-08-26", "2026-08-27"]
    monkeypatch.setattr(
        psc.seeking_alpha_client, "get_daily_ohlcv",
        lambda *a, **k: _sa_bars(dates, [99.99, 101.0, 102.02]),
    )
    psc.log_price_source_comparison({"NVDA": _yf_df(dates, [100.0, 101.0, 102.0])}, "post_close", _cfg_on)

    rows = _read_rows(psc._CSV_PATH)
    assert len(rows) == 1
    r = rows[0]
    assert r["ticker"] == "NVDA" and r["scan_type"] == "post_close"
    assert r["common_days"] == "3"
    assert r["sa_staleness_days"] == "0"
    assert abs(float(r["close_pct_diff_max"])) < 0.05
    assert r["note"] == ""


def test_sa_empty_logs_note(monkeypatch, _cfg_on):
    monkeypatch.setattr(psc.seeking_alpha_client, "get_daily_ohlcv", lambda *a, **k: [])
    psc.log_price_source_comparison({"NVDA": _yf_df(["2026-08-27"], [100.0])}, "pre_market", _cfg_on)
    r = _read_rows(psc._CSV_PATH)[0]
    assert r["note"] == "sa_empty"
    assert r["yf_bars"] == "1" and r["sa_bars"] == ""


def test_missing_yf_frame_logs_note(monkeypatch, _cfg_on):
    monkeypatch.setattr(psc.seeking_alpha_client, "get_daily_ohlcv", lambda *a, **k: _sa_bars(["2026-08-27"], [100.0]))
    psc.log_price_source_comparison({"NVDA": None}, "post_close", _cfg_on)
    assert _read_rows(psc._CSV_PATH)[0]["note"] == "yf_missing"


def test_detects_a_mishandled_corporate_action(monkeypatch, _cfg_on):
    # SA failed to back-adjust one historical day across a 2:1 split.
    dates = ["2026-08-24", "2026-08-25", "2026-08-26"]
    monkeypatch.setattr(
        psc.seeking_alpha_client, "get_daily_ohlcv",
        lambda *a, **k: _sa_bars(dates, [200.0, 100.5, 101.0]),  # day 1 is 2x
    )
    psc.log_price_source_comparison({"NVDA": _yf_df(dates, [100.0, 100.5, 101.0])}, "post_close", _cfg_on)
    r = _read_rows(psc._CSV_PATH)[0]
    assert float(r["close_pct_diff_max"]) > 40  # the un-split day screams
    assert abs(float(r["close_pct_diff_last"])) < 0.01  # recent days fine


def test_reports_sa_staleness(monkeypatch, _cfg_on):
    yf_dates = ["2026-08-25", "2026-08-26", "2026-08-27"]
    sa_dates = ["2026-08-25"]  # SA is 2 days behind
    monkeypatch.setattr(psc.seeking_alpha_client, "get_daily_ohlcv", lambda *a, **k: _sa_bars(sa_dates, [100.0]))
    psc.log_price_source_comparison({"NVDA": _yf_df(yf_dates, [100.0, 101.0, 102.0])}, "post_close", _cfg_on)
    r = _read_rows(psc._CSV_PATH)[0]
    assert r["sa_staleness_days"] == "2"
    assert r["common_days"] == "1"


def test_header_written_once_then_appended(monkeypatch, _cfg_on):
    monkeypatch.setattr(psc.seeking_alpha_client, "get_daily_ohlcv", lambda *a, **k: _sa_bars(["2026-08-27"], [100.0]))
    df = {"NVDA": _yf_df(["2026-08-27"], [100.0])}
    psc.log_price_source_comparison(df, "pre_market", _cfg_on)
    psc.log_price_source_comparison(df, "post_close", _cfg_on)
    text = psc._CSV_PATH.read_text(encoding="utf-8")
    assert text.count("logged_at_utc") == 1
    assert len(_read_rows(psc._CSV_PATH)) == 2


def test_never_raises_on_bad_input(monkeypatch, _cfg_on):
    monkeypatch.setattr(
        psc.seeking_alpha_client, "get_daily_ohlcv",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    # must not propagate
    psc.log_price_source_comparison({"NVDA": _yf_df(["2026-08-27"], [100.0])}, "post_close", _cfg_on)
