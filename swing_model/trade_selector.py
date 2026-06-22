from shared.utils.risk_reward import (
    compute_rr_ratio,
    compute_stop_level,
    compute_target_level,
    meets_minimum_rr,
)


class SwingTradeSelector:
    """Maps composite swing score and IV regime to a recommended trade structure.

    Structures available: long_stock, long_calls, bull_call_spread, sell_put_credit_spread,
    short_stock, long_puts, bear_put_spread. Returns None when confidence is too low or the
    setup does not meet the minimum R:R threshold.
    """

    _ATR_MULTIPLIER = 2.0  # Stop placed this many ATRs from entry

    def __init__(self, swing_config: dict):
        self.thresholds = swing_config["scoring_thresholds"]
        self.selector_cfg = swing_config["trade_selector"]
        self.min_rr: float = self.thresholds["min_rr_ratio"]
        self.min_score: int = self.thresholds.get("min_score_threshold", 3)

    def select(self, ticker: str, score: int, indicators: dict) -> dict | None:
        """
        Return a trade recommendation dict for the ticker given its score and current IV regime.
        Returns None if confidence is too low or no structure meets the minimum R:R threshold.
        """
        if abs(score) < self.min_score:
            return None  # Low or conflicting signals — no trade

        # Broad market filter: stand aside entirely when SPY is below its 200-day MA
        if not indicators.get("market_above_ma200", True):
            return None

        entry = indicators.get("close", 0.0)
        atr_val = indicators.get("atr", 0.0)
        if entry <= 0 or atr_val <= 0:
            return None

        direction = "bullish" if score > 0 else "bearish"

        # Sector regime filters: longs require sector uptrend, shorts require sector downtrend.
        # Both rules ensure we're trading with the sector trend, not against it.
        sector_above_ma50 = indicators.get("sector_above_ma50", True)
        if direction == "bullish" and not sector_above_ma50:
            return None
        if direction == "bearish" and sector_above_ma50:
            return None
        iv_regime = self._get_iv_regime(indicators)

        if direction == "bullish":
            stop = compute_stop_level(entry, atr_val, self._ATR_MULTIPLIER)
            target = compute_target_level(entry, stop, self.min_rr)
        else:
            stop = entry + self._ATR_MULTIPLIER * atr_val
            target = entry - abs(entry - stop) * self.min_rr

        if not meets_minimum_rr(entry, stop, target, self.min_rr):
            return None

        rr = compute_rr_ratio(entry, stop, target)
        structure = self._select_structure(score, direction, iv_regime)
        return self._build_recommendation(ticker, structure, entry, stop, target, rr, score, direction, iv_regime)

    def _get_iv_regime(self, indicators: dict) -> str:
        """Classify current IV as 'low', 'normal', or 'high' relative to the IV percentile threshold."""
        pct = indicators.get("vol_percentile_52w")
        if pct is None:
            return "normal"
        high_threshold = self.selector_cfg.get("iv_percentile_high_threshold", 50) / 100.0
        if pct >= high_threshold:
            return "high"
        if pct < 0.25:
            return "low"
        return "normal"

    def _select_structure(self, score: int, direction: str, iv_regime: str) -> str:
        """Choose a trade structure from the scope doc's decision table."""
        high_conf = abs(score) >= 4
        mod_conf = 2 <= abs(score) <= 3

        if direction == "bullish":
            if high_conf and iv_regime in ("low", "normal"):
                return "long_stock"
            if high_conf and iv_regime == "high":
                return "bull_call_spread"
            if mod_conf and iv_regime in ("low", "normal"):
                return "sell_put_credit_spread"
            if mod_conf and iv_regime == "high":
                return "bull_call_spread"
        else:  # bearish
            if high_conf and iv_regime in ("low", "normal"):
                return "short_stock"
            if high_conf and iv_regime == "high":
                return "bear_put_spread"
            if mod_conf and iv_regime in ("low", "normal"):
                return "long_puts"
            if mod_conf and iv_regime == "high":
                return "bear_put_spread"

        return "no_trade"

    def _build_recommendation(
        self,
        ticker: str,
        structure: str,
        entry: float,
        stop: float,
        target: float,
        rr: float,
        score: int,
        direction: str,
        iv_regime: str,
    ) -> dict:
        """Assemble the final recommendation dict surfaced to output."""
        return {
            "ticker": ticker,
            "direction": direction,
            "structure": structure,
            "entry": round(entry, 2),
            "stop": round(stop, 2),
            "target": round(target, 2),
            "rr_ratio": round(rr, 2),
            "score": score,
            "iv_regime": iv_regime,
        }
