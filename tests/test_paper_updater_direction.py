"""
Tests for paper_trading/paper_updater.py::_resolve_outcome's direction handling.
Bearish trades are the mirror image of bullish (stop above entry, target
below) — added alongside risk_reward.py's bearish support so a short signal's
outcome actually resolves correctly instead of using bullish stop/target logic
on a bearish trade's price levels.
"""

import pandas as pd
import pytest

from paper_trading.paper_updater import _resolve_outcome


def _bars(rows):
    """rows: list of (date_str, open, high, low, close)."""
    df = pd.DataFrame(
        [{"Open": o, "High": h, "Low": lo, "Close": c} for _, o, h, lo, c in rows],
        index=pd.to_datetime([d for d, *_ in rows]),
    )
    return df


class TestResolveOutcomeBullish:
    def test_stop_hit(self):
        df = _bars([("2026-01-02", 100, 101, 94, 95)])
        result = _resolve_outcome(df, entry_price=100, stop_loss=95, target=115)
        assert result["outcome"] == "loss"
        assert result["exit_price"] == pytest.approx(95)

    def test_target_hit(self):
        df = _bars([("2026-01-02", 100, 116, 99, 110)])
        result = _resolve_outcome(df, entry_price=100, stop_loss=95, target=115)
        assert result["outcome"] == "win"
        assert result["exit_price"] == pytest.approx(115)

    def test_still_open(self):
        df = _bars([("2026-01-02", 100, 105, 98, 102)])
        assert _resolve_outcome(df, entry_price=100, stop_loss=95, target=115) is None


class TestResolveOutcomeBearish:
    def test_stop_hit_is_price_rising_through_stop(self):
        # Short entered at 100, stop at 105 (above entry) — a rally to/through
        # 105 is the loss case, the mirror of a bullish stop being below entry.
        df = _bars([("2026-01-02", 100, 106, 99, 104)])
        result = _resolve_outcome(df, entry_price=100, stop_loss=105, target=85, direction="bearish")
        assert result["outcome"] == "loss"
        assert result["exit_price"] == pytest.approx(105)

    def test_target_hit_is_price_falling_through_target(self):
        # Short entered at 100, target at 85 (below entry) — a decline to/through
        # 85 is the win case.
        df = _bars([("2026-01-02", 100, 101, 84, 90)])
        result = _resolve_outcome(df, entry_price=100, stop_loss=105, target=85, direction="bearish")
        assert result["outcome"] == "win"
        assert result["exit_price"] == pytest.approx(85)

    def test_still_open(self):
        df = _bars([("2026-01-02", 100, 102, 97, 99)])
        assert _resolve_outcome(df, entry_price=100, stop_loss=105, target=85, direction="bearish") is None

    def test_gap_up_through_stop_exits_at_open_not_stop(self):
        # Open already above stop — filled at the worse (higher) open price,
        # mirroring the bullish gap-down-through-stop case (exit at min(stop, open)).
        df = _bars([("2026-01-02", 108, 110, 107, 109)])
        result = _resolve_outcome(df, entry_price=100, stop_loss=105, target=85, direction="bearish")
        assert result["outcome"] == "loss"
        assert result["exit_price"] == pytest.approx(108)
