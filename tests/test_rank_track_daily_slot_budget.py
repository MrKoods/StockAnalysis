"""
Tests for _run_rank_track()'s per-(day, sector) slot budget.

rank_track.top_n_per_sector is a budget for the DAY, not for each scan. The
dedup key set the function loads is (signal_date, ticker), which stops the
same ticker being logged twice but never stopped a later scan from walking
further down the same sector's ranking and filling top_n fresh slots. With
three scans a day (pre-market / mid-session / post-close) that logged
3 x top_n per sector — observed live on 2026-08-25 as exactly 6 rows per
sector against a configured top_n of 2, 24 rows in one day — and scans 2
and 3 are systematically the LOWER-ranked names, every one of them reported
as "rank #1"/"rank #2" in the scan log.

That inflates and biases the very dataset the rank track exists to build
(see _run_rank_track's own sample-size rationale), so it is a correctness
bug in the experiment, not a cosmetic logging one.
"""

import pytest

import paper_trading.paper_runner as pr


SECTORS = {
    "semiconductors": ["MU", "ADI", "AMD", "QCOM", "ASML", "NVDA"],
    "healthcare": ["AMGN", "GILD", "MRK", "BMY"],
}

# Descending score per sector, so "rank #1" is unambiguous and a later scan
# picking up where an earlier one left off is visible in the tickers logged.
SCORES = {
    "MU": 49.5, "ASML": 47.4, "ADI": 45.3, "NVDA": 44.1, "AMD": 42.9, "QCOM": 40.7,
    "AMGN": 75.0, "MRK": 69.1, "GILD": 68.7, "BMY": 65.3,
}

# watchlist.sectors, not a top-level "sectors" key — that's the shape
# sector_config.get_all_sectors() actually reads; a top-level key silently
# falls through to the legacy flat-key synthesis instead.
CFG = {
    "rank_track": {"top_n_per_sector": 2, "scan_type": "any"},
    "watchlist": {
        "sectors": {
            name: {"tickers": tickers, "active": True, "benchmark": "SMH"}
            for name, tickers in SECTORS.items()
        },
    },
}


def _candidates():
    out = []
    for sector, tickers in SECTORS.items():
        for ticker in tickers:
            out.append({
                "ticker": ticker,
                "sector": sector,
                "final_score": SCORES[ticker],
                "score": {},
            })
    return out


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    """Own CSV, no Discord, and a row builder that can't fail for data reasons."""
    csv_path = tmp_path / "rank_trades.csv"
    monkeypatch.setattr(pr, "RANK_TRADES_CSV", csv_path)
    monkeypatch.setattr(pr, "RANK_TRADES_LOCK_FILE", tmp_path / "rank_trades.csv.lock")
    monkeypatch.setattr(pr, "send_paper_signal_alert", lambda *a, **k: True)

    def _fake_row(candidate, cfg, rr_cfg, today_str, win_probability_calibration):
        row = {col: "" for col in pr._CSV_COLUMNS}
        row.update({
            "signal_date": today_str,
            "ticker": candidate["ticker"],
            "confidence": f"{candidate['final_score']:.1f}",
            "direction": "bullish",
            "entry_zone_lower": "99.00", "entry_zone_upper": "101.00",
            "entry_price": "100.00", "stop_loss": "95.00", "target": "115.00",
            "rr_ratio": "3.00", "position_type": "shares", "position_size": "5",
        })
        return row

    monkeypatch.setattr(pr, "_build_rank_track_row", _fake_row)
    return csv_path


def _scan(today_str="2026-08-25", cfg=None, scan_type="post_close"):
    return pr._run_rank_track(
        candidates=_candidates(), cfg=cfg or CFG, rr_cfg={}, model_version="test",
        today_str=today_str, win_probability_calibration=None, scan_type=scan_type,
    )


def _logged(csv_path):
    import csv as _csv
    # A scan that logs nothing never creates the file — that's the real
    # behaviour on a skipped scan, not a test-setup gap.
    if not csv_path.exists():
        return []
    with open(csv_path, newline="", encoding="utf-8") as f:
        return [(r["signal_date"], r["ticker"]) for r in _csv.DictReader(f)]


class TestDailySlotBudget:
    def test_single_scan_logs_top_n_per_sector(self, _isolate):
        assert _scan() == 4  # 2 sectors x top_n 2
        assert set(_logged(_isolate)) == {
            ("2026-08-25", "MU"), ("2026-08-25", "ASML"),
            ("2026-08-25", "AMGN"), ("2026-08-25", "MRK"),
        }

    def test_later_same_day_scans_add_nothing(self, _isolate):
        """The regression: scans 2 and 3 used to fill top_n fresh slots each."""
        assert _scan() == 4
        assert _scan() == 0
        assert _scan() == 0
        assert len(_logged(_isolate)) == 4

    def test_no_sector_exceeds_top_n_across_a_day(self, _isolate):
        for _ in range(3):
            _scan()
        ticker_sector = {t: s for s, ts in SECTORS.items() for t in ts}
        per_sector: dict[str, int] = {}
        for _date, ticker in _logged(_isolate):
            sector = ticker_sector[ticker]
            per_sector[sector] = per_sector.get(sector, 0) + 1
        assert per_sector == {"semiconductors": 2, "healthcare": 2}

    def test_lower_ranked_names_are_never_picked_up_by_a_later_scan(self, _isolate):
        """AMD/QCOM/ADI/NVDA are ranks 3-6; a second scan must not log them."""
        _scan()
        _scan()
        logged_tickers = {t for _d, t in _logged(_isolate)}
        assert logged_tickers.isdisjoint({"ADI", "NVDA", "AMD", "QCOM"})

    def test_next_day_gets_a_fresh_budget(self, _isolate):
        assert _scan("2026-08-25") == 4
        assert _scan("2026-08-25") == 0
        assert _scan("2026-08-26") == 4
        assert len(_logged(_isolate)) == 8


class TestRankReporting:
    def test_log_reports_true_within_sector_rank_not_slot_counter(self, _isolate, caplog):
        """
        `picks` is a slot counter; reporting it as the rank is what made every
        row read "rank #1"/"rank #2" regardless of where it actually placed.
        With MU already open, ASML takes the slot but is still rank #2.
        """
        monkey_open = {"MU"}
        import unittest.mock as mock
        with mock.patch.object(pr, "_load_open_positions", return_value=monkey_open):
            with caplog.at_level("INFO"):
                _scan()
        asml_lines = [r.message for r in caplog.records if "ASML" in r.message and "RANK-TRACK" in r.message]
        assert asml_lines, "ASML should have been logged"
        assert "rank #2" in asml_lines[0], asml_lines[0]


class TestOwningScanGate:
    """
    Only rank_track.scan_type (default post_close) competes for the day's
    slots. Before this gate they went to whichever scan ran first — pre_market,
    ranking on the LEAST information of the day's three scans.

    This is deliberately belt-and-braces with the per-(day, sector) budget
    above: the gate picks WHICH scan ranks, the budget stops any scan —
    including a manual re-run of the owning one — logging past top_n.
    """

    DEFAULT_CFG = {
        "rank_track": {"top_n_per_sector": 2},  # scan_type omitted -> post_close
        "watchlist": CFG["watchlist"],
    }

    def test_defaults_to_post_close(self, _isolate):
        assert _scan(cfg=self.DEFAULT_CFG, scan_type="post_close") == 4

    def test_pre_market_does_not_consume_slots_by_default(self, _isolate):
        assert _scan(cfg=self.DEFAULT_CFG, scan_type="pre_market") == 0
        assert _logged(_isolate) == []

    def test_mid_session_does_not_consume_slots_by_default(self, _isolate):
        assert _scan(cfg=self.DEFAULT_CFG, scan_type="mid_session") == 0
        assert _logged(_isolate) == []

    def test_earlier_scans_leave_the_slots_for_post_close(self, _isolate):
        """The ordering that used to hand pre_market the whole budget."""
        assert _scan(cfg=self.DEFAULT_CFG, scan_type="pre_market") == 0
        assert _scan(cfg=self.DEFAULT_CFG, scan_type="mid_session") == 0
        assert _scan(cfg=self.DEFAULT_CFG, scan_type="post_close") == 4
        assert {t for _d, t in _logged(_isolate)} == {"MU", "ASML", "AMGN", "MRK"}

    def test_configurable_to_another_scan(self, _isolate):
        cfg = {
            "rank_track": {"top_n_per_sector": 2, "scan_type": "pre_market"},
            "watchlist": CFG["watchlist"],
        }
        assert _scan(cfg=cfg, scan_type="post_close") == 0
        assert _scan(cfg=cfg, scan_type="pre_market") == 4

    def test_any_lets_every_scan_compete_but_budget_still_binds(self, _isolate):
        """The escape hatch must not reopen the 3x overcounting."""
        assert _scan(cfg=CFG, scan_type="pre_market") == 4
        assert _scan(cfg=CFG, scan_type="mid_session") == 0
        assert _scan(cfg=CFG, scan_type="post_close") == 0
        assert len(_logged(_isolate)) == 4

    def test_a_rerun_of_the_owning_scan_cannot_double_log(self, _isolate):
        """A manual re-run/retry of post_close passes the gate — budget stops it."""
        assert _scan(cfg=self.DEFAULT_CFG, scan_type="post_close") == 4
        assert _scan(cfg=self.DEFAULT_CFG, scan_type="post_close") == 0
        assert len(_logged(_isolate)) == 4
