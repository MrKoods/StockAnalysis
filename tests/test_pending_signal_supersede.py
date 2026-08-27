"""
Tests for the duplicate-position guard's pending-vs-filled split (v2.2.101).

Previously any open row on a ticker blocked a new signal. But an open row has
two very different meanings:

  * PENDING  — logged, entry order never triggered, no capital at risk. Its
    entry zone/stop/target were computed from data that is now days old, so
    it's a stale opinion the model has since revised.
  * FILLED   — real exposure. Doubling up on it is the thing the guard exists
    to prevent.

A pending row is now cancelled (outcome=superseded) and the newer qualifying
signal takes its place. A filled row still blocks, unchanged.
"""

import csv

import pytest

import paper_trading.paper_runner as pr
from shared.utils.trade_outcomes import (
    OUTCOME_EXPIRED, OUTCOME_SUPERSEDED, UNFUNDED_OUTCOMES, is_scored, is_unfunded,
)


def _row(**overrides):
    row = {col: "" for col in pr._CSV_COLUMNS}
    row.update({
        "signal_date": "2026-08-20",
        "ticker": "AMZN",
        "confidence": "72.0",
        "direction": "bullish",
        "entry_price": "287.20",
        "stop_loss": "269.76",
        "target": "339.53",
        "position_type": "shares",
        "position_size": "2",
        "outcome": "",
        "fill_date": "",
    })
    row.update(overrides)
    return row


@pytest.fixture
def ledger(tmp_path, monkeypatch):
    csv_path = tmp_path / "paper_trades.csv"
    monkeypatch.setattr(pr, "PAPER_TRADES_CSV", csv_path)
    monkeypatch.setattr(pr, "PAPER_TRADES_LOCK_FILE", tmp_path / "paper_trades.csv.lock")
    return csv_path


def _read(csv_path):
    with open(csv_path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


class TestOutcomeConstants:
    def test_superseded_is_unfunded(self):
        assert is_unfunded(OUTCOME_SUPERSEDED)
        assert OUTCOME_SUPERSEDED in UNFUNDED_OUTCOMES

    def test_superseded_is_not_scored(self):
        """The whole point — it must never land in a win-rate denominator."""
        assert not is_scored(OUTCOME_SUPERSEDED)

    def test_expired_still_unfunded(self):
        assert is_unfunded(OUTCOME_EXPIRED)
        assert not is_scored(OUTCOME_EXPIRED)

    def test_real_outcomes_are_scored(self):
        for outcome in ("win", "loss", "time_stop", "earnings_exit", "early_exit"):
            assert is_scored(outcome), outcome

    def test_open_row_is_neither(self):
        assert not is_scored("")
        assert not is_unfunded("")


class TestPendingDetection:
    def test_unfilled_open_row_is_pending(self, ledger):
        pr._append_row(_row())
        assert pr._load_pending_positions() == {"AMZN"}

    def test_filled_open_row_is_not_pending(self, ledger):
        pr._append_row(_row(fill_date="2026-08-21", fill_price="288.00"))
        assert pr._load_pending_positions() == set()
        assert pr._load_open_positions() == {"AMZN"}

    def test_closed_row_is_not_pending(self, ledger):
        pr._append_row(_row(outcome="loss", exit_date="2026-08-22"))
        assert pr._load_pending_positions() == set()
        assert pr._load_open_positions() == set()

    def test_a_filled_row_suppresses_a_pending_one_on_the_same_ticker(self, ledger):
        """Real exposure wins — the ticker must not look replaceable."""
        pr._append_row(_row(signal_date="2026-08-18", fill_date="2026-08-19"))
        pr._append_row(_row(signal_date="2026-08-20"))
        assert pr._load_pending_positions() == set()
        assert pr._load_open_positions() == {"AMZN"}

    def test_missing_file_is_empty(self, ledger):
        assert pr._load_pending_positions() == set()


class TestSupersede:
    def test_marks_the_pending_row_superseded(self, ledger):
        pr._append_row(_row())
        cancelled = pr._supersede_pending_signals("AMZN", "2026-08-26", 77.1)
        assert cancelled == ["2026-08-20"]
        row = _read(ledger)[0]
        assert row["outcome"] == OUTCOME_SUPERSEDED
        assert row["exit_date"] == "2026-08-26"

    def test_records_why_in_the_sizing_note(self, ledger):
        pr._append_row(_row())
        pr._supersede_pending_signals("AMZN", "2026-08-26", 77.1)
        note = _read(ledger)[0]["sizing_note"]
        assert "superseded 2026-08-26" in note
        assert "77.1" in note

    def test_preserves_an_existing_sizing_note(self, ledger):
        pr._append_row(_row(sizing_note="capital cap capped this position"))
        pr._supersede_pending_signals("AMZN", "2026-08-26", 77.1)
        note = _read(ledger)[0]["sizing_note"]
        assert note.startswith("capital cap capped this position")
        assert "superseded" in note

    def test_books_no_pnl(self, ledger):
        """No capital was ever at risk — it must not look like a loss."""
        pr._append_row(_row())
        pr._supersede_pending_signals("AMZN", "2026-08-26", 77.1)
        row = _read(ledger)[0]
        assert row["pnl_dollars"] == ""
        assert row["pnl_pct"] == ""
        assert row["achieved_rr"] == ""

    def test_refuses_to_cancel_a_filled_row(self, ledger):
        """
        The race this guards: paper_updater.py stamps fill_date the moment the
        entry zone trades, and can do so between the guard's snapshot and this
        call. Cancelling then would close real exposure.
        """
        pr._append_row(_row(fill_date="2026-08-21", fill_price="288.00"))
        assert pr._supersede_pending_signals("AMZN", "2026-08-26", 77.1) == []
        assert _read(ledger)[0]["outcome"] == ""

    def test_leaves_other_tickers_alone(self, ledger):
        pr._append_row(_row(ticker="AMZN"))
        pr._append_row(_row(ticker="NVDA"))
        pr._supersede_pending_signals("AMZN", "2026-08-26", 77.1)
        rows = {r["ticker"]: r for r in _read(ledger)}
        assert rows["AMZN"]["outcome"] == OUTCOME_SUPERSEDED
        assert rows["NVDA"]["outcome"] == ""

    def test_cancels_every_pending_row_for_the_ticker(self, ledger):
        pr._append_row(_row(signal_date="2026-08-19"))
        pr._append_row(_row(signal_date="2026-08-20"))
        cancelled = pr._supersede_pending_signals("AMZN", "2026-08-26", 77.1)
        assert sorted(cancelled) == ["2026-08-19", "2026-08-20"]
        assert all(r["outcome"] == OUTCOME_SUPERSEDED for r in _read(ledger))

    def test_does_not_touch_already_closed_rows(self, ledger):
        pr._append_row(_row(signal_date="2026-08-10", outcome="win", exit_date="2026-08-14"))
        pr._append_row(_row(signal_date="2026-08-20"))
        pr._supersede_pending_signals("AMZN", "2026-08-26", 77.1)
        rows = {r["signal_date"]: r for r in _read(ledger)}
        assert rows["2026-08-10"]["outcome"] == "win"
        assert rows["2026-08-20"]["outcome"] == OUTCOME_SUPERSEDED

    def test_preserves_all_columns(self, ledger):
        """Full-file rewrite must not drop the schema."""
        pr._append_row(_row())
        pr._supersede_pending_signals("AMZN", "2026-08-26", 77.1)
        with open(ledger, newline="", encoding="utf-8") as f:
            assert csv.DictReader(f).fieldnames == pr._CSV_COLUMNS

    def test_missing_file_is_a_noop(self, ledger):
        assert pr._supersede_pending_signals("AMZN", "2026-08-26", 77.1) == []


class TestMetricsExcludeSuperseded:
    def test_superseded_stays_out_of_the_win_rate_denominator(self):
        closed = [
            {"outcome": "win"}, {"outcome": "loss"},
            {"outcome": OUTCOME_SUPERSEDED}, {"outcome": OUTCOME_EXPIRED},
        ]
        scored = [t for t in closed if is_scored(t.get("outcome"))]
        assert len(scored) == 2

    def test_calibration_skips_superseded(self):
        """feedback_loop's training set filter — a phantom loss here would
        silently steer live scoring weights."""
        rows = [{"outcome": OUTCOME_SUPERSEDED}, {"outcome": "win"}, {"outcome": ""}]
        kept = [r for r in rows if is_scored(r.get("outcome"))]
        assert kept == [{"outcome": "win"}]


class TestSupersedeIgnoresDirection:
    """
    Supersede fires across OPPOSITE directions, deliberately — confirmed with
    the user 2026-08-26.

    Three reasons: (1) it matches the guard it sits inside, which already
    blocks regardless of direction on the Signal Integrity Audit's C.5
    reasoning (conflicting-direction signals on one name read as noisy signal
    quality, not a hedge this model is built to run); (2) a direction flip is
    the STRONGEST evidence the pending order is stale — restricting to
    same-direction would preserve the stale order precisely when the model has
    most emphatically repudiated it, and discard the newer read; (3) a pending
    order has no capital committed, so there is no exposure to net out.

    The code achieves this by never consulting `direction` at all, which reads
    as an oversight rather than a decision. These tests exist so it can't be
    "fixed" into same-direction-only by someone assuming it was one.
    """

    def test_bearish_signal_supersedes_a_pending_bullish_one(self, ledger):
        pr._append_row(_row(direction="bullish"))
        assert pr._supersede_pending_signals("AMZN", "2026-08-26", 74.0) == ["2026-08-20"]
        assert _read(ledger)[0]["outcome"] == OUTCOME_SUPERSEDED

    def test_bullish_signal_supersedes_a_pending_bearish_one(self, ledger):
        pr._append_row(_row(direction="bearish", stop_loss="300.00", target="240.00"))
        assert pr._supersede_pending_signals("AMZN", "2026-08-26", 74.0) == ["2026-08-20"]
        assert _read(ledger)[0]["outcome"] == OUTCOME_SUPERSEDED

    def test_a_filled_opposite_direction_position_still_blocks(self, ledger):
        """Direction is ignored for SUPERSEDE, never for the filled check —
        real exposure blocks whichever way it points."""
        pr._append_row(_row(direction="bearish", fill_date="2026-08-21", fill_price="285.00"))
        assert pr._supersede_pending_signals("AMZN", "2026-08-26", 74.0) == []
        assert _read(ledger)[0]["outcome"] == ""

    def test_the_flip_is_recorded_rather_than_silently_discarded(self, ledger):
        """Previously the newer opposite-direction signal was just dropped and
        the flip left no trace. The note makes flips countable."""
        pr._append_row(_row(direction="bullish"))
        pr._supersede_pending_signals("AMZN", "2026-08-26", 74.0)
        row = _read(ledger)[0]
        assert row["direction"] == "bullish"      # the cancelled row keeps its own direction
        assert "74.0" in row["sizing_note"]       # ...and records what replaced it


class TestUnfundedClosedRowsExcludedFromPerformance:
    """
    A row can resolve a real directional call and still never deploy a cent —
    its best structure cost more than the risk budget allowed, so it sized to
    0 units (see paper_runner's sizing_note).

    Live case: LLY 2026-08-12 closed 2026-08-26 as a time_stop at -0.264R with
    position_size=0 and pnl_dollars=0.00. Counted by outcome alone it lands in
    the win-rate DENOMINATOR and — being unprofitable — not the numerator,
    taking the paper track from 0-of-2 to 0-of-3 on a trade that could not have
    won or lost a dollar.
    """

    LLY = {"outcome": "time_stop", "position_size": "0", "pnl_dollars": "0.00"}
    REAL = {"outcome": "loss", "position_size": "3", "pnl_dollars": "-43.14"}

    def test_size_zero_row_is_not_funded(self):
        from shared.utils.trade_outcomes import is_funded
        assert not is_funded(self.LLY)
        assert is_funded(self.REAL)

    def test_size_zero_row_is_still_scored_by_outcome(self):
        """It resolved a real directional call — that part is genuine."""
        from shared.utils.trade_outcomes import is_scored
        assert is_scored(self.LLY["outcome"])

    def test_but_it_is_not_a_performance_row(self):
        from shared.utils.trade_outcomes import is_performance_row
        assert not is_performance_row(self.LLY)
        assert is_performance_row(self.REAL)

    def test_win_rate_denominator_excludes_it(self):
        from shared.utils.trade_outcomes import is_performance_row
        closed = [self.REAL, self.LLY, {"outcome": "earnings_exit", "position_size": "3"}]
        assert len([r for r in closed if is_performance_row(r)]) == 2

    def test_expired_and_superseded_are_also_excluded(self):
        from shared.utils.trade_outcomes import is_performance_row
        for outcome in (OUTCOME_EXPIRED, OUTCOME_SUPERSEDED):
            assert not is_performance_row({"outcome": outcome, "position_size": "5"})

    def test_malformed_position_size_is_treated_as_unfunded(self):
        from shared.utils.trade_outcomes import is_funded
        for bad in ("", None, "n/a", "abc"):
            assert not is_funded({"position_size": bad})
