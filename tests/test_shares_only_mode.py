"""
Tests for config `shares_only` (v2.2.133): every trade is the stock itself,
long or short — no options structure is evaluated or recommended.
"""

import pytest
import yaml

import paper_trading.paper_runner as pr
from shared.utils.position_sizer import derive_sizing_inputs
from swing_model.trade_selector import rank_trade_structures

SHARES_CFG = {"shares_only": True, "position_sizing": {"starting_capital": 15000, "max_capital_pct": 0.33333}}


def _rank(direction, cfg):
    entry, stop, target = (100.0, 95.0, 115.0) if direction == "bullish" else (100.0, 105.0, 85.0)
    return rank_trade_structures(
        {"ticker": "AAA", "direction": direction, "confidence": 60.0, "entry": entry,
         "stop_loss": stop, "target": target, "atr_14": 2.0},
        account_equity=15000.0, options_approval_level=2, iv_percentile=50.0, cfg=cfg,
    )


@pytest.mark.parametrize("direction,name", [("bullish", "long_stock"), ("bearish", "short_stock")])
def test_shares_only_returns_the_stock_itself(direction, name):
    result = _rank(direction, SHARES_CFG)
    [best] = result["ranked_structures"]
    assert best["name"] == name and best["recommended"] and best["position_type"] == "shares"
    assert best["capital_required"] == pytest.approx(5.0)              # per-share risk = stop distance
    assert derive_sizing_inputs(best["position_type"], best["capital_required"], 100.0, 95.0) == ("shares", 5.0, 100.0)


def test_bearish_short_is_not_dropped_by_the_under_50k_filter():
    """The 42-structure Filter 1 excludes short_stock under $50k; shares-only mode must not."""
    assert _rank("bearish", SHARES_CFG)["ranked_structures"][0]["name"] == "short_stock"


def test_without_the_switch_options_are_still_ranked():
    result = _rank("bullish", {})
    assert result["structures_evaluated"] == 42


def test_config_ships_with_shares_only_on():
    with open("config/swing_config.yaml", encoding="utf-8") as f:
        assert yaml.safe_load(f)["shares_only"] is True


@pytest.mark.parametrize("direction,name", [("bullish", "long_stock"), ("bearish", "short_stock")])
def test_rank_track_row_is_a_sized_stock_position(direction, name):
    candidate = {
        "ticker": "AAA", "sector": "semis", "direction": direction, "final_score": 60.0, "score": {},
        "earnings_result": {}, "positioning": {}, "regime": "normal", "vix_val": 15.0,
        "news_count": 0, "dominant_theme": "",
        "indicators": {"close": 100.0, "atr_14": 2.0, "rolling_high_20": 100.0, "rolling_low_20": 100.0},
    }
    row = pr._build_rank_track_row(candidate, SHARES_CFG, {}, "2026-10-14", None)
    assert row["position_type"] == "shares" and row["structure_recommended"] == name
    shares = int(row["position_size"])
    assert shares > 0
    assert float(row["capital_deployed"]) <= 15000 * 0.33333 + 1e-6
    risk = abs(float(row["entry_price"]) - float(row["stop_loss"])) * shares
    assert float(row["actual_dollar_risk"]) == pytest.approx(risk, rel=0.02)
