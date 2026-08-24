"""
Tests for the consecutive-loss circuit-breaker escalation ladder, the net-
directional-delta exposure cap, and the Yellow-CB confidence-floor config fix
— all in swing_model/portfolio_manager.py — plus the matching sizing pieces
in shared/utils/position_sizer.py.

Before this fix: consecutive_losses was tracked (incremented/reset in
close_position) but nothing ever read it when deciding whether a new position
could open — the config-declared 2/3/4-loss escalation ladder
(circuit_breakers.consecutive_loss.at_2/at_3/at_4) had no enforcement code
anywhere. get_portfolio_delta() computed a net-exposure number every call but
nothing checked it against its own documented 1.5% cap. And Yellow CB's
confidence floor was a bare `95` literal, ignoring
circuit_breakers.yellow.min_confidence_override entirely.
"""

from datetime import datetime, timedelta, timezone

import pytest

from swing_model.portfolio_manager import (
    close_position,
    can_open_new_position,
    _EMPTY_STATE,
)
from shared.utils.position_sizer import (
    apply_consecutive_loss_sizing,
    compute_position_size,
)


def _state_with_open_position(ticker="NVDA", direction="bullish", entry=100.0, stop=95.0, risk_pct=0.01):
    state = dict(_EMPTY_STATE)
    state["positions"] = [{
        "ticker": ticker, "direction": direction, "entry_price": entry, "stop_loss": stop,
        "target": entry + 3 * (entry - stop), "risk_pct": risk_pct, "confidence": 90.0,
        "opened_at_utc": (datetime.now(timezone.utc) - timedelta(days=2)).isoformat(),
        "open": True,
    }]
    return state


def _close_as_loss(state, ticker="NVDA", cfg=None):
    """Close the ticker's open position at a price that guarantees a loss."""
    pos = next(p for p in state["positions"] if p["ticker"] == ticker and p.get("open", True))
    entry = pos["entry_price"]
    exit_price = entry * 0.9 if pos["direction"] == "bullish" else entry * 1.1
    return close_position(state, ticker, exit_price, "stop_hit", cfg=cfg)


class TestConsecutiveLossLadder:
    @pytest.fixture(autouse=True)
    def _isolate_trade_outcomes_file(self, tmp_path, monkeypatch):
        """
        close_position() -> _log_trade_outcome() -> feedback_loop.log_trade_outcome()
        writes to real data/logs files by default — redirect both to tmp_path so
        these tests never pollute the real trade_outcomes.csv / signal_win_rates.json.
        Same fixture as test_phase8_portfolio.py's TestClosePosition; this class
        is the other place in the suite that calls close_position() directly.
        """
        import swing_model.feedback_loop as fl
        monkeypatch.setattr(fl, "_TRADE_OUTCOMES_FILE", tmp_path / "trade_outcomes.csv")
        monkeypatch.setattr(fl, "_SIGNAL_WIN_RATES_FILE", tmp_path / "signal_win_rates.json")

    def test_two_losses_does_not_block_only_sizes_down(self):
        state = dict(_EMPTY_STATE)
        state["positions"] = []
        state["consecutive_losses"] = 2
        ok, reason = can_open_new_position(state, {"ticker": "NVDA", "direction": "bullish", "confidence": 90.0, "risk_pct": 0.01})
        assert ok is True, reason

    def test_three_losses_sets_pause_window(self):
        state = _state_with_open_position()
        state["consecutive_losses"] = 2  # about to become the 3rd loss
        state = _close_as_loss(state)
        assert state["consecutive_losses"] == 3
        assert "consecutive_loss_pause_until_utc" in state

    def test_pause_window_blocks_new_positions(self):
        state = _state_with_open_position()
        state["consecutive_losses"] = 2
        state = _close_as_loss(state)  # -> 3 losses, pause set

        ok, reason = can_open_new_position(state, {"ticker": "AMD", "direction": "bullish", "confidence": 95.0, "risk_pct": 0.01})
        assert ok is False
        assert "consecutive_loss_pause_active" in reason

    def test_pause_window_lifts_once_expired(self):
        state = dict(_EMPTY_STATE)
        state["positions"] = []
        state["consecutive_losses"] = 3
        # Pause already expired (set in the past).
        state["consecutive_loss_pause_until_utc"] = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()

        ok, reason = can_open_new_position(state, {"ticker": "AMD", "direction": "bullish", "confidence": 95.0, "risk_pct": 0.01})
        assert ok is True, reason

    def test_a_win_clears_the_pause_window(self):
        state = _state_with_open_position()
        state["consecutive_losses"] = 2
        state = _close_as_loss(state)  # -> 3 losses, pause set
        assert "consecutive_loss_pause_until_utc" in state

        state["positions"].append({
            "ticker": "AMD", "direction": "bullish", "entry_price": 100.0, "stop_loss": 95.0,
            "target": 115.0, "risk_pct": 0.01, "confidence": 90.0,
            "opened_at_utc": datetime.now(timezone.utc).isoformat(), "open": True,
        })
        state = close_position(state, "AMD", 120.0, "target_hit")  # a win
        assert state["consecutive_losses"] == 0
        assert "consecutive_loss_pause_until_utc" not in state

    def test_four_losses_fully_blocks_new_positions(self):
        state = dict(_EMPTY_STATE)
        state["positions"] = []
        state["consecutive_losses"] = 4
        ok, reason = can_open_new_position(state, {"ticker": "NVDA", "direction": "bullish", "confidence": 99.0, "risk_pct": 0.01})
        assert ok is False
        assert "full_pause" in reason

    def test_full_pause_config_can_be_disabled(self):
        state = dict(_EMPTY_STATE)
        state["positions"] = []
        state["consecutive_losses"] = 4
        cfg = {"circuit_breakers": {"consecutive_loss": {"at_4": {"full_pause": False}}}}
        ok, reason = can_open_new_position(
            state, {"ticker": "NVDA", "direction": "bullish", "confidence": 99.0, "risk_pct": 0.01}, cfg=cfg
        )
        assert ok is True, reason

    def test_configured_pause_days_is_read(self):
        state = _state_with_open_position()
        state["consecutive_losses"] = 2
        cfg = {"circuit_breakers": {"consecutive_loss": {"at_3": {"pause_days": 1}}}}
        state = _close_as_loss(state, cfg=cfg)
        pause_until = datetime.fromisoformat(state["consecutive_loss_pause_until_utc"])
        # 1 trading day ~= 1-2 calendar days, must be well under the default 3-day (5 cal day) window.
        assert pause_until - datetime.now(timezone.utc) < timedelta(days=3)


class TestNetDirectionalDeltaCap:
    def test_single_small_position_within_cap(self):
        ok, _ = can_open_new_position(_EMPTY_STATE, {"ticker": "NVDA", "direction": "bullish", "confidence": 90.0, "risk_pct": 0.01})
        assert ok is True

    def test_stacking_same_direction_risk_trips_the_cap(self):
        state = dict(_EMPTY_STATE)
        state["positions"] = [{
            "ticker": "NVDA", "direction": "bullish", "risk_pct": 0.06, "open": True,
            "entry_price": 100.0, "stop_loss": 95.0,
        }]
        # +6% more same-direction risk -> 12% net long, over the 10% cap
        # (raised 2026-08-23 from 1.5% — see MAX_NET_DIRECTIONAL_DELTA) —
        # kept well under the 20% total-risk cap so that check doesn't fire
        # first and mask the one this test actually targets.
        ok, reason = can_open_new_position(
            state, {"ticker": "AMD", "direction": "bullish", "confidence": 90.0, "risk_pct": 0.06}
        )
        assert ok is False
        assert "net_directional_delta" in reason

    def test_opposite_direction_offsets_and_does_not_trip_cap(self):
        state = dict(_EMPTY_STATE)
        state["positions"] = [{
            "ticker": "NVDA", "direction": "bullish", "risk_pct": 0.01, "open": True,
            "entry_price": 100.0, "stop_loss": 95.0,
        }]
        ok, reason = can_open_new_position(
            state, {"ticker": "AMD", "direction": "bearish", "confidence": 90.0, "risk_pct": 0.01}
        )
        assert ok is True, reason

    def test_configurable_via_cfg(self):
        state = dict(_EMPTY_STATE)
        state["positions"] = [{
            "ticker": "NVDA", "direction": "bullish", "risk_pct": 0.01, "open": True,
            "entry_price": 100.0, "stop_loss": 95.0,
        }]
        # ZION, not AMD — AMD is in NVDA's default correlated group, which
        # would trip a different (unrelated) check once the delta cap itself
        # is loosened enough to not be the binding constraint.
        cfg = {"portfolio": {"max_net_directional_delta": 0.03}}
        ok, reason = can_open_new_position(
            state, {"ticker": "ZION", "direction": "bullish", "confidence": 90.0, "risk_pct": 0.01}, cfg=cfg
        )
        assert ok is True, reason


class TestYellowConfidenceFloorConfigFix:
    def test_default_floor_is_95(self):
        state = dict(_EMPTY_STATE)
        state["circuit_breaker_state"] = "yellow"
        ok, reason = can_open_new_position(state, {"ticker": "NVDA", "direction": "bullish", "confidence": 94.0, "risk_pct": 0.01})
        assert ok is False
        assert "95" in reason

    def test_configured_floor_is_actually_read(self):
        state = dict(_EMPTY_STATE)
        state["circuit_breaker_state"] = "yellow"
        cfg = {"circuit_breakers": {"yellow": {"min_confidence_override": 92}}}
        ok, reason = can_open_new_position(
            state, {"ticker": "NVDA", "direction": "bullish", "confidence": 93.0, "risk_pct": 0.01}, cfg=cfg
        )
        assert ok is True, reason


class TestConsecutiveLossSizing:
    def test_zero_or_one_loss_no_reduction(self):
        adjusted, mult = apply_consecutive_loss_sizing(0.02, 0)
        assert mult == 1.0
        assert adjusted == 0.02
        adjusted, mult = apply_consecutive_loss_sizing(0.02, 1)
        assert mult == 1.0

    def test_two_losses_halves_size(self):
        adjusted, mult = apply_consecutive_loss_sizing(0.02, 2)
        assert mult == 0.5
        assert adjusted == 0.01

    def test_configured_multiplier_is_read(self):
        cfg = {"circuit_breakers": {"consecutive_loss": {"at_2": {"size_multiplier": 0.25}}}}
        adjusted, mult = apply_consecutive_loss_sizing(0.02, 2, cfg)
        assert mult == 0.25
        assert adjusted == 0.005


class TestComputePositionSizeLayersBothMultipliers:
    def test_yellow_cb_and_two_losses_compound(self):
        """Both a drawdown-based circuit breaker AND a loss streak active at
        once should compound (0.5 x 0.5 = 0.25), not just pick one."""
        result = compute_position_size(
            confidence_score=99.0, account_equity=15000.0, circuit_breaker_state="yellow",
            capital_required=100.0, consecutive_losses=2,
        )
        # get_risk_pct(99) = 2500/15000 (raised 2026-08-23, was 0.025);
        # x0.5 (yellow) x0.5 (2 losses) = 1/24, rounded to 4dp at each stage
        # like every other sizing function here.
        assert result["risk_pct"] == pytest.approx((2500 / 15000) * 0.25, abs=1e-4)
        assert result["size_multiplier"] == pytest.approx(0.25, abs=1e-6)

    def test_normal_cb_no_losses_is_unadjusted(self):
        result = compute_position_size(
            confidence_score=99.0, account_equity=15000.0, circuit_breaker_state="normal",
            capital_required=100.0, consecutive_losses=0,
        )
        assert result["risk_pct"] == pytest.approx(2500 / 15000, abs=1e-4)
        assert result["size_multiplier"] == 1.0
