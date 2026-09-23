"""
Tests for wiring hypothetical (never-filled opportunity-cost) tracking onto
superseded rows, not just expired ones. Before this, _update_hypothetical_outcomes
only ever picked up outcome == "expired", so a cancelled-for-a-newer-signal
row (the majority of all rank-track signals) never got a counterfactual —
there was no data on whether replacing it was the right call.
"""

import pandas as pd

import paper_trading.paper_updater as pu
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


class TestSupersededOpportunityCostMetric:
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
