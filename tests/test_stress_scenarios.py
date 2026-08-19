"""
Tests for backtesting/stress_test.py.
Verifies stress scenarios produce valid output structure and that
circuit breaker thresholds trigger correctly under shock conditions.
"""

import pytest

from backtesting.stress_test import run_all_scenarios, SCENARIOS


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_positions():
    """
    Two open positions for stress testing. Keys match the real position-dict
    schema swing_model/portfolio_manager.py uses (stop_loss, risk_pct) —
    run_scenario() reads these exact field names.
    """
    return [
        {
            "ticker": "NVDA",
            "direction": "bullish",
            "entry_price": 120.0,
            "current_price": 125.0,
            "stop_loss": 112.0,
            "target": 138.0,
            "structure": "bull_call_spread",
            "risk_pct": 0.02,
            "days_held": 3,
        },
        {
            "ticker": "MU",
            "direction": "bullish",
            "entry_price": 85.0,
            "current_price": 87.0,
            "stop_loss": 79.0,
            "target": 103.0,
            "structure": "long_call",
            "risk_pct": 0.015,
            "days_held": 1,
        },
    ]


# ---------------------------------------------------------------------------
# Stress scenario tests
# ---------------------------------------------------------------------------

class TestStressScenarios:
    def test_all_scenarios_return_valid_structure(self, sample_positions):
        results = run_all_scenarios(
            open_positions=sample_positions,
            account_equity=15000.0,
        )
        assert set(results.keys()) == set(SCENARIOS.keys())
        for name, result in results.items():
            assert "total_pnl" in result
            assert "pct_of_equity" in result
            assert "circuit_breaker_triggered" in result

    def test_smh_30_drop_triggers_circuit_breaker(self, sample_positions):
        results = run_all_scenarios(
            open_positions=sample_positions,
            account_equity=15000.0,
        )
        smh_result = results.get("smh_30_pct_drop", {})
        # A 30% SMH drop should trigger at minimum Yellow circuit breaker
        assert smh_result.get("circuit_breaker_triggered") in ("yellow", "orange", "red")

    def test_nvda_40_gap_primarily_affects_nvda(self, sample_positions):
        results = run_all_scenarios(
            open_positions=sample_positions,
            account_equity=15000.0,
        )
        nvda_result = results.get("nvda_40_gap_down", {})
        pnl_by_ticker = nvda_result.get("pnl_by_position", {})
        # NVDA should have larger loss than MU in this scenario
        assert pnl_by_ticker.get("NVDA", 0) < pnl_by_ticker.get("MU", 0)

    def test_all_scenarios_defined(self):
        """Confirm all five required scenarios are present."""
        required = {
            "smh_30_pct_drop", "nvda_40_gap_down",
            "vix_spike_80", "fed_emergency_hike", "china_export_restriction",
        }
        assert required.issubset(set(SCENARIOS.keys()))
