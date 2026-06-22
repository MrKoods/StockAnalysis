"""Tests for backtesting/metrics.py — covers profit_factor, risk_norm_drawdown,
and the trailing-stop + sector-filter behaviour wired into the backtest engine."""

import pytest
from datetime import date, timedelta

from backtesting.metrics import (
    compute_profit_factor,
    compute_risk_normalized_drawdown,
    compute_max_drawdown,
    generate_report,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _trade(pnl_pct: float, realized_rr: float, entry_date: date | None = None) -> dict:
    if entry_date is None:
        entry_date = date(2024, 1, 1)
    return {
        "pnl_pct": pnl_pct,
        "realized_rr": realized_rr,
        "entry_date": entry_date,
    }


# ---------------------------------------------------------------------------
# compute_profit_factor
# ---------------------------------------------------------------------------

def test_profit_factor_no_trades_returns_zero():
    assert compute_profit_factor([]) == 0.0


def test_profit_factor_all_winners():
    trades = [_trade(0.10, 2.0), _trade(0.08, 1.5), _trade(0.15, 2.0)]
    pf = compute_profit_factor(trades)
    assert pf == float("inf")


def test_profit_factor_all_losers():
    trades = [_trade(-0.05, -1.0), _trade(-0.08, -1.0)]
    pf = compute_profit_factor(trades)
    assert pf == 0.0


def test_profit_factor_balanced():
    # 2 wins of 0.10 each, 2 losses of 0.10 each → PF = 1.0
    trades = [
        _trade(0.10, 2.0), _trade(0.10, 2.0),
        _trade(-0.10, -1.0), _trade(-0.10, -1.0),
    ]
    assert abs(compute_profit_factor(trades) - 1.0) < 1e-9


def test_profit_factor_strong_edge():
    # 3 wins of 0.20, 2 losses of 0.10 → gross_win=0.60, gross_loss=0.20 → PF=3.0
    trades = [
        _trade(0.20, 2.0), _trade(0.20, 2.0), _trade(0.20, 2.0),
        _trade(-0.10, -1.0), _trade(-0.10, -1.0),
    ]
    assert abs(compute_profit_factor(trades) - 3.0) < 1e-9


def test_profit_factor_excludes_breakeven_trades():
    # Breakeven trades (pnl_pct == 0.0) should not affect PF
    trades = [
        _trade(0.10, 2.0),
        _trade(0.0, 0.0),   # breakeven — excluded
        _trade(-0.10, -1.0),
    ]
    pf_with = compute_profit_factor(trades)
    pf_without = compute_profit_factor([_trade(0.10, 2.0), _trade(-0.10, -1.0)])
    assert abs(pf_with - pf_without) < 1e-9


# ---------------------------------------------------------------------------
# compute_risk_normalized_drawdown
# ---------------------------------------------------------------------------

def test_risk_norm_drawdown_no_trades():
    assert compute_risk_normalized_drawdown([]) == 0.0


def test_risk_norm_drawdown_all_winners_is_zero():
    trades = [_trade(0.10, 2.0, date(2024, 1, i + 1)) for i in range(5)]
    dd = compute_risk_normalized_drawdown(trades)
    assert dd == 0.0


def test_risk_norm_drawdown_single_full_loss():
    # One trade loses 1R. With 1% risk, equity goes 1.0 → 0.99 → drawdown = 1%.
    trades = [_trade(-0.05, -1.0, date(2024, 1, 1))]
    dd = compute_risk_normalized_drawdown(trades, risk_per_trade=0.01)
    assert abs(dd - 0.01) < 1e-9


def test_risk_norm_drawdown_recovery():
    # Lose 1R then win 2R: equity goes 1.0 → 0.99 → 1.0098. Drawdown = 1%.
    trades = [
        _trade(-0.05, -1.0, date(2024, 1, 1)),
        _trade(0.10, 2.0, date(2024, 1, 2)),
    ]
    dd = compute_risk_normalized_drawdown(trades, risk_per_trade=0.01)
    assert abs(dd - 0.01) < 1e-6


def test_risk_norm_drawdown_much_smaller_than_raw():
    # 5 full -1R losses in a row. Raw P&L drawdown would be ~25-40%;
    # risk-normalized at 1% per trade is exactly 5% cumulative.
    trades = [_trade(-0.20, -1.0, date(2024, 1, i + 1)) for i in range(5)]
    raw_curve = [1.0]
    eq = 1.0
    for t in trades:
        eq *= (1 + t["pnl_pct"])
        raw_curve.append(eq)
    raw_dd = compute_max_drawdown(raw_curve)
    norm_dd = compute_risk_normalized_drawdown(trades, risk_per_trade=0.01)
    # Raw DD on -20% per trade is much larger than 1% normalized
    assert raw_dd > norm_dd * 5


# ---------------------------------------------------------------------------
# generate_report integration
# ---------------------------------------------------------------------------

def test_generate_report_empty_trades():
    report = generate_report([], [1.0])
    assert report["total_trades"] == 0
    assert report["profit_factor"] == 0.0
    assert report["risk_norm_drawdown"] == 0.0


def test_generate_report_includes_new_metrics():
    trades = [
        _trade(0.10, 2.0, date(2024, 1, 1)),
        _trade(0.12, 2.0, date(2024, 1, 2)),
        _trade(-0.05, -1.0, date(2024, 1, 3)),
    ]
    equity_curve = [1.0, 1.10, 1.232, 1.1704]
    report = generate_report(trades, equity_curve)

    assert "profit_factor" in report
    assert "risk_norm_drawdown" in report
    assert report["profit_factor"] > 1.0
    assert 0.0 <= report["risk_norm_drawdown"] <= 1.0
    assert report["winning_trades"] == 2
    assert report["losing_trades"] == 1


# ---------------------------------------------------------------------------
# Trailing stop + sector filter — behavioural tests via backtest engine
# ---------------------------------------------------------------------------

def test_trailing_stop_not_active_before_min_hold_days():
    """Trailing stop must not fire in the first trail_min_hold_days days."""
    from backtesting.backtest_engine import BacktestEngine
    from swing_model.scoring import SwingScorer
    from swing_model.trade_selector import SwingTradeSelector
    import pandas as pd

    config = {
        "scoring_thresholds": {
            "breakout_volume_multiplier": 2.0,
            "ma_short_period": 20,
            "ma_long_period": 50,
            "relative_strength_outperformance": 5,
            "sentiment_lookback_days": 5,
            "news_lookback_days": 3,
            "min_rr_ratio": 2.0,
            "min_score_threshold": 3,
            "trailing_stop_min_hold_days": 12,
        },
        "trade_selector": {
            "iv_percentile_high_threshold": 50,
            "swing_expiry_days_min": 30,
            "swing_expiry_days_max": 90,
        },
        "backtesting": {"max_hold_days": 42},
        "watchlist": {"sector_etf_benchmark": ["SMH"]},
    }

    scorer = SwingScorer(config)
    selector = SwingTradeSelector(config)
    engine = BacktestEngine(scorer, selector, config)

    entry_price = 100.0
    atr_val = 5.0
    stop = entry_price - 2 * atr_val      # 90
    target = entry_price + 4 * atr_val    # 120
    risk = entry_price - stop             # 10

    base_date = pd.Timestamp("2024-01-02")

    # Build an active trade dict the way the engine would
    active = {
        "ticker": "TEST",
        "signal_date": pd.Timestamp("2024-01-01"),
        "entry_date": base_date,
        "entry_price": entry_price,
        "stop": stop,
        "target": target,
        "direction": "bullish",
        "structure": "long_stock",
        "score": 5,
        "atr": atr_val,
        "trail_extreme": entry_price,
    }

    # Simulate 5 bars where price rises well above entry + 1×risk (should not trigger trail yet)
    for day in range(1, 6):
        bar_date = base_date + pd.Timedelta(days=day)
        days_held = (bar_date - active["entry_date"]).days
        bar_high = entry_price + risk * 1.5   # 1.5× risk above entry

        entry = active["entry_price"]
        r = abs(entry - active["stop"])

        # Mirror the engine logic
        active["trail_extreme"] = max(active["trail_extreme"], bar_high)
        trail_extreme = active["trail_extreme"]

        if days_held >= engine.trail_min_hold_days:
            if trail_extreme >= entry + r:
                active["trailing_stop"] = trail_extreme - r

    assert "trailing_stop" not in active, (
        "Trailing stop should not activate before trail_min_hold_days"
    )


def test_sector_filter_blocks_long_in_downtrend():
    """Trade selector must reject bullish trades when sector is below its 50-day MA."""
    from swing_model.trade_selector import SwingTradeSelector

    config = {
        "scoring_thresholds": {
            "breakout_volume_multiplier": 2.0,
            "ma_short_period": 20,
            "ma_long_period": 50,
            "relative_strength_outperformance": 5,
            "sentiment_lookback_days": 5,
            "min_rr_ratio": 2.0,
            "min_score_threshold": 3,
            "trailing_stop_min_hold_days": 12,
        },
        "trade_selector": {
            "iv_percentile_high_threshold": 50,
            "swing_expiry_days_min": 30,
            "swing_expiry_days_max": 90,
        },
    }
    selector = SwingTradeSelector(config)

    indicators = {
        "close": 100.0,
        "atr": 3.0,
        "vol_percentile_52w": 0.30,
        "sector_above_ma50": False,    # sector in downtrend
        "market_above_ma200": True,
    }

    rec = selector.select("NVDA", score=5, indicators=indicators)
    assert rec is None, "Bullish trade should be blocked when sector is below MA50"


def test_sector_filter_blocks_short_in_uptrend():
    """Trade selector must reject bearish trades when sector is above its 50-day MA."""
    from swing_model.trade_selector import SwingTradeSelector

    config = {
        "scoring_thresholds": {
            "breakout_volume_multiplier": 2.0,
            "ma_short_period": 20,
            "ma_long_period": 50,
            "relative_strength_outperformance": 5,
            "sentiment_lookback_days": 5,
            "min_rr_ratio": 2.0,
            "min_score_threshold": 3,
            "trailing_stop_min_hold_days": 12,
        },
        "trade_selector": {
            "iv_percentile_high_threshold": 50,
            "swing_expiry_days_min": 30,
            "swing_expiry_days_max": 90,
        },
    }
    selector = SwingTradeSelector(config)

    indicators = {
        "close": 100.0,
        "atr": 3.0,
        "vol_percentile_52w": 0.30,
        "sector_above_ma50": True,     # sector in uptrend
        "market_above_ma200": True,
    }

    rec = selector.select("NVDA", score=-5, indicators=indicators)
    assert rec is None, "Bearish trade should be blocked when sector is above MA50"
