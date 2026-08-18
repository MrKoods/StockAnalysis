"""
Tests for the paper_trades.csv race condition fix.

Before this fix: paper_updater.py's update_paper_trades() loaded the whole
CSV into memory, spent minutes on per-ticker yfinance calls, then rewrote the
ENTIRE file from that stale in-memory snapshot. Any row paper_runner.py
appended (a brand-new qualifying signal, complete with its own Discord alert
already sent) during that window was silently erased — no error, no trace —
since paper_updater.py's rewrite had no idea it existed. This is the ledger
every win-rate/Sharpe/EV number in this project is computed from.

Fixed with a lock shared between both modules (paper_runner.PAPER_TRADES_
LOCK_FILE) plus a merge step in _save_trades: right before writing, it
re-reads the live file and folds in any row not present in its own snapshot
(keyed the same way paper_runner.py's own dedup already does — by
(signal_date, ticker)), rather than blindly overwriting from the stale copy.
"""

import threading
import time

import pytest

import paper_trading.paper_runner as pr
import paper_trading.paper_updater as pu


def _row(signal_date="2026-08-17", ticker="NVDA", **overrides):
    row = {col: "" for col in pr._CSV_COLUMNS}
    row.update({"signal_date": signal_date, "ticker": ticker})
    row.update(overrides)
    return row


@pytest.fixture(autouse=True)
def _isolate_csv(tmp_path, monkeypatch):
    csv_path = tmp_path / "paper_trades.csv"
    lock_path = tmp_path / "paper_trades.csv.lock"
    monkeypatch.setattr(pr, "PAPER_TRADES_CSV", csv_path)
    monkeypatch.setattr(pr, "PAPER_TRADES_LOCK_FILE", lock_path)
    monkeypatch.setattr(pu, "PAPER_TRADES_CSV", csv_path)
    monkeypatch.setattr(pu, "PAPER_TRADES_LOCK_FILE", lock_path)
    return csv_path


class TestRowKey:
    def test_same_signal_date_and_ticker_is_same_key(self):
        a = _row(signal_date="2026-08-17", ticker="NVDA")
        b = _row(signal_date="2026-08-17", ticker="NVDA", confidence="99")
        assert pu._row_key(a) == pu._row_key(b)

    def test_different_ticker_is_different_key(self):
        a = _row(ticker="NVDA")
        b = _row(ticker="AMD")
        assert pu._row_key(a) != pu._row_key(b)


class TestSaveTradesMergesConcurrentAppend:
    def test_row_appended_after_load_survives_the_rewrite(self, tmp_path):
        """
        Direct simulation of the exact failure mode: paper_updater.py's
        in-memory snapshot doesn't know about a row paper_runner.py appended
        to the live file after the snapshot was taken. The fixed
        _save_trades must still preserve it.
        """
        # Snapshot as paper_updater.py would have loaded it (NVDA only).
        stale_snapshot = [_row(ticker="NVDA", outcome="win")]

        # Simulate paper_runner.py appending a brand-new signal (AMD) to the
        # live file WHILE paper_updater.py was still doing its yfinance walk
        # — i.e., after the snapshot was taken but before _save_trades runs.
        pr._append_row(_row(ticker="AMD"))

        pu._save_trades(stale_snapshot)

        final = pu._load_trades()
        tickers = {t["ticker"] for t in final}
        assert tickers == {"NVDA", "AMD"}
        # The updater's own change (NVDA's outcome) must also be present.
        nvda_row = next(t for t in final if t["ticker"] == "NVDA")
        assert nvda_row["outcome"] == "win"

    def test_update_to_an_existing_row_is_not_duplicated_by_the_merge(self, tmp_path):
        # Live file already has NVDA (open), matching the snapshot exactly.
        pr._append_row(_row(ticker="NVDA"))
        snapshot = pu._load_trades()
        snapshot[0]["outcome"] = "win"  # simulate the outcome update in place

        pu._save_trades(snapshot)

        final = pu._load_trades()
        assert len(final) == 1
        assert final[0]["outcome"] == "win"


class TestConcurrentAppendAndSaveUnderRealThreading:
    def test_no_row_is_lost_under_real_thread_contention(self, tmp_path):
        """
        The real-world scenario, exercised with actual thread concurrency
        rather than just sequenced calls: paper_updater.py's save (holding a
        stale snapshot) races against several paper_runner.py appends firing
        while it's mid-save. None may be lost.
        """
        pr._append_row(_row(ticker="NVDA", outcome="win"))
        stale_snapshot = pu._load_trades()

        new_signals = [_row(ticker=t) for t in ("AMD", "AVGO", "TSM", "MU")]

        def do_save():
            pu._save_trades(stale_snapshot)

        def do_append(row):
            time.sleep(0.001)
            pr._append_row(row)

        threads = [threading.Thread(target=do_save)]
        threads += [threading.Thread(target=do_append, args=(row,)) for row in new_signals]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        final_tickers = {t["ticker"] for t in pu._load_trades()}
        assert final_tickers == {"NVDA", "AMD", "AVGO", "TSM", "MU"}
