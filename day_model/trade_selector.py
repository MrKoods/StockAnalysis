# DAY-ONLY: Maps composite day score and market conditions to a recommended intraday trade structure.
# Selects from: long stock, short-dated long calls, short stock, short-dated long puts,
# debit spread, or no trade. Favors equity over options to avoid theta decay per day_config.yaml.


class DayTradeSelector:

    def __init__(self, day_config: dict):
        pass

    def select(self, ticker: str, score: int, indicators: dict) -> dict:
        """
        Return a trade recommendation dict for the ticker given its day score and current conditions.
        Returns None if conviction is too low or conditions are choppy.
        """
        pass

    def _should_use_options(self, score: int, indicators: dict) -> bool:
        """Return True only when directional conviction is strong and an IV-justified move is expected."""
        pass

    def _build_recommendation(self, ticker: str, structure: str, entry: float,
                               stop: float, target: float, rr: float) -> dict:
        """Assemble the final recommendation dict surfaced to output."""
        pass
