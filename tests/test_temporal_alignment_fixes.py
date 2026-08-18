"""
Tests for two fixes in shared/utils/temporal_alignment.py:

1. classify_timezone_window() hardcoded a fixed UTC-5 (EST) offset year-round,
   off by an hour for roughly 8 months/year during EDT (UTC-4, mid-March to
   early November) — true 9:30am ET market open (13:30 UTC in EDT) used to
   classify as "european" instead of "us_session".

2. align_signals_to_price_bars() only matched a signal to a price bar via an
   exact same-calendar-date comparison — after-hours news (4pm-8pm ET, a very
   common corporate-release window including after-close earnings) got
   attributed to the day that already closed instead of the next session,
   and a signal dated on a non-trading day (weekend/holiday) matched nothing
   and was silently dropped rather than forward-filled to the next open bar.

Both were confirmed dead code at the time of the audit (no live caller), so
these tests protect correctness for whenever this module is wired in.
"""

from datetime import datetime, timezone

import pandas as pd

from shared.utils.temporal_alignment import (
    classify_timezone_window,
    align_signals_to_price_bars,
    _assign_trading_day,
)


class TestClassifyTimezoneWindowDST:
    def test_market_open_classifies_correctly_during_edt_summer(self):
        # 9:30am ET during EDT (UTC-4) = 13:30 UTC. The old hardcoded-EST
        # code would read this as 8:30am ET -> "european", wrong.
        ts = datetime(2026, 7, 15, 13, 30, tzinfo=timezone.utc)
        assert classify_timezone_window(ts) == "us_session"

    def test_market_open_classifies_correctly_during_est_winter(self):
        # 9:30am ET during EST (UTC-5) = 14:30 UTC.
        ts = datetime(2026, 1, 15, 14, 30, tzinfo=timezone.utc)
        assert classify_timezone_window(ts) == "us_session"

    def test_after_hours_boundary_correct_during_edt(self):
        # 4pm ET during EDT = 20:00 UTC -> us_after_hours begins.
        ts = datetime(2026, 7, 15, 20, 0, tzinfo=timezone.utc)
        assert classify_timezone_window(ts) == "us_after_hours"

    def test_same_wall_clock_hour_classifies_differently_across_dst(self):
        """The exact bug: identical UTC hour, different real ET time
        depending on the season — must classify differently."""
        winter = datetime(2026, 1, 15, 13, 30, tzinfo=timezone.utc)  # 8:30am ET (EST)
        summer = datetime(2026, 7, 15, 13, 30, tzinfo=timezone.utc)  # 9:30am ET (EDT)
        assert classify_timezone_window(winter) != classify_timezone_window(summer)
        assert classify_timezone_window(winter) == "european"
        assert classify_timezone_window(summer) == "us_session"

    def test_asian_premarket_wraps_midnight_et(self):
        # 9pm ET (EDT) = 01:00 UTC next day.
        assert classify_timezone_window(datetime(2026, 7, 15, 1, 0, tzinfo=timezone.utc)) == "asian_pre_market"
        # 2am ET (EDT) = 06:00 UTC.
        assert classify_timezone_window(datetime(2026, 7, 15, 6, 0, tzinfo=timezone.utc)) == "asian_pre_market"


class TestAssignTradingDay:
    def _bars(self, dates):
        return pd.DatetimeIndex(pd.to_datetime(dates))

    def test_us_session_signal_assigned_to_same_day(self):
        bars = self._bars(["2026-08-17", "2026-08-18"])
        ts = datetime(2026, 8, 17, 15, 0, tzinfo=timezone.utc)  # 11am ET, in-session
        assert _assign_trading_day(ts, bars) == pd.Timestamp("2026-08-17")

    def test_after_hours_signal_rolls_to_next_trading_day(self):
        bars = self._bars(["2026-08-17", "2026-08-18"])
        # 5pm ET on 8/17 (after close) = 21:00 UTC.
        ts = datetime(2026, 8, 17, 21, 0, tzinfo=timezone.utc)
        assert _assign_trading_day(ts, bars) == pd.Timestamp("2026-08-18")

    def test_weekend_signal_forward_fills_to_monday(self):
        # Saturday news, only Monday's bar exists in the index.
        bars = self._bars(["2026-08-17"])  # a Monday
        ts = datetime(2026, 8, 15, 15, 0, tzinfo=timezone.utc)  # Saturday, mid-day
        assert _assign_trading_day(ts, bars) == pd.Timestamp("2026-08-17")

    def test_signal_after_last_available_bar_returns_none(self):
        bars = self._bars(["2026-08-17"])
        ts = datetime(2026, 8, 20, 15, 0, tzinfo=timezone.utc)
        assert _assign_trading_day(ts, bars) is None


class TestAlignSignalsToPriceBars:
    def _bars(self, dates):
        return pd.DatetimeIndex(pd.to_datetime(dates))

    def test_after_hours_news_counts_toward_next_session_not_the_closed_one(self):
        bars = self._bars(["2026-08-17", "2026-08-18"])
        signals = [{
            # After-close earnings release: 5pm ET on 8/17 = 21:00 UTC.
            "timestamp_utc": "2026-08-17T21:00:00+00:00",
            "sentiment": "bullish",
        }]
        df = align_signals_to_price_bars(signals, bars)
        assert df.loc[pd.Timestamp("2026-08-18"), "total"] == 1
        assert df.loc[pd.Timestamp("2026-08-17"), "total"] == 0

    def test_weekend_dated_signal_is_not_silently_dropped(self):
        bars = self._bars(["2026-08-17"])  # Monday only
        signals = [{
            "timestamp_utc": "2026-08-15T15:00:00+00:00",  # Saturday
            "sentiment": "bearish",
        }]
        df = align_signals_to_price_bars(signals, bars)
        assert df.loc[pd.Timestamp("2026-08-17"), "total"] == 1
        assert df.loc[pd.Timestamp("2026-08-17"), "bearish_count"] == 1

    def test_in_session_news_still_counts_same_day(self):
        bars = self._bars(["2026-08-17", "2026-08-18"])
        signals = [{
            "timestamp_utc": "2026-08-17T15:00:00+00:00",  # 11am ET
            "sentiment": "bullish",
        }]
        df = align_signals_to_price_bars(signals, bars)
        assert df.loc[pd.Timestamp("2026-08-17"), "total"] == 1

    def test_signal_with_no_matching_or_future_bar_does_not_crash(self):
        bars = self._bars(["2026-08-17"])
        signals = [{"timestamp_utc": "2026-08-25T15:00:00+00:00", "sentiment": "bullish"}]
        df = align_signals_to_price_bars(signals, bars)
        assert df.loc[pd.Timestamp("2026-08-17"), "total"] == 0
