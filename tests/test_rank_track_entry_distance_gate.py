"""
Tests for rank_track.max_entry_distance_atr — a rank-track candidate whose
entry trigger sits too far from the current close is skipped and the slot
passes to the next-ranked candidate in the sector.

Entry anchors on the prior 20-day high (bullish) / low (bearish), so a
pulled-back name gets a trigger far from the market. Live through
2026-09-25, signals >1 ATR out filled ~5% of the time inside the 5-day
window — a slot spent on one was almost always a slot spent on nothing.
"""

import csv

import pytest

import paper_trading.paper_runner as pr


def _cand(ticker, score, close, rolling_high, atr=2.0, direction="bullish", rolling_low=None):
    return {
        "ticker": ticker,
        "sector": "semiconductors",
        "final_score": score,
        "direction": direction,
        "score": {},
        "indicators": {
            "close": close, "atr_14": atr, "rolling_high_20": rolling_high,
            "rolling_low_20": rolling_low if rolling_low is not None else close,
        },
    }


class TestEntryDistanceAtr:
    def test_bullish_measures_from_the_20d_high(self):
        assert pr._entry_distance_atr(_cand("X", 50, close=100.0, rolling_high=106.0)) == pytest.approx(3.0)

    def test_bullish_breakout_above_the_high_is_zero(self):
        assert pr._entry_distance_atr(_cand("X", 50, close=110.0, rolling_high=106.0)) == 0.0

    def test_bearish_measures_from_the_20d_low(self):
        c = _cand("X", 50, close=100.0, rolling_high=120.0, direction="bearish", rolling_low=97.0)
        assert pr._entry_distance_atr(c) == pytest.approx(1.5)

    def test_missing_indicators_is_none(self):
        assert pr._entry_distance_atr({"ticker": "X", "direction": "bullish"}) is None


@pytest.fixture
def ledger(tmp_path, monkeypatch):
    csv_path = tmp_path / "rank_trades.csv"
    monkeypatch.setattr(pr, "RANK_TRADES_CSV", csv_path)
    monkeypatch.setattr(pr, "RANK_TRADES_LOCK_FILE", tmp_path / "rank_trades.csv.lock")
    monkeypatch.setattr(pr, "send_paper_signal_alert", lambda *a, **k: True)

    def _fake_row(candidate, cfg, rr_cfg, today_str, win_probability_calibration):
        row = {col: "" for col in pr._CSV_COLUMNS}
        row.update({
            "signal_date": today_str, "ticker": candidate["ticker"],
            "confidence": f"{candidate['final_score']:.1f}", "direction": "bullish",
            "entry_zone_lower": "99.00", "entry_zone_upper": "101.00",
            "entry_price": "100.00", "stop_loss": "95.00", "target": "115.00",
            "rr_ratio": "3.00", "position_type": "shares", "position_size": "5",
        })
        return row

    monkeypatch.setattr(pr, "_build_rank_track_row", _fake_row)
    return csv_path


def _cfg(max_dist):
    return {
        "rank_track": {"top_n_per_sector": 2, "scan_type": "any", "max_entry_distance_atr": max_dist},
        "watchlist": {"sectors": {"semiconductors": {
            "tickers": ["FAR", "NEAR1", "NEAR2"], "active": True, "benchmark": "SMH",
        }}},
    }


def _candidates():
    # FAR is ranked #1 but its trigger is 4 ATR above the close.
    return [
        _cand("FAR", 80.0, close=100.0, rolling_high=108.0),
        _cand("NEAR1", 70.0, close=100.0, rolling_high=101.0),
        _cand("NEAR2", 60.0, close=100.0, rolling_high=100.5),
    ]


def _logged(csv_path):
    if not csv_path.exists():
        return []
    with open(csv_path, newline="", encoding="utf-8") as f:
        return [r["ticker"] for r in csv.DictReader(f)]


def _scan(cfg):
    return pr._run_rank_track(
        candidates=_candidates(), cfg=cfg, rr_cfg={}, model_version="test",
        today_str="2026-09-28", win_probability_calibration=None, scan_type="post_close",
    )


def test_far_trigger_is_skipped_and_slot_passes_down(ledger):
    assert _scan(_cfg(1.5)) == 2
    assert _logged(ledger) == ["NEAR1", "NEAR2"]


def test_zero_disables_the_gate(ledger):
    assert _scan(_cfg(0)) == 2
    assert _logged(ledger) == ["FAR", "NEAR1"]


def test_skipped_candidate_does_not_supersede_its_pending_order(ledger):
    """A pending FAR order from yesterday must survive a scan that skips FAR."""
    row = {col: "" for col in pr._CSV_COLUMNS}
    row.update({
        "signal_date": "2026-09-25", "ticker": "FAR", "direction": "bullish",
        "entry_zone_lower": "99.00", "entry_zone_upper": "101.00",
        "entry_price": "100.00", "stop_loss": "95.00", "target": "115.00", "confidence": "75.0",
    })
    pr._append_row(row, csv_path=ledger, lock_path=pr.RANK_TRADES_LOCK_FILE)

    _scan(_cfg(1.5))

    with open(ledger, newline="", encoding="utf-8") as f:
        far_rows = [r for r in csv.DictReader(f) if r["ticker"] == "FAR"]
    assert len(far_rows) == 1
    assert far_rows[0]["outcome"] == ""
