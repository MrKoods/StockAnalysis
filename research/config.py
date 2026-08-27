"""
Single source of truth for every constant the research phases share.

V2's defining bug was a threshold hardcoded in one file, then independently
duplicated into three more, so that four months of backtests silently graded a
population live trading could never produce (see docs/v2_postmortem.md, rule 3).
Nothing in `research/` defines a shared constant locally. It is imported from
here or it does not exist.
"""

from pathlib import Path

# --------------------------------------------------------------------------
# Paths
# --------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"
HISTORICAL_DIR = DATA_DIR / "historical"
PANEL_DIR = DATA_DIR / "panel"
RESULTS_DIR = PROJECT_ROOT / "research" / "results"

# --------------------------------------------------------------------------
# Sample periods
#
# The out-of-sample window is not to be touched before Phase 6. Every parameter
# choice, every variant comparison and every discarded idea happens inside the
# in-sample window. The moment OOS data informs a decision it stops being
# out-of-sample, and the Phase 6 gate becomes meaningless.
# --------------------------------------------------------------------------

DATA_START = "2004-01-01"          # 1 extra year for the 252-day formation warmup
IN_SAMPLE_START = "2005-01-01"
IN_SAMPLE_END = "2018-12-31"
OUT_OF_SAMPLE_START = "2019-01-01"
OUT_OF_SAMPLE_END = "2026-08-31"

# --------------------------------------------------------------------------
# Benchmarks and market context
# --------------------------------------------------------------------------

BENCHMARK = "SPY"
VOLATILITY_INDEX = "^VIX"
CONTEXT_TICKERS = [BENCHMARK, VOLATILITY_INDEX]

# --------------------------------------------------------------------------
# Excluded tickers — names whose vendor data is unusable, with the reason.
#
# Applied at load time, not download time, so the cache stays a faithful record
# of what the vendor actually returned and the exclusion stays auditable.
# research.panel.detect_adjustment_anomalies() is what found this one, and runs
# on every --verify, so a re-download cannot silently reintroduce the problem or
# hide a new instance of it.
# --------------------------------------------------------------------------

EXCLUDED_TICKERS: dict[str, str] = {
    # Found in the Phase 1 verification, 2026-08-26. MNST oscillates between
    # ~$95 and ~$47 on scattered days through Jul-Aug 2026 — a clean 2:1 factor
    # appearing and disappearing. This is not a split: a split happens once and
    # adjusts all prior history. The vendor is intermittently serving
    # unadjusted values, producing six >50% moves with alternating signs in
    # three weeks. Left in, it would hand a momentum ranker enormous spurious
    # signals on a name that never actually moved.
    "MNST": "vendor split-adjustment oscillates Jul-Aug 2026 (six alternating >50% moves)",
}

# --------------------------------------------------------------------------
# Signal definition — the Phase 2/3 hypothesis
#
# Classic 12-1 cross-sectional momentum: rank on the return from t-252 to t-21,
# skipping the most recent month to avoid short-term reversal contaminating the
# formation window (Jegadeesh & Titman 1993; Asness et al. 2013).
# --------------------------------------------------------------------------

FORMATION_LOOKBACK_DAYS = 252
FORMATION_SKIP_DAYS = 21
TREND_FILTER_WINDOW = 200          # name-level and market-level 200-day MA
REBALANCE_FREQUENCY = "ME"         # month-end; pandas offset alias
N_QUANTILES = 5                    # quintiles — top quintile is the long book

# --------------------------------------------------------------------------
# Portfolio constraints — what $15,000 can actually hold
# --------------------------------------------------------------------------

ACCOUNT_SIZE = 15_000.0
MAX_POSITIONS = 15
LIQUIDITY_UNIVERSE_SIZE = 250      # top N by dollar volume, to keep costs real

# --------------------------------------------------------------------------
# Cost model — applied from Phase 4 onward, never optional
#
# An entry you could not have gotten is not a trade (post-mortem rule 4).
# --------------------------------------------------------------------------

COMMISSION_PER_TRADE = 0.0         # most retail brokers, US equities
SLIPPAGE_BPS_PER_SIDE = 10.0       # 0.10% each way on liquid large caps

# --------------------------------------------------------------------------
# Evaluation
# --------------------------------------------------------------------------

RISK_FREE_RATE = 0.04
TRADING_DAYS_PER_YEAR = 252
MONTHS_PER_YEAR = 12
BOOTSTRAP_ITERATIONS = 10_000
BOOTSTRAP_SEED = 42
FDR_LEVEL = 0.05

# --------------------------------------------------------------------------
# Phase 6 go/no-go gate — written before the work, per post-mortem rule 10.
#
# These are the numbers the strategy must clear on the untouched out-of-sample
# window, with rules locked beforehand. They are not aspirational targets to be
# revised downward when missed; missing any one of them is the documented kill
# trigger for the momentum thesis.
# --------------------------------------------------------------------------

GATE_MIN_OOS_SHARPE = 0.8              # net of costs, long-only
GATE_MIN_WALK_FORWARD_PASS_RATE = 0.5  # majority of windows positive expectancy
GATE_MAX_DRAWDOWN_VS_BENCHMARK = 1.3   # multiple of SPY drawdown, same window
GATE_MAX_DEFLATED_SHARPE_P = 0.1       # i.e. PSR >= 0.9
GATE_REQUIRE_IC_BH_SIGNIFICANT = True
