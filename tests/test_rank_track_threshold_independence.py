"""
Tests that the rank track's candidate pool is not silently filtered by the
threshold track's ledger (v2.2.102).

_run_rank_track's docstring promises the two tracks are "fully independent:
own CSV, own duplicate-position guard (own RANK_TRADES_CSV, never
cross-checked against the threshold track — a ticker can legitimately be open
in both, even opposite directions)".

They weren't. paper_runner's main loop checked the THRESHOLD track's same-day
dedup — `(today_str, ticker) in already_logged`, read from paper_trades.csv —
at the top of the loop, and `continue`d before the rank-track candidate stash.
So a ticker that already produced a qualifying signal today never entered the
rank track's candidate pool at all.

The bias has a direction, which is what makes it matter: the only tickers that
land in the threshold ledger are the ones scoring 70+, so the rank track was
systematically blind to the STRONGEST name in a sector. Confirmed live on
2026-08-25 — AMGN qualified pre-market at 75.0 and is absent from the entire
47-ticker post-close scoreboard, so healthcare's post-close rank picks were
MRK (72.6) and ABT (68.7) while the sector's top scorer was ineligible.

Gating the rank track to post_close (v2.2.100) made this worse: it now always
runs last, when the threshold ledger is most populated.
"""

import csv
import inspect

import pytest

import paper_trading.paper_runner as pr


class TestDedupOrdering:
    """
    Static checks on the loop's structure. The behavioural path needs a full
    scan (network, 47 tickers, a real config), so these assert the ordering
    invariant directly against the source — the same approach the repo's own
    guardrail checkers take.
    """

    @staticmethod
    def _scan_source():
        return inspect.getsource(pr._run_paper_scan_locked)

    def test_rank_stash_happens_before_the_threshold_dedup(self):
        src = self._scan_source()
        stash = src.index("rank_track_candidates.append(")
        dedup = src.index("in already_logged")
        assert stash < dedup, (
            "The threshold track's same-day dedup must not short-circuit before the "
            "rank-track candidate stash — that silently removes already-qualified "
            "tickers from the rank track's pool. See this module's docstring."
        )

    def test_the_dedup_still_exists(self):
        """Guard against 'fixing' the ordering by deleting the check outright,
        which would double-log threshold signals."""
        assert "in already_logged" in self._scan_source()

    def test_dedup_sits_above_the_sub_threshold_branch(self):
        """
        Kept above the near-miss branch on purpose: a ticker with a live signal
        already logged today shouldn't also fire a near-miss Discord ping if it
        slips under 70 on a later scan.
        """
        src = self._scan_source()
        dedup = src.index("in already_logged")
        sub_threshold = src.index("if final_score < CONFIDENCE_THRESHOLD:")
        assert dedup < sub_threshold

    def test_only_the_threshold_ledger_feeds_this_dedup(self):
        """_load_logged_keys() with no argument reads PAPER_TRADES_CSV. The
        rank track has its own separate call passing RANK_TRADES_CSV."""
        src = self._scan_source()
        assert "already_logged = _load_logged_keys()" in src


class TestRankTrackSeesQualifiedTickers:
    """The end state the fix exists to produce: a ticker sitting in the
    threshold ledger is still rankable."""

    SECTORS = {"healthcare": ["AMGN", "MRK", "ABT", "GILD"]}
    SCORES = {"AMGN": 75.0, "MRK": 72.6, "ABT": 68.7, "GILD": 65.3}
    CFG = {
        "rank_track": {"top_n_per_sector": 2, "scan_type": "any"},
        "watchlist": {
            "sectors": {
                "healthcare": {"tickers": SECTORS["healthcare"], "active": True, "benchmark": "XLV"}
            }
        },
    }

    @pytest.fixture(autouse=True)
    def _isolate(self, tmp_path, monkeypatch):
        rank_csv = tmp_path / "rank_trades.csv"
        monkeypatch.setattr(pr, "RANK_TRADES_CSV", rank_csv)
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
        return rank_csv

    def _candidates(self):
        return [
            {"ticker": t, "sector": "healthcare", "final_score": self.SCORES[t], "score": {}}
            for t in self.SECTORS["healthcare"]
        ]

    def test_top_two_by_score_are_picked(self, _isolate):
        """
        AMGN is the sector's top scorer and, in the live 2026-08-25 case, was
        already in the threshold ledger. Given it reaches the candidate pool,
        it must win a rank slot.
        """
        assert pr._run_rank_track(
            candidates=self._candidates(), cfg=self.CFG, rr_cfg={}, model_version="test",
            today_str="2026-08-25", win_probability_calibration=None, scan_type="post_close",
        ) == 2
        with open(_isolate, newline="", encoding="utf-8") as f:
            picked = {r["ticker"] for r in csv.DictReader(f)}
        assert picked == {"AMGN", "MRK"}, (
            "Expected the sector's true top 2. Getting {MRK, ABT} is the exact live "
            "2026-08-25 symptom: the top scorer missing from the pool entirely."
        )

    def test_the_rank_ledger_is_what_gates_rank_picks(self, _isolate):
        """A prior rank-track row for the day consumes its slot; the threshold
        ledger has no say here."""
        pr._append_row(
            {**{c: "" for c in pr._CSV_COLUMNS},
             "signal_date": "2026-08-25", "ticker": "AMGN", "direction": "bullish"},
            csv_path=pr.RANK_TRADES_CSV, lock_path=pr.RANK_TRADES_LOCK_FILE,
        )
        pr._run_rank_track(
            candidates=self._candidates(), cfg=self.CFG, rr_cfg={}, model_version="test",
            today_str="2026-08-25", win_probability_calibration=None, scan_type="post_close",
        )
        with open(_isolate, newline="", encoding="utf-8") as f:
            picked = [r["ticker"] for r in csv.DictReader(f)]
        # AMGN already held a slot; only one remained, and MRK is next by score.
        assert picked == ["AMGN", "MRK"]
