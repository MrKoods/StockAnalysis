"""
Tests for the shares-only track (v2.2.133): the rank track's exact ranking,
slot budget and guards, but every row a plain long/short stock position.
"""

import csv

import pytest

import paper_trading.paper_runner as pr

CFG = {
    "rank_track": {"top_n_per_sector": 2, "scan_type": "post_close"},
    "position_sizing": {"starting_capital": 15000, "max_capital_pct": 0.33333},
    "watchlist": {"sectors": {
        "semis": {"tickers": ["AAA", "BBB", "CCC"], "active": True, "benchmark": "SMH"},
        "banks": {"tickers": ["XXX", "YYY", "ZZZ"], "active": True, "benchmark": "KRE"},
    }},
}
SCORES = {"AAA": 70.0, "BBB": 60.0, "CCC": 50.0, "XXX": 65.0, "YYY": 55.0, "ZZZ": 45.0}


def _candidate(ticker, sector, direction="bullish", close=100.0):
    return {
        "ticker": ticker, "sector": sector, "direction": direction, "final_score": SCORES.get(ticker, 50.0),
        "score": {}, "earnings_result": {}, "positioning": {}, "regime": "normal", "vix_val": 15.0,
        "news_count": 0, "dominant_theme": "",
        "indicators": {"close": close, "atr_14": 2.0, "rolling_high_20": close, "rolling_low_20": close},
    }


def _candidates():
    return [_candidate(t, "semis") for t in ("AAA", "BBB", "CCC")] + \
           [_candidate(t, "banks", "bearish") for t in ("XXX", "YYY", "ZZZ")]


def _rows(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


@pytest.mark.parametrize("direction,structure", [("bullish", "long_stock"), ("bearish", "short_stock")])
def test_row_is_a_plain_stock_position_and_never_ranks_options(monkeypatch, direction, structure):
    monkeypatch.setattr(pr, "rank_trade_structures", lambda *a, **k: pytest.fail("shares track ranked options"))
    row = pr._build_rank_track_row(_candidate("AAA", "semis", direction), CFG, {}, "2026-10-14", None,
                                   shares_only=True)
    assert row["position_type"] == "shares"
    assert row["structure_recommended"] == structure
    assert int(row["position_size"]) > 0
    assert float(row["capital_deployed"]) <= 15000 * 0.33333 + 1e-6
    assert row["sizing_note"].startswith("shares track")
    # stop distance x shares = the dollar risk actually taken
    risk = abs(float(row["entry_price"]) - float(row["stop_loss"])) * int(row["position_size"])
    assert float(row["actual_dollar_risk"]) == pytest.approx(risk, rel=0.02)


def test_rank_track_rows_still_rank_options(monkeypatch):
    called = []
    monkeypatch.setattr(pr, "rank_trade_structures", lambda *a, **k: called.append(1) or {"ranked_structures": []})
    pr._build_rank_track_row(_candidate("AAA", "semis"), CFG, {}, "2026-10-14", None)
    assert called


def test_shares_track_takes_the_rank_tracks_picks(tmp_path, monkeypatch):
    alerts = []
    monkeypatch.setattr(pr, "send_paper_signal_alert", lambda payload, model_version, track: alerts.append(track))
    monkeypatch.setattr(pr, "rank_trade_structures", lambda *a, **k: {"ranked_structures": []})
    for track, shares_only in (("rank", False), ("shares", True)):
        pr._run_rank_track(_candidates(), CFG, {}, "test", "2026-10-14", None, scan_type="post_close",
                           csv_path=tmp_path / f"{track}.csv", lock_path=tmp_path / f"{track}.lock",
                           track=track, shares_only=shares_only)
    rank, shares = _rows(tmp_path / "rank.csv"), _rows(tmp_path / "shares.csv")
    assert [(r["ticker"], r["direction"]) for r in shares] == [(r["ticker"], r["direction"]) for r in rank]
    assert {r["ticker"] for r in shares} == {"AAA", "BBB", "XXX", "YYY"}
    assert all(r["position_type"] == "shares" for r in shares)
    assert alerts.count("shares") == 4 and alerts.count("rank") == 4


def test_ledgers_keep_independent_guards(tmp_path, monkeypatch):
    """A filled shares position blocks only the shares ledger, not the rank ledger."""
    monkeypatch.setattr(pr, "send_paper_signal_alert", lambda *a, **k: True)
    monkeypatch.setattr(pr, "rank_trade_structures", lambda *a, **k: {"ranked_structures": []})
    shares = tmp_path / "shares.csv"
    with open(shares, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=pr._CSV_COLUMNS, extrasaction="ignore")
        w.writeheader()
        w.writerow({"signal_date": "2026-10-13", "ticker": "AAA", "direction": "bullish", "fill_date": "2026-10-14"})
    for track, shares_only in (("rank", False), ("shares", True)):
        pr._run_rank_track(_candidates(), CFG, {}, "test", "2026-10-14", None, scan_type="post_close",
                           csv_path=tmp_path / f"{track}.csv", lock_path=tmp_path / f"{track}.lock",
                           track=track, shares_only=shares_only)
    today = lambda p: [r["ticker"] for r in _rows(p) if r["signal_date"] == "2026-10-14" and r["ticker"] in ("AAA", "BBB", "CCC")]
    assert today(tmp_path / "rank.csv") == ["AAA", "BBB"]
    assert today(shares) == ["BBB", "CCC"]


def test_shares_track_has_its_own_discord_identity():
    from shared.utils.discord_alerts import _brand_payload
    out = _brand_payload({"embeds": [{"title": "PAPER TRADE"}]}, "shares")
    assert out["username"].endswith("Shares Track") and out["embeds"][0]["title"].startswith("📈 [SHARES]")
