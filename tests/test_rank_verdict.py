"""Tests for paper_trading/rank_verdict.py — the pre-registered rank-track go/no-go rule."""

import csv

import pandas as pd
import pytest

import paper_trading.rank_verdict as rv
from paper_trading.paper_runner import _CSV_COLUMNS

CFG = {
    "rank_track": {"go_no_go": {"min_closed_trades": 4, "min_mean_r": 0.15, "min_week_t": 2.0, "cost_per_side": 0.0}},
    "watchlist": {"sectors": {"semis": {"tickers": ["AAA"], "active": True, "benchmark": "ETF"}}},
}


def _write(path, trades):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=_CSV_COLUMNS, extrasaction="ignore")
        w.writeheader()
        for fill, exit_, rr, exit_px, direction in trades:
            w.writerow({"signal_date": fill, "ticker": "AAA", "direction": direction, "fill_date": fill,
                        "fill_price": "100", "stop_loss": "95" if direction == "bullish" else "105",
                        "exit_date": exit_, "exit_price": exit_px, "achieved_rr": rr, "outcome": "time_stop"})


@pytest.fixture
def flat_etf(monkeypatch):
    idx = pd.bdate_range("2026-08-01", "2026-12-31")
    monkeypatch.setattr(rv, "fetch_ohlcv_since", lambda t, s: pd.DataFrame({"Close": [100.0] * len(idx)}, index=idx))


def _weeks(rs, direction="bullish"):
    days = pd.bdate_range("2026-09-01", periods=len(rs), freq="W-MON")
    return [(d.strftime("%Y-%m-%d"), (d + pd.Timedelta(days=3)).strftime("%Y-%m-%d"), r,
             str(100 + 5 * r if direction == "bullish" else 100 - 5 * r), direction) for d, r in zip(days, rs)]


def test_collecting_below_min_trades(tmp_path, flat_etf):
    _write(tmp_path / "r.csv", _weeks([1.0, 1.2]))
    v = rv.compute_verdict(CFG, tmp_path / "r.csv", tmp_path / "none.csv")
    assert v["verdict"] == "COLLECTING"


def test_go_when_all_three_conditions_hold(tmp_path, flat_etf):
    _write(tmp_path / "r.csv", _weeks([1.0, 1.2, 0.9, 1.1, 1.0]))
    v = rv.compute_verdict(CFG, tmp_path / "r.csv", tmp_path / "none.csv")
    assert v["verdict"] == "GO" and v["vs_etf"] > 0


def test_no_go_when_mean_negative(tmp_path, flat_etf):
    _write(tmp_path / "r.csv", _weeks([-1.0, -0.8, 0.2, -1.0]))
    assert rv.compute_verdict(CFG, tmp_path / "r.csv", tmp_path / "none.csv")["verdict"] == "NO-GO"


def test_keep_collecting_when_noisy(tmp_path, flat_etf):
    _write(tmp_path / "r.csv", _weeks([3.0, -1.0, 2.0, -1.0]))
    assert rv.compute_verdict(CFG, tmp_path / "r.csv", tmp_path / "none.csv")["verdict"] == "KEEP COLLECTING"


def test_costs_are_charged_in_r_via_stop_distance(tmp_path, flat_etf):
    _write(tmp_path / "r.csv", _weeks([1.0, 1.0, 1.0, 1.0]))
    cfg = {**CFG, "rank_track": {"go_no_go": {**CFG["rank_track"]["go_no_go"], "cost_per_side": 0.005}}}
    v = rv.compute_verdict(cfg, tmp_path / "r.csv", tmp_path / "none.csv")
    assert v["mean_r_net"] == pytest.approx(1.0 - 0.01 / 0.05)   # 1% round trip on a 5% stop = 0.2R


def test_bearish_trade_vs_etf_is_signed(tmp_path, monkeypatch):
    idx = pd.bdate_range("2026-08-01", "2026-12-31")
    falling = pd.DataFrame({"Close": [100.0 - 0.1 * i for i in range(len(idx))]}, index=idx)
    monkeypatch.setattr(rv, "fetch_ohlcv_since", lambda t, s: falling)
    _write(tmp_path / "r.csv", _weeks([1.0, 1.0, 1.0, 1.0], direction="bearish"))
    v = rv.compute_verdict(CFG, tmp_path / "r.csv", tmp_path / "none.csv")
    # short made 5%; ETF fell ~0.3% over each 3-day hold, which a short also earns -> excess ~ +4.7%
    assert 0.04 < v["vs_etf"] < 0.05
