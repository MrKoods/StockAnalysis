# DAY-ONLY: Orchestrates intraday indicator data pull for the mega-cap/liquid basket.
# Calls shared API clients for price data, then feeds bars into intraday_indicators.py
# and options_flow.py, combining results into a per-ticker snapshot for the scorer.


class DayIndicatorPipeline:

    def __init__(self, day_config: dict, global_config: dict):
        pass

    def run(self) -> list[dict]:
        """Fetch and compute all intraday indicators for every ticker in the watchlist. Returns a list of ticker dicts."""
        pass

    def _fetch_intraday(self, ticker: str) -> dict:
        """Pull minute-level bars for today's session and compute VWAP, opening range, and relative volume."""
        pass

    def _fetch_options_flow(self, ticker: str) -> dict:
        """Pull current options flow snapshot (IV, unusual activity, put/call ratio) for one ticker."""
        pass
