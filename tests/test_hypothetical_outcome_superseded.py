"""
Tests for wiring hypothetical (never-filled opportunity-cost) tracking onto
superseded rows, not just expired ones. Before this, _update_hypothetical_outcomes
only ever picked up outcome == "expired", so a cancelled-for-a-newer-signal
row (the majority of all rank-track signals) never got a counterfactual —
there was no data on whether replacing it was the right call.
"""

import pandas as pd
import pytest

import paper_trading.paper_updater as pu
from shared.utils.trade_outcomes import HYPOTHETICAL_NO_ENTRY
from paper_trading.paper_trade_metrics import (
    compute_expired_signal_opportunity_cost,
    compute_superseded_signal_opportunity_cost,
)


def _bars(rows):
    """rows: list of (date_str, open, high, low, close)."""
    df = pd.DataFrame(
        [{"Open": o, "High": h, "Low": lo, "Close": c} for _, o, h, lo, c in rows],
        index=pd.to_datetime([d for d, *_ in rows]),
    )
    return df


def _row(**overrides):
    row = {
        "ticker": "NVDA",
        "signal_date": "2026-08-10",
        "direction": "bullish",
        "entry_price": "100.00",
        "stop_loss": "95.00",
        "target": "115.00",
        "outcome": "",
        "hypothetical_outcome": "",
        "actual_dollar_risk": "500",
        "dollar_risk": "500",
    }
    row.update(overrides)
    return row


class TestUpdateHypotheticalOutcomesCoversSuperseded:
    def test_resolves_superseded_rows_not_just_expired(self, monkeypatch):
        # Price gaps straight through target on the first bar after signal_date.
        bars = _bars([("2026-08-11", 101, 116, 100, 115)])
        monkeypatch.setattr(pu, "_download_ohlcv", lambda ticker, start: bars)

        trades = [_row(outcome="superseded")]
        resolved = pu._update_hypothetical_outcomes(trades, time_stop_day=10, min_progress_pct=0.30)

        assert resolved == 1
        assert trades[0]["hypothetical_outcome"] == "win"

    def test_still_resolves_expired_rows_as_before(self, monkeypatch):
        bars = _bars([("2026-08-11", 101, 116, 100, 115)])
        monkeypatch.setattr(pu, "_download_ohlcv", lambda ticker, start: bars)

        trades = [_row(outcome="expired")]
        resolved = pu._update_hypothetical_outcomes(trades, time_stop_day=10, min_progress_pct=0.30)

        assert resolved == 1
        assert trades[0]["hypothetical_outcome"] == "win"

    def test_ignores_rows_with_a_real_terminal_outcome(self, monkeypatch):
        bars = _bars([("2026-08-11", 101, 116, 100, 115)])
        monkeypatch.setattr(pu, "_download_ohlcv", lambda ticker, start: bars)

        trades = [_row(outcome="loss")]
        resolved = pu._update_hypothetical_outcomes(trades, time_stop_day=10, min_progress_pct=0.30)

        assert resolved == 0
        assert trades[0]["hypothetical_outcome"] == ""

    def test_leaves_already_resolved_hypothetical_alone(self, monkeypatch):
        monkeypatch.setattr(
            pu, "_download_ohlcv",
            lambda ticker, start: (_ for _ in ()).throw(AssertionError("should not re-fetch a resolved row")),
        )
        trades = [_row(outcome="superseded", hypothetical_outcome="win")]
        resolved = pu._update_hypothetical_outcomes(trades, time_stop_day=10, min_progress_pct=0.30)
        assert resolved == 0


class TestHypotheticalEntersAtNextOpen:
    """
    2026-09-28: the hypothetical used to "fill" at the signal-time
    entry_price — the breakout trigger, often a price the stock never traded.
    For a trigger far from the market the stop sat on the far side of the
    first Open too, so the row booked an instant loss (104 of 115 resolved
    superseded hypotheticals live). Entry is now the next session's Open.
    """

    def test_r_is_measured_from_the_open_not_entry_price(self, monkeypatch):
        # Opens at 98 (below the 100 trigger), closes day 1 at the 115 target.
        bars = _bars([("2026-08-11", 98, 116, 97, 115)])
        monkeypatch.setattr(pu, "_download_ohlcv", lambda ticker, start: bars)
        trades = [_row(outcome="superseded")]

        assert pu._update_hypothetical_outcomes(trades, time_stop_day=10, min_progress_pct=0.30) == 1
        assert trades[0]["hypothetical_outcome"] == "win"
        # (115 - 98) / (98 - 95), not (115 - 100) / (100 - 95) = 3.0
        assert float(trades[0]["hypothetical_achieved_rr"]) == pytest.approx(17 / 3, abs=1e-3)

    def test_open_already_through_the_stop_is_no_entry_not_a_loss(self, monkeypatch):
        # The AMZN 2026-08-26 shape: bullish trigger 100 / stop 95, stock at 90.
        bars = _bars([("2026-08-11", 90, 91, 88, 89)])
        monkeypatch.setattr(pu, "_download_ohlcv", lambda ticker, start: bars)
        trades = [_row(outcome="superseded")]

        assert pu._update_hypothetical_outcomes(trades, time_stop_day=10, min_progress_pct=0.30) == 1
        assert trades[0]["hypothetical_outcome"] == HYPOTHETICAL_NO_ENTRY
        assert trades[0]["hypothetical_achieved_rr"] == ""

    def test_bearish_open_already_above_the_stop_is_no_entry(self, monkeypatch):
        bars = _bars([("2026-08-11", 106, 107, 104, 105)])
        monkeypatch.setattr(pu, "_download_ohlcv", lambda ticker, start: bars)
        trades = [_row(outcome="expired", direction="bearish", stop_loss="105.00", target="85.00")]

        assert pu._update_hypothetical_outcomes(trades, time_stop_day=10, min_progress_pct=0.30) == 1
        assert trades[0]["hypothetical_outcome"] == HYPOTHETICAL_NO_ENTRY

    def test_no_entry_is_terminal(self, monkeypatch):
        monkeypatch.setattr(
            pu, "_download_ohlcv",
            lambda ticker, start: (_ for _ in ()).throw(AssertionError("should not re-fetch")),
        )
        trades = [_row(outcome="superseded", hypothetical_outcome=HYPOTHETICAL_NO_ENTRY)]
        assert pu._update_hypothetical_outcomes(trades, time_stop_day=10, min_progress_pct=0.30) == 0


class TestSupersededOpportunityCostMetric:
    def test_no_entry_rows_excluded_from_win_rate_and_avg_r(self, tmp_path):
        rows = [
            {"outcome": "superseded", "hypothetical_outcome": "win",
             "hypothetical_pnl_pct": "0.10", "hypothetical_achieved_rr": "3.0"},
            {"outcome": "superseded", "hypothetical_outcome": HYPOTHETICAL_NO_ENTRY},
            {"outcome": "superseded", "hypothetical_outcome": HYPOTHETICAL_NO_ENTRY},
        ]
        csv_path = self._isolate_csv(tmp_path, None, rows)
        result = compute_superseded_signal_opportunity_cost(csv_path)

        assert result["total_superseded"] == 3
        assert result["resolved_count"] == 1
        assert result["no_entry_count"] == 2
        assert result["pending_count"] == 0
        assert result["hypothetical_win_rate"] == 1.0
        assert result["avg_hypothetical_r"] == 3.0

    def _isolate_csv(self, tmp_path, monkeypatch, rows):
        csv_path = tmp_path / "paper_trades.csv"
        fieldnames = sorted({k for r in rows for k in r.keys()} | {"outcome", "hypothetical_outcome"})
        df = pd.DataFrame(rows).reindex(columns=fieldnames)
        df.to_csv(csv_path, index=False)
        return csv_path

    def test_scoped_to_superseded_only(self, tmp_path):
        rows = [
            {"outcome": "superseded", "hypothetical_outcome": "win",
             "hypothetical_pnl_pct": "0.10", "hypothetical_achieved_rr": "3.0"},
            {"outcome": "superseded", "hypothetical_outcome": "loss",
             "hypothetical_pnl_pct": "-0.05", "hypothetical_achieved_rr": "-1.0"},
            {"outcome": "expired", "hypothetical_outcome": "win",
             "hypothetical_pnl_pct": "0.10", "hypothetical_achieved_rr": "3.0"},
            {"outcome": "superseded", "hypothetical_outcome": "pending"},
            {"outcome": "loss"},
        ]
        csv_path = self._isolate_csv(tmp_path, None, rows)

        superseded_result = compute_superseded_signal_opportunity_cost(csv_path)
        expired_result = compute_expired_signal_opportunity_cost(csv_path)

        assert superseded_result["total_superseded"] == 3
        assert superseded_result["resolved_count"] == 2
        assert superseded_result["pending_count"] == 1
        assert superseded_result["hypothetical_win_rate"] == 0.5
        assert superseded_result["avg_hypothetical_r"] == 1.0  # (3.0 + -1.0) / 2

        # The one expired row must not leak into the superseded view, and
        # vice versa — the two are deliberately kept from double-counting.
        assert expired_result["total_expired"] == 1
        assert expired_result["resolved_count"] == 1
