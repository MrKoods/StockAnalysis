"""
Tests for the Black Swan detector's config-key fix and its advisory-only
live wiring (shared.utils.black_swan_detector's cfg key mismatch,
swing_model.portfolio_manager.update_black_swan_state).

Prior to this fix, check_black_swan() read cfg["black_swan"]["smh_drop_threshold"]/
["vix_spike_threshold"], but config/swing_config.yaml only ever defined
"smh_drop_threshold_pct"/"vix_spike_threshold_pct" — so a configured value was
silently never applied. Also, check_black_swan() itself was never called from
run_swing_model.py at all (dead code) — a 9% SMH drop produced no alert.

Black Swan is advisory only (explicit product decision — see module docstring):
it must never gate/block a signal, only flag it.
"""

import pandas as pd
import pytest

from shared.utils.black_swan_detector import check_black_swan
from swing_model.portfolio_manager import update_black_swan_state, _EMPTY_STATE
from swing_model.run_swing_model import _compute_last_bar_pct_change


class TestConfigKeyFix:
    def test_configured_smh_threshold_is_actually_read(self):
        cfg = {"black_swan": {"smh_drop_threshold_pct": -0.03}}
        # -4% breaches the tighter -3% configured threshold, but not the
        # hardcoded -7% default — proves the configured key is being read.
        result = check_black_swan(smh_current_pct_change=-0.04, vix_current_pct_change=0.0, cfg=cfg)
        assert result["black_swan_triggered"] is True
        assert result["trigger_type"] == "smh_drop"

    def test_configured_vix_threshold_is_actually_read(self):
        cfg = {"black_swan": {"vix_spike_threshold_pct": 0.10}}
        result = check_black_swan(smh_current_pct_change=0.0, vix_current_pct_change=0.15, cfg=cfg)
        assert result["black_swan_triggered"] is True
        assert result["trigger_type"] == "vix_spike"

    def test_old_unsuffixed_keys_no_longer_do_anything(self):
        # The bug: these keys don't match config's real names, so they must
        # NOT override the real (now-correctly-read) defaults.
        cfg = {"black_swan": {"smh_drop_threshold": -0.01, "vix_spike_threshold": 0.01}}
        result = check_black_swan(smh_current_pct_change=-0.04, vix_current_pct_change=0.15, cfg=cfg)
        # -4%/+15% don't breach the real defaults (-7%/40%) — if the old
        # unsuffixed keys were still being read, this would incorrectly trigger.
        assert result["black_swan_triggered"] is False

    def test_no_cfg_falls_back_to_hardcoded_defaults(self):
        result = check_black_swan(smh_current_pct_change=-0.08, vix_current_pct_change=0.0, cfg=None)
        assert result["black_swan_triggered"] is True


class TestUpdateBlackSwanStateAdvisoryOnly:
    def _state(self):
        return dict(_EMPTY_STATE)

    def test_triggered_sets_mode_and_newly_triggered_flag(self):
        state = self._state()
        result = check_black_swan(smh_current_pct_change=-0.09, vix_current_pct_change=0.0)
        state = update_black_swan_state(state, result)
        assert state["black_swan_mode"] is True
        assert state["_black_swan_newly_triggered"] is True

    def test_second_consecutive_trigger_does_not_re_flag_newly_triggered(self):
        """Alert-dedup: must only fire once per episode, not every scan while
        conditions remain extreme."""
        state = self._state()
        result = check_black_swan(smh_current_pct_change=-0.09, vix_current_pct_change=0.0)
        state = update_black_swan_state(state, result)
        state.pop("_black_swan_newly_triggered", None)  # caller's job after alerting

        state = update_black_swan_state(state, result)  # still triggered
        assert state.get("_black_swan_newly_triggered", False) is False

    def test_mode_stays_active_through_the_cooldown_window(self):
        # Signal Integrity Audit follow-up: mode used to clear the instant
        # ONE scan read normal, even though config's black_swan.
        # resume_after_normal_days ("resume after 3 consecutive normal
        # days") and black_swan_normal_days were both already tracking a
        # cooldown nothing ever gated on. 1 and 2 normal days must NOT clear it.
        state = self._state()
        triggered = check_black_swan(smh_current_pct_change=-0.09, vix_current_pct_change=0.0)
        state = update_black_swan_state(state, triggered)
        assert state["black_swan_mode"] is True

        normal = check_black_swan(smh_current_pct_change=-0.01, vix_current_pct_change=0.0)
        state = update_black_swan_state(state, normal)  # day 1 normal
        assert state["black_swan_mode"] is True
        assert state["black_swan_normal_days"] == 1

        state = update_black_swan_state(state, normal)  # day 2 normal
        assert state["black_swan_mode"] is True
        assert state["black_swan_normal_days"] == 2

    def test_clearing_resets_mode_after_the_full_cooldown(self):
        state = self._state()
        triggered = check_black_swan(smh_current_pct_change=-0.09, vix_current_pct_change=0.0)
        state = update_black_swan_state(state, triggered)

        normal = check_black_swan(smh_current_pct_change=-0.01, vix_current_pct_change=0.0)
        for _ in range(3):  # config default: resume_after_normal_days = 3
            state = update_black_swan_state(state, normal)
        assert state["black_swan_mode"] is False

    def test_cooldown_window_is_configurable(self):
        state = self._state()
        cfg = {"black_swan": {"resume_after_normal_days": 1}}
        triggered = check_black_swan(smh_current_pct_change=-0.09, vix_current_pct_change=0.0)
        state = update_black_swan_state(state, triggered, cfg=cfg)

        normal = check_black_swan(smh_current_pct_change=-0.01, vix_current_pct_change=0.0)
        state = update_black_swan_state(state, normal, cfg=cfg)
        assert state["black_swan_mode"] is False

    def test_re_triggering_after_clearing_flags_newly_triggered_again(self):
        state = self._state()
        triggered = check_black_swan(smh_current_pct_change=-0.09, vix_current_pct_change=0.0)
        state = update_black_swan_state(state, triggered)
        state.pop("_black_swan_newly_triggered", None)

        normal = check_black_swan(smh_current_pct_change=-0.01, vix_current_pct_change=0.0)
        for _ in range(3):  # clear the cooldown for real before re-triggering
            state = update_black_swan_state(state, normal)
        assert state["black_swan_mode"] is False

        state = update_black_swan_state(state, triggered)
        assert state["_black_swan_newly_triggered"] is True

    def test_advisory_only_never_present_in_can_open_new_position_gating(self):
        """
        Regression guard for the "advisory, not blocking" product decision:
        can_open_new_position must not reference black_swan_mode at all.
        """
        import inspect
        from swing_model.portfolio_manager import can_open_new_position
        src = inspect.getsource(can_open_new_position)
        assert "black_swan" not in src.lower()


class TestComputeLastBarPctChange:
    def _df(self, closes):
        return pd.DataFrame({"Close": closes})

    def test_computes_pct_change_from_last_two_bars(self):
        df = self._df([100.0, 110.0, 99.0])
        result = _compute_last_bar_pct_change(df)
        assert result == pytest.approx((99.0 - 110.0) / 110.0)

    def test_none_when_fewer_than_two_bars(self):
        assert _compute_last_bar_pct_change(self._df([100.0])) is None

    def test_none_when_df_is_none(self):
        assert _compute_last_bar_pct_change(None) is None

    def test_none_on_zero_prior_close(self):
        assert _compute_last_bar_pct_change(self._df([0.0, 5.0])) is None
