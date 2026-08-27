"""
Tests for paper_trading/paper_updater.py's mark-to-market / dollar-risk-basis
code (commit c6e0d1b, 2026-08-22) — added open-position mark_price/mark_date/
unrealized_rr/unrealized_pnl_dollars, and re-anchored actual_dollar_risk to
the real fill price for shares positions. That commit shipped with ZERO
tests despite fixing a real ~30% dollar-risk drift bug, flagged as the
single highest-risk untested code in the repo by the 2026-08-22 full model
audit — this closes that gap.

Two scenarios exercised via the real update_paper_trades() end to end
(mocked _download_ohlcv/fetch_next_earnings_date, isolated CSV/lock paths):

1. Mark-to-market for a still-open position (no entry zone, fill_date
   already stamped, so only the mark-to-market branch is exercised, not the
   once-only fill/re-anchor block).
2. The fill-price re-anchor itself (blank fill_date, a real entry zone that
   fills away from the zone midpoint), which needs a fresh fill to fire.

Plus direct unit tests for _fmt_dollars, the small pure formatting helper
this same commit introduced.
"""

import pandas as pd
import pytest

import paper_trading.paper_runner as pr
import paper_trading.paper_updater as pu
from paper_trading.paper_updater import _fmt_dollars, update_paper_trades


def _row(**overrides):
    row = {col: "" for col in pr._CSV_COLUMNS}
    row.update({
        "signal_date": "2026-08-10",
        "ticker": "NVDA",
        "direction": "bullish",
        "entry_price": "100.00",
        "stop_loss": "95.00",
        "target": "115.00",
        "position_type": "shares",
        "position_size": "10",
        "dollar_risk": "75.00",
        "actual_dollar_risk": "50.00",
        "outcome": "",
    })
    row.update(overrides)
    return row


def _bars(rows):
    """rows: list of (date_str, open, high, low, close)."""
    return pd.DataFrame(
        [{"Open": o, "High": h, "Low": lo, "Close": c} for _, o, h, lo, c in rows],
        index=pd.to_datetime([d for d, *_ in rows]),
    )


@pytest.fixture(autouse=True)
def _isolate_csv(tmp_path, monkeypatch):
    csv_path = tmp_path / "paper_trades.csv"
    lock_path = tmp_path / "paper_trades.csv.lock"
    monkeypatch.setattr(pr, "PAPER_TRADES_CSV", csv_path)
    monkeypatch.setattr(pr, "PAPER_TRADES_LOCK_FILE", lock_path)
    monkeypatch.setattr(pu, "PAPER_TRADES_CSV", csv_path)
    monkeypatch.setattr(pu, "PAPER_TRADES_LOCK_FILE", lock_path)
    monkeypatch.setattr(pu, "fetch_next_earnings_date", lambda ticker: None)
    return csv_path


def _run_with_bars(bars: pd.DataFrame, monkeypatch):
    monkeypatch.setattr(pu, "_download_ohlcv", lambda ticker, start: bars)
    update_paper_trades()
    trades = pu._load_trades()
    assert len(trades) == 1
    return trades[0]


class TestMarkToMarketStillOpen:
    """No entry zone (falls back to signal-time entry_price as the P&L
    basis) and fill_date already stamped, so only the mark-to-market branch
    runs — isolates it from the fill/re-anchor block below."""

    def test_bullish_gain_computes_positive_unrealized_rr_and_dollars(self, monkeypatch):
        pr._append_row(_row(
            direction="bullish", entry_price="100.00", stop_loss="95.00",
            fill_date="2026-08-11", fill_price="100.00", actual_dollar_risk="50.00",
        ))
        # risk_per_r = |100-95| = 5; mark=104 -> price_change=+4 -> unrealized_rr=0.8
        bars = _bars([("2026-08-12", 101, 105, 100, 104)])
        trade = _run_with_bars(bars, monkeypatch)

        assert trade["mark_price"] == "104.00"
        assert trade["mark_date"] == "2026-08-12"
        assert float(trade["unrealized_rr"]) == pytest.approx(0.8)
        assert float(trade["unrealized_pnl_dollars"]) == pytest.approx(0.8 * 50.00)
        assert trade["outcome"] == ""  # still open, not closed

    def test_bearish_position_flips_the_price_change_sign(self, monkeypatch):
        pr._append_row(_row(
            direction="bearish", entry_price="100.00", stop_loss="105.00", target="85.00",
            fill_date="2026-08-11", fill_price="100.00", actual_dollar_risk="50.00",
        ))
        # Bearish: price_change = entry - mark. mark=97 -> price_change=+3 -> rr=0.6
        bars = _bars([("2026-08-12", 99, 100, 96, 97)])
        trade = _run_with_bars(bars, monkeypatch)

        assert trade["mark_price"] == "97.00"
        assert float(trade["unrealized_rr"]) == pytest.approx(0.6)
        assert float(trade["unrealized_pnl_dollars"]) == pytest.approx(0.6 * 50.00)

    def test_bearish_adverse_move_gives_negative_unrealized_rr(self, monkeypatch):
        pr._append_row(_row(
            direction="bearish", entry_price="100.00", stop_loss="105.00", target="85.00",
            fill_date="2026-08-11", fill_price="100.00", actual_dollar_risk="50.00",
        ))
        # Price rose against a bearish position: mark=103 -> price_change=-3 -> rr=-0.6
        bars = _bars([("2026-08-12", 101, 103.5, 100, 103)])
        trade = _run_with_bars(bars, monkeypatch)
        assert float(trade["unrealized_rr"]) == pytest.approx(-0.6)
        assert float(trade["unrealized_pnl_dollars"]) == pytest.approx(-0.6 * 50.00)

    def test_zero_risk_per_r_defaults_to_zero_rr_without_crashing(self, monkeypatch):
        """entry_price == stop_loss is degenerate (shouldn't happen from a
        real signal, but a malformed/legacy row could have it) — must not
        raise a ZeroDivisionError. Low kept strictly above the degenerate
        100.00 stop so the trade stays open rather than immediately
        stopping out (Low <= stop_loss is a real, correct stop hit)."""
        pr._append_row(_row(
            direction="bullish", entry_price="100.00", stop_loss="100.00", target="115.00",
            fill_date="2026-08-11", fill_price="100.00", actual_dollar_risk="50.00",
        ))
        bars = _bars([("2026-08-12", 101, 105, 100.5, 104)])
        trade = _run_with_bars(bars, monkeypatch)
        assert trade["outcome"] == ""  # confirms still open, not accidentally stopped out
        assert float(trade["unrealized_rr"]) == pytest.approx(0.0)

    def test_missing_dollar_risk_leaves_unrealized_pnl_dollars_blank(self, monkeypatch):
        """Both actual_dollar_risk and dollar_risk blank (e.g. a very old
        row) — unrealized_pnl_dollars must stay blank, not "0.00" or crash,
        since there's no real risk basis to multiply against."""
        pr._append_row(_row(
            direction="bullish", entry_price="100.00", stop_loss="95.00",
            fill_date="2026-08-11", fill_price="100.00",
            actual_dollar_risk="", dollar_risk="",
        ))
        bars = _bars([("2026-08-12", 101, 105, 100, 104)])
        trade = _run_with_bars(bars, monkeypatch)
        assert trade["mark_price"] == "104.00"  # mark itself still computed
        assert trade["unrealized_pnl_dollars"] == ""

    def test_falls_back_to_dollar_risk_when_actual_dollar_risk_blank(self, monkeypatch):
        pr._append_row(_row(
            direction="bullish", entry_price="100.00", stop_loss="95.00",
            fill_date="2026-08-11", fill_price="100.00",
            actual_dollar_risk="", dollar_risk="75.00",
        ))
        bars = _bars([("2026-08-12", 101, 105, 100, 104)])
        trade = _run_with_bars(bars, monkeypatch)
        # unrealized_rr = 4/5 = 0.8; falls back to dollar_risk (75.00), not actual_dollar_risk
        assert float(trade["unrealized_pnl_dollars"]) == pytest.approx(0.8 * 75.00)


class TestFillPriceReanchor:
    """Blank fill_date + a real entry zone that fills away from the zone
    midpoint (entry_price) — exercises the once-only fill-stamp/re-anchor
    block (paper_updater.py ~576-607)."""

    def test_shares_position_reanchors_actual_dollar_risk_to_real_fill_price(self, monkeypatch):
        pr._append_row(_row(
            direction="bullish", entry_price="102.00", stop_loss="95.00", target="130.00",
            entry_zone_lower="101.00", entry_zone_upper="103.00",
            position_type="shares", position_size="10",
            fill_date="", fill_price="", actual_dollar_risk="70.00",  # signal-time (midpoint-based) value
        ))
        # Gaps up through the zone -> fills at the bar's Open (104), not the 102 midpoint.
        bars = _bars([("2026-08-11", 104, 106, 103.5, 105)])
        trade = _run_with_bars(bars, monkeypatch)

        assert trade["fill_date"] == "2026-08-11"
        assert trade["fill_price"] == "104.00"
        # Re-anchored: 10 shares * |104 - 95| = 90.00, not the stale 70.00.
        assert trade["actual_dollar_risk"] == "90.00"

    def test_options_position_leaves_actual_dollar_risk_untouched(self, monkeypatch):
        """Options structures' actual_dollar_risk is a defined max-loss/
        premium figure, not price*shares — the re-anchor must not touch it."""
        pr._append_row(_row(
            direction="bullish", entry_price="102.00", stop_loss="95.00", target="130.00",
            entry_zone_lower="101.00", entry_zone_upper="103.00",
            position_type="long_call", position_size="2",
            fill_date="", fill_price="", actual_dollar_risk="211.46",
        ))
        bars = _bars([("2026-08-11", 104, 106, 103.5, 105)])
        trade = _run_with_bars(bars, monkeypatch)
        assert trade["fill_price"] == "104.00"
        assert trade["actual_dollar_risk"] == "211.46"  # unchanged

    def test_zero_shares_skips_the_reanchor(self, monkeypatch):
        pr._append_row(_row(
            direction="bullish", entry_price="102.00", stop_loss="95.00", target="130.00",
            entry_zone_lower="101.00", entry_zone_upper="103.00",
            position_type="shares", position_size="0", actual_dollar_risk="0.00",
        ))
        bars = _bars([("2026-08-11", 104, 106, 103.5, 105)])
        trade = _run_with_bars(bars, monkeypatch)
        assert trade["actual_dollar_risk"] == "0.00"  # untouched, not recomputed off 0 shares

    def test_malformed_position_size_does_not_crash_the_run(self, monkeypatch, caplog):
        """Today position_size is always a plain int string — this proves a
        future drift (e.g. a float-formatted string) fails safe rather than
        crashing the whole update run, and now logs a warning instead of
        silently keeping the stale value with no trace of why."""
        pr._append_row(_row(
            direction="bullish", entry_price="102.00", stop_loss="95.00", target="130.00",
            entry_zone_lower="101.00", entry_zone_upper="103.00",
            position_type="shares", position_size="not_a_number", actual_dollar_risk="70.00",
        ))
        bars = _bars([("2026-08-11", 104, 106, 103.5, 105)])
        with caplog.at_level("WARNING"):
            trade = _run_with_bars(bars, monkeypatch)
        assert trade["fill_price"] == "104.00"  # fill itself still confirmed
        assert trade["actual_dollar_risk"] == "70.00"  # re-anchor silently no-ops, original value kept
        assert any("position_size" in rec.message and "re-anchor skipped" in rec.message for rec in caplog.records)


class TestFmtDollars:
    def test_positive_value_formats_normally(self):
        assert _fmt_dollars(42.5) == "42.50"

    def test_negative_value_formats_normally(self):
        assert _fmt_dollars(-42.5) == "-42.50"

    def test_negative_zero_collapses_to_plain_zero(self):
        assert _fmt_dollars(-0.0) == "0.00"

    def test_negative_rr_times_zero_risk_collapses_to_plain_zero(self):
        # The exact real scenario this exists for: a negative R-multiple
        # times a $0 actual_dollar_risk (sized-to-0 trade) is -0.0 in IEEE
        # float arithmetic.
        unrealized_rr = -0.6
        actual_dollar_risk = 0.0
        assert _fmt_dollars(unrealized_rr * actual_dollar_risk) == "0.00"


class TestZeroSizePositionGetsNoDollarMark:
    """
    A signal that sized to 0 units (risk budget too small for even one
    share/contract at this account size) never put capital at risk, so it
    must not carry a dollar mark. It used to be written as "0.00" — a
    NON-BLANK string, which is exactly what the summary's `marked` filter
    tests for, so these rows counted as real marked positions in the open
    capital-at-risk total, contradicting that filter's own "blank for
    pending/expired/zero-size rows" comment. Live on 2026-08-25, 2 of the 8
    reported "marked position(s)" — LLY and MU — were these.

    unrealized_rr is still written: the R-multiple is a genuine read on
    signal quality whatever the position's dollar size.
    """

    def test_zero_size_row_gets_rr_but_blank_dollar_mark(self, monkeypatch):
        pr._append_row(_row(
            direction="bullish", entry_price="100.00", stop_loss="95.00",
            fill_date="2026-08-11", fill_price="100.00",
            position_type="options", position_size="0",
            actual_dollar_risk="0.00", dollar_risk="75.00",
        ))
        bars = _bars([("2026-08-12", 101, 105, 100, 104)])
        trade = _run_with_bars(bars, monkeypatch)

        assert trade["mark_price"] == "104.00"
        # The R-multiple is still tracked...
        assert float(trade["unrealized_rr"]) == pytest.approx(0.8)
        # ...but there is no dollar mark to total.
        assert trade["unrealized_pnl_dollars"] == ""

    def test_zero_size_row_is_excluded_from_the_marked_total(self, monkeypatch):
        """The `marked` filter is a non-blank test — assert on that contract."""
        pr._append_row(_row(
            ticker="LLY", direction="bullish", entry_price="100.00", stop_loss="95.00",
            fill_date="2026-08-11", fill_price="100.00",
            position_type="options", position_size="0", actual_dollar_risk="0.00",
        ))
        bars = _bars([("2026-08-12", 101, 105, 100, 104)])
        trade = _run_with_bars(bars, monkeypatch)
        marked = [t for t in [trade] if (t.get("unrealized_pnl_dollars") or "").strip()]
        assert marked == []

    def test_a_normally_sized_row_still_gets_its_dollar_mark(self, monkeypatch):
        """Guard against the zero-check swallowing real positions."""
        pr._append_row(_row(
            direction="bullish", entry_price="100.00", stop_loss="95.00",
            fill_date="2026-08-11", fill_price="100.00",
            position_size="10", actual_dollar_risk="50.00",
        ))
        bars = _bars([("2026-08-12", 101, 105, 100, 104)])
        trade = _run_with_bars(bars, monkeypatch)
        assert float(trade["unrealized_pnl_dollars"]) == pytest.approx(0.8 * 50.00)


class TestRRRatioAtFill:
    """
    rr_ratio_at_fill (v2.2.105): the reward:risk the trade actually got,
    measured from the FILL rather than the signal-time zone midpoint.

    `rr_ratio` is frozen at signal time off entry_price, but the target does
    NOT move when the fill lands elsewhere — so the advertised ratio stops
    being the ratio the trade is running. Measured across the 10 filled trades
    on 2026-08-26, 8 drifted: worst were PFE 2026-08-07 (planned 3.01, really
    2.00 — a 33% overstatement) and TGT (3.00 -> 2.34). Signed and
    trade-specific, so it does not wash out across a sample.
    """

    def test_worse_fill_lowers_the_real_rr(self, monkeypatch):
        """More risk for the same target — the PFE/TGT case."""
        # A real entry zone is required: with it blank the updater takes the
        # legacy no-zone path and fills at entry_price, so no slippage happens
        # and there is nothing to measure.
        pr._append_row(_row(
            direction="bullish", entry_price="100.00", stop_loss="95.00", target="115.00",
            entry_zone_lower="99.00", entry_zone_upper="101.00", fill_date="",
            actual_dollar_risk="50.00",
        ))
        # Bar GAPS above the zone -> fill_price = max(zone_lower, open) = 102,
        # i.e. worse than planned. risk 7, reward 13 -> 1.86 vs a planned 3.00.
        bars = _bars([("2026-08-12", 102.0, 104.0, 101.5, 103.0)])
        trade = _run_with_bars(bars, monkeypatch)
        assert trade["fill_price"] == "102.00"
        assert float(trade["rr_ratio_at_fill"]) == pytest.approx(13 / 7, abs=0.01)

    def test_better_fill_raises_the_real_rr(self, monkeypatch):
        """Less risk for the same target — the MRK/ABBV/JNJ case."""
        pr._append_row(_row(
            direction="bullish", entry_price="100.00", stop_loss="95.00", target="115.00",
            entry_zone_lower="99.00", entry_zone_upper="101.00", fill_date="",
            actual_dollar_risk="50.00",
        ))
        bars = _bars([("2026-08-12", 99.0, 100.5, 98.5, 100.0)])
        trade = _run_with_bars(bars, monkeypatch)
        fill = float(trade["fill_price"])
        expected = (115.0 - fill) / (fill - 95.0)
        assert float(trade["rr_ratio_at_fill"]) == pytest.approx(expected, abs=0.01)
        assert float(trade["rr_ratio_at_fill"]) > 3.0

    def test_planned_rr_ratio_is_left_intact(self, monkeypatch):
        """Written alongside, never over — rr_ratio is what the signal was
        selected on and is worth keeping for provenance."""
        pr._append_row(_row(
            direction="bullish", entry_price="100.00", stop_loss="95.00", target="115.00",
            rr_ratio="3.00", entry_zone_lower="99.00", entry_zone_upper="101.00",
            fill_date="", actual_dollar_risk="50.00",
        ))
        bars = _bars([("2026-08-12", 102.0, 104.0, 101.5, 103.0)])
        trade = _run_with_bars(bars, monkeypatch)
        assert trade["rr_ratio"] == "3.00"
        assert trade["rr_ratio_at_fill"] != "3.00"

    def test_column_is_in_the_shared_schema(self):
        assert "rr_ratio_at_fill" in pr._CSV_COLUMNS
