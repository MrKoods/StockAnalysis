import pandas as pd

from shared.api_clients.market_data_client import get_ohlcv
from shared.indicators.technical_common import (
    moving_average,
    is_breakout,
    relative_strength,
    rolling_low,
    average_volume,
    rsi,
    atr,
    macd,
)
from shared.utils.risk_reward import compute_stop_level, compute_target_level
from shared.utils.logger import get_logger

logger = get_logger(__name__)

# Calendar days prepended to start_date so MA50 and ATR are fully warmed up by signal-time.
_WARMUP_CALENDAR_DAYS = 150
# Extra lookback needed to prime the SPY 200-day MA (~280 trading days ≈ 400 calendar days).
_SPY_WARMUP_CALENDAR_DAYS = 400


class BacktestEngine:
    """Runs either model's scoring logic against historical data.

    Accepts a scorer and trade selector as parameters so it is model-agnostic —
    the same engine drives both run_backtest_swing.py and run_backtest_day.py.
    """

    def __init__(self, scorer, trade_selector, config: dict):
        self.scorer = scorer
        self.trade_selector = trade_selector
        self.config = config
        self.thresholds = config.get("scoring_thresholds", {})
        self.bt_cfg = config.get("backtesting", {})
        self.max_hold_days: int = self.bt_cfg.get("max_hold_days", 30)
        self.trail_min_hold_days: int = self.thresholds.get("trailing_stop_min_hold_days", 10)
        self._benchmark_df: pd.DataFrame | None = None
        self._benchmark_ma50: pd.Series | None = None
        self._spy_df: pd.DataFrame | None = None
        self._spy_ma200: pd.Series | None = None

    def run(self, tickers: list[str], start_date: str, end_date: str) -> list[dict]:
        """
        Replay the given scorer and trade selector over historical data for all tickers.
        Returns a list of trade records with entry, exit, P&L, and score at signal time.
        """
        # Pre-fetch benchmark for relative strength (best-effort)
        benchmark = self.config.get("watchlist", {}).get("sector_etf_benchmark", [None])[0]
        if benchmark:
            extended_start = (
                pd.Timestamp(start_date) - pd.Timedelta(days=_WARMUP_CALENDAR_DAYS)
            ).strftime("%Y-%m-%d")
            try:
                self._benchmark_df = get_ohlcv(benchmark, extended_start, end_date)
                self._benchmark_ma50 = moving_average(self._benchmark_df, 50)
                logger.info(f"Loaded benchmark {benchmark} for backtest")
            except ValueError as exc:
                logger.warning(f"Benchmark load failed ({exc}); RS scores will be 0")

        # Pre-fetch SPY for the broad-market 200-day MA filter (best-effort)
        spy_start = (
            pd.Timestamp(start_date) - pd.Timedelta(days=_SPY_WARMUP_CALENDAR_DAYS)
        ).strftime("%Y-%m-%d")
        try:
            self._spy_df = get_ohlcv("SPY", spy_start, end_date)
            self._spy_ma200 = moving_average(self._spy_df, 200)
            logger.info("Loaded SPY 200-day MA filter")
        except ValueError as exc:
            logger.warning(f"SPY load failed ({exc}); market filter disabled")

        all_trades = []
        for ticker in tickers:
            logger.info(f"Backtesting {ticker}…")
            bars = self._load_indicator_bars(ticker, start_date, end_date)
            trades = self._replay_ticker(ticker, bars)
            logger.info(f"  {ticker}: {len(trades)} trade(s) simulated")
            all_trades.extend(trades)

        return all_trades

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load_indicator_bars(
        self, ticker: str, start_date: str, end_date: str
    ) -> list[dict]:
        """Load OHLCV, pre-compute all indicators for the full series, and return as a list of bar dicts."""
        extended_start = (
            pd.Timestamp(start_date) - pd.Timedelta(days=_WARMUP_CALENDAR_DAYS)
        ).strftime("%Y-%m-%d")

        try:
            df = get_ohlcv(ticker, extended_start, end_date)
        except ValueError as exc:
            logger.warning(f"Could not load data for {ticker}: {exc}")
            return []

        t = self.thresholds
        short = t.get("ma_short_period", 20)
        long_ = t.get("ma_long_period", 50)
        vol_mult = t.get("breakout_volume_multiplier", 1.5)
        rs_threshold = t.get("relative_strength_outperformance", 5) / 100.0

        # Pre-compute series for the full DataFrame (O(n), not O(n²))
        ma_short_s = moving_average(df, short)
        ma_long_s = moving_average(df, long_)
        breakout_s = is_breakout(df, lookback_window=short, volume_multiplier=vol_mult)
        rsi_s = rsi(df)
        atr_s = atr(df)
        macd_df = macd(df)

        prior_low_s = rolling_low(df, short).shift(1)
        prior_avg_vol_s = average_volume(df, short).shift(1)
        breakdown_s = (df["Close"] < prior_low_s) & (df["Volume"] > vol_mult * prior_avg_vol_s)

        returns = df["Close"].pct_change()
        realized_vol_s = returns.rolling(20).std() * (252 ** 0.5)
        vol_pct_s = _rolling_percentile_series(realized_vol_s, window=252)

        rs_s: pd.Series | None = None
        if self._benchmark_df is not None:
            try:
                rs_s = relative_strength(df, self._benchmark_df, window=short)
            except Exception:
                pass

        # Convert to a list of bar dicts, only for the actual backtest window
        backtest_start = pd.Timestamp(start_date)
        bars: list[dict] = []

        for i, date in enumerate(df.index):
            if date < backtest_start:
                continue

            # Skip bars where core indicators haven't warmed up yet
            if pd.isna(ma_long_s.iloc[i]) or pd.isna(atr_s.iloc[i]):
                continue

            close = float(df["Close"].iloc[i])
            ma_short_val = float(ma_short_s.iloc[i])
            ma_long_val = float(ma_long_s.iloc[i])

            lo = max(0, i - 2)
            breakout_recent = bool(breakout_s.iloc[lo : i + 1].any())
            breakdown_recent = bool(breakdown_s.iloc[lo : i + 1].any())

            rs_val: float | None = None
            if rs_s is not None and date in rs_s.index and not pd.isna(rs_s.loc[date]):
                rs_val = float(rs_s.loc[date])

            # Sector regime: benchmark close vs. benchmark MA50 on this date
            sector_above_ma50 = True
            if self._benchmark_ma50 is not None and date in self._benchmark_ma50.index:
                ma50_val = self._benchmark_ma50.loc[date]
                bench_close = self._benchmark_df.loc[date, "Close"] if date in self._benchmark_df.index else None
                if bench_close is not None and not pd.isna(ma50_val):
                    sector_above_ma50 = float(bench_close) > float(ma50_val)

            # Broad market filter: SPY close vs. SPY 200-day MA on this date
            market_above_ma200 = True
            if self._spy_ma200 is not None and date in self._spy_ma200.index:
                spy_ma200_val = self._spy_ma200.loc[date]
                spy_close = self._spy_df.loc[date, "Close"] if date in self._spy_df.index else None
                if spy_close is not None and not pd.isna(spy_ma200_val):
                    market_above_ma200 = float(spy_close) > float(spy_ma200_val)

            bar: dict = {
                "date": date,
                "open": float(df["Open"].iloc[i]),
                "high": float(df["High"].iloc[i]),
                "low": float(df["Low"].iloc[i]),
                "close": close,
                "volume": float(df["Volume"].iloc[i]),
                "ma_short": ma_short_val,
                "ma_long": ma_long_val,
                "above_ma_short": close > ma_short_val,
                "above_ma_long": close > ma_long_val,
                "ma_short_above_ma_long": ma_short_val > ma_long_val,
                "breakout_recent": breakout_recent,
                "breakdown_recent": breakdown_recent,
                "rsi": float(rsi_s.iloc[i]) if not pd.isna(rsi_s.iloc[i]) else 50.0,
                "atr": float(atr_s.iloc[i]),
                "macd": float(macd_df["macd"].iloc[i]) if not pd.isna(macd_df["macd"].iloc[i]) else 0.0,
                "macd_signal": float(macd_df["signal"].iloc[i]) if not pd.isna(macd_df["signal"].iloc[i]) else 0.0,
                "macd_histogram": float(macd_df["histogram"].iloc[i]) if not pd.isna(macd_df["histogram"].iloc[i]) else 0.0,
                "rs_vs_benchmark": rs_val,
                "rs_threshold": rs_threshold,
                "realized_vol_20d": float(realized_vol_s.iloc[i]) if not pd.isna(realized_vol_s.iloc[i]) else 0.0,
                "vol_percentile_52w": float(vol_pct_s.iloc[i]) if not pd.isna(vol_pct_s.iloc[i]) else 0.5,
                "sector_above_ma50": sector_above_ma50,
                "market_above_ma200": market_above_ma200,
                # Sentiment and news not available for historical backtest
                "sentiment_score_component": 0,
                "sentiment_direction": "neutral",
                "news_score_component": 0,
                "news_direction": "neutral",
            }
            bars.append(bar)

        return bars

    def _replay_ticker(self, ticker: str, historical_bars: list[dict]) -> list[dict]:
        """Step through historical bars for one ticker, generate signals, and record simulated trades."""
        trades: list[dict] = []
        active: dict | None = None

        for i, bar in enumerate(historical_bars):
            if active is not None:
                date = bar["date"]
                days_held = (date - active["entry_date"]).days
                entry = active["entry_price"]
                atr_val = active["atr"]

                risk = abs(entry - active["stop"])

                # Always track running extreme from entry day so the trailing stop
                # has the true high/low when it first activates.
                if active["direction"] == "bullish":
                    active["trail_extreme"] = max(active["trail_extreme"], bar["high"])
                else:
                    active["trail_extreme"] = min(active["trail_extreme"], bar["low"])
                trail_extreme = active["trail_extreme"]

                # Trailing stop: after the minimum hold period, once the trade gains 1× risk
                # trail 1× risk below the running extreme. The hold-day guard lets fast
                # breakout trades reach the fixed 2R target without being cut short;
                # the trailing stop then captures the slower drift-and-reverse time exits.
                if days_held >= self.trail_min_hold_days:
                    if active["direction"] == "bullish":
                        if trail_extreme >= entry + risk:
                            active["trailing_stop"] = trail_extreme - risk
                    else:
                        if trail_extreme <= entry - risk:
                            active["trailing_stop"] = trail_extreme + risk

                trailing_stop = active.get("trailing_stop")
                effective_stop = trailing_stop if trailing_stop is not None else active["stop"]

                hit_stop = (
                    (active["direction"] == "bullish" and bar["low"] <= effective_stop)
                    or (active["direction"] == "bearish" and bar["high"] >= effective_stop)
                )
                hit_target = (
                    (active["direction"] == "bullish" and bar["high"] >= active["target"])
                    or (active["direction"] == "bearish" and bar["low"] <= active["target"])
                )

                # Conservative: stop wins if both stop and target touched on the same bar
                if hit_stop:
                    active["exit_date"] = date
                    active["exit_price"] = round(effective_stop, 4)
                    active["exit_reason"] = "trailing_stop" if trailing_stop is not None else "stop"
                elif hit_target:
                    active["exit_date"] = date
                    active["exit_price"] = active["target"]
                    active["exit_reason"] = "target"
                elif days_held >= self.max_hold_days:
                    active["exit_date"] = date
                    active["exit_price"] = bar["close"]
                    active["exit_reason"] = "time"

                if "exit_date" in active:
                    active = _finalize_trade(active)
                    trades.append(active)
                    active = None
                continue  # Don't generate a new signal while in a trade

            # Not in a trade — check for a new signal
            score = self.scorer.score(bar)
            rec = self.trade_selector.select(ticker, score, bar)

            if rec is not None and i + 1 < len(historical_bars):
                next_bar = historical_bars[i + 1]
                entry_price = next_bar["open"]
                atr_val = bar["atr"]
                min_rr = self.thresholds.get("min_rr_ratio", 2.0)

                if rec["direction"] == "bullish":
                    stop = compute_stop_level(entry_price, atr_val, 2.0)
                    target = compute_target_level(entry_price, stop, min_rr)
                else:
                    stop = entry_price + 2.0 * atr_val
                    target = entry_price - abs(entry_price - stop) * min_rr

                active = {
                    "ticker": ticker,
                    "signal_date": bar["date"],
                    "entry_date": next_bar["date"],
                    "entry_price": round(entry_price, 4),
                    "stop": round(stop, 4),
                    "target": round(target, 4),
                    "direction": rec["direction"],
                    "structure": rec["structure"],
                    "score": score,
                    "atr": atr_val,
                    "trail_extreme": entry_price,  # tracks running high (bull) or low (bear)
                }

        return trades


def _finalize_trade(trade: dict) -> dict:
    """Compute P&L and realized R:R once exit is known."""
    entry = trade["entry_price"]
    exit_ = trade["exit_price"]
    stop = trade["stop"]
    direction = trade["direction"]

    pnl_pct = (exit_ - entry) / entry if direction == "bullish" else (entry - exit_) / entry
    risk = abs(entry - stop)
    realized_rr = (pnl_pct * entry / risk) if risk > 0 else 0.0

    trade["pnl_pct"] = round(pnl_pct, 4)
    trade["realized_rr"] = round(realized_rr, 4)
    return trade


def _rolling_percentile_series(series: pd.Series, window: int = 252) -> pd.Series:
    """For each date, the fraction of prior `window` values in `series` below the current value."""
    return series.rolling(window, min_periods=window // 2).apply(
        lambda x: float((x[:-1] < x[-1]).sum()) / max(len(x) - 1, 1), raw=True
    )
