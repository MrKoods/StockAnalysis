# DAY-ONLY: Options flow data fetching and parsing — implied volatility, unusual options activity,
# and put/call ratio. Used by the day model to confirm or contradict intraday price signals.


def get_implied_volatility(ticker: str) -> float:
    """Return the current at-the-money implied volatility for the ticker."""
    pass


def get_put_call_ratio(ticker: str) -> float:
    """Return today's put/call volume ratio for the ticker."""
    pass


def get_unusual_activity(ticker: str) -> list[dict]:
    """Return a list of unusual options prints (large blocks, sweeps) detected today for the ticker."""
    pass


def is_iv_expanding(ticker: str, lookback_minutes: int) -> bool:
    """Return True if implied volatility has expanded over the recent intraday window — signals accelerating move."""
    pass


def has_bullish_flow(ticker: str) -> bool:
    """Return True if unusual call activity significantly exceeds put activity today."""
    pass
