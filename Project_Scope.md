# AI-Assisted Trading Signal System — Project Scope

---

## Executive Summary

**What this is:** A swing trading decision-support system for the semiconductor sector. It pulls technical, sentiment, and news data for 6 semiconductor stocks, combines them into a statistically-grounded confidence score, evaluates 42 trade structures by expected value, and delivers ranked trade recommendations via Discord alerts.

**What it is not:** An autonomous trading system. Every recommendation requires your review and manual execution.

**Starting capital:** $15,000 | **Holding period:** 5-15 trading days | **Sector:** Semiconductors (NVDA, AMD, AVGO, TSM, MU, ASML)

**Performance thresholds (all three required before live trading):** 80% win rate | 90/100 minimum confidence | 1:3 minimum R:R

**Build status:** Phase 1 complete (market data + technical indicators). Phase 2 in progress. 16 phases total.

**Quick reference — where to find things:**
| Topic | Section |
|---|---|
| Watchlist and sector focus | Watchlist & Niche Focus |
| File structure and build status | File Structure |
| How confidence is calculated | Statistical Methods |
| All 42 trade structures | Trade Selector — EV Framework |
| Discord alert format | Output & Alerts |
| Performance thresholds and backtesting rules | Performance Thresholds |
| Position sizing, circuit breakers, capital architecture | Performance & Capital Management Framework |
| All risk mitigations and solutions | Risk Mitigation Framework |
| Paper trading protocol | System Enhancements — Enhancement 1 |
| Model versioning rules | System Enhancements — Enhancement 2 |
| Full 16-phase roadmap | Implementation Roadmap |

---

## README Structure (for `README.md` in VS Code project root)

The `README.md` file in the `StockAnalysis/` project root must contain the following sections so any developer or collaborator can orient themselves without reading the full scope document:

**Section 1 — What this project does** (3-4 sentences): semiconductor swing trading decision-support system, confidence scoring, 42 trade structures, Discord output.

**Section 2 — Quick start** (numbered steps): clone repo → install requirements (`pip install -r requirements.txt`) → copy `.env.example` to `.env` and fill in API keys → run `python swing_model/run_swing_model.py` → check Discord for output.

**Section 3 — API keys required** (table): which keys, where to get them, which `.env` variable name to use.

**Section 4 — Project structure** (one-line description per top-level folder): `shared/`, `swing_model/`, `backtesting/`, `paper_trading/`, `monitoring/`, `data/`, `config/`.

**Section 5 — Current build status** (phase number, what's built, what's next): updated every time a phase completes.

**Section 6 — How to run each component** (one command per component): run swing model, run backtest, run paper trading, run stress test, run performance dashboard.

**Section 7 — Configuration** (what lives in `swing_config.yaml` vs `global_config.yaml`, how to change the watchlist or thresholds).

**Section 8 — Warnings** (3 bullet points): backtesting required before live use, not financial advice, $15k must not go live until Phase 13 paper trading passes all criteria.

---

## Overview

This project builds a **swing trading decision-support system** for the semiconductor sector, combining a technical indicator layer (price/volume, statistical analysis) with a sentiment/news layer (social media, news feeds) to produce a confidence-scored recommendation — including optimal trade structure (long/short equity, calls, puts, spreads) — for each ticker in the watchlist.

**Important framing:** this is a decision-support tool, not an autonomous trading system. No component should be trusted to execute trades without backtesting and human review.

---

## Watchlist & Niche Focus

The system is semiconductor-sector focused rather than broad-market, so indicator thresholds stay meaningful and backtesting results are coherent (a threshold tuned for semiconductors won't behave the same for utilities).

### Semiconductor Sector Watchlist

**Rationale:** Semiconductors move on multi-week narratives (AI demand cycles, supply chain news, earnings), have a clear sector ETF for relative-strength comparison, and carry high retail/social interest — good alignment with the swing model's sentiment + technical scoring approach.

**Sector ETF (for relative strength benchmark):** SMH or SOXX

**Starter watchlist:**
| Ticker | Company |
|---|---|
| NVDA | Nvidia |
| AMD | AMD |
| AVGO | Broadcom |
| TSM | Taiwan Semiconductor |
| MU | Micron |
| ASML | ASML Holding |
| SMH | Sector ETF (relative strength benchmark) |

**Future expansion candidates:** Clean energy/EV (TAN), biotech (XBI), regional banks/financials (KRE) — each would get its own sector ETF benchmark and watchlist if added.

---

## System Architecture

The system follows a two-layer pattern:

1. **Indicator Layer** — pulls and computes all relevant metrics (technical, sentiment, news) with full timestamp precision for temporal alignment
2. **Analysis/Decision Layer** — statistically combines indicator data into a 0-100 confidence score and recommends a trade structure optimized for risk/reward

Decision logic is rules-based and statistically grounded (z-score normalization, rolling win rates) for transparency and backtestability.

---

## File Structure (StockAnalysis project — current, as built)

```
StockAnalysis/
├── README.md                          # Project overview, setup instructions, how to run the model
├── Project_Scope.md                   # This document
├── .env.example                       # Template showing which API keys are needed (no real keys)
├── .gitignore                         # Excludes .env, data/raw, data/historical from version control
├── requirements.txt                   # Python dependencies for the whole project
│
├── config/
│   ├── global_config.yaml             # Shared settings: API base URLs, rate limits, output formats
│   └── swing_config.yaml              # Semiconductor watchlist, SMH/SOXX benchmark, all thresholds
│
├── shared/
│   ├── api_clients/
│   │   ├── market_data_client.py      # SHARED: wraps yfinance — pulls daily OHLCV + earnings calendar data (BUILT)
│   │   ├── sentiment_client.py        # SHARED: wraps Reddit via PRAW — timestamped posts, keyword-classified bullish/bearish labels
│   │   └── news_client.py             # SHARED: wraps Alpha Vantage News & Sentiment + Yahoo Finance + Finnhub headlines — timestamped, decay-weighted
│   │
│   ├── indicators/
│   │   └── technical_common.py        # SHARED: MA, breakout, RS, RSI, ATR, MACD + z-score normalization (BUILT)
│   │
│   └── utils/
│       ├── logger.py                  # SHARED: logging setup
│       ├── risk_reward.py             # SHARED: ATR-based + volume-profile stop/target math, R:R ratio calculation
│       ├── temporal_alignment.py      # SHARED: timestamp alignment, news decay weighting, leading/lagging classification, divergence detection
│       ├── regime_detection.py        # SHARED: classifies market into trending/choppy/high-vol/range-bound using VIX + SMH + breadth
│       ├── sector_rotation.py         # SHARED: tracks SMH vs. SPY flows across 5/20/60-day windows; outputs rotation state + modifier
│       ├── volume_profile.py          # SHARED: computes high/low volume nodes at price levels for target + stop placement
│       ├── earnings_calendar.py       # SHARED: fetches upcoming earnings dates via yfinance; outputs days-to-earnings + confidence penalty
│       ├── source_credibility.py      # SHARED: scores news outlets by historical accuracy and reputation
│       ├── ner_extractor.py           # SHARED: named entity recognition on news headlines — extracts ticker-specific sentiment from multi-company articles
│       ├── narrative_tracker.py       # SHARED: clusters news/social keywords into dominant themes per ticker; tracks theme momentum over time
│       ├── insider_tracker.py         # SHARED: fetches SEC Form 4 insider transactions via yfinance; flags unusual buying/selling clusters
│       ├── options_math.py            # SHARED: Black-Scholes pricing, Greeks, EV calculation, bid/ask spread adjustment, capital efficiency scoring
│       ├── position_sizer.py          # SHARED: calculates trade size based on account equity, confidence tier, circuit breaker state, structure capital requirement
│       ├── data_validator.py          # SHARED: pre-flight validation of all incoming data; excludes corrupt tickers; logs failures to validation_log.csv
│       ├── black_swan_detector.py     # SHARED: intraday monitor for SMH > 7% drop or VIX > 40% spike; fires Red Alert; suspends new signals until regime normalizes
│       ├── seasonality.py             # SHARED: calendar-based confidence modifier — semiconductor seasonal patterns by month/quarter; amplifies or reduces confidence based on historical seasonal win rates
│       ├── macro_overlay.py           # SHARED: monitors Fed rate direction, USD strength, China trade policy signals; applies macro confidence modifier above individual ticker scoring
│       ├── notification_router.py     # SHARED: routes alerts to Discord (primary) + email/SMS (secondary, critical alerts only); reads NOTIFICATION_CONFIG from .env
│       └── discord_alerts.py          # SHARED: formats + sends all Discord alert types; reads DISCORD_WEBHOOK_URL from .env
│
├── swing_model/
│   ├── indicator_pipeline.py          # Orchestrates all data pulls + indicator calculations for semiconductor watchlist (in progress)
│   ├── sentiment_layer.py             # Credibility-weighted sentiment trajectory + velocity; leading/lagging classification; divergence flagging; cross-platform consistency; spike detection
│   ├── news_layer.py                  # NER-extracted ticker-specific news sentiment; source credibility weighting; narrative theme tracking; news clustering; timezone-adjusted windows
│   ├── cross_ticker_analysis.py       # Detects sector-wide moves vs. genuine individual divergence across the 6-ticker watchlist
│   ├── signal_decay.py                # Re-scores open positions daily; flags early exit when confidence drops significantly post-entry
│   ├── portfolio_manager.py           # Tracks open positions; reads/writes data/processed/position_state.json on every run for persistence between scans; enforces simultaneous position limits; manages circuit breaker state; calculates portfolio delta; fires circuit breaker Discord alerts; PDT tracking; entry confirmation handling
│   ├── scoring.py                     # Master confidence scorer — combines all inputs + applies all modifiers including seasonality and macro overlay
│   ├── trade_selector.py              # EV-based trade ranker — evaluates all 42 trade structures; runs standard EV formula for simple structures and full P&L surface for complex (ratio/back spreads); applies all 8 filter types; outputs ranked eligible structures with exclusion reasons for ineligible ones
│   ├── feedback_loop.py               # Logs closed trade outcomes; updates rolling win rate per signal combination; feeds back into scoring engine calibration
│   └── run_swing_model.py             # Entry point — run daily to generate ranked swing recommendations; reads model version from CHANGELOG.md
│
├── backtesting/
│   ├── backtest_engine.py             # Replays scoring logic against historical data; 70/30 split; walk-forward validation; per-regime reporting
│   ├── metrics.py                     # Win rate, R:R, drawdown, Sharpe — confidence calibration, per-regime stats, stress test results
│   ├── stress_test.py                 # Runs hypothetical extreme scenarios (30% sector drop, 40% single-ticker gap) against current portfolio and scoring system
│   ├── run_backtest.py                # Entry point for backtesting; accepts --sensitivity flag to run threshold sensitivity analysis (85/87/90/92/95) before full backtest
│   └── reports/
│       └── sensitivity_analysis.csv   # Output of --sensitivity run: win rate, R:R, signal frequency, max consecutive losses at each confidence threshold
│
├── paper_trading/
│   ├── paper_trade_engine.py          # Simulates live trading with real-time data but no real capital; tracks fills, slippage, and P&L against Discord alert prices
│   ├── fill_tracker.py                # Logs recommended price vs. actual fill price per trade; feeds slippage model calibration
│   └── paper_trade_metrics.py         # Forward-testing win rate, R:R, and EV vs. theoretical; pass/fail criteria for Phase 13 go-live decision
│
├── monitoring/
│   └── performance_dashboard.py       # Generates weekly Discord performance summary: rolling win rate, avg R:R, confidence distribution, actual vs. theoretical EV per structure
│
├── data/
│   ├── raw/                           # Cached raw API responses (gitignored)
│   ├── processed/
│   │   ├── position_state.json        # Persistent position tracker — open positions, entry prices, current stops, holding day count, circuit breaker state; read/written by portfolio_manager.py on every scan run
│   │   ├── signal_win_rates.json      # Rolling win rate per signal combination — updated by feedback_loop.py after every closed trade; NOT directly used by scoring engine until monthly calibration passes
│   │   ├── live_weights.json          # Current live scoring weights — updated only after monthly calibration passes out-of-sample check; read by scoring.py on every scan
│   │   └── macro_state.json           # Current macro overlay state (favorable/neutral/adverse) — updated daily; read by scoring.py as a modifier input
│   ├── historical/                    # Historical data for backtesting (gitignored)
│   └── logs/
│       ├── audit_log.csv              # Forensic log of every scan decision, score, modifier, and management action
│       ├── override_log.csv           # Manual log of every system override with reason — reviewed weekly
│       ├── validation_log.csv         # Log of every data validation failure with ticker, timestamp, and failure type
│       ├── fill_log.csv               # Recommended fill price vs. actual fill price per trade — feeds slippage model calibration
│       ├── trade_outcomes.csv         # Closed trade outcomes: entry/exit price, structure, confidence score, signal components, P&L — feeds feedback loop
│       └── performance_log.csv        # Weekly rolling win rate, R:R, EV accuracy, drawdown — feeds performance dashboard
│
├── output/
│   └── swing_recommendations/         # Daily ranked CSV/JSON output
│
└── tests/
    ├── test_shared_indicators.py
    ├── test_swing_scoring.py
    └── test_stress_scenarios.py
```

**Organizing principle:** `shared/` holds all reusable logic (data clients, indicator math, utilities). `swing_model/` contains only the pipeline, scoring, and trade selection logic specific to the semiconductor swing strategy. `config/swing_config.yaml` is the single source of truth for the watchlist and all thresholds.

**Build status:** `market_data_client.py` and `technical_common.py` complete and tested. `swing_model/indicator_pipeline.py` in progress. Everything else pending.

---

## Swing Trading Model

**Timeframe:** 5-15 trading days (1-3 calendar weeks). This is the target holding period for all swing trade candidates — short enough to capture fast semiconductor sector moves driven by news/AI narratives, long enough for multi-day sentiment and technical setups to play out. Backtesting success metrics (win rate, R:R, drawdown) are all measured against this specific window.

**Cadence:** Indicator layer runs 2-3 times daily — once pre-market, once mid-session, once after close. Technical indicators are recalculated on daily bars after close; sentiment/news layers run more frequently to capture intraday developments that may affect the next session.

### Indicator Layer (Swing)

| Category | Indicators | Source | Cost |
|---|---|---|---|
| Technical | 20/50-day MAs, 20/50-day breakout levels, 20-day avg volume, relative strength vs. SMH/SOXX, RSI, ATR, MACD, volume profile | yfinance | Free |
| Social/Sentiment | Timestamped posts, keyword-classified bullish/bearish labels, mention volume, sentiment trajectory, velocity, unusual spike detection, cross-subreddit consistency (r/wallstreetbets vs. r/stocks, r/investing, r/semiconductors) | Reddit API via PRAW | Free |
| News (primary) | Timestamped articles, NER-extracted ticker-specific sentiment, pre-computed scores, source credibility weighting, narrative theme tracking | Alpha Vantage News & Sentiment (25 calls/day free tier) | Free |
| News (secondary) | Recent headlines with timestamps; NER applied for ticker precision | Yahoo Finance via yfinance + Finnhub `/company-news` (free tier) | Free |
| Insider/Institutional | SEC Form 4 insider buying/selling; institutional commentary appearing in social discussion | yfinance calendar data | Free |
| Geographic/Timezone | Pre-market Asian + European social/news signals as leading indicators for US session open | Reddit + Alpha Vantage (timezone-filtered) | Free |

### Statistical Methods (How Confidence Is Actually Computed)

The confidence score (0-100) is derived from statistical analysis of each indicator's current value relative to its own history, combined with historical win rates for similar signal patterns, regime awareness, and cross-ticker context. This makes the score data-driven and market-condition-aware rather than assumption-driven.

**1. Z-score normalization**
Before combining any indicators, each indicator's current value is converted to a z-score — how many standard deviations above or below its own historical mean it currently sits. This puts all indicators (price, volume, RSI, sentiment volume, etc.) on a comparable scale regardless of their units, and ensures a signal that is unusually strong contributes more confidence than one that is only marginally above its threshold.

Example: a breakout where volume is 3.2 standard deviations above its 20-day mean contributes more confidence than one where volume is only 0.8 standard deviations above — even though both technically qualify as "above average."

**2. Rolling historical win rate per signal combination**
For each combination of indicator states (e.g., breakout confirmed + RSI 50-65 + positive RS vs. SMH + sentiment building), the system looks back at historical instances of that same pattern in the semiconductor watchlist and calculates: what percentage of the time did price produce a meaningful move in the expected direction within the 5-15 trading day window? That empirical win rate directly weights the confidence contribution of that signal pattern. Calibrated during backtesting (Phase 7) and updated as new data accumulates.

**3. Correlation filtering**
Some indicators are correlated and effectively say the same thing (e.g., MACD crossover and 20/50-day MA crossover often fire together). If both are weighted equally, the same signal gets double-counted. Before computing the final confidence score, indicator correlations are checked and redundant signals are downweighted proportionally, so the score reflects the number of *independent* confirming signals, not just the total number of signals.

**4. Volatility-adjusted targets (ATR-based)**
Rather than fixed percentage price targets, the model uses ATR to define what a "meaningful move" looks like for each specific ticker over the 5-15 day window. NVDA's meaningful move is much larger in absolute terms than ASML's — ATR scaling ensures targets and stop-losses are proportional to each stock's actual volatility profile, not arbitrary fixed numbers.

**5. Market regime detection**
The model classifies the current market into one of four regimes before scoring any ticker — trending up, trending down, high-volatility/choppy, or range-bound. Regime is determined using VIX level, SMH trend (sector benchmark direction), and market breadth indicators. Confidence weights adjust dynamically based on regime:
- Trending market: breakout and momentum signals weighted higher; mean-reversion signals weighted lower
- Choppy/range-bound market: breakout signals weighted lower (more false breakouts); RSI overbought/oversold signals weighted higher
- High-volatility regime: overall confidence thresholds raised (more evidence required before surfacing a candidate); options structure selection shifts toward spreads regardless of IV on individual tickers

This prevents the model from producing high-confidence signals during hostile market environments where even good individual setups fail because of macro conditions. Regime is computed daily and stored as a field alongside each ticker's indicator output.

**6. Signal decay within the holding period**
The model scores a setup at entry, but also re-scores it daily throughout the 5-15 day holding window. Signal decay tracks how the confidence score evolves day by day after entry — if a bullish setup's confidence drops significantly (e.g., sentiment reverses, price breaks back below a key MA, news turns negative), that is flagged as an early exit signal rather than waiting for a fixed time stop. Without this, the model gives you an entry signal but no framework for managing the trade after entry. Signal decay output is a daily updated confidence time series per open position.

**7. Cross-ticker correlation within the sector**
The six semiconductor tickers are heavily correlated — when NVDA moves strongly, AMD often follows. If the model fires bullish signals on three tickers simultaneously, those are likely not three independent opportunities; they may reflect one sector-wide move expressed across correlated names. Cross-ticker correlation detection distinguishes between:
- Sector-wide move: multiple tickers firing simultaneously, each signal discounted individually since they share a common cause
- Individual divergence: one ticker outperforming or underperforming its peers despite similar sector conditions — this is genuine stock-specific strength/weakness and warrants higher individual confidence

This prevents over-trading correlated names and ensures confidence scores reflect stock-specific evidence, not just sector tailwinds.

**8. Volume profile analysis**
Beyond comparing today's volume to a simple rolling average, volume profile maps where volume has historically been concentrated at specific price levels for each ticker. Price tends to move quickly through low-volume price areas and stall at high-volume nodes. This adds precision to ATR-based targets:
- Price targets are set at the next low-volume area above entry (where price can travel quickly) rather than an arbitrary ATR multiple
- Stop-losses are set just below the nearest high-volume support node (where price is most likely to find buyers)
- This makes entries, exits, and targets defensible based on actual historical trading activity at each price level

**9. Earnings calendar awareness**
Each ticker's upcoming earnings date is checked before any trade recommendation is surfaced. Earnings create a fundamentally different risk profile — IV spikes into the event, and even a correct directional call can lose money on a long options position due to IV crush after the announcement. The model applies the following earnings-aware adjustments:
- Within 5 trading days of earnings: confidence score reduced by a fixed penalty (configurable in `swing_config.yaml`); trade structure automatically shifted toward defined-risk spreads regardless of IV level
- On earnings day itself: no new trade recommendations for that ticker
- Within 3 trading days after earnings (IV settling): confidence scores tentatively restored; new setups evaluated fresh post-event
- Earnings dates sourced from yfinance's calendar data (free, no additional API needed)

**10. Sector rotation signal**
A macro-level filter that sits above individual ticker scoring. Tracks whether institutional money is flowing into or out of semiconductors as a whole relative to the broader market, using SMH vs. SPY performance across multiple timeframes (5-day, 20-day, 60-day). If semiconductors are in a rotation-out phase at the sector level, even strong individual ticker setups warrant reduced confidence — the sector headwind reduces the probability that any individual name can sustain a meaningful move against the flow. Sector rotation state is computed daily alongside regime detection and stored as a modifier applied to all ticker confidence scores before output.

### Confidence Scoring (Swing)

| Signal Category | Starting Weight | Statistical Method |
|---|---|---|
| Technical (breakout, trend, RS, RSI, ATR, MACD, volume profile) | 50-60% | Z-score normalized; volume profile levels for target/stop precision |
| Social/Sentiment (Reddit) | 20-25% | Trajectory + velocity over rolling 3-5 day window; cross-subreddit consistency multiplier; spike type classification |
| News (Alpha Vantage + Yahoo Finance + Finnhub) | 15-20% | NER ticker-specific sentiment; source credibility weighted; time-decayed; narrative theme alignment; news clustering |

**Modifiers applied after base score is computed:**
| Modifier | Effect |
|---|---|
| Market regime: trending | Breakout/momentum weights +10%; mean-reversion weights -10% |
| Market regime: choppy/range-bound | Breakout weights -15%; RSI overbought/oversold weights +10% |
| Market regime: high-volatility | All scores capped at 70 max; structure forced to spreads |
| Sector rotation: outflow from semis | All ticker scores reduced by up to -15 points |
| Earnings within 5 days | Score reduced by configurable penalty; structure forced to defined-risk |
| Cross-ticker: sector-wide move detected | Individual ticker scores discounted proportionally |
| Cross-ticker: genuine individual divergence | Individual ticker score boosted |
| Insider buying detected (Form 4) | Bullish confidence boosted; bearish confidence suppressed |
| Insider selling cluster detected | Bearish modifier applied regardless of technical signal |
| Narrative theme aligned with trade thesis | Sentiment/news contribution weighted up |
| Narrative theme opposed to trade thesis | Sentiment/news contribution weighted down |
| Cross-subreddit inconsistency (WSB vs. other subreddits diverge) | Social confidence contribution reduced |
| Manufactured spike detected (sudden, low-diversity accounts) | Social contribution flagged; confidence held pending cross-subreddit validation |
| Pre-market Asian/European signal contradicts US thesis | Confidence reduced; flagged for review |
| Seasonality: historically strong period for semis (e.g., Q4) | Confidence boosted by configurable seasonal modifier |
| Seasonality: historically weak period for semis (e.g., post-Q1) | Confidence reduced by configurable seasonal modifier |
| Macro overlay: rising rates + strong USD + China tensions | Confidence reduced across all tickers; only 95+ scores surfaced |
| Macro overlay: neutral/favorable macro environment | No modifier applied |
| Entry confirmation: position confirmed entered | Portfolio manager updates open position state |
| Entry confirmation: position skipped | Signal cleared; slot freed for next candidate; logged in override_log.csv |
| Signal decay (open position): confidence declining | Early exit flag triggered |

**Starting weights are hypotheses — calibrated win rates from backtesting (Phase 11) replace them with empirically derived weights.**

**Formal confidence score formula:**

The confidence score is computed as a weighted sum across three signal categories, then modified by a separate modifier layer. The formula is explicit and must be implemented exactly as defined in `swing_model/scoring.py`:

```
Base Score = (Technical Score × Technical Weight)
           + (Sentiment Score × Sentiment Weight)
           + (News Score × News Weight)

Final Score = Base Score + Sum(all applicable modifiers)
Final Score = min(100, max(0, Final Score))  # clamped to 0-100
```

**Maximum contribution per signal category (these must sum to 100 for Base Score):**

| Signal Category | Max Contribution | Weight | How Scored |
|---|---|---|---|
| Technical | 60 points max | 60% | Z-score of each indicator mapped to 0-20 points per sub-signal; 5 sub-signals (breakout, trend, RS, RSI, volume profile) × max 12 points each = 60 total |
| Sentiment | 25 points max | 25% | Trajectory (0-10) + velocity (0-5) + cross-platform consistency (0-5) + spike classification (0-5) = 25 total |
| News | 15 points max | 15% | Credibility-weighted score (0-6) + theme alignment (0-4) + clustering (0-3) + decay factor (0-2) = 15 total |
| **Total Base Score** | **100 points max** | **100%** | Sum of above three categories |

**Modifier bounds (applied after base score, can push above/below category scores but final is clamped 0-100):**

| Modifier | Min | Max |
|---|---|---|
| Regime (trending up/down, choppy, high-vol) | -15 | +10 |
| Sector rotation (outflow/neutral/inflow) | -15 | +5 |
| Earnings proximity (0-5 days / 6-18 days / 18+ days) | -20 | 0 |
| Cross-ticker (sector-wide / neutral / diverging) | -10 | +5 |
| Insider activity (selling cluster / none / buying) | -8 | +8 |
| Seasonality (weak / neutral / strong period) | -5 | +5 |
| Macro overlay (adverse / neutral / favorable) | -10 | +3 |
| **Total modifier range** | **-83** | **+36** |

**Example confidence breakdown (mathematically consistent):**
| Component | Sub-score | Category Max | Contribution |
|---|---|---|---|
| Breakout (volume z-score +2.4 → maps to 11/12) | 11 | 12 | +11 |
| Trend intact (20MA > 50MA, price > 50MA → 10/12) | 10 | 12 | +10 |
| Relative strength vs. SMH (z-score +1.8 → 9/12) | 9 | 12 | +9 |
| RSI at 58 neutral-bullish (7/12) | 7 | 12 | +7 |
| Volume profile: price above high-vol support (10/12) | 10 | 12 | +10 |
| **Technical subtotal** | **47** | **60** | **+47** |
| Sentiment trajectory: building 4/5 days (8/10) | 8 | 10 | +8 |
| Sentiment velocity: accelerating (4/5) | 4 | 5 | +4 |
| Cross-platform consistency: both bullish (4/5) | 4 | 5 | +4 |
| Spike classification: organic (4/5) | 4 | 5 | +4 |
| **Sentiment subtotal** | **20** | **25** | **+20** |
| News credibility-weighted score (5/6) | 5 | 6 | +5 |
| Theme alignment: AI demand (4/4) | 4 | 4 | +4 |
| News clustering: 2 independent sources (2/3) | 2 | 3 | +2 |
| Decay factor: article 6hrs ago (2/2) | 2 | 2 | +2 |
| **News subtotal** | **13** | **15** | **+13** |
| **Base Score** | | | **80/100** |
| Regime: trending up | | | +5 |
| Sector rotation: neutral | | | 0 |
| Earnings: 18 days away | | | 0 |
| Cross-ticker: NVDA diverging from peers | | | +5 |
| Insider: no recent Form 4 activity | | | 0 |
| Seasonality: neutral period | | | 0 |
| Macro overlay: neutral | | | 0 |
| **Final bullish confidence** | | | **90/100** ✅ |

### Social & News Signal Enhancements

**1. Source credibility scoring**
Not all news outlets carry equal weight. A Reuters article about NVDA carries more weight than an obscure financial blog. Source credibility scores are stored per outlet and updated on each data pull.

**2. Named entity recognition (NER) on news headlines**
Many semiconductor articles mention multiple companies simultaneously. An article saying "NVDA gains market share as AMD struggles with supply chain" is bullish for NVDA and bearish for AMD — without NER, this could be tagged as generically positive semiconductor news and applied equally to both. NER extracts which specific company names appear in each article and what sentiment is directed at each one individually, making news signals ticker-precise rather than sector-wide. Applied to Alpha Vantage, Yahoo Finance, and Finnhub headlines alike.

**3. Narrative theme tracking**
Beyond individual post/article sentiment, the model tracks which themes dominate semiconductor discussion at any given time — AI demand, supply chain constraints, China export restrictions, earnings expectations, competitive dynamics (NVDA vs. AMD), memory pricing cycles, etc. A bullish breakout in NVDA during a period when "AI demand" is the dominant narrative has more conviction than the same setup when "supply chain uncertainty" dominates. Themes are extracted from news headlines and social posts using keyword clustering. Current dominant theme per ticker is stored as a field and used to weight the news/sentiment confidence contribution up or down depending on whether the trade thesis aligns with or runs against the prevailing narrative.

**4. Unusual social volume spike detection**
Extends basic mention-volume tracking to distinguish between two types of spikes:
- Organic acceleration: mention volume building gradually over multiple days — typical of legitimate momentum building; treated as a confirmatory signal
- Sudden manufactured spike: volume appearing suddenly within minutes/hours from a small number of accounts — typical of coordinated activity or a breaking news catalyst; treated as a warning flag requiring cross-subreddit validation before contributing to confidence
Spike type classification uses rate-of-change of mention volume (acceleration, not just level) and account diversity analysis (are the spike posts coming from many independent accounts or a cluster of similar ones?).

**5. Cross-subreddit sentiment consistency**
r/wallstreetbets (hype/degen) and the more measured subreddits (r/investing, r/stocks, r/semiconductors) are cross-validated against each other rather than simply summed. When both show bullish sentiment independently and simultaneously, that's a much stronger signal than either alone. When they diverge (WSB strongly bullish, the rest neutral or bearish on the same ticker at the same time), confidence is reduced — WSB may be experiencing hype/manipulation isolated to one community. Cross-subreddit consistency score is a multiplier applied to the combined social sentiment contribution.

**6. Insider and institutional signal detection**
Two sub-components: SEC Form 4 insider transactions (executives buying/selling shares on the open market — sourced free from yfinance) and social discussion patterns suggesting institutional awareness (references to unusual options activity, acquisition rumors, or large block trades appearing in social before price moves). Insider buying by executives is one of the highest-conviction bullish signals available and is systematically underused in retail systems. Insider selling is treated as a bearish modifier, especially when clustered across multiple executives in a short window.

**7. Sentiment velocity**
Adds a second derivative to sentiment trajectory. The existing scope tracks whether sentiment is building (first derivative — direction). Sentiment velocity tracks whether that building is accelerating (second derivative — rate of change of rate of change). Sentiment that has been building slowly for 5 days and then suddenly accelerates often precedes a sharp price move — analogous to price momentum acceleration in technical analysis. Sentiment velocity is computed as a rolling second derivative of the bullish ratio over a 5-day window and stored as a separate field from sentiment trajectory.

**8. Geographic/timezone-adjusted sentiment windows**
Semiconductors are a globally-traded sector with heavy Asian retail interest (NVDA, AMD) and significant European institutional coverage (TSML, ASML). Social and news signals originating from Asian markets (appearing during US after-hours, roughly 6pm-4am ET) can be leading indicators for the next US session open. The sentiment layer applies timezone-aware windowing:
- Pre-market Asian window (6pm-midnight ET): signals weighted as leading indicators for next US session
- European window (2am-9:30am ET): signals weighted as early confirmation/contradiction of Asian signal direction
- US session (9:30am-4pm ET): real-time signals weighted at full value
- US after-hours (4pm-6pm ET): signals weighted as early reads on next-day Asian reaction
This turns what would otherwise be ignored after-hours noise into structured, time-contextualized leading information.

### Temporal Alignment (Sentiment + News ↔ Technical)

Temporal alignment determines *when* each sentiment or news signal appeared relative to price action — which determines how much weight it carries. A signal that *preceded* a price move is a leading indicator (high value); one that appeared *after* a move already happened is a lagging reaction (low value).

**Leading vs. lagging classification**
Every sentiment and news data point carries a full timestamp. The system tracks whether each signal appeared before or after a significant price move in the same ticker. Signals that historically precede moves are up-weighted; signals that historically follow moves are down-weighted. Classification is established empirically during backtesting and refined as new data accumulates.

**News decay weighting**
News sentiment is weighted by recency using a time-decay function — a bullish article published 2 hours ago gets full weight; one published 3 days ago gets near-zero weight. The decay curve is calibrated to the 5-15 day holding period (news older than ~5 trading days is effectively zeroed out for a swing trade thesis).

**Sentiment momentum vs. sentiment snapshot**
The model does not just ask "is sentiment bullish right now." It asks "has sentiment been consistently building over the last N days, and is it accelerating?" Both trajectory (first derivative) and velocity (second derivative) are computed in `swing_model/sentiment_layer.py` as rolling slopes, not point-in-time values.

**Price-sentiment divergence detection**
When sentiment and price move in opposite directions over a defined window:
- Sentiment bullish + building, price flat or down → potential setup (price may catch up) — increases bullish confidence moderately
- Price up strongly, sentiment flat or declining → warning flag (price move may lack conviction) — reduces confidence even if technical score is high
- Both aligned in same direction → standard confidence contribution

**News clustering**
Multiple independent bullish (or bearish) news items about the same ticker within a short window (same day or adjacent days) are treated as a stronger signal than one item repeated across outlets. Source diversity (not just article count) and NER-confirmed ticker specificity are both required for a cluster to be counted.

**Temporal alignment output fields per ticker:**
`sentiment_trajectory`, `sentiment_velocity`, `sentiment_lead_lag`, `news_decay_weighted_score`, `divergence_flag`, `news_cluster_count`, `cross_platform_consistency_score`, `dominant_narrative_theme`, `timezone_window_signals`, `insider_transaction_flag`, `source_credibility_weighted_score`

**Critical caveat:** confidence reflects statistically aligned evidence, not a guaranteed probability. Calibration to empirical win rates happens in Phase 10 backtesting.

### Trade Selector — Expected Value (EV) Framework

The trade selector does not use a lookup table or simple if/then rules. Instead it runs an **Expected Value (EV) calculation for every applicable trade type simultaneously**, ranks them by EV, filters by constraints, and surfaces the highest-ranking structure as the recommendation with alternatives. The decision is math, not opinion.

**Core EV Formula**

```
EV = (Win Probability × Average Win) - (Loss Probability × Average Loss)
```

Where:
- Win Probability = confidence score (e.g., 0.93 for a 93/100 score)
- Average Win = price move to volume-profile target × structure's profit multiplier
- Loss Probability = 1 - confidence score
- Average Loss = price move to ATR-based stop × structure's loss multiplier
- Structure multipliers differ per trade type — defined individually for each of the 42 structures below
- For complex structures (ratio spreads, P&L surface required), EV is computed across a full P&L surface at Day 1, 5, 10, 15 rather than a single terminal value

**Entry Zone Calculation (explicit formula, implemented in `risk_reward.py`):**

The entry zone shown in every Discord alert is calculated as follows — not approximated or manually estimated:

```
Entry Zone Lower = max(current_close, breakout_level) - (0.25 × ATR_14)
Entry Zone Upper = max(current_close, breakout_level) + (0.25 × ATR_14)
```

Where `breakout_level` is the 20-day rolling high. ATR_14 is the 14-day Average True Range. This produces an entry zone centered on the breakout level with a half-width of 0.25 ATR on each side — tight enough to preserve R:R but wide enough to account for normal intraday noise on entry day.

Stop loss: `entry_zone_lower - (2.0 × ATR_14)` OR the nearest high-volume support node below entry (whichever is closer to entry), configurable in `swing_config.yaml`.

Target: the next low-volume area above entry per volume profile, minimum distance = `3 × (entry - stop)` to satisfy 1:3 R:R threshold.

If the minimum 1:3 R:R target distance would place the target above the next high-volume resistance node (where price is likely to stall), the candidate fails the R:R filter and is not surfaced regardless of confidence score.

**Complete Trade Universe — All 42 Structures**

**Category 1: Equity**
| # | Trade Type | Direction | Risk Profile | Best Conditions |
|---|---|---|---|---|
| 1 | Long stock | Bullish | Unlimited upside, linear loss | High confidence, any IV, no options access |
| 2 | Short stock | Bearish | Unlimited loss risk (requires margin/locate) | High bearish confidence; capital filter often excludes at $15k |
| 3 | Long stock with trailing stop | Bullish | Linear, stop trails dynamically | Trending regime, high confidence, want no theta risk |
| 4 | Protective put (long stock + long put) | Bullish hedge | Defined downside, unlimited upside | Existing long position, rising uncertainty, want to keep upside |
| 5 | Collar (long stock + long put + short call) | Neutral/hedge | Defined both sides | Existing long position, high IV, want free or cheap hedge |
| 6 | Married put (stock + put entered simultaneously) | Bullish | Defined downside from entry | High confidence bullish but elevated uncertainty — insurance at entry |

**Category 2: Long Premium (Defined Risk, Directional)**
| # | Trade Type | Direction | Risk Profile | Best Conditions |
|---|---|---|---|---|
| 7 | Long call | Bullish | Premium paid is max loss | High confidence bullish, low/normal IV, fast move expected |
| 8 | Long put | Bearish | Premium paid is max loss | High confidence bearish, low/normal IV |
| 9 | Deep ITM call (stock replacement) | Bullish | High delta, behaves like stock, capped downside | High confidence, want stock-like exposure with defined risk |
| 10 | Deep ITM put | Bearish | High delta bearish, defined risk short alternative | High confidence bearish, want defined-risk short |
| 11 | LEAPS call (12-24 month expiry) | Bullish | Low theta decay vs. short-dated, slower decay | High conviction longer-term view; delta acts like stock, less time pressure |
| 12 | LEAPS put | Bearish | Same as LEAPS call benefits but bearish | Long-term bearish conviction, want time to play out without theta pressure |

**Category 3: Debit Spreads (Defined Risk, Directional, Capped Upside)**
| # | Trade Type | Direction | Risk Profile | Best Conditions |
|---|---|---|---|---|
| 13 | Bull call debit spread | Bullish | Net debit is max loss; spread width - debit is max gain | High confidence bullish, high IV (reduces cost vs. naked call) |
| 14 | Bear put debit spread | Bearish | Net debit is max loss; spread width - debit is max gain | High confidence bearish, high IV |
| 15 | Calendar call spread (horizontal) | Bullish/neutral | Limited loss (net debit), benefits from IV expansion and time decay on short leg | Neutral to mildly bullish, low IV, expecting gradual move |
| 16 | Calendar put spread (horizontal) | Bearish/neutral | Limited loss, benefits from time decay on short leg | Neutral to mildly bearish, low IV |
| 17 | Diagonal call spread (poor man's covered call) | Bullish | Buy far-dated call, sell near-dated call — reduced cost, benefits from time decay on short leg | Bullish, moderate IV, want cheap stock replacement with income from short call |
| 18 | Diagonal put spread | Bearish | Buy far-dated put, sell near-dated put | Bearish, moderate IV, want cheap short exposure with income |

**Category 4: Credit Spreads (Defined Risk, Premium Collection)**
| # | Trade Type | Direction | Risk Profile | Best Conditions |
|---|---|---|---|---|
| 19 | Bull put credit spread | Bullish | Max loss = spread width - premium; max gain = premium collected | High confidence bullish, time decay works for you, stock expected to stay above short strike |
| 20 | Bear call credit spread | Bearish | Max loss = spread width - premium; max gain = premium collected | High confidence bearish, stock expected to stay below short strike |

**Category 5: Undefined Risk (Short Premium — Capital Filter Will Typically Exclude at $15k)**
| # | Trade Type | Direction | Risk Profile | Auto-Filter Conditions |
|---|---|---|---|---|
| 21 | Naked short call | Bearish/neutral | Unlimited loss risk — only included in ranking; capital and Greeks filters exclude unless account > $50k | Excluded at $15k by capital filter; shown with exclusion reason |
| 22 | Naked short put | Bullish/neutral | Large loss risk (stock to zero) — same exclusion logic | Excluded at $15k; shown with exclusion reason |

**Category 6: Income/Yield Structures**
| # | Trade Type | Direction | Risk Profile | Best Conditions |
|---|---|---|---|---|
| 23 | Cash-secured put | Bullish | Put premium collected; loss = effective cost below breakeven | Bullish, want to own stock at discount, high IV |
| 24 | Covered call | Neutral/bullish | Capped upside; downside is stock loss minus premium | Existing long position, confidence below 90, want yield |
| 25 | Covered strangle (covered call + cash-secured put) | Neutral | Double premium collection; double directional risk | High IV, strong neutral conviction, sufficient capital |
| 26 | The Wheel (systematic cash-secured put → covered call cycle) | Bullish-neutral | Sequence of defined-risk premium collection trades | Bullish on stock fundamentals, want systematic income, prepared to own shares |

**Category 7: Neutral/Volatility (Range-Bound or Big-Move Plays)**
| # | Trade Type | Direction | Risk Profile | Best Conditions |
|---|---|---|---|---|
| 27 | Iron condor | Neutral | Defined both sides; profits from range-bound price | Choppy regime, high IV, confidence regime = neutral |
| 28 | Iron butterfly | Neutral | Tighter range than condor, higher premium, defined risk | Same as iron condor but higher conviction on pinning at specific price |
| 29 | Long butterfly (call or put) | Neutral | Defined risk; profits from price pinning at middle strike at expiry | Low IV, expecting price to stall at specific level |
| 30 | Short butterfly | Neutral/volatile | Defined risk; profits from large move away from middle strike | High IV expected to compress; expecting breakout from a range |
| 31 | Condor spread (4 different strikes) | Neutral | Wider profitable range than iron butterfly, lower premium | Choppy regime, want wider range than iron butterfly |
| 32 | Long straddle (buy call + put same strike) | Volatile | Premium paid is max loss; profits from large move either direction | Major catalyst expected (earnings, FDA), direction uncertain, low IV (cheap premium) |
| 33 | Long strangle (buy OTM call + OTM put) | Volatile | Premium paid is max loss; cheaper than straddle, needs larger move | Same as straddle but cheaper; needs bigger move to profit |
| 34 | Short straddle (sell call + put same strike) | Neutral | Undefined risk; max gain = premium collected | High IV expected to crush; strong neutral conviction; excluded at $15k by capital filter |
| 35 | Short strangle (sell OTM call + put) | Neutral | Undefined risk; wider range than short straddle | Same as short straddle; excluded at $15k |

**Category 8: Ratio and Back Spreads (Complex P&L Surface)**
| # | Trade Type | Direction | Risk Profile | Best Conditions |
|---|---|---|---|---|
| 36 | Call ratio spread (buy 1, sell 2) | Mildly bullish | Profits from small move up; risks large upside move — complex P&L | Mildly bullish, expect limited move, IV expected to drop |
| 37 | Put ratio spread (buy 1, sell 2) | Mildly bearish | Profits from small move down; risks large downside move | Mildly bearish, expect limited move |
| 38 | Call back spread / ratio back spread (sell 1, buy 2) | Bullish/volatile | Defined risk; profits from large bullish move OR large move down past short strike | Expect explosive move, low IV at entry |
| 39 | Put back spread (sell 1, buy 2) | Bearish/volatile | Defined risk; profits from large bearish move | Expect explosive bearish move, low IV |

**Category 9: Synthetic Structures**
| # | Trade Type | Direction | Risk Profile | Best Conditions |
|---|---|---|---|---|
| 40 | Risk reversal (sell OTM put, buy OTM call) | Bullish | Typically low/zero cost; undefined downside on short put below strike | Bullish, want stock-like exposure at low cost, high confidence, sufficient margin |
| 41 | Synthetic long stock (long call + short put same strike) | Bullish | Behaves like long stock; undefined downside | Bullish, want leveraged stock exposure; capital filter excludes at $15k |
| 42 | Synthetic short stock (short call + long put same strike) | Bearish | Behaves like short stock; undefined upside risk | Bearish, want leveraged short; capital filter excludes at $15k |

**Structure Classification by Filter Behavior**

Not all 42 structures will appear in ranked output for every candidate. The filter cascade determines which structures are eligible:

| Filter | Structures Affected | Behavior |
|---|---|---|
| **Undefined risk filter** | Naked short call, naked short put, short straddle, short strangle, synthetic long/short | Evaluated but displayed with ❌ EXCLUDED tag and reason at $15k account size; auto-eligible when account > $50k if margin approved |
| **Capital filter (5% max = $750 at $15k)** | Any structure requiring > $750 capital | Excluded from ranking; shown with exclusion reason and capital required |
| **R:R filter (≥ 1:3)** | Any structure with EV < 1:3 after slippage | Excluded from ranking; shown with actual R:R calculated |
| **Greeks filter** | Severe theta (< 5 day burn), misaligned vega, gamma spike risk near expiry | Excluded or penalized in ranking |
| **Liquidity filter** | Wide bid/ask spreads reducing real-world EV below 1:3 | Excluded after real-world EV recalculation |
| **Account type filter** | Structures requiring options Level 3+ approval | Excluded if `options_approval_level` in `swing_config.yaml` is insufficient |
| **Direction filter** | Bullish structures when thesis is bearish, and vice versa | Excluded; only neutral structures and thesis-aligned structures evaluated |
| **P&L surface requirement** | Ratio spreads, back spreads (items 36-39) | EV computed across full P&L surface (Day 1, 5, 10, 15 × target/flat/stop scenarios) rather than simple terminal EV formula; flagged as COMPLEX in output |
| **0DTE exclusion** | Any structure with expiry same day | Permanently excluded — not applicable to 5-15 day swing timeframe |

**EV Ranking Output (stored per candidate)**

```python
{
  "ticker": "NVDA",
  "direction": "bullish",
  "confidence": 93,
  "structures_evaluated": 42,
  "structures_eligible_after_filters": 8,
  "ranked_structures": [
    {
      "rank": 1,
      "type": "Bull Call Debit Spread",
      "ev_per_dollar_risked": 3.42,
      "max_loss": "$320",
      "max_gain": "$1,095",
      "rr_ratio": "1:3.4",
      "capital_required": "$320",
      "greeks": {"delta": 0.52, "theta": -0.08, "vega": 0.12},
      "recommended": True,
      "strikes": "Buy $120C / Sell $130C — 35 DTE",
      "filter_notes": []
    },
    {
      "rank": 2,
      "type": "Diagonal Call Spread",
      "ev_per_dollar_risked": 3.18,
      "max_loss": "$280",
      "max_gain": "$890",
      "rr_ratio": "1:3.2",
      "capital_required": "$280",
      "greeks": {"delta": 0.48, "theta": +0.04, "vega": 0.08},
      "recommended": False,
      "strikes": "Buy $120C 90 DTE / Sell $125C 35 DTE",
      "filter_notes": ["Alt if IV expected to rise — benefits from short leg decay"]
    },
    {
      "rank": null,
      "type": "Naked Short Call",
      "ev_per_dollar_risked": null,
      "recommended": False,
      "filter_notes": ["❌ EXCLUDED — undefined risk; eligible when account > $50k with Level 3 approval"]
    },
    {
      "rank": null,
      "type": "Long Stock",
      "ev_per_dollar_risked": 3.10,
      "capital_required": "$11,900",
      "recommended": False,
      "filter_notes": ["❌ EXCLUDED — capital required exceeds 5% max ($750) at current account size"]
    }
  ]
}
```

**New shared utility required:** `shared/utils/options_math.py` expanded to handle all 42 structure types — includes Black-Scholes pricing, Greeks calculations, EV formula per structure category, full P&L surface calculator for complex structures (ratio/back spreads), bid/ask spread slippage adjustment, capital efficiency scoring, and all filter logic. Standalone module testable with known inputs independent of the rest of the system.

---

## Implementation Roadmap

| Phase | Scope | Key Deliverables |
|---|---|---|
| **Phase 1** ✅ | Shared foundation | `market_data_client.py` (BUILT), `technical_common.py` with z-score normalization (BUILT) |
| **Phase 2** 🔄 | Technical pipeline | `swing_model/indicator_pipeline.py` — daily OHLCV pull, all technical indicators, normalized output table per ticker |
| **Phase 3** | Macro context layer | `regime_detection.py` (VIX + SMH + breadth → regime), `sector_rotation.py` (SMH vs. SPY flows), `earnings_calendar.py` (earnings penalty + structure override), `seasonality.py` (monthly/quarterly semiconductor seasonal modifiers), `macro_overlay.py` (Fed rates, USD strength, China trade policy → macro confidence modifier) |
| **Phase 4** | Sentiment + news layer | `sentiment_client.py`, `news_client.py`, `source_credibility.py`, `ner_extractor.py`, `narrative_tracker.py`, `insider_tracker.py`, `temporal_alignment.py`, `swing_model/sentiment_layer.py`, `swing_model/news_layer.py` |
| **Phase 5** | Advanced technical layer | `volume_profile.py` (high/low volume nodes), `swing_model/cross_ticker_analysis.py` (sector-wide vs. individual divergence) |
| **Phase 6** | Confidence scoring | `swing_model/scoring.py` — master scorer combining all inputs + all modifiers including seasonal and macro overlay |
| **Phase 7** | EV-based trade selector | `options_math.py` (Black-Scholes, Greeks, EV, slippage), `trade_selector.py` (15 trade types, all filters), `risk_reward.py`, `position_sizer.py` |
| **Phase 8** | Signal decay + portfolio management | `signal_decay.py` (daily re-scoring, all management stops), `portfolio_manager.py` (position tracking, circuit breakers, PDT tracking, entry confirmation handling, correlation override) |
| **Phase 9** | Risk mitigation layer | `data_validator.py`, `black_swan_detector.py`, exponential backoff in all clients, data fallback hierarchy, Alpha Vantage call budget enforcement, UTC timestamp normalization, audit_log, override_log, validation_log |
| **Phase 10** | Notification + output layer | `discord_alerts.py` (all alert types, entry confirmation listener), `notification_router.py` (Discord primary + email secondary + SMS tertiary for critical alerts), `run_swing_model.py` (daily entry point, health check, missed scan detection) |
| **Phase 11** | Model versioning + CHANGELOG | `CHANGELOG.md` structure, `model_versioning.py` (version tracking, re-backtest enforcement before version increment, version logged in every audit entry) |
| **Phase 12** | Backtesting | `backtest_engine.py` + `metrics.py` — 70/30 out-of-sample split, minimum 100 qualifying trades, walk-forward validation, per-regime performance reporting, stress testing (`stress_test.py`), confidence calibration |
| **Phase 13** | Paper trading (60-90 days minimum) | `paper_trading/paper_trade_engine.py` (real-time data, simulated fills), `fill_tracker.py` (recommended vs. actual fill price logging), `paper_trade_metrics.py` (forward-testing win rate, R:R, EV accuracy vs. theoretical). Pass criteria: 80% win rate, 1:3 R:R, and slippage within 10% of modeled estimates sustained over minimum 60 trading days |
| **Phase 14** | Feedback loop + performance monitoring | `swing_model/feedback_loop.py` (closed trade outcomes → rolling win rate update → scoring engine recalibration), `monitoring/performance_dashboard.py` (weekly Discord performance summary: rolling win rate, avg R:R, actual vs. theoretical EV, confidence distribution, drawdown), `data/logs/trade_outcomes.csv`, `data/logs/fill_log.csv`, `data/logs/performance_log.csv` |
| **Phase 15 (future)** | Live execution | Only after Phase 13 paper trading passes all criteria — Alpaca live trading with manual confirmation on every alert; cloud hosting deployment for production reliability; slippage model updated from fill_log.csv data |
| **Phase 16 (ongoing)** | Continuous improvement | Quarterly model reviews using performance_log.csv; version increments with mandatory re-backtesting per CHANGELOG protocol; seasonality and macro overlay weights updated annually; watchlist expansion review (add new sectors per future expansion candidates) |

---

## API Stack (All Free)

| API | Purpose | Cost | Notes |
|---|---|---|---|
| yfinance | Daily OHLCV price data, Yahoo Finance news headlines, earnings calendar, insider transactions | Free | No API key needed; unofficial |
| Reddit API via PRAW | Social sentiment — timestamped posts, keyword-classified bullish/bearish labels, community discussion volume | Free | Rate limits manageable for 6-ticker watchlist |
| Alpha Vantage | News sentiment with pre-computed scores | Free | 25 calls/day free tier; 20 used per day per budget |
| Finnhub | Company news headlines (`/company-news`) | Free | Social-sentiment endpoint is paid-only, not used |
| Discord Webhook | Primary alert delivery for all signal types | Free | Webhook URL stored in .env |
| SMTP email | Secondary alert delivery for critical alerts only (circuit breakers, Black Swan, open position stops) | Free | Gmail SMTP or similar; backup when Discord unavailable |
| Twilio SMS (optional) | Tertiary alert for highest-priority alerts only (Black Swan, Red circuit breaker) | Free tier available | Twilio free tier: 3 numbers, ~$15 free credit; optional but recommended |

---

## Risk Mitigation Framework

This section defines the specific solutions implemented for each identified risk category. Every solution maps to a concrete implementation in the codebase or operational protocol.

---

### Category 1 — Model Risk Mitigations

**Solution: Out-of-sample split (70/30)**
70% of historical data is used for calibrating all confidence weights, win rates, and modifier values. The remaining 30% is held out completely and used only for final validation. Held-out period must include at least one bear market or high-volatility period (VIX > 30) and one semiconductor-specific stress period.

**Solution: Minimum 100 qualifying trades before win rate is valid**
Win rate of 80% is not statistically meaningful on fewer than 100 qualifying trades. If historical data produces fewer than 100 qualifying setups, extend the historical window — do not lower the confidence threshold to inflate sample size artificially.

**Solution: Walk-forward validation**
After initial calibration on months 1-18, validate on months 19-24. Roll forward: calibrate on 1-24, validate on 25-30. Repeat for all available windows. Model must meet performance thresholds across every walk-forward window, not just the initial one.

**Solution: Per-regime performance reporting**
Win rate and R:R are reported separately for each of the four market regimes (trending up, trending down, choppy, high-volatility). Model must meet thresholds in each regime independently. A model that passes overall but fails in a specific regime has a hidden regime dependency that must be addressed.

---

### Category 2 — Data Risk Mitigations

**Solution: Data fallback hierarchy (per source)**

Price data: yfinance (primary) → Alpha Vantage daily endpoint (fallback) → data-unavailable mode. In data-unavailable mode: all new signals frozen, immediate Discord alert sent, open positions managed using last-known cached data flagged as stale.

Sentiment data: Reddit → sentiment-offline mode. In sentiment-offline mode: sentiment layer contributes zero to confidence score, maximum confidence capped at 70 (below the 90 threshold, preventing new trades from firing), Discord alert sent flagging sentiment layer offline.

News data: Alpha Vantage (primary) → Yahoo Finance (secondary) → news-offline mode. Same cap behavior as sentiment-offline mode.

Open position management during data outage: even when all sources are unavailable, the system reads from `data/processed/` cache and fires time stop, trailing stop, and structure stop alerts using last-known data, clearly flagged as stale — "⚠️ Using cached data from [timestamp] — verify manually before acting."

**Solution: Alpha Vantage call budget (explicit daily allocation)**
Defined in `global_config.yaml` and enforced by `market_data_client.py`:
- Post-close scan: 6 news calls (one per ticker) + 1 SMH + 1 VIX = 8 calls
- Pre-market scan: 6 news calls = 6 calls
- Mid-session scan: 6 news calls = 6 calls
- Total daily: 20 calls (25/day limit — 5 calls buffer for retries)
Any scan that would exceed 25 total calls is rate-limited automatically — lowest-priority calls (mid-session news) are deferred first.

**Solution: Data validation layer (`shared/utils/data_validator.py`)**
Runs before every indicator calculation on every data pull. Checks:
- Price data: no gaps longer than 3 trading days; High ≥ Low ≥ 0; Close between High and Low; Volume > 0; no single-day move > 50% (likely split or data error)
- Sentiment data: bullish ratio between 0.0 and 1.0; mention volume positive integer; timestamps within expected range
- News data: sentiment scores within documented range; publication timestamp not in future; ticker attribution present
Any validation failure: exclude that ticker from current scan, log to `data/logs/validation_log.csv`, send Discord data validation alert. System continues scanning remaining tickers.

**Solution: Universal timestamp normalization**
All incoming data timestamps are converted to UTC immediately on ingestion, before any processing. Timezone of each source is hardcoded in the respective client (`sentiment_client.py`, `news_client.py`) based on each API's documented timezone convention. Any record with ambiguous or missing timezone is excluded from temporal alignment calculations and logged.

**Solution: Automatic retry with exponential backoff**
All API calls use exponential backoff: fail → wait 30s → retry → wait 60s → retry → wait 120s → retry → invoke fallback. Implemented in all client files (`market_data_client.py`, `sentiment_client.py`, `news_client.py`).

---

### Category 3 — Execution Risk Mitigations

**Solution: Slippage modeling in EV calculations**
Real-world EV = theoretical EV minus slippage estimate. Slippage modeled as 50% of bid/ask spread per leg for options structures; $0.02/share for stock. If real-world EV after slippage reduces R:R below 1:3, structure is excluded from ranking regardless of theoretical EV. Slippage estimates sourced from live bid/ask data at time of scan.

**Solution: Execution guidance in every Discord alert**
Every trade alert includes:
- Order type recommendation (limit at mid-price)
- Maximum acceptable fill price (above which R:R drops below 1:3 — cancel)
- Entry validity window (today only — do not carry to next session)
- Legging instruction (spread order vs. individual legs)
- If-unfilled instruction (discard — system re-evaluates at next scan, do not chase)

**Solution: Entry validity expiry**
Each signal includes a hard expiry timestamp. If not filled by market close on the alert day, the signal is discarded. The system re-evaluates at the next scan and re-alerts only if the setup still qualifies at current prices with valid R:R.

---

### Category 4 — Concentration Risk Mitigations

**Solution: Black Swan detector (`shared/utils/black_swan_detector.py`)**
Monitors intraday for two triggers: SMH drops > 7% in a single session, or VIX spikes > 40% intraday. When either trigger fires:
1. Immediate 🚨 Discord Red Alert with all open positions listed
2. Theoretical current P&L for each open position calculated and displayed
3. Recommended immediate action per position (close immediately, hold with reduced stop, or roll to defined-risk structure)
4. All new signal generation suspended
5. System remains in Black Swan mode until regime returns to normal for 3 consecutive trading days

**Solution: Geopolitical risk flag per ticker**
TSM and ASML carry elevated geopolitical risk (Taiwan Strait, EU semiconductor policy). When either fires as a candidate, the Discord alert includes a geopolitical risk warning and applies a fixed confidence penalty (configurable in `swing_config.yaml`, default -5 points). This does not prevent the trade but makes the risk explicit in every recommendation.

---

### Category 5 — Operational Risk Mitigations

**Solution: Daily system health check Discord alert**
Sent at 4:30pm ET after every post-close scan regardless of whether candidates were found:
```
✅ SYSTEM HEALTH — 4:30pm ET
Scan completed:      6/6 tickers processed
Data sources:        yfinance ✅ | Reddit ✅ | Alpha Vantage ✅ | Finnhub ✅
Alpha Vantage calls: 20/25 used today
Candidates found:    0 (threshold: 90/100)
Open positions:      1 (NVDA — Day 4, confidence: 88, trailing stop: $112.00)
Circuit breaker:     Normal 🟢
Day trades (5-day):  0/3
Next scan:           Tomorrow pre-market ~8:30am ET
```
Silence from the system (no health check by 5pm ET) is itself an alert — immediate sign something failed.

**Solution: Missed scan detection**
At the start of each scan, the system checks the audit log for the expected timestamp of the previous scan. If a scan was missed, an immediate ⚠️ Discord alert fires before the current scan begins. Open positions should be reviewed manually until the system confirms it has resumed normal operation.

**Solution: Structured audit log**
`shared/utils/logger.py` maintains `data/logs/audit_log.csv` recording for every scan: timestamp, each ticker's full indicator values, confidence score with complete component breakdown, all modifier values, final score, signal surfaced (yes/no), and if yes: structure recommended, EV, R:R, entry zone, stop, target. For open positions: daily confidence re-score, current P&L, trailing stop level, any management alert triggered. This is the complete forensic record of every system decision.

**Solution: Override log**
`data/logs/override_log.csv` records every instance where you act differently from the system's recommendation — entries include: date, ticker, system recommendation, action taken, reason. If overrides exceed once per week on average, this triggers a review — either the system needs recalibration or behavioral discipline is breaking down.

**Solution: Override policy (formal)**
You may override the system in two situations only:
1. Closing a position earlier than recommended (always acceptable)
2. Skipping a signal the system surfaces (always acceptable — you are never obligated to take every signal)

You may NOT:
1. Enter a trade the system has not signaled
2. Hold a position past a time stop or circuit breaker trigger
3. Reduce a stop loss (moving it further away, increasing risk)

Every override is logged. The system's statistical advantage depends on its rules being followed consistently.

---

### Category 6 — Psychological/Behavioral Risk Mitigations

**Solution: Disagreement protocol**
If you see a setup the system has not signaled: note it, wait for the next scan, see if the system agrees. If the system consistently misses setups you can visually identify, add a new indicator rather than overriding the current system. This preserves statistical integrity while using your trader intuition as a feedback mechanism for improvement.

**Solution: Review triggers**
Automatic review is triggered (Discord alert) when: override log shows > 1 override/week average, circuit breaker Orange or Red fires, 3+ consecutive losses occur, or system health check is missed. Review means manually examining recent trades and system decisions before resuming normal operation — not necessarily changing anything, but confirming the system is behaving as designed.

---

### Category 7 — Regulatory and Brokerage Risk Mitigations

**Solution: PDT rule tracking**
`portfolio_manager.py` tracks same-day opens and closes (day trades) in a rolling 5-trading-day window. When a management alert (signal decay, time stop, structure stop) would result in closing a position opened the same day:
- Alert includes ⚠️ PDT NOTICE with current day trade count
- If already at 2 day trades in the window: alert includes explicit warning to verify PDT status with broker before acting
- System tracks and displays day trade count in every health check alert

**Solution: Account type verification**
A field `options_approval_level` (values: 1, 2, 3) is set once in `swing_config.yaml` based on your actual brokerage account permissions. `trade_selector.py` filters out any structure requiring higher approval than your configured level before ranking. Structures requiring unavailable permissions never appear in recommendations.

**Solution: Tax reserve (Bucket 4)**
30% of every realized profit is earmarked for the tax reserve account immediately upon closing a trade. The realized profit and 30% tax reserve amount are included in every trade close Discord alert. Quarterly estimated tax payments are funded from Bucket 4, never from trading capital or Bucket 1.

---

### New Files Required (Risk Mitigation)

| File | Purpose |
|---|---|
| `shared/utils/data_validator.py` | Pre-flight validation of all incoming data before indicator calculation; logs failures; excludes corrupt tickers from current scan |
| `shared/utils/black_swan_detector.py` | Intraday monitor for SMH > 7% drop or VIX > 40% spike; fires Red Alert with open position guidance; suspends new signals |
| `data/logs/audit_log.csv` | Structured forensic log of every scan decision, score, and management action |
| `data/logs/override_log.csv` | Manual log of every override with reason; reviewed weekly |
| `data/logs/validation_log.csv` | Log of every data validation failure with ticker, timestamp, and failure type |

---

## System Enhancements (10 Improvements)

The following improvements are fully integrated into the file structure, roadmap, and relevant sections above. This section documents each one formally with its rationale, implementation approach, and where it lives in the build sequence.

---

### Enhancement 1 — Paper Trading Protocol (Phase 13)

**Rationale:** Backtesting validates against historical data. Paper trading validates against real-time data with zero financial risk. It catches issues backtesting cannot — real-time data quality problems, execution latency, alert timing, Discord delivery reliability, and your own psychological response to seeing positions move in real time. It also provides 60-90 days of forward-testing performance data to compare directly against backtested expectations before any real capital is deployed.

**Implementation:** `paper_trading/paper_trade_engine.py` runs the full system against live market data but simulates fills instead of executing. `fill_tracker.py` logs the recommended fill price from the Discord alert vs. the actual mid-price at the time you would have executed, building a real-world slippage dataset. `paper_trade_metrics.py` tracks forward-testing win rate, R:R, and EV accuracy vs. theoretical.

**Infrastructure (choose one before Phase 13 starts, document in README Section 5):**

Option A (Windows Task Scheduler — simplest): schedule `paper_trade_engine.py` to run at 8:30am ET, 12:00pm ET, and 4:30pm ET using Windows Task Scheduler (built into Windows, free). Requires your local machine to be on and connected during market hours.

Option B (cloud hosting — more reliable): deploy to AWS EC2 t2.micro (free tier 12 months) or Google Cloud e2-micro (always-free tier) running a Linux cron job at the same three times. Recommended for Phase 15 live trading where reliability is critical. The Python code is identical — only the scheduling mechanism differs.

**Pass criteria for going live:** 80% win rate sustained over minimum 60 trading days (approximately 3 calendar months), 1:3 R:R maintained, actual slippage within 10% of modeled estimates, zero critical system failures (missed scans, data outages not caught by fallback) during the paper trading period. All three criteria must be met simultaneously — same standard as backtesting.

**Duration:** 60-90 trading days minimum. Cannot be shortened even if early results look excellent — a small early sample is not statistically meaningful.

---

### Enhancement 2 — Model Versioning and Change Control (Phase 11)

**Rationale:** Every change to confidence weights, indicator parameters, or thresholds must be tracked formally. Without versioning, a performance improvement after a change can't be distinguished from random variance, and a performance degradation can't be traced back to its cause.

**Implementation:** `CHANGELOG.md` records every model change with: version number (semantic versioning — v1.0.0, v1.1.0, etc.), date, what changed, why it was changed, and who approved it. `model_versioning.py` enforces a mandatory re-backtesting requirement before any version increment — the system will not accept a new version number unless `run_backtest.py` has been run against the new configuration and produced a passing result logged in `metrics.py`. The current model version is stamped into every audit log entry and every Discord alert, so any performance change can be correlated to a specific version.

**Rule:** no changes to scoring weights, indicator parameters, or thresholds go live without a version increment and re-backtesting. No exceptions.

---

### Enhancement 3 — Live Performance Monitoring (Phase 14)

**Rationale:** The system must be monitored continuously after going live, not just validated before going live. A model that performs well in backtesting and paper trading can degrade in live trading due to regime changes, data quality drift, or overfitting exposure. Without continuous monitoring, degradation may not be noticed until significant capital is lost.

**Implementation:** `monitoring/performance_dashboard.py` generates a weekly Discord performance summary every Sunday at 6pm ET covering: rolling win rate (last 10, 20, 50 trades), average achieved R:R vs. 1:3 target, confidence score distribution of surfaced trades (are 90+ scores clustering or spreading?), actual vs. theoretical EV per structure type, and peak-to-trough drawdown. Results are logged to `data/logs/performance_log.csv`. If rolling win rate drops below 70% over the last 20 trades, an automatic review alert fires.

---

### Enhancement 4 — Fill Quality and Slippage Feedback Loop (Phase 14)

**Rationale:** The EV calculations use modeled slippage estimates. Real-world fills may consistently differ — better or worse than modeled. Without tracking actual fills against recommended prices, the EV model stays calibrated to theory rather than your actual execution reality.

**Implementation:** After every trade, you log the actual fill price in `data/logs/fill_log.csv` (Discord alert includes a one-line logging prompt). `fill_tracker.py` compares recommended price vs. actual fill, computes the slippage delta, and runs a quarterly recalibration of the slippage estimates in `options_math.py`. If actual slippage consistently exceeds modeled estimates by more than 15%, a Discord alert fires recommending review of structure liquidity thresholds.

---

### Enhancement 5 — Closed Trade Feedback Loop (Phase 14)

**Rationale:** The system's rolling historical win rate — the empirical component of the confidence score — is initially calibrated from backtesting. In live trading it should continuously update based on your actual closed trade outcomes, making the confidence score more accurate and more tailored to current market conditions over time.

**Implementation:** `swing_model/feedback_loop.py` runs after every trade closes. It logs the outcome to `data/logs/trade_outcomes.csv` (ticker, entry/exit price, structure, confidence score at entry, signal components that fired, holding period, P&L). It then updates the rolling historical win rate for that specific signal combination in the scoring engine — the same combination that produced a winning or losing outcome now has one more data point in its empirical win rate. Over time this makes the scoring engine's win rate estimates reflect your actual live trading history rather than only historical backtesting data.

---

### Enhancement 6 — Seasonality Layer (Phase 3)

**Rationale:** Semiconductor stocks have well-documented seasonal patterns. Q4 tends to be strong driven by consumer electronics demand and year-end institutional positioning. Post-Q1 (January-February) tends to be weaker as consumer demand normalizes. These patterns are consistent enough to serve as a calendar-based confidence modifier — not strong enough to drive trades on their own, but meaningful as a tailwind/headwind modifier on top of other signals.

**Implementation:** `shared/utils/seasonality.py` stores historical semiconductor win rate data by month and quarter (calibrated during backtesting Phase 12). Each month gets a seasonality multiplier (e.g., Q4: +5 confidence boost, January: -5 confidence penalty). Multiplier is applied as a modifier in `scoring.py` after the base score is computed. Configurable thresholds stored in `swing_config.yaml`. Seasonal modifier is shown explicitly in Discord alerts.

---

### Enhancement 7 — Macro Overlay (Phase 3)

**Rationale:** Semiconductor stocks are acutely sensitive to three macro factors that the current technical/sentiment indicators don't capture: Federal Reserve rate direction (rising rates compress tech valuations), US dollar strength (strong dollar hurts TSM and ASML which report in non-USD currencies and hurts US semiconductor exports), and China trade/export policy (directly affects the entire watchlist given exposure to Asian supply chains and markets). When all three are adverse simultaneously, even technically perfect setups have a materially lower probability of achieving the 5-15 day target move.

**Implementation:** `shared/utils/macro_overlay.py` monitors: Fed funds futures implied rate direction (from yfinance or Alpha Vantage), DXY (US Dollar Index) trend, and China-related news keyword frequency (using the existing `news_client.py` filtered for China/Taiwan/export policy terms). Outputs a macro state (favorable/neutral/adverse) updated daily. In adverse macro state: all ticker confidence scores reduced by configurable penalty (default -10 points), maximum surfaced confidence capped at 92 (still above 90 threshold but tighter), and Discord alerts include a macro warning flag. In favorable state: small boost applied (default +3 points).

---

### Enhancement 8 — Notification Redundancy (Phase 10)

**Rationale:** Discord is the primary output channel, but it has no guaranteed uptime SLA and webhook failures are possible. Critical alerts (circuit breakers, Black Swan events, open position stops) require guaranteed delivery — missing one while traveling or during a Discord outage could result in an unmanaged open position past its stop level.

**Implementation:** `shared/utils/notification_router.py` sits above `discord_alerts.py` and routes alerts based on priority:

- All alerts → Discord (primary)
- Critical alerts only → email via SMTP (secondary): circuit breakers (all levels), Black Swan detection, time stops on open positions, structure stops on open positions, missed scan detection
- Highest priority alerts → SMS via Twilio free tier (tertiary): Black Swan detection, Red circuit breaker only

Critical vs. non-critical classification is defined in `global_config.yaml`. SMTP credentials and Twilio credentials stored in `.env`. If Discord delivery fails (HTTP error on webhook POST), `notification_router.py` automatically escalates to email for that alert regardless of priority level.

---

### Enhancement 9 — Entry Confirmation Protocol (Phase 8)

**Rationale:** The portfolio manager's position tracking (open positions, portfolio delta, circuit breaker state, PDT count, max 2 slots) depends on knowing whether you actually entered a trade. Without a confirmation mechanism, the system can't distinguish between "signal surfaced and entered" vs. "signal surfaced and skipped" — leading to slot availability errors, incorrect portfolio delta calculations, and potentially surfacing a third signal when only one slot is actually used.

**Implementation:** Every trade alert Discord message includes a confirmation instruction: reply "entered" to confirm the position is open, or "skipped" to clear the signal. `portfolio_manager.py` listens for these replies via Discord webhook response (or alternatively via a simple slash command). If no reply is received within 2 hours of the alert, the system defaults to "skipped" and logs it as an override. Confirmed entries immediately update open position state, portfolio delta, PDT counter, and slot availability. This closes the loop between the signal system and the position tracking system.

---

### Enhancement 10 — Stress Testing (Phase 12)

**Rationale:** Historical backtesting validates against scenarios that actually occurred. Stress testing validates against hypothetical extreme scenarios that haven't occurred in the backtesting window but are plausible given the semiconductor sector's specific risk profile — a Taiwan Strait incident, a sudden AI bubble burst hitting NVDA specifically, a broad semiconductor supply chain shock, or a major export restriction announcement. Knowing in advance what happens to open positions under these scenarios allows you to define response protocols before they're needed under pressure.

**Implementation:** `backtesting/stress_test.py` runs a suite of pre-defined shock scenarios against any current portfolio state and against the scoring/trade selection system. Scenarios include: SMH -30% in one week, NVDA -40% gap down overnight, VIX spike to 80, Fed emergency rate hike, China export restriction announcement affecting ASML and TSM simultaneously. For each scenario the stress test outputs: theoretical P&L on all open positions, whether circuit breakers would have triggered and at what point, which structures would have suffered most vs. least, and maximum possible loss under the scenario. Results stored in `backtesting/` and summarized in a Discord stress test alert. Stress tests run quarterly and whenever a new model version is deployed.

---

## Implementation Clarifications

This section resolves specific design questions that were identified during scope review. Each clarification translates directly to implementation decisions in the corresponding module.

---

### Clarification 1 — Feedback Loop Calibration Cycle

**Problem:** `feedback_loop.py` updates rolling win rates after each trade closes, but the scope didn't define when these updated weights get reintegrated into the live scoring engine. Immediate integration after every trade could introduce instability.

**Resolution:** The feedback loop operates on a two-speed cycle:

*Immediate (after every closed trade):* log outcome to `trade_outcomes.csv`. Compute updated rolling win rate for that specific signal combination. Store updated win rate in `data/processed/signal_win_rates.json` — does NOT immediately affect live scoring.

*Scheduled recalibration (monthly, or after every 20 closed trades, whichever comes first):* `feedback_loop.py` runs a mini-calibration pass — reads all outcomes from `trade_outcomes.csv`, recomputes win rates per signal combination, runs a quick out-of-sample check against the most recent 5 trades (withheld from calibration), and only if the new weights produce equal or better results on the withheld trades does it update the scoring engine's live weights in `data/processed/live_weights.json`. If the check fails, the old weights remain and a Discord alert fires flagging the calibration attempt and its result.

*Version requirement:* any calibration that changes a weight by more than 5 percentage points requires a version increment in `CHANGELOG.md` and a mini-backtest run before going live — enforced by `model_versioning.py`.

---

### Clarification 2 — Macro Overlay Data Sources (Free Alternatives)

**Problem:** `macro_overlay.py` was specified to monitor Fed funds futures implied rate direction — but this data is not available via yfinance or Alpha Vantage's free tier.

**Resolution:** Three free proxy data sources replace Fed funds futures:

*Fed rate direction:* 10-year US Treasury yield (`^TNX` via yfinance) direction over 20-day and 60-day windows. Rising yield trend = hawkish proxy. A 3% or greater rise over 20 days triggers the adverse macro modifier. More reliable than futures for swing trading purposes since it directly affects semiconductor stock discount rates.

*USD strength:* US Dollar Index (`DX-Y.NYB` via yfinance) 20-day trend. Rising DXY over 20 days = strong dollar = adverse modifier for TSM and ASML specifically (these companies report in non-USD currencies and are most affected).

*China trade policy:* keyword frequency from existing `news_client.py` filtered for terms: "export restriction", "chip ban", "China tariff", "Taiwan Strait", "semiconductor embargo". Rising keyword frequency over 5 days triggers the China tension component of the adverse macro modifier. No additional API needed — reuses the existing news pipeline.

All three sources available free via yfinance and Alpha Vantage. Macro state (favorable/neutral/adverse) computed daily. Stored in `data/processed/macro_state.json` alongside regime and rotation state.

---

### Clarification 3 — Confidence Threshold Sensitivity Analysis Protocol

**Problem:** If the 90/100 confidence threshold produces fewer than 100 qualifying trades during backtesting, the scope said "don't lower the threshold to inflate sample size" but offered no alternative path forward.

**Resolution:** Before running full backtesting, run a sensitivity analysis pass across 5 confidence thresholds: 85, 87, 90, 92, 95. For each threshold, compute: number of qualifying trades in the historical window, win rate, average R:R, signal frequency (trades per month), and maximum consecutive losses. Present all five results in a table. This produces a full tradeoff curve showing the relationship between selectivity (threshold level), statistical confidence (sample size), and performance metrics.

Decision rule from the sensitivity table: choose the lowest threshold that simultaneously achieves ≥ 100 qualifying trades AND ≥ 80% win rate AND ≥ 1:3 R:R. If 90 achieves all three, keep 90. If only 85 achieves ≥ 100 trades but win rate drops to 74% at 85, then the watchlist/window parameters need revision rather than accepting a lower threshold. The sensitivity table makes this decision transparent and principled rather than arbitrary.

Sensitivity analysis run by `backtesting/run_backtest.py` with a `--sensitivity` flag before the full backtesting run. Results logged to `backtesting/reports/sensitivity_analysis.csv`.

---

### Clarification 4 — Paper Trading Infrastructure

**Problem:** Phase 13 paper trading requires the system to run reliably during market hours on a defined schedule, but the scope never addressed where or how it runs.

**Resolution:** Two options depending on your setup preference:

*Option A (local machine, simplest):* Windows Task Scheduler (since you're on Windows per the VS Code screenshots) runs `paper_trading/paper_trade_engine.py` at three scheduled times: 8:30am ET (pre-market), 12:00pm ET (mid-session), 4:30pm ET (post-close). Task Scheduler is free, built into Windows, and reliable for a scheduled Python script. Requires your machine to be on and connected during market hours.

*Option B (cloud, more reliable):* Deploy to a free-tier cloud instance (AWS EC2 t2.micro free tier or Google Cloud e2-micro free tier) running a Linux cron job. More reliable than local since it runs 24/7 regardless of your machine state. Recommended for Phase 15 live trading where reliability is critical.

Paper trading infrastructure decision should be made and documented in `README.md` Section 5 before Phase 13 starts. `paper_trading/paper_trade_engine.py` is identical in both options — only the scheduling mechanism differs.

---

### Clarification 5 — Discord Alert Collapsed Exclusion Summary

**Problem:** With 42 structures evaluated per candidate, listing exclusion reasons for 25-30 excluded structures in every Discord alert produces unreadably long messages.

**Resolution:** Discord alert structure updated to show only eligible (non-excluded) structures in the ranked list, with excluded structures collapsed into a single summary line:

```
— TRADE RANKING (by Expected Value) —
Structures evaluated: 42 | Eligible: 6 | Excluded: 36

ELIGIBLE STRUCTURES (ranked by EV):
#1 ✅ Bull Call Debit Spread       EV: $3.42/$1  R:R: 1:3.4
#2 🔄 Diagonal Call Spread (alt)   EV: $3.18/$1  R:R: 1:3.2
#3 🔄 Bull Put Credit Spread (alt) EV: $3.05/$1  R:R: 1:3.1

EXCLUDED (36 total):
  • Capital filter: 18 structures (require > $750 — eligible at $50k+)
  • R:R filter: 9 structures (EV < 1:3 after slippage)
  • Undefined risk: 4 structures (eligible with Level 3 approval)
  • Direction filter: 3 structures (bearish structures excluded for bullish thesis)
  • Greeks filter: 2 structures (theta too severe for 5-15 day hold)
Reply "details" for full exclusion breakdown
```

If you reply "details" to the alert, a follow-up message sends the complete exclusion list. This keeps the primary alert readable while preserving full transparency on demand. Implemented in `discord_alerts.py` with a two-message architecture (primary alert + optional detail expansion).

---

### Clarification 6 — Live Trading Transition Protocol

**Problem:** After Phase 13 paper trading passes, the transition to Phase 15 live trading had no defined protocol — creating risk of a poorly initialized system or psychological pressure on the first live trade.

**Resolution:** A formal five-step transition protocol before the first live trade:

**Step 1 — Transition checklist (complete before any live funds deposited):** confirm paper trading passed all Phase 13 criteria (80% win rate, 1:3 R:R, slippage within 10% over 60+ trading days); confirm `swing_config.yaml` has correct `options_approval_level` for your live brokerage account; confirm all API keys in `.env` are live (not paper trading API keys); confirm Bucket 2 income buffer is funded (3-6 months living expenses in separate account); confirm Bucket 4 tax reserve account is open and ready.

**Step 2 — Initialize position state for live trading:** reset `data/processed/position_state.json` to empty (no carry-over from paper trading); reset circuit breaker baseline to $15,000 (starting live capital); reset PDT counter to 0; set model version to current CHANGELOG version in `global_config.yaml`.

**Step 3 — Parallel running period (2 weeks):** run paper trading and live trading simultaneously for the first 2 weeks. If they produce different signals for the same ticker on the same day, investigate immediately before proceeding — this indicates a configuration difference between paper and live environments.

**Step 4 — Scale-in period (first month live):** first month of live trading: position sizes at 50% of normal (confidence-scaled fractional still applies but halved). This is the psychological adjustment period — you'll be trading with real money for the first time on this system and the reduced size protects the compounding curve while you verify everything behaves as expected. Full-size positions begin in month 2 if rolling win rate is on track.

**Step 5 — First monthly review:** after first 20 live trades (or 30 trading days, whichever comes first), run `monitoring/performance_dashboard.py` manually and compare live win rate, R:R, and EV to paper trading results. If live results are within 10% of paper results on all metrics, proceed normally. If live results diverge significantly, pause and investigate before continuing.

--- The following are residual risks that remain after mitigations — risks that are reduced but not eliminated.

**Model risks (residual):**
- Confidence scores remain uncalibrated probabilities until Phase 10 backtesting with 100+ qualifying trades across all regimes. Do not size positions based on confidence scores until calibration is complete.
- Walk-forward validation cannot fully predict future regime changes not present in historical data. The model may underperform in genuinely novel market conditions (e.g., a new type of macro shock with no historical precedent).
- Overfitting risk persists despite walk-forward validation — the more parameters tuned during calibration, the higher the residual overfitting risk. Treat the first 6 months of live trading as an extended validation period.

**Data risks (residual):**
- yfinance is unofficial and may break without warning. Fallback to Alpha Vantage uses daily call budget headroom but is not a permanent solution — if yfinance breaks persistently, a paid data source (Polygon.io ~$29/month) becomes necessary.
- NER accuracy on financial text is imperfect. Misattributed sentiment on multi-company articles will occasionally produce incorrect ticker-specific signals despite the NER layer.
- Source credibility scores decay over time. Scores must be recalculated monthly — scores computed once and frozen become unreliable within weeks.
- Insider data from yfinance has 1-2 business day delays. Treat as confirmation only, never as a leading signal.
- Earnings calendar data from yfinance occasionally contains errors. Spot-check upcoming earnings dates against a second source (e.g., Nasdaq.com earnings calendar) weekly.

**Execution risks (residual):**
- Black-Scholes EV calculations assume constant IV and European exercise. Real-world semiconductor options have volatility skew and are American-style. Always cross-check theoretical prices against actual market quotes before executing.
- Actual execution slippage may differ from modeled estimates in fast-moving markets. If fills consistently exceed maximum acceptable prices in Discord alerts, reduce position size until conditions stabilize.
- Complex structures (ratio spreads, back spreads, synthetics, wheel strategy) require higher options approval levels and more active management. Confirm broker approval level in `swing_config.yaml` — the account type filter will exclude structures above your approval level automatically, but verify this is configured correctly before going live.
- The full P&L surface calculation for ratio/back spreads is computationally more intensive than the standard EV formula. If scan time increases significantly, consider computing P&L surfaces only when simpler structures fail to clear the 1:3 threshold — a configurable option in `swing_config.yaml`.

**Concentration risks (residual):**
- All 6 watchlist tickers are semiconductors. A severe sector-specific event can affect all simultaneously despite cross-ticker correlation rules and Black Swan detection. The Black Swan detector reduces response time but cannot prevent the initial impact.

**Operational risks (residual):**
- The system requires a reliable internet connection and running Python environment. No cloud hosting is specified in this scope — if the system runs on a local machine that powers off or disconnects, scans will be missed. Consider cloud hosting for production reliability (Phase 15).
- Notification redundancy (email + SMS) adds delivery resilience but not guaranteed delivery — SMTP servers and Twilio can also experience outages. For highest-stakes alerts (Black Swan, Red circuit breaker), manual monitoring is still recommended as a final backstop.
- Entry confirmation via Discord reply requires Discord to be available and the reply to be processed before the 2-hour default timeout. In poor connectivity conditions, confirmation may be delayed — monitor `data/logs/override_log.csv` to catch misclassified entries.

**Performance monitoring risks (residual):**
- The feedback loop from closed trades improves the scoring engine over time but requires accurate manual fill logging. If fill prices are not logged consistently, the slippage calibration and rolling win rate updates degrade silently. Treat fill logging as a non-negotiable operational discipline.
- Rolling win rate can be misleading over small sample sizes. A 70% win rate over 10 trades is not statistically meaningful — the review trigger (rolling 20-trade win rate below 70%) should be treated as a signal for investigation, not immediate action.

**Regulatory risks (residual):**
- Tax treatment assumptions (30% effective rate) are estimates. Consult a tax professional before the first tax year of active trading.
- Options approval levels and PDT rules vary by broker. Verify your specific broker's requirements before assuming any structure is available.
- No live execution until Phase 15 — system remains a decision-support tool only until paper trading passes all Phase 13 criteria.

---

## Open Decisions for Team Discussion

1. ~~Confirm watchlist~~ ✅ Resolved: NVDA, AMD, AVGO, TSM, MU, ASML with SMH as benchmark
2. ~~Confirm API stack~~ ✅ Resolved: yfinance, Reddit/PRAW, Alpha Vantage, Finnhub (all free)
3. ~~Define holding period~~ ✅ Resolved: 5-15 trading days
4. ~~Define backtesting success metrics~~ ✅ Resolved (see Performance Thresholds below)
5. ~~Define minimum confidence threshold~~ ✅ Resolved: 90/100 minimum confidence required before any trade is surfaced
6. ~~Define minimum R:R threshold~~ ✅ Resolved: 1:3 minimum risk/reward ratio required per candidate
7. ~~Decide on output format/interface~~ ✅ Resolved: Discord alerts via webhook (see Output & Alerts section below)

---

## Output & Alerts (Discord)

All trade recommendations are delivered as formatted Discord alerts via webhook. No dashboard or CSV output required — Discord is the primary interface for reviewing system output.

**Why Discord webhooks:** no bot token or special server permissions needed — a webhook URL is generated in Discord server settings in seconds, stored as an environment variable in `.env`, and called directly from `run_swing_model.py` via a simple HTTP POST. Free, reliable, and already part of your daily workflow.

**Alert structure — one message per surfaced candidate:**

```
🟢 SWING TRADE ALERT — NVDA
━━━━━━━━━━━━━━━━━━━━━━━━━
📊 Confidence Score:     93/100
⏱ Holding Period:       5-15 trading days
📈 Direction:           BULLISH

— SIGNAL BREAKDOWN —
Technical:              +57 (breakout confirmed, trend intact, RS strong)
Sentiment:              +22 (building 4/5 days, cross-platform consistent)
News:                   +14 (bullish, NER-confirmed, recent)
Base Score:             75
Regime modifier:        +5 (trending market)
Cross-ticker:           NVDA diverging from peers (+3)
Earnings:               18 days away — no penalty
Final Score:            93/100 ✅ (threshold: 90)

— ENTRY PARAMETERS —
Entry zone:             $118.50 - $120.00
Stop loss:              $112.00 (2x ATR, high-vol node support)
Target:                 $138.00 (next low-volume area above entry)

— POSITION SIZING —
Account equity:         $15,000
Confidence tier:        93-95 → 1.5% risk
Dollar risk:            $225
Circuit breaker state:  Normal ✅ (full size)
Open positions:         0/2 slots used

— TRADE RANKING (by Expected Value) —
Structures evaluated: 42 | Eligible after filters: 8

#1 ✅ Bull Call Debit Spread
   Strikes:    Buy $120C / Sell $130C — 35 DTE
   EV:         $3.42 per $1 risked
   Max loss:   $320 | Max gain: $1,095
   R:R:        1:3.4 ✅
   Greeks:     Δ0.52 Θ-0.08 V0.12
   Capital:    $320 (2.1% of account) ✅
   Why #1:     Best EV in current high-IV environment; vega controlled

#2 🔄 Diagonal Call Spread (alt)
   Strikes:    Buy $120C 90 DTE / Sell $125C 35 DTE
   EV:         $3.18 per $1 risked | R:R: 1:3.2 ✅
   Note:       Benefits from short leg decay; good if IV expected to rise

#3 ❌ Long Stock — excluded
   Capital:    $11,900 — exceeds 5% max at current account size

#4 ❌ Naked Short Call — excluded
   Reason:     Undefined risk; eligible when account > $50k, Level 3 approval

#5 ❌ Long Call — excluded
   R:R:        1:2.9 (below 1:3 threshold after slippage)

— TRADE MANAGEMENT RULES —
Profit target:          Close at 60% max gain (~$657)
Time stop:              Close by Day 10 if < 30% of target reached
Structure stop:         Close if spread loses 50% of value ($160)
Trailing stop:          Updates daily — current: $112.00

— DOMINANT NARRATIVE —
Theme:                  AI demand cycle
Alignment:              ✅ Trade thesis aligned with prevailing narrative

— IV CONTEXT —
IV Percentile:          68th (elevated — debit spread preferred over naked call)
Earnings:               18 days — sufficient room; no structure override

— EXECUTION GUIDANCE —
Order type:     Limit order at mid-price ($4.85 debit)
Max fill price: $5.10 debit (above this R:R < 1:3 — cancel order)
Entry window:   Valid until market close today — do not enter tomorrow
Legging:        Use spread order — do not leg individually
If unfilled:    Discard — system re-evaluates at next scan
PDT status:     Day trades this week: 0/3 ✅

— CONFIRMATION REQUIRED —
Reply to this alert:
  ✅ "entered" — position confirmed open (system updates tracking)
  ❌ "skipped" — signal not taken (slot freed, logged in override log)
  (No reply = system assumes skipped after 2 hours)

— REGULATORY —
Account type:   Requires options Level 2 approval (debit spreads)
Tax note:       Short-term gain — reserve 30% of profit in Bucket 4
Geopolitical:   No active flags on this ticker

⚠️ Decision-support signal only. Not financial advice.
   Validate before trading. Backtesting ongoing — Phase 10.
━━━━━━━━━━━━━━━━━━━━━━━━━
```

**Alert types:**

| Alert Type | Trigger | Color/Emoji |
|---|---|---|
| New bullish candidate | Confidence ≥ 90, R:R ≥ 1:3, direction bullish | 🟢 Green |
| New bearish candidate | Confidence ≥ 90, R:R ≥ 1:3, direction bearish | 🔴 Red |
| Signal decay — early exit | Open position confidence drops significantly post-entry | 🟡 Yellow |
| Profit target hit | Open position reaches 60% of max gain | 💰 Gold |
| Time stop triggered | Day 10 reached, < 30% of target profit | ⏰ Orange |
| Structure stop hit | Options position hits structure-specific stop level | 🛑 Red |
| Trailing stop updated | Daily stop recalculation for open position | 📍 Grey |
| Earnings warning | Open position earnings within 5 days | ⚠️ Orange |
| Circuit breaker — Yellow | Account drops 5% from peak | 🟡 Yellow |
| Circuit breaker — Orange | Account drops 10% from peak; trading paused | 🟠 Orange |
| Circuit breaker — Red | Account drops 15% from peak; full stop | 🔴 Red |
| Consecutive loss warning | 2+ consecutive losses detected | ⚠️ Yellow |
| Regime change | Market regime shifts (e.g., trending → choppy) | 🔵 Blue |
| Sector rotation shift | SMH vs SPY rotation state changes | 🔵 Blue |
| Black Swan detected | SMH drops 7%+ or VIX spikes 40%+ intraday | 🚨 Red |
| Seasonal modifier applied | Confidence adjusted for seasonal pattern | 📅 Blue |
| Macro overlay warning | Adverse macro conditions detected (rates/USD/China) | 🌐 Orange |
| Data source unavailable | Any primary data source fails after retries | ⚠️ Orange |
| Sentiment-only mode | Sentiment layer offline — technical-only scoring active | ℹ️ Blue |
| Missed scan detected | Expected scan did not complete on schedule | ⚠️ Orange |
| Data validation failure | Corrupted or suspicious data detected for a ticker | ⚠️ Orange |
| PDT warning | Approaching 3 day trades in rolling 5-day window | ⚠️ Yellow |
| Entry confirmed | User confirmed position entered — portfolio updated | ✅ Green |
| Entry skipped | User skipped signal — slot freed, override logged | ℹ️ Grey |
| Weekly performance summary | Rolling win rate, R:R, EV accuracy, drawdown | 📊 Blue |
| Model version change | New model version deployed after re-backtesting | 🔄 Blue |
| Stress test alert | Hypothetical extreme scenario impact on portfolio | 🧪 Orange |
| Slippage model update | Fill log data has updated slippage estimates | 📋 Grey |
| System health check | Daily confirmation scan completed successfully | ✅ Green |
| No candidates today | Daily scan complete, zero setups met thresholds | ⬜ Grey (optional) |

**Cadence:** alerts fire after each indicator layer run (up to 3x daily — pre-market, mid-session, post-close). Post-close scan is the primary alert window for next-day swing setups. Pre-market scan catches overnight developments. Mid-session scan flags signal decay on open positions.

**Implementation:** `swing_model/run_swing_model.py` calls a `discord_alerts.py` module in `shared/utils/` after scoring is complete. The module formats the message and POSTs to the webhook URL stored in `.env` as `DISCORD_WEBHOOK_URL`. Each alert is sent as a Discord embed for clean formatting.

**New file to add to structure:** `shared/utils/discord_alerts.py` — formats and sends Discord webhook alerts; takes a scored candidate object and alert type as inputs; reads `DISCORD_WEBHOOK_URL` from environment variables.

---

## Performance Thresholds (Non-Negotiable Before Live Use)

These are the minimum validated benchmarks the system must achieve during Phase 10 backtesting before any live or paper trading begins. All three must be met simultaneously — meeting two of three is not sufficient.

| Metric | Required Threshold | What It Means |
|---|---|---|
| Win rate | 80% | At least 80% of surfaced trade candidates must produce a profitable outcome within the 5-15 day holding window, measured across the full backtesting period |
| Minimum confidence score | 90/100 | No trade recommendation is surfaced unless the final confidence score (after all modifiers) is 90 or above — this is a hard filter, not a soft guideline |
| Minimum risk/reward ratio | 1:3 | For every $1 of risk (stop-loss distance), the trade must offer at least $3 of potential reward (target distance) based on ATR-based + volume-profile stop/target calculation — candidates below this threshold are not surfaced regardless of confidence score |

**Backtesting methodology requirements (all mandatory):**

Minimum qualifying trades: backtesting must produce a minimum of 100 qualifying trades (confidence 90+, R:R 1:3+) before win rate is considered statistically meaningful. At approximately 4 signals per month, this requires roughly 25 months of historical data minimum. If the full historical window produces fewer than 100 qualifying trades, the confidence threshold or signal frequency must be re-evaluated before conclusions are drawn.

Out-of-sample split: 70% of historical data is used for calibrating confidence weights and win rates. The remaining 30% is held out completely — never seen during calibration — and used only for final validation. The held-out period must include at least one bear market or high-volatility period (VIX > 30) and at least one semiconductor-specific stress period. If the naturally held-out 30% does not contain these regimes, extend the total historical window until it does.

Walk-forward validation: after initial backtesting, the model is re-validated using walk-forward testing. Calibrate on months 1-18, validate on months 19-24. Then roll forward: calibrate on months 1-24, validate on months 25-30. Repeat for each available window. The model must meet performance thresholds across every walk-forward validation window, not just the initial one. A model that meets thresholds in one period but fails in another has a regime dependency that must be investigated before live use.

Regime coverage requirement: the backtesting period must include results across all four regime types (trending up, trending down, choppy/range-bound, high-volatility). Win rate and R:R must be reported separately per regime. If the model fails to meet thresholds in any single regime, that regime requires specific remediation (adjusted confidence weights, additional disqualifying conditions) before live use.

**Important context on these thresholds:**

An 80% win rate at 1:3 R:R is an exceptionally high bar. Many professional systematic strategies operate profitably at 40-50% win rates — because even losing trades stay small relative to winners. Setting both win rate and R:R high simultaneously means the system will surface very few trade candidates, which is intentional — precision over frequency.

The 90/100 confidence threshold enforces this selectivity. Most days, the model may surface zero candidates. That is expected and correct behavior — not a sign the system is broken.

**What happens during backtesting if thresholds aren't met:**
- Win rate below 80%: review which signal categories are contributing false positives; recalibrate confidence weights; tighten modifier penalties
- Fewer than 100 qualifying trades in historical window: extend historical data window; do not lower confidence threshold to artificially inflate sample size
- Model fails in specific regime: add regime-specific disqualifying conditions; do not average across regimes to hide regime-specific failure
- R:R below 1:3 consistently: review volume profile target placement and ATR-based stop distance; tighten stop logic or widen target criteria
- Thresholds unmet after reasonable recalibration: re-evaluate semiconductor watchlist and 5-15 day window before assuming model logic is fundamentally flawed

---

## Performance & Capital Management Framework

This section defines how capital is protected, sized, managed during open trades, and structured for long-term income generation. It covers four distinct systems that work together: position sizing, trade management, portfolio construction, and capital architecture.

**Starting capital: $15,000**

---

### System 1 — Position Sizing (Confidence-Scaled Fixed Fractional)

Risk per trade is a percentage of current account equity — not a fixed dollar amount — so position size scales automatically as the account grows without manual adjustment.

| Confidence Score | Risk % of Account | Dollar Risk at $15k | Win (1:3) | Loss |
|---|---|---|---|---|
| 90-92 | 1.0% | $150 | $450 | $150 |
| 93-95 | 1.5% | $225 | $675 | $225 |
| 96-98 | 2.0% | $300 | $900 | $300 |
| 99-100 | 2.5% | $375 | $1,125 | $375 |

**Maximum capital per single trade:** 5% of current account equity ($750 at $15k). Any structure requiring more capital than this is excluded by the capital efficiency filter in `trade_selector.py` regardless of EV.

**Structure viability at $15k by ticker:**
| Ticker | Viable Structures |
|---|---|
| NVDA | Narrow debit spreads ($500-700), deep ITM call if under $750 |
| AMD | Debit spreads, 1-2 contracts long call, small stock position |
| MU | Long calls, stock, debit spreads — most flexible at this account size |
| AVGO | Narrow debit spreads only |
| TSM | Debit spreads, small stock position |
| ASML | Narrow debit spreads only (very high stock price) |

**Kelly Criterion note:** Full Kelly for 80% win rate at 1:3 R:R theoretically suggests ~70% per trade — this is dangerously aggressive and ignored entirely. Fixed fractional at 1-2.5% is used instead. Kelly sizing is only reconsidered after 200+ live validated trades confirm that backtested win rate and R:R are holding in real market conditions.

---

### System 2 — Trade Management (During the Hold)

Positions are actively managed throughout the 5-15 day holding window. The system re-evaluates every open position daily and fires Discord alerts when any threshold is hit.

**Profit target rules (structure-specific):**
| Structure Category | Profit Target Action |
|---|---|
| Vertical debit spreads (bull call, bear put) | Close at 60% of max theoretical gain |
| Calendar / diagonal spreads | Close at 50% of max theoretical gain — time component makes holding longer riskier |
| Long call / long put / LEAPS | Close at 60% of max gain OR when delta drops below 0.30 (momentum fading) |
| Vertical credit spreads (bull put, bear call) | Close at 50% of premium collected |
| Cash-secured put | Close at 75% of premium collected if stock well above strike |
| Covered call | Let expire worthless (full premium kept) OR close at 80% of premium collected |
| Iron condor / iron butterfly / condor | Close at 50% of max premium collected |
| Long butterfly / condor spread | Close at 60% of max theoretical gain near center strike |
| Long straddle / long strangle | Close one side (the profitable leg) at 100% gain; hold other side as free trade |
| Ratio spreads / back spreads | Exit when positive EV zone on P&L surface is reached — no fixed percentage |
| Protective put / collar / married put | Manage the stock position; let hedge expire or roll it |
| Wheel strategy | Full cycle: let put expire or assign; then sell covered call; repeat |
| Long stock with trailing stop | Trailing stop triggers exit; no fixed profit target — let winners run |
| Risk reversal / synthetic structures | Close at equivalent stock target price per volume profile analysis |

**Time stop (universal — all structures):**
If position has not reached 30% of target profit by day 10 of the holding window, close regardless of confidence score. Thesis has not played out on schedule; time decay accelerating on options structures; capital better redeployed.

**Structure-specific stop loss:**
| Structure Category | Stop Trigger |
|---|---|
| Debit spreads (vertical, calendar, diagonal) | Close if spread loses 50% of value |
| Long call / long put / LEAPS | Close if option loses 40% of purchase value |
| Credit spreads | Close if position costs 2x the premium collected to close |
| Long stock / stock with trailing stop | ATR-based trailing stop, recalculated daily |
| Cash-secured put | Close/roll if stock approaches within 1 ATR of strike |
| Covered call | Close short call if stock approaches strike with 5+ days remaining |
| Iron condor / iron butterfly / condor | Close if either spread leg doubles in cost against you |
| Long butterfly / short butterfly | Close at 50% of max theoretical gain; time stop at Day 10 |
| Long straddle / long strangle | Close if position loses 40% of premium paid — move hasn't materialized |
| Ratio spreads / back spreads (COMPLEX) | P&L surface tracked daily; close if enters negative EV zone on surface |
| Risk reversal / synthetic structures | Treat short leg as primary stop trigger; close entire position |
| Wheel strategy | Manage each leg independently per cash-secured put and covered call rules above |
| Protective put / collar / married put | Stop on underlying stock position; put acts as insurance, not primary stop |

**Dynamic stop adjustment (daily):**
Price-based stops are not static after entry. Each day after entry, stops are recalculated as the position moves in favor:
- Bullish trade: stop trails up at 1.5x ATR below the highest close since entry
- Bearish trade: stop trails down at 1.5x ATR above the lowest close since entry
- Stop never moves against the position (trailing only, never backward)
- Updated stop levels sent as Discord alert daily for open positions

**P&L surface tracking:**
For each open position, the system calculates theoretical position value at Day 1, 5, 10, and 15 under three scenarios (target hit, flat/no move, stop hit). This produces a forward-looking P&L range that is included in the open position management Discord alert, showing the realistic outcome distribution across the remaining holding period.

---

### System 3 — Portfolio Construction

Manages risk across multiple simultaneous open positions. At $15k, maximum 2 simultaneous positions are viable given capital constraints and correlation risk.

**Simultaneous position limits:**
| Rule | Limit | Rationale |
|---|---|---|
| Maximum open positions | 2 | Capital constraint + correlation risk at $15k |
| Maximum simultaneous risk | 3% of account ($450) | Both positions losing simultaneously stays within yellow flag |
| Correlated pair rule | Max 1 position from NVDA/AMD simultaneously | Treat as one slot — high correlation means two positions = one sector bet |
| New signal rule | Skip if total open risk would exceed $450 | Hard cap regardless of confidence score |

**Portfolio delta management:**
Net directional exposure across all open positions must not exceed the equivalent of 1.5% of account per 1% broad market move. `swing_model/portfolio_manager.py` calculates portfolio delta daily and flags any breach.

**Correlation override:**
If cross-ticker analysis detects a sector-wide move (not individual divergence) and two signals fire simultaneously, only the higher-confidence ticker is surfaced. The second is queued and re-evaluated after the first position is closed.

---

### System 4 — Drawdown Circuit Breakers

Three escalating levels of protection that trigger automatically based on account drawdown from peak equity. All circuit breaker state changes trigger an immediate Discord alert.

**Drawdown circuit breakers:**
| Level | Trigger | Dollar Amount at $15k | Action |
|---|---|---|---|
| 🟡 Yellow | 5% drawdown from peak | $750 | Position size reduced to 50% of normal; only 95+ confidence signals surfaced |
| 🟠 Orange | 10% drawdown from peak | $1,500 | No new positions; manage all existing positions to close; 5 trading day pause minimum |
| 🔴 Red | 15% drawdown from peak | $2,250 | Full stop; no trading until manual review and explicit reset; Discord alert with full review checklist |

**Consecutive loss circuit breaker:**
| Streak | Probability at 80% Win Rate | Action |
|---|---|---|
| 2 consecutive losses | ~4% | Reduce position size 50% until next winner |
| 3 consecutive losses | ~0.8% | Pause new entries 3 trading days; review recent trades for regime shift |
| 4 consecutive losses | ~0.16% | Full pause; system review required — this is statistically rare and likely signals model underperformance or regime change |

**Maximum dollar loss at 4-loss streak (at 1.5% risk):** $225 × 4 = $900 = 6% drawdown. Survivable, within orange flag threshold, and statistically very rare at 80% win rate.

---

### System 5 — Capital Architecture (Three Buckets)

Separates trading capital from living expenses to ensure the trading account is never under income pressure during the compounding phase.

**Bucket 1 — Trading Account ($15,000 starting)**
All profits reinvested. No withdrawals until account reaches $50,000. This is the compounding phase — treat as untouchable growth capital. Duration approximately 10-11 months at target performance.

**Bucket 2 — Income Buffer (separate account, funded from other income)**
3-6 months of living expenses held in cash outside the trading account. This is what funds living expenses during the compounding phase. The trading account never faces income pressure — this is the most important structural protection against psychological decision-making errors.

**Bucket 3 — Income Draw (activated at $50,000 account milestone)**
Once trading account reaches $50,000, withdraw 20% of monthly profits into a separate income account monthly. Leave 80% compounding. At $50k with 1.5% average risk at target performance, average monthly profit is approximately $5,250. 20% withdrawal = ~$1,050/month income while account continues compounding toward $100k+.

**Bucket 4 — Tax Reserve (active from first trade)**
All realized profits are subject to short-term capital gains tax (held under 1 year = taxed as ordinary income). Assuming a 30% effective tax rate (federal + state combined estimate), 30% of every realized profit is transferred immediately to a separate tax reserve account. This account is never touched except for quarterly estimated tax payments. This prevents a strong trading year from creating a tax bill that must be paid from trading capital, which would create an unplanned drawdown.

After-tax compounding curve adjustment (30% effective tax rate applied):
| Timeframe | Gross Account | After-Tax Account | After-Tax Monthly Income (at 20% draw) |
|---|---|---|---|
| Start | $15,000 | $15,000 | — |
| Month 6 | ~$27,000 | ~$23,400 | — |
| Month 11 | ~$50,000 | ~$42,500 | ~$735/month draw |
| Month 18 | ~$115,000 | ~$93,500 | ~$1,690/month draw |
| Month 24 | ~$240,000 | ~$192,000 | ~$3,530/month draw |
| Month 30 | ~$500,000 | ~$395,000 | ~$7,350/month draw |

After-tax projections are approximately 70% of gross projections. Plan income expectations accordingly.

**Compounding curve at $15k (target performance, all profits reinvested):**
| Timeframe | Account Value | Avg Monthly Profit | Income (20% draw if applicable) |
|---|---|---|---|
| Start | $15,000 | ~$1,575 | — (compounding phase) |
| Month 3 | ~$19,500 | ~$2,050 | — |
| Month 6 | ~$27,000 | ~$2,835 | — |
| Month 9 | ~$38,000 | ~$3,990 | — |
| Month 11 | ~$50,000 | ~$5,250 | $1,050/month draw begins |
| Month 15 | ~$95,000 | ~$9,975 | ~$2,000/month draw |
| Month 18 | ~$115,000 | ~$12,075 | ~$2,415/month draw |
| Month 24 | ~$240,000 | ~$25,200 | ~$5,040/month draw |
| Month 30 | ~$500,000+ | ~$52,500 | ~$10,500/month draw |

**Critical caveat:** every number above assumes system achieves and maintains 80% win rate and 1:3 R:R in live trading. These are targets, not guarantees. The compounding curve is powerful but fragile — a sustained period of underperformance (60% win rate or 1:2 R:R) dramatically changes these projections. Circuit breakers exist specifically to detect underperformance early and pause trading before it derails the compounding curve.

**The $15,000 must not go live until Phase 10 backtesting confirms all three performance thresholds simultaneously across multiple market regimes including at least one high-volatility or bear market period.**

---

### New Files Required (Capital Management)

Two new files added to the codebase to implement this framework:

`swing_model/portfolio_manager.py` — tracks all open positions, calculates portfolio delta, enforces simultaneous position limits, checks correlation override rules, manages circuit breaker state (yellow/orange/red), sends circuit breaker Discord alerts when triggered.

`shared/utils/position_sizer.py` — calculates position size per trade based on current account equity (read from config or tracked state), confidence score tier, structure capital requirement, and current circuit breaker state (reduces size when yellow flag active). Called by `trade_selector.py` before finalizing any recommendation.
