"""
Tests for paper_trading/paper_updater.py::_find_fill — added after AVGO/ABBV
signals on 2026-08-14 showed the gap this closes: their entry zones (breakout/
breakdown trigger prices from shared/utils/risk_reward.py's compute_entry_zone)
sat well above/below where the stock actually traded that day, but
update_paper_trades() was tracking stop/target against them anyway as if the
order had already filled at signal time. _find_fill answers "did price ever
actually trade into the zone" before that tracking is allowed to start.
"""

import pandas as pd

from paper_trading.paper_updater import _find_fill


def _bars(rows):
    """rows: list of (date_str, open, high, low, close)."""
    df = pd.DataFrame(
        [{"Open": o, "High": h, "Low": lo, "Close": c} for _, o, h, lo, c in rows],
        index=pd.to_datetime([d for d, *_ in rows]),
    )
    return df


class TestFindFillBullish:
    def test_fills_same_bar_when_high_reaches_zone(self):
        # Breakout zone at 428.82-436.64 (AVGO-shaped); high clears the lower bound.
        df = _bars([("2026-08-17", 411.96, 430.00, 388.50, 425.00)])
        result = _find_fill(df, entry_zone_lower=428.82, entry_zone_upper=436.64)
        assert "fill_date" in result
        assert len(result["bars_from_fill"]) == 1

    def test_fills_on_a_later_bar_within_window(self):
        df = _bars([
            ("2026-08-17", 412, 415, 388, 393),   # zone not reached
            ("2026-08-18", 415, 420, 410, 418),   # zone not reached
            ("2026-08-19", 420, 432, 415, 430),   # zone reached (high >= 428.82)
        ])
        result = _find_fill(df, entry_zone_lower=428.82, entry_zone_upper=436.64)
        assert result["fill_date"] == pd.Timestamp("2026-08-19")
        # bars_from_fill starts at the fill bar, not the whole window
        assert len(result["bars_from_fill"]) == 1

    def test_expires_after_window_days_never_reaching_zone(self):
        # AVGO actually did this: kept falling, never got near $428.82.
        df = _bars([
            (f"2026-08-{17 + i}", 410 - i, 415 - i, 388 - i, 393 - i)
            for i in range(5)
        ])
        result = _find_fill(df, entry_zone_lower=428.82, entry_zone_upper=436.64, window_days=5)
        assert result.get("expired") is True
        assert result["last_date"] == df.index[-1]

    def test_still_pending_inside_window(self):
        df = _bars([("2026-08-17", 412, 415, 388, 393)])
        result = _find_fill(df, entry_zone_lower=428.82, entry_zone_upper=436.64, window_days=5)
        assert result is None

    def test_gap_up_through_zone_still_registers_fill(self):
        df = _bars([("2026-08-17", 440, 445, 439, 442)])
        result = _find_fill(df, entry_zone_lower=428.82, entry_zone_upper=436.64)
        assert result is not None
        assert "fill_date" in result


class TestFindFillBearish:
    def test_fills_when_low_reaches_zone_upper(self):
        # Breakdown zone below current price; low dips into it.
        df = _bars([("2026-08-17", 100, 101, 94, 95)])
        result = _find_fill(df, entry_zone_lower=90, entry_zone_upper=95.5, direction="bearish")
        assert result is not None
        assert "fill_date" in result

    def test_still_pending_when_low_never_reaches_zone(self):
        df = _bars([("2026-08-17", 100, 101, 97, 98)])
        result = _find_fill(df, entry_zone_lower=90, entry_zone_upper=95.5, direction="bearish", window_days=5)
        assert result is None

    def test_expires_after_window_days(self):
        df = _bars([(f"2026-08-{17 + i}", 100, 101, 97, 98) for i in range(5)])
        result = _find_fill(df, entry_zone_lower=90, entry_zone_upper=95.5, direction="bearish", window_days=5)
        assert result.get("expired") is True
