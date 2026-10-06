"""Strategy parameters, universe, and paths for the liquidity-sweep-reversal test."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data" / "intraday"
OUTPUT_DIR = ROOT / "output"

TZ = "America/New_York"

# Top ~50 most liquid US stocks/ETFs (tight spreads, clean 1m bars).
UNIVERSE: list[str] = [
    # Index / sector ETFs
    "SPY", "QQQ", "IWM", "DIA", "SMH", "XLF", "XLE", "XLK", "TLT", "GLD",
    # Mega/large caps
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "AVGO", "AMD", "NFLX",
    "JPM", "BAC", "WFC", "C", "GS", "V", "MA", "XOM", "CVX", "UNH",
    "LLY", "JNJ", "PFE", "MRK", "ABBV", "KO", "PEP", "WMT", "COST", "HD",
    "DIS", "INTC", "MU", "QCOM", "ORCL", "CRM", "ADBE", "CSCO", "BA", "PLTR",
]


@dataclass(frozen=True)
class Params:
    tick: float = 0.01            # stocks: $0.01
    sweep_ticks: int = 2
    reclaim_bars: int = 3         # 5m bars, counting the bar that starts the sweep
    swing_n: int = 2
    choch_window: int = 20        # 1m bars after the reclaim close
    entry_timeout: int = 15       # 1m bars after the CHoCH bar
    stop_buffer_ticks: int = 2
    min_r: float = 1.5
    risk_pct: float = 0.005
    fib_lo: float = 0.62          # fallback zone when the CHoCH leg has no FVG
    fib_hi: float = 0.79
    use_tp2: bool = False
    max_trades_per_day: int = 2
    session_open: time = time(9, 30)
    last_entry: time = time(15, 30)   # no new entries at or after this bar open
    flatten: time = time(15, 55)      # exit at the open of this bar
    slippage_ticks: int = 1           # applied to every fill, each side

    @property
    def sweep_dist(self) -> float:
        return self.sweep_ticks * self.tick

    @property
    def stop_buffer(self) -> float:
        return self.stop_buffer_ticks * self.tick

    @property
    def slippage(self) -> float:
        return self.slippage_ticks * self.tick


DEFAULT = Params()
