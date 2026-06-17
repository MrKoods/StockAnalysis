# SHARED ENGINE: Runs either model's scoring logic against historical data.
# Accepts a scorer and trade selector as parameters so it is model-agnostic —
# the same engine drives both run_backtest_swing.py and run_backtest_day.py.


class BacktestEngine:

    def __init__(self, scorer, trade_selector, config: dict):
        pass

    def run(self, tickers: list[str], start_date: str, end_date: str) -> list[dict]:
        """
        Replay the given scorer and trade selector over historical data for all tickers.
        Returns a list of trade records with entry, exit, P&L, and score at signal time.
        """
        pass

    def _replay_ticker(self, ticker: str, historical_bars: list[dict]) -> list[dict]:
        """Step through historical bars for one ticker, generate signals, and record simulated trades."""
        pass
