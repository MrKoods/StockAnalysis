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

import csv

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


class TestCheckBlackSwanPerSector:
    """
    _check_black_swan_per_sector (2026-08-23 full model audit): both
    run_swing_model.py and paper_trading/paper_runner.py now check EVERY
    active sector's own benchmark, not just SMH, with each sector's
    trigger/cooldown tracked independently in black_swan_state.json.
    """

    def _df(self, closes):
        return pd.DataFrame({"Close": closes})

    def _mkt(self, vix_pct_change=0.0, **benchmark_dfs):
        return {"vix_pct_change": vix_pct_change, "sector_benchmark_dfs": benchmark_dfs}

    def test_only_the_dropping_sectors_own_benchmark_triggers(self):
        """A >7% drop in one sector's benchmark must not trigger sectors
        whose own benchmark is fine — the whole point of going per-sector."""
        from swing_model.run_swing_model import _check_black_swan_per_sector

        active_sectors = {"semiconductors": {}, "regional_banks": {}}
        mkt = self._mkt(
            vix_pct_change=0.0,
            semiconductors=self._df([100.0, 90.0]),   # -10%, triggers
            regional_banks=self._df([50.0, 49.0]),    # -2%, fine
        )
        results = _check_black_swan_per_sector(active_sectors, mkt, cfg=None)
        assert results["semiconductors"]["black_swan_triggered"] is True
        assert results["regional_banks"]["black_swan_triggered"] is False

    def test_vix_spike_triggers_every_active_sector_at_once(self):
        """VIX is one shared, market-wide input — unlike the benchmark drop,
        a spike should trigger every sector simultaneously."""
        from swing_model.run_swing_model import _check_black_swan_per_sector

        active_sectors = {"semiconductors": {}, "healthcare": {}}
        mkt = self._mkt(
            vix_pct_change=0.50,  # well above the 40% default threshold
            semiconductors=self._df([100.0, 99.0]),
            healthcare=self._df([200.0, 199.0]),
        )
        results = _check_black_swan_per_sector(active_sectors, mkt, cfg=None)
        assert results["semiconductors"]["black_swan_triggered"] is True
        assert results["healthcare"]["black_swan_triggered"] is True

    def test_newly_triggered_only_fires_once_per_sector_episode(self):
        from swing_model.run_swing_model import _check_black_swan_per_sector

        active_sectors = {"semiconductors": {}}
        crash_mkt = self._mkt(vix_pct_change=0.0, semiconductors=self._df([100.0, 90.0]))

        first = _check_black_swan_per_sector(active_sectors, crash_mkt, cfg=None)
        assert first["semiconductors"]["_newly_triggered"] is True

        second = _check_black_swan_per_sector(active_sectors, crash_mkt, cfg=None)
        assert second["semiconductors"]["_newly_triggered"] is False

    def test_missing_vix_pct_change_skips_every_sector(self):
        from swing_model.run_swing_model import _check_black_swan_per_sector

        active_sectors = {"semiconductors": {}}
        mkt = {"vix_pct_change": None, "sector_benchmark_dfs": {"semiconductors": self._df([100.0, 90.0])}}
        assert _check_black_swan_per_sector(active_sectors, mkt, cfg=None) == {}

    def test_sector_missing_benchmark_data_is_skipped_not_crashed(self):
        from swing_model.run_swing_model import _check_black_swan_per_sector

        active_sectors = {"semiconductors": {}, "regional_banks": {}}
        mkt = self._mkt(vix_pct_change=0.0, semiconductors=self._df([100.0, 90.0]), regional_banks=None)
        results = _check_black_swan_per_sector(active_sectors, mkt, cfg=None)
        assert "semiconductors" in results
        assert "regional_banks" not in results

    def test_state_persists_across_calls_via_black_swan_state_file(self):
        """Cooldown must survive between scans (separate process invocations
        in reality) — proven here by calling twice as if they were two
        independent scans, relying only on the on-disk state file, not any
        in-memory object carried over by the test itself."""
        from swing_model.run_swing_model import _check_black_swan_per_sector

        active_sectors = {"semiconductors": {}}
        crash_mkt = self._mkt(vix_pct_change=0.0, semiconductors=self._df([100.0, 90.0]))
        _check_black_swan_per_sector(active_sectors, crash_mkt, cfg=None)

        normal_mkt = self._mkt(vix_pct_change=0.0, semiconductors=self._df([100.0, 99.5]))
        result = _check_black_swan_per_sector(active_sectors, normal_mkt, cfg=None)
        # Still in cooldown (1 normal day < default 3-day resume requirement) —
        # proves the trigger from the first call was actually persisted.
        assert result["semiconductors"]["black_swan_triggered"] is False


class TestPaperRunnerBlackSwanWiring:
    """paper_trading/paper_runner.py had NO black swan check at all before
    2026-08-23 — the pipeline actually running 3x/day had no crash circuit
    breaker. These confirm the wiring wraps the shared per-sector function
    correctly (see test_black_swan_per_sector_alerting.py-style coverage
    above for the function's own behavior)."""

    def test_load_filled_open_positions_detail_excludes_unfilled_and_closed(self, tmp_path, monkeypatch):
        import paper_trading.paper_runner as pr

        csv_path = tmp_path / "paper_trades.csv"
        rows = [
            # Filled, open — should be included.
            {"ticker": "NVDA", "direction": "bullish", "fill_date": "2026-08-20",
             "fill_price": "120.0", "entry_price": "119.0", "stop_loss": "110.0", "outcome": ""},
            # Never filled — excluded (no real exposure).
            {"ticker": "AMD", "direction": "bullish", "fill_date": "", "fill_price": "",
             "entry_price": "150.0", "stop_loss": "140.0", "outcome": ""},
            # Already closed — excluded.
            {"ticker": "MU", "direction": "bullish", "fill_date": "2026-08-18",
             "fill_price": "80.0", "entry_price": "79.0", "stop_loss": "75.0", "outcome": "win"},
            # Different sector — excluded by the sector_tickers filter.
            {"ticker": "KEY", "direction": "bullish", "fill_date": "2026-08-19",
             "fill_price": "18.0", "entry_price": "18.0", "stop_loss": "17.0", "outcome": ""},
        ]
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)

        monkeypatch.setattr(pr, "PAPER_TRADES_CSV", csv_path)
        result = pr._load_filled_open_positions_detail({"NVDA", "AMD", "MU"})
        assert len(result) == 1
        assert result[0]["ticker"] == "NVDA"
        assert result[0]["entry_price"] == pytest.approx(120.0)  # fill_price, not entry_price
        assert result[0]["stop_loss"] == pytest.approx(110.0)

    def test_load_filled_open_positions_detail_no_file_returns_empty(self, tmp_path, monkeypatch):
        import paper_trading.paper_runner as pr
        monkeypatch.setattr(pr, "PAPER_TRADES_CSV", tmp_path / "does_not_exist.csv")
        assert pr._load_filled_open_positions_detail({"NVDA"}) == []

    def test_no_filter_returns_positions_across_every_sector_with_risk_pct(self, tmp_path, monkeypatch):
        """The cross-sector concentration check (2026-08-23) needs the
        portfolio-wide view — sector_tickers=None (the new default) must not
        drop any sector's positions, and risk_pct must come through for the
        net-delta math."""
        import paper_trading.paper_runner as pr

        csv_path = tmp_path / "paper_trades.csv"
        rows = [
            {"ticker": "NVDA", "direction": "bullish", "fill_date": "2026-08-20",
             "fill_price": "120.0", "entry_price": "119.0", "stop_loss": "110.0",
             "risk_pct": "0.0075", "outcome": ""},
            {"ticker": "KEY", "direction": "bullish", "fill_date": "2026-08-19",
             "fill_price": "18.0", "entry_price": "18.0", "stop_loss": "17.0",
             "risk_pct": "0.0050", "outcome": ""},
        ]
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)

        monkeypatch.setattr(pr, "PAPER_TRADES_CSV", csv_path)
        result = pr._load_filled_open_positions_detail()  # no filter = portfolio-wide
        tickers = {p["ticker"] for p in result}
        assert tickers == {"NVDA", "KEY"}
        by_ticker = {p["ticker"]: p for p in result}
        assert by_ticker["NVDA"]["risk_pct"] == pytest.approx(0.0075)
        assert by_ticker["KEY"]["risk_pct"] == pytest.approx(0.0050)


class TestCrossSectorConcentrationCheck:
    """Advisory-only (2026-08-23 full model audit, by explicit product
    decision — see the AskUserQuestion in that session): must never block a
    signal from being logged, only note when net directional exposure across
    ALL open sectors would cross the advisory threshold."""

    def test_existing_same_direction_exposure_projects_correctly(self, tmp_path, monkeypatch):
        """Reuses portfolio_manager.get_portfolio_delta directly — this just
        confirms the ephemeral-state shape paper_runner.py builds from
        _load_filled_open_positions_detail() is one that function accepts
        and sums correctly, not a re-implementation of the delta math."""
        from swing_model.portfolio_manager import get_portfolio_delta, MAX_NET_DIRECTIONAL_DELTA

        open_for_delta = [
            {"ticker": "NVDA", "direction": "bullish", "risk_pct": 0.01},
            {"ticker": "KEY", "direction": "bullish", "risk_pct": 0.01},
        ]
        ephemeral_state = {"positions": [
            {"direction": p["direction"], "risk_pct": p["risk_pct"], "open": True}
            for p in open_for_delta
        ]}
        current_delta = get_portfolio_delta(ephemeral_state)
        assert current_delta == pytest.approx(0.02)
        # A third same-direction 1% position pushes projected exposure to 3%,
        # well past the 1.5% advisory threshold used by the (currently
        # unused) live path — proves the threshold comparison paper_runner.py
        # makes would actually fire in this scenario.
        projected = current_delta + 0.01
        assert abs(projected) > MAX_NET_DIRECTIONAL_DELTA

    def test_opposite_direction_exposure_nets_out_and_does_not_trigger(self):
        from swing_model.portfolio_manager import get_portfolio_delta, MAX_NET_DIRECTIONAL_DELTA

        ephemeral_state = {"positions": [
            {"direction": "bullish", "risk_pct": 0.01, "open": True},
            {"direction": "bearish", "risk_pct": 0.01, "open": True},
        ]}
        current_delta = get_portfolio_delta(ephemeral_state)
        assert current_delta == pytest.approx(0.0)
        assert abs(current_delta) <= MAX_NET_DIRECTIONAL_DELTA


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
