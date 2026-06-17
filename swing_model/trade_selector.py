# SWING-ONLY: Maps composite swing score and IV regime to a recommended trade structure.
# Selects from: long stock, long calls, bull call spread, sell put credit spread,
# short stock, long puts, bear put spread, or no trade.
# R:R is computed via shared/utils/risk_reward.py before a candidate is surfaced.


class SwingTradeSelector:

    def __init__(self, swing_config: dict):
        pass

    def select(self, ticker: str, score: int, indicators: dict) -> dict:
        """
        Return a trade recommendation dict for the ticker given its score and current IV regime.
        Returns None if no structure meets the minimum R:R threshold.
        """
        pass

    def _get_iv_regime(self, indicators: dict) -> str:
        """Classify current IV as 'low', 'normal', or 'high' relative to the IV percentile threshold."""
        pass

    def _build_recommendation(self, ticker: str, structure: str, entry: float,
                               stop: float, target: float, rr: float) -> dict:
        """Assemble the final recommendation dict surfaced to output."""
        pass
