"""
Tests for _run_random_control() — the rank track's random-pick yardstick.

It must mirror the rank track's mechanics (owning scan, per-(day, sector)
slot budget, entry-distance gate, filled-position guard) and differ ONLY in
how tickers and directions are chosen — otherwise a rank-vs-random gap could
come from the plumbing instead of the model's scoring.
"""

import csv

import pytest

import paper_trading.paper_runner as pr
import paper_trading.paper_updater as pu


SECTORS = {
    "semiconductors": ["MU", "ADI", "AMD", "QCOM", "ASML", "NVDA"],
    "healthcare": ["AMGN", "GILD", "MRK", "BMY"],
}

CFG = {
    "rank_track": {"top_n_per_sector": 2, "scan_type": "post_close", "max_entry_distance_atr": 1.5},
    "watchlist": {
        "sectors": {
            name: {"tickers": tickers, "active": True, "benchmark": "SMH"}
            for name, tickers in SECTORS.items()
        },
    },
}


def _candidates(far=()):
    """Every candidate sits at its 20-day high/low (0 ATR away) unless listed in `far`."""
    out = []
    for sector, tickers in SECTORS.items():
        for ticker in tickers:
            hi, lo = (110.0, 90.0) if ticker in far else (100.0, 100.0)
            out.append({
                "ticker": ticker, "sector": sector, "final_score": 50.0, "direction": "bullish",
                "score": {},
                "indicators": {"close": 100.0, "atr_14": 2.0, "rolling_high_20": hi, "rolling_low_20": lo},
            })
    return out


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(pr, "RANDOM_TRADES_CSV", tmp_path / "random_trades.csv")
    monkeypatch.setattr(pr, "RANDOM_TRADES_LOCK_FILE", tmp_path / "random_trades.csv.lock")
    monkeypatch.setattr(pr, "RANK_TRADES_CSV", tmp_path / "rank_trades.csv")

    def _fake_row(candidate, cfg, rr_cfg, today_str, win_probability_calibration):
        row = {col: "" for col in pr._CSV_COLUMNS}
        row.update({
            "signal_date": today_str, "ticker": candidate["ticker"], "direction": candidate["direction"],
            "confidence": "50.0", "entry_price": "100.00", "stop_loss": "95.00", "target": "115.00",
            "sizing_note": "rank track — flat 3.33% risk",
        })
        return row

    monkeypatch.setattr(pr, "_build_rank_track_row", _fake_row)
    monkeypatch.setattr(pr, "send_paper_signal_alert", lambda *a, **k: pytest.fail("control must not alert"))
    return tmp_path / "random_trades.csv"


def _scan(today="2026-10-14", scan_type="post_close", far=()):
    return pr._run_random_control(_candidates(far), CFG, {}, today, None, scan_type=scan_type)


def _rows(path):
    if not path.exists():
        return []
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def test_logs_top_n_per_sector_and_tags_rows(_isolate):
    assert _scan() == 4
    rows = _rows(_isolate)
    by_sector = {}
    for r in rows:
        sector = next(s for s, t in SECTORS.items() if r["ticker"] in t)
        by_sector[sector] = by_sector.get(sector, 0) + 1
        assert r["sizing_note"].startswith("random control")
    assert by_sector == {"semiconductors": 2, "healthcare": 2}


def test_same_day_rerun_adds_nothing_and_draw_is_reproducible(_isolate, tmp_path, monkeypatch):
    _scan()
    first = [(r["ticker"], r["direction"]) for r in _rows(_isolate)]
    assert _scan() == 0
    other = tmp_path / "again.csv"
    monkeypatch.setattr(pr, "RANDOM_TRADES_CSV", other)
    _scan()
    assert [(r["ticker"], r["direction"]) for r in _rows(other)] == first


def test_only_the_owning_scan_logs(_isolate):
    assert _scan(scan_type="pre_market") == 0
    assert _rows(_isolate) == []


def test_picks_and_directions_actually_vary(_isolate):
    """Over many days both directions occur and more than the top-2 names get picked."""
    for day in range(1, 29):
        _scan(today=f"2026-11-{day:02d}")
    rows = _rows(_isolate)
    assert {r["direction"] for r in rows} == {"bullish", "bearish"}
    assert len({r["ticker"] for r in rows if r["ticker"] in SECTORS["semiconductors"]}) > 2


def test_entry_distance_gate_passes_the_slot_on(_isolate):
    far = set(SECTORS["semiconductors"][:4])          # 5 ATR from the trigger either way
    assert _scan(far=far) == 4
    semis = [r["ticker"] for r in _rows(_isolate) if r["ticker"] in SECTORS["semiconductors"]]
    assert sorted(semis) == ["ASML", "NVDA"]


def test_filled_open_position_is_skipped(_isolate):
    _scan(today="2026-10-14")
    rows = _rows(_isolate)
    for r in rows:
        r["fill_date"] = "2026-10-15"
    with open(_isolate, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=pr._CSV_COLUMNS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    held = {r["ticker"] for r in rows}
    _scan(today="2026-10-15")
    new = [r["ticker"] for r in _rows(_isolate) if r["signal_date"] == "2026-10-15"]
    assert new and not (set(new) & held)


def test_rank_ledger_untouched(_isolate, tmp_path):
    _scan()
    assert not (tmp_path / "rank_trades.csv").exists()


def test_random_track_never_posts_daily_summary(monkeypatch):
    monkeypatch.setattr(pu, "send_daily_summary_alert", lambda *a, **k: pytest.fail("silent track posted"))
    monkeypatch.setattr(pu, "generate_daily_summary", lambda **k: {})
    pu._try_send_daily_summary(track="random")
