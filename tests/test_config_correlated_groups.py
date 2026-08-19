"""
Signal Integrity Audit finding C.4: config/swing_config.yaml's
regional_banks/healthcare correlated_groups each used to list every ticker
in the sector as ONE group, which made portfolio_manager.can_open_new_position's
correlated-group rule trivially match any two same-direction tickers from
that sector — the sector's own max_open_positions: 2 was structurally
unreachable for same-direction trades. Verifies both the config shape
directly, and the real end-to-end behavior through can_open_new_position.
"""

from swing_model.indicator_pipeline import load_config
from swing_model.portfolio_manager import can_open_new_position


def _cfg() -> dict:
    return load_config()


class TestCorrelatedGroupsConfigShape:
    def test_no_group_contains_every_ticker_in_regional_banks(self):
        cfg = _cfg()
        sector_cfg = cfg["portfolio"]["sectors"]["regional_banks"]
        all_tickers = set(cfg["watchlist"]["sectors"]["regional_banks"]["tickers"])
        for group in sector_cfg["correlated_groups"]:
            assert set(group) != all_tickers, (
                "a correlated_groups entry still lists every regional_banks ticker "
                "as one group — this makes max_open_positions unreachable for "
                "any same-direction pair (Signal Integrity Audit finding C.4)"
            )

    def test_no_group_contains_every_ticker_in_healthcare(self):
        cfg = _cfg()
        sector_cfg = cfg["portfolio"]["sectors"]["healthcare"]
        all_tickers = set(cfg["watchlist"]["sectors"]["healthcare"]["tickers"])
        for group in sector_cfg["correlated_groups"]:
            assert set(group) != all_tickers


class TestCanOpenNewPositionRealConfig:
    """End-to-end: with the real config, a second same-direction position in
    a genuinely-uncorrelated pair within regional_banks/healthcare must be
    allowed to reach the sector's own max_open_positions: 2 cap."""

    # Small enough that two same-direction positions stay under the 1.5%
    # net-directional-delta cap (an earlier, unrelated check) — isolates
    # these tests to the correlated-group rule specifically.
    _RISK_PCT = 0.005

    def _state_with_open(self, ticker: str, direction: str = "bullish") -> dict:
        return {
            "positions": [{
                "ticker": ticker, "direction": direction, "open": True,
                "risk_pct": self._RISK_PCT, "entry_price": 100.0, "stop_loss": 95.0,
            }],
            "account_equity": 15000.0, "peak_equity": 15000.0,
            "circuit_breaker_state": "normal", "consecutive_losses": 0,
        }

    def test_regional_banks_can_reach_two_open_positions(self):
        cfg = _cfg()
        state = self._state_with_open("ZION", "bullish")
        # ZION/KEY is not one of the fixed groups (KEY/FITB, HBAN/FITB,
        # KEY/HBAN, RF/FITB, ZION/RF) — a genuinely uncorrelated pair.
        allowed, reason = can_open_new_position(
            state, {"ticker": "KEY", "direction": "bullish", "risk_pct": self._RISK_PCT}, cfg=cfg,
        )
        assert allowed, f"expected allowed, got blocked: {reason}"

    def test_healthcare_can_reach_two_open_positions(self):
        cfg = _cfg()
        state = self._state_with_open("UNH", "bullish")
        # UNH is deliberately ungrouped (different business model — see
        # config's own comment), so any second healthcare ticker must clear.
        allowed, reason = can_open_new_position(
            state, {"ticker": "LLY", "direction": "bullish", "risk_pct": self._RISK_PCT}, cfg=cfg,
        )
        assert allowed, f"expected allowed, got blocked: {reason}"

    def test_genuinely_correlated_pair_still_blocked(self):
        # Regression guard: the fix shouldn't accidentally remove real
        # correlation protection — KEY/FITB (both large Midwest
        # super-regionals) must still block.
        cfg = _cfg()
        state = self._state_with_open("KEY", "bullish")
        allowed, reason = can_open_new_position(
            state, {"ticker": "FITB", "direction": "bullish", "risk_pct": self._RISK_PCT}, cfg=cfg,
        )
        assert not allowed
        assert "correlated_group" in reason
