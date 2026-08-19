"""
Tests for paper_trading/paper_updater.py::_check_earnings_exit.

Signal-time earnings screening (shared/utils/earnings_calendar.py) only ever
runs once, when a signal is first generated. A trade that was 6+ days from
earnings at signal time (and so allowed to size as a plain, undefined-risk
shares position) can still be open when earnings actually lands inside its
up-to-15-day holding window. _check_earnings_exit closes that gap by
re-checking days-to-earnings on every update run and flattening an
undefined-risk position early once it ages into the same 0-5-day window that
would have forced a defined-risk structure had the signal fired that close
to the print.
"""

from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from paper_trading.paper_updater import _check_earnings_exit


def _bars(rows):
    """rows: list of (date_str, open, high, low, close)."""
    df = pd.DataFrame(
        [{"Open": o, "High": h, "Low": lo, "Close": c} for _, o, h, lo, c in rows],
        index=pd.to_datetime([d for d, *_ in rows]),
    )
    return df


def _trade(position_type="shares", ticker="NVDA"):
    return {"ticker": ticker, "position_type": position_type}


class TestCheckEarningsExit:
    def test_flattens_shares_position_inside_5_day_window(self):
        bars = _bars([("2026-08-14", 227, 228, 225, 226), ("2026-08-19", 220, 221, 218, 219.25)])
        earnings_date = datetime.now(timezone.utc) + timedelta(days=3)
        result = _check_earnings_exit(_trade(), bars, earnings_date)
        assert result is not None
        assert result["outcome"] == "earnings_exit"
        assert result["exit_price"] == pytest.approx(219.25)
        assert result["exit_date"] == "2026-08-19"
        assert result["holding_days"] == 2

    def test_flattens_on_earnings_day_itself(self):
        bars = _bars([("2026-08-19", 220, 221, 218, 219.25)])
        earnings_date = datetime.now(timezone.utc)
        result = _check_earnings_exit(_trade(), bars, earnings_date)
        assert result["outcome"] == "earnings_exit"

    def test_leaves_position_open_when_earnings_far_out(self):
        bars = _bars([("2026-08-19", 220, 221, 218, 219.25)])
        earnings_date = datetime.now(timezone.utc) + timedelta(days=12)
        assert _check_earnings_exit(_trade(), bars, earnings_date) is None

    def test_leaves_options_structure_open_even_inside_window(self):
        # Defined-risk structures already have a capped max loss — nothing
        # extra to protect against a gap, so they ride through untouched.
        bars = _bars([("2026-08-19", 220, 221, 218, 219.25)])
        earnings_date = datetime.now(timezone.utc) + timedelta(days=3)
        result = _check_earnings_exit(_trade(position_type="options"), bars, earnings_date)
        assert result is None

    def test_no_earnings_date_leaves_position_open(self):
        bars = _bars([("2026-08-19", 220, 221, 218, 219.25)])
        assert _check_earnings_exit(_trade(), bars, None) is None

    def test_missing_position_type_defaults_to_shares(self):
        # Rows logged before position_type existed in the CSV schema should
        # still get the same undefined-risk protection, not silently skip it.
        bars = _bars([("2026-08-19", 220, 221, 218, 219.25)])
        earnings_date = datetime.now(timezone.utc) + timedelta(days=3)
        trade = {"ticker": "NVDA"}
        result = _check_earnings_exit(trade, bars, earnings_date)
        assert result["outcome"] == "earnings_exit"

    def test_empty_bars_leaves_position_open(self):
        earnings_date = datetime.now(timezone.utc) + timedelta(days=3)
        assert _check_earnings_exit(_trade(), pd.DataFrame(), earnings_date) is None
