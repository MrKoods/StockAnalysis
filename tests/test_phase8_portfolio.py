"""
Tests for Phase 8: portfolio_manager.
No market data, no file I/O dependencies in most tests.
"""

import pytest
from datetime import datetime, timezone, timedelta

from swing_model.portfolio_manager import (
    add_position,
    close_position,
    update_circuit_breaker,
    can_open_new_position,
    get_portfolio_delta,
    count_day_trades,
    is_pdt_warning,
)


# ---------------------------------------------------------------------------
# portfolio_manager
# ---------------------------------------------------------------------------

def _empty_state():
    return {
        "positions": [],
        "account_equity": 15000.0,
        "peak_equity": 15000.0,
        "circuit_breaker_state": "normal",
        "day_trades_rolling_5d": [],
        "consecutive_losses": 0,
        "black_swan_mode": False,
        "black_swan_normal_days": 0,
        "last_scan_timestamp_utc": None,
        "model_version": "v1.0.0",
    }


def _position(ticker="NVDA", direction="bullish", risk_pct=0.01, confidence=92.0, entry=500.0, stop=480.0, target=560.0):
    return {
        "ticker": ticker,
        "direction": direction,
        "entry_price": entry,
        "stop_loss": stop,
        "target": target,
        "risk_pct": risk_pct,
        "structure": "long_stock",
        "confidence": confidence,
    }


class TestCanOpenNewPosition:
    def test_can_open_when_empty(self):
        ok, _ = can_open_new_position(_empty_state(), _position())
        assert ok is True

    def test_blocked_at_max_positions(self):
        state = _empty_state()
        state["positions"] = [
            {**_position("NVDA"), "open": True},
            {**_position("MU"), "open": True},
        ]
        ok, reason = can_open_new_position(state, _position("AMD"))
        assert ok is False
        assert "max_total_positions" in reason

    def test_blocked_by_orange_circuit_breaker(self):
        state = _empty_state()
        state["circuit_breaker_state"] = "orange"
        ok, reason = can_open_new_position(state, _position())
        assert ok is False
        assert "orange" in reason

    def test_blocked_by_red_circuit_breaker(self):
        state = _empty_state()
        state["circuit_breaker_state"] = "red"
        ok, reason = can_open_new_position(state, _position())
        assert ok is False
        assert "red" in reason

    def test_blocked_by_total_risk_20pct(self):
        state = _empty_state()
        # First position at 15% risk
        state["positions"] = [{**_position("NVDA"), "open": True, "risk_pct": 0.15}]
        # +6% more -> 21% total, over the 20% cap (raised 2026-08-23 from 3%).
        ok, reason = can_open_new_position(state, _position("AMD", risk_pct=0.06))
        assert ok is False
        assert "20pct" in reason

    def test_blocked_by_correlated_pair_same_direction(self):
        state = _empty_state()
        state["positions"] = [{**_position("NVDA"), "open": True, "direction": "bullish"}]
        # Net-directional-delta cap disabled here (2 same-direction 1%-risk
        # positions would otherwise trip it first) — isolates this test's own
        # target, the correlated-group check; the delta cap has its own
        # dedicated tests.
        cfg = {"portfolio": {"max_net_directional_delta": 1.0}}
        ok, reason = can_open_new_position(state, _position("AMD", direction="bullish"), cfg=cfg)
        assert ok is False
        assert "correlated_group" in reason

    def test_allowed_when_correlated_pair_opposite_direction(self):
        state = _empty_state()
        state["positions"] = [{**_position("NVDA"), "open": True, "direction": "bullish"}]
        ok, _ = can_open_new_position(state, _position("AMD", direction="bearish"))
        assert ok is True

    def test_blocked_same_ticker_opposite_direction(self):
        # Signal Integrity Audit finding C.5: the same-ticker duplicate rule
        # used to only check same-direction — nothing stopped the same
        # ticker carrying simultaneous long AND short exposure, each sized
        # independently. Contrast with the DIFFERENT-ticker case just above
        # (NVDA long + AMD short), which is correctly still allowed — this
        # is specifically about one ticker held both ways at once.
        state = _empty_state()
        state["positions"] = [{**_position("NVDA"), "open": True, "direction": "bullish"}]
        ok, reason = can_open_new_position(state, _position("NVDA", direction="bearish"))
        assert ok is False
        assert "duplicate_position" in reason
        assert "opposite_direction" in reason

    def test_blocked_same_ticker_same_direction_still_says_same(self):
        # Regression guard: the reason string's same/opposite label must
        # still correctly report "same" for the pre-existing same-direction
        # case (not just always say "opposite" now that both are checked).
        # Net-directional-delta cap disabled here (2 same-direction 1%-risk
        # positions would otherwise trip it first) — same isolation as
        # test_blocked_by_correlated_pair_same_direction above.
        state = _empty_state()
        state["positions"] = [{**_position("NVDA"), "open": True, "direction": "bullish"}]
        cfg = {"portfolio": {"max_net_directional_delta": 1.0}}
        ok, reason = can_open_new_position(state, _position("NVDA", direction="bullish"), cfg=cfg)
        assert ok is False
        assert "same_direction" in reason

    def test_blocked_by_yellow_cb_low_confidence(self):
        state = _empty_state()
        state["circuit_breaker_state"] = "yellow"
        ok, reason = can_open_new_position(state, _position(confidence=92.0))
        assert ok is False
        assert "yellow" in reason

    def test_allowed_by_yellow_cb_high_confidence(self):
        state = _empty_state()
        state["circuit_breaker_state"] = "yellow"
        ok, _ = can_open_new_position(state, _position(confidence=96.0))
        assert ok is True


def _two_sector_cfg():
    return {
        "watchlist": {
            "sectors": {
                "semiconductors": {
                    "active": True, "benchmark": "SMH",
                    "tickers": ["NVDA", "AMD", "AVGO", "TSM", "MU", "ASML"],
                },
                "regional_banks": {
                    "active": True, "benchmark": "KRE",
                    "tickers": ["ZION", "KEY", "HBAN", "RF", "FITB"],
                },
            },
        },
        "portfolio": {
            "max_simultaneous_risk_pct": 0.03,
            "max_total_open_positions": 4,
            # Disabled for this multi-sector test class — it's an account-wide,
            # sector-agnostic cap (own dedicated tests below), and several of
            # these fixtures deliberately stack same-direction positions
            # across sectors to isolate the per-sector/global-ceiling/
            # correlated-group checks, which would otherwise also trip it.
            "max_net_directional_delta": 1.0,
            "sectors": {
                "semiconductors": {
                    "max_open_positions": 2,
                    "correlated_groups": [["NVDA", "AMD"], ["NVDA", "AVGO"]],
                },
                "regional_banks": {
                    "max_open_positions": 2,
                    "correlated_groups": [["ZION", "KEY", "HBAN", "RF", "FITB"]],
                },
            },
        },
    }


class TestCanOpenNewPositionMultiSector:
    """Per-sector caps and correlated-group isolation with two active sectors."""

    def test_sector_slots_dont_share_a_pool(self):
        # 2 semis positions already open (at the semis cap) — a bank position
        # must still be allowed, since it's a different sector's slot.
        state = _empty_state()
        state["positions"] = [
            {**_position("NVDA"), "open": True},
            {**_position("AMD", direction="bearish"), "open": True},
        ]
        ok, reason = can_open_new_position(state, _position("ZION"), cfg=_two_sector_cfg())
        assert ok is True, reason

    def test_third_semis_position_blocked_by_sector_cap(self):
        state = _empty_state()
        state["positions"] = [
            {**_position("NVDA"), "open": True},
            {**_position("AMD", direction="bearish"), "open": True},
        ]
        ok, reason = can_open_new_position(state, _position("TSM"), cfg=_two_sector_cfg())
        assert ok is False
        assert "sector_semiconductors" in reason

    def test_global_ceiling_blocks_a_5th_position_even_with_sector_room(self):
        # 2 semis + 2 banks open = 4, at the global ceiling. A bank sector cap
        # of 2 hasn't been exceeded per-sector, but the total ceiling has.
        state = _empty_state()
        state["positions"] = [
            {**_position("NVDA"), "open": True},
            {**_position("AMD", direction="bearish"), "open": True},
            {**_position("ZION"), "open": True},
            {**_position("KEY", direction="bearish"), "open": True},
        ]
        ok, reason = can_open_new_position(state, _position("HBAN"), cfg=_two_sector_cfg())
        assert ok is False
        assert "max_total_positions" in reason

    def test_bank_correlated_group_does_not_block_semis_ticker(self):
        # 5-ticker bank correlated group open on ZION — a semis ticker must
        # not be affected by a correlated-group check scoped to another sector.
        state = _empty_state()
        state["positions"] = [{**_position("ZION"), "open": True}]
        ok, reason = can_open_new_position(state, _position("NVDA"), cfg=_two_sector_cfg())
        assert ok is True, reason

    def test_bank_correlated_group_blocks_within_sector(self):
        state = _empty_state()
        state["positions"] = [{**_position("ZION"), "open": True}]
        ok, reason = can_open_new_position(state, _position("KEY"), cfg=_two_sector_cfg())
        assert ok is False
        assert "correlated_group" in reason


class TestAddPosition:
    def test_add_increases_position_count(self):
        state = _empty_state()
        state = add_position(state, _position())
        assert len(state["positions"]) == 1

    def test_add_blocked_when_full(self):
        state = _empty_state()
        state["positions"] = [
            {**_position("NVDA"), "open": True},
            {**_position("MU"), "open": True},
        ]
        with pytest.raises(ValueError, match="max_total_positions"):
            add_position(state, _position("AMD"))

    def test_position_has_required_fields(self):
        state = _empty_state()
        state = add_position(state, _position())
        pos = state["positions"][0]
        for field in ("ticker", "entry_price", "stop_loss", "target",
                      "risk_pct", "opened_at_utc", "open"):
            assert field in pos

    def test_position_marked_open(self):
        state = _empty_state()
        state = add_position(state, _position())
        assert state["positions"][0]["open"] is True


class TestClosePosition:
    @pytest.fixture(autouse=True)
    def _isolate_trade_outcomes_file(self, tmp_path, monkeypatch):
        """
        close_position() -> _log_trade_outcome() -> feedback_loop.log_trade_outcome()
        writes to real data/logs files by default — redirect both to tmp_path so
        these tests never pollute the real trade_outcomes.csv / signal_win_rates.json.
        """
        import swing_model.feedback_loop as fl
        monkeypatch.setattr(fl, "_TRADE_OUTCOMES_FILE", tmp_path / "trade_outcomes.csv")
        monkeypatch.setattr(fl, "_SIGNAL_WIN_RATES_FILE", tmp_path / "signal_win_rates.json")

    def test_close_profitable_increases_equity(self):
        state = _empty_state()
        state["positions"] = [{
            **_position(), "open": True,
            "entry_price": 500.0, "stop_loss": 480.0,
            "opened_at_utc": "2026-06-20T14:00:00+00:00",
        }]
        state = close_position(state, "NVDA", exit_price=560.0, reason="target_hit")
        assert state["account_equity"] > 15000.0

    def test_close_losing_decreases_equity(self):
        state = _empty_state()
        state["positions"] = [{
            **_position(), "open": True,
            "entry_price": 500.0, "stop_loss": 480.0,
            "opened_at_utc": "2026-06-20T14:00:00+00:00",
        }]
        state = close_position(state, "NVDA", exit_price=475.0, reason="stop_hit")
        assert state["account_equity"] < 15000.0

    def test_consecutive_losses_incremented(self):
        state = _empty_state()
        state["positions"] = [{
            **_position(), "open": True,
            "entry_price": 500.0, "stop_loss": 480.0,
            "opened_at_utc": "2026-06-20T14:00:00+00:00",
        }]
        state = close_position(state, "NVDA", exit_price=475.0, reason="stop_hit")
        assert state["consecutive_losses"] == 1

    def test_consecutive_losses_reset_on_win(self):
        state = _empty_state()
        state["consecutive_losses"] = 3
        state["positions"] = [{
            **_position(), "open": True,
            "entry_price": 500.0, "stop_loss": 480.0,
            "opened_at_utc": "2026-06-20T14:00:00+00:00",
        }]
        state = close_position(state, "NVDA", exit_price=560.0, reason="target_hit")
        assert state["consecutive_losses"] == 0

    def test_close_nonexistent_raises(self):
        state = _empty_state()
        with pytest.raises(ValueError):
            close_position(state, "NVDA", 480.0, "manual")

    def test_position_marked_closed(self):
        state = _empty_state()
        state["positions"] = [{
            **_position(), "open": True,
            "entry_price": 500.0, "stop_loss": 480.0,
            "opened_at_utc": "2026-06-20T14:00:00+00:00",
        }]
        state = close_position(state, "NVDA", exit_price=540.0, reason="target_hit")
        closed = [p for p in state["positions"] if p["ticker"] == "NVDA"][0]
        assert closed["open"] is False


class TestUpdateCircuitBreaker:
    def _state_with_drawdown(self, drawdown_pct):
        state = _empty_state()
        state["peak_equity"] = 15000.0
        state["account_equity"] = 15000.0 * (1 - drawdown_pct)
        return state

    def test_no_drawdown_stays_normal(self):
        state = self._state_with_drawdown(0.0)
        state = update_circuit_breaker(state)
        assert state["circuit_breaker_state"] == "normal"

    def test_4pct_drawdown_stays_normal(self):
        state = self._state_with_drawdown(0.04)
        state = update_circuit_breaker(state)
        assert state["circuit_breaker_state"] == "normal"

    def test_5pct_drawdown_triggers_yellow(self):
        state = self._state_with_drawdown(0.05)
        state = update_circuit_breaker(state)
        assert state["circuit_breaker_state"] == "yellow"

    def test_10pct_drawdown_triggers_orange(self):
        state = self._state_with_drawdown(0.10)
        state = update_circuit_breaker(state)
        assert state["circuit_breaker_state"] == "orange"

    def test_15pct_drawdown_triggers_red(self):
        state = self._state_with_drawdown(0.15)
        state = update_circuit_breaker(state)
        assert state["circuit_breaker_state"] == "red"

    def test_state_change_recorded(self):
        state = self._state_with_drawdown(0.06)
        state["circuit_breaker_state"] = "normal"
        state = update_circuit_breaker(state)
        assert "_cb_state_changed" in state
        assert state["_cb_state_changed"]["from"] == "normal"
        assert state["_cb_state_changed"]["to"] == "yellow"

    def test_no_change_event_when_same_state(self):
        state = self._state_with_drawdown(0.06)
        state["circuit_breaker_state"] = "yellow"
        state = update_circuit_breaker(state)
        assert "_cb_state_changed" not in state


class TestPortfolioDelta:
    def test_empty_portfolio_zero_delta(self):
        state = _empty_state()
        delta = get_portfolio_delta(state, {})
        assert delta == 0.0

    def test_single_bullish_positive_delta(self):
        state = _empty_state()
        state["positions"] = [{**_position(), "open": True, "risk_pct": 0.01}]
        delta = get_portfolio_delta(state, {"NVDA": 500.0})
        assert delta > 0

    def test_single_bearish_negative_delta(self):
        state = _empty_state()
        state["positions"] = [{**_position(direction="bearish"), "open": True, "risk_pct": 0.01}]
        delta = get_portfolio_delta(state, {"NVDA": 500.0})
        assert delta < 0

    def test_offset_positions_net_zero(self):
        state = _empty_state()
        state["positions"] = [
            {**_position("NVDA", direction="bullish"), "open": True, "risk_pct": 0.01},
            {**_position("AMD", direction="bearish"), "open": True, "risk_pct": 0.01},
        ]
        delta = get_portfolio_delta(state, {"NVDA": 500.0, "AMD": 180.0})
        assert abs(delta) < 0.001


class TestPDT:
    def test_no_day_trades_returns_zero(self):
        state = _empty_state()
        assert count_day_trades(state) == 0

    def test_old_day_trades_excluded(self):
        state = _empty_state()
        # 30 days ago — should be pruned
        old = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%d")
        state["day_trades_rolling_5d"] = [old, old]
        assert count_day_trades(state) == 0

    def test_recent_day_trades_counted(self):
        state = _empty_state()
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        state["day_trades_rolling_5d"] = [today, today]
        assert count_day_trades(state) == 2

    def test_pdt_warning_at_threshold(self):
        state = _empty_state()
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        state["day_trades_rolling_5d"] = [today, today]
        assert is_pdt_warning(state, threshold=2) is True

    def test_pdt_warning_below_threshold(self):
        state = _empty_state()
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        state["day_trades_rolling_5d"] = [today]
        assert is_pdt_warning(state, threshold=2) is False
