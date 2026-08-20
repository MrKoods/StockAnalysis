"""
Tests for run_swing_model.py's _rescore_and_alert_open_positions() — the
live wiring for swing_model.position_rescoring.rescore_open_positions(), which
previously had zero call sites anywhere outside its own module (open
positions were never re-scored after entry: no early-exit flag, no time
stop, no trailing-stop update).

Also covers the position_rescoring.py config-key fix: "time_stop_min_progress_pct"
(never read, since config/swing_config.yaml defines "time_stop_no_progress_pct").
"""

from unittest.mock import patch

import swing_model.run_swing_model as rsm
from swing_model.position_rescoring import rescore_open_positions


def _position(ticker="NVDA", confidence=85.0, entry_price=100.0, stop_loss=95.0,
              target=115.0, direction="bullish", opened_days_ago=3):
    from datetime import datetime, timedelta, timezone
    opened = (datetime.now(timezone.utc) - timedelta(days=opened_days_ago)).isoformat()
    return {
        "ticker": ticker, "open": True, "direction": direction,
        "entry_price": entry_price, "stop_loss": stop_loss, "target": target,
        "confidence": confidence, "opened_at_utc": opened, "risk_pct": 0.01,
    }


def _indicators(ticker="NVDA", close=100.0):
    return {
        "ticker": ticker, "close": close, "atr_14": 2.0, "rsi_14": 55.0,
        "sma_20": close, "sma_50": close, "trend_intact": True,
        "sma_20_above_sma_50": True, "price_above_sma_50": True,
        "macd_bullish": True, "breakout_confirmed": False, "breakout_volume_zscore": 0.0,
        "rs_zscore": 0.0, "volume_profile_score": 4.0,
        "_fundamental_full": {}, "_positioning_full": {},
    }


class TestRescoreAndAlertOpenPositions:
    def test_no_open_positions_is_a_cheap_no_op(self):
        state = {"positions": [{"ticker": "NVDA", "open": False}]}
        with patch.object(rsm, "rescore_open_positions") as mock_rescore:
            result = rsm._rescore_and_alert_open_positions(
                state, {}, {}, {}, {}, {}, {}, {},
            )
        mock_rescore.assert_not_called()
        assert result == state["positions"]

    def test_open_position_gets_rescored_and_flagged_for_early_exit(self):
        state = {"positions": [_position(confidence=90.0)]}
        indicators_by_ticker = {"NVDA": _indicators(close=90.0)}  # price fell — confidence should drop
        ticker_sector_map = {"NVDA": "semiconductors"}

        with patch.object(rsm, "_try_send_signal_decay_alert"):
            updated = rsm._rescore_and_alert_open_positions(
                state, indicators_by_ticker, ticker_sector_map,
                {"semiconductors": "trending_up"}, {"semiconductors": 0.0},
                {"semiconductors": 0.0}, {"semiconductors": 0.0}, {},
            )

        assert len(updated) == 1
        assert "current_confidence" in updated[0]
        assert "management_action" in updated[0]
        # Whatever the action is, it should have been recorded for next
        # scan's change-detection.
        assert updated[0]["_last_management_action"] == updated[0]["management_action"]

    def test_alert_fires_only_once_per_new_management_action(self):
        """The dedup guard: an action that stays the same across two
        consecutive rescores must not re-alert the second time."""
        state = {"positions": [_position()]}
        indicators_by_ticker = {"NVDA": _indicators()}
        ticker_sector_map = {"NVDA": "semiconductors"}
        common_args = (
            indicators_by_ticker, ticker_sector_map,
            {"semiconductors": "trending_up"}, {"semiconductors": 0.0},
            {"semiconductors": 0.0}, {"semiconductors": 0.0}, {},
        )

        with patch.object(rsm, "rescore_open_positions", return_value=[
            {**_position(), "management_action": "time_stop", "current_confidence": 80.0, "confidence_drop": 5.0}
        ]):
            with patch.object(rsm, "_try_send_signal_decay_alert") as mock_alert:
                state["positions"] = rsm._rescore_and_alert_open_positions(state, *common_args)
                assert mock_alert.call_count == 1

                # Second scan, same action again — must NOT re-alert.
                state["positions"] = rsm._rescore_and_alert_open_positions(state, *common_args)
                assert mock_alert.call_count == 1

    def test_action_change_re_triggers_alert(self):
        state = {"positions": [_position()]}
        common_args = (
            {"NVDA": _indicators()}, {"NVDA": "semiconductors"},
            {"semiconductors": "trending_up"}, {"semiconductors": 0.0},
            {"semiconductors": 0.0}, {"semiconductors": 0.0}, {},
        )

        with patch.object(rsm, "_try_send_signal_decay_alert") as mock_alert:
            with patch.object(rsm, "rescore_open_positions", return_value=[
                {**_position(), "management_action": "early_exit", "current_confidence": 70.0, "confidence_drop": 15.0}
            ]):
                state["positions"] = rsm._rescore_and_alert_open_positions(state, *common_args)
            with patch.object(rsm, "rescore_open_positions", return_value=[
                {**_position(), "management_action": "time_stop", "current_confidence": 70.0, "confidence_drop": 15.0}
            ]):
                state["positions"] = rsm._rescore_and_alert_open_positions(state, *common_args)

        assert mock_alert.call_count == 2

    def test_hold_action_never_alerts(self):
        state = {"positions": [_position()]}
        with patch.object(rsm, "rescore_open_positions", return_value=[
            {**_position(), "management_action": "hold", "current_confidence": 85.0, "confidence_drop": 0.0}
        ]):
            with patch.object(rsm, "_try_send_signal_decay_alert") as mock_alert:
                rsm._rescore_and_alert_open_positions(
                    state, {"NVDA": _indicators()}, {"NVDA": "semiconductors"},
                    {"semiconductors": "trending_up"}, {"semiconductors": 0.0},
                    {"semiconductors": 0.0}, {"semiconductors": 0.0}, {},
                )
        mock_alert.assert_not_called()

    def test_closed_positions_pass_through_unrescored(self):
        state = {"positions": [
            _position(ticker="NVDA"),
            {**_position(ticker="AMD"), "open": False, "exit_price": 90.0},
        ]}
        with patch.object(rsm, "rescore_open_positions", return_value=[
            {**_position(ticker="NVDA"), "management_action": "hold", "current_confidence": 85.0, "confidence_drop": 0.0}
        ]):
            updated = rsm._rescore_and_alert_open_positions(
                state, {"NVDA": _indicators()}, {"NVDA": "semiconductors"},
                {"semiconductors": "trending_up"}, {"semiconductors": 0.0},
                {"semiconductors": 0.0}, {"semiconductors": 0.0}, {},
            )
        amd = next(p for p in updated if p["ticker"] == "AMD")
        assert amd["open"] is False
        assert amd["exit_price"] == 90.0

    def test_positions_grouped_by_sector_get_their_own_modifiers(self):
        """Two positions in different sectors must each be scored against
        THEIR sector's regime, not one sector's leaking into the other."""
        state = {"positions": [_position(ticker="NVDA"), _position(ticker="ZION")]}
        indicators_by_ticker = {"NVDA": _indicators("NVDA"), "ZION": _indicators("ZION")}
        ticker_sector_map = {"NVDA": "semiconductors", "ZION": "regional_banks"}

        seen_market_modifiers = []
        real_rescore = rescore_open_positions

        def spy(open_positions, current_indicators, cfg=None, market_modifiers=None, **kwargs):
            seen_market_modifiers.append(dict(market_modifiers or {}))
            return real_rescore(open_positions, current_indicators, cfg=cfg, market_modifiers=market_modifiers)

        with patch.object(rsm, "rescore_open_positions", side_effect=spy):
            with patch.object(rsm, "_try_send_signal_decay_alert"):
                rsm._rescore_and_alert_open_positions(
                    state, indicators_by_ticker, ticker_sector_map,
                    {"semiconductors": "trending_up", "regional_banks": "choppy"},
                    {"semiconductors": 5.0, "regional_banks": -5.0},
                    {"semiconductors": 0.0, "regional_banks": 0.0},
                    {"semiconductors": 0.0, "regional_banks": 0.0},
                    {},
                )

        regimes_seen = {m["regime"] for m in seen_market_modifiers}
        assert regimes_seen == {"trending_up", "choppy"}


class TestBearishPositionRescoring:
    """rescore_open_positions() must honor a position's OWN stored direction
    (Signal Integrity Audit finding B.2) rather than re-deriving it, and must
    select the bearish positioning mirror for a bearish position. Fixed
    previously but had no regression test — added while building the
    direction-parity registry/CI check (2026-08-19)."""

    def test_bearish_position_uses_bearish_positioning_mirror_and_stored_direction(self):
        indicators = _indicators()
        indicators["_positioning_full"] = {"marker": "bullish_mirror"}
        indicators["_positioning_full_bearish"] = {"marker": "bearish_mirror"}
        pos = _position(direction="bearish", entry_price=100.0, stop_loss=105.0, target=85.0)

        seen = {}
        from swing_model.position_rescoring import compute_confidence_score as real_ccs

        def spy(*args, **kwargs):
            seen["positioning"] = kwargs.get("positioning")
            seen["direction_override"] = kwargs.get("direction_override")
            return real_ccs(*args, **kwargs)

        with patch("swing_model.position_rescoring.compute_confidence_score", side_effect=spy):
            rescore_open_positions([pos], {"NVDA": indicators})

        assert seen["positioning"] == {"marker": "bearish_mirror"}
        assert seen["direction_override"] == "bearish"


class TestTimeStopConfigKeyFix:
    def test_configured_min_progress_pct_is_actually_read(self):
        pos = _position(entry_price=100.0, target=110.0, opened_days_ago=12)
        indicators = {"NVDA": _indicators(close=102.0)}  # 20% of target reached
        cfg = {"signal_decay": {"time_stop_no_progress_pct": 0.50}}  # stricter than default 0.30

        results = rescore_open_positions([pos], indicators, cfg=cfg)
        # 20% progress < the configured 50% floor -> time stop must fire.
        assert results[0]["time_stop_flag"] is True

    def test_old_unsuffixed_key_no_longer_does_anything(self):
        pos = _position(entry_price=100.0, target=110.0, opened_days_ago=12)
        indicators = {"NVDA": _indicators(close=102.0)}  # 20% of target reached
        # Old (wrong) key name — must NOT override the real default (0.30),
        # under which 20% progress still fails to clear the bar (time stop
        # fires either way here) — use a case where the two keys would
        # disagree to prove only the real one is read.
        cfg = {"signal_decay": {"time_stop_min_progress_pct": 0.01}}
        results = rescore_open_positions([pos], indicators, cfg=cfg)
        # If the bogus key were being read, 0.01 floor would mean 20%
        # progress clears it (no time stop). Since it's ignored, the real
        # default (0.30) still applies and time stop fires.
        assert results[0]["time_stop_flag"] is True
