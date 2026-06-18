# AI-Assisted Trading Signal System — Project Scope

## Overview

This project builds two parallel decision-support systems — a **swing trading model** and a **day trading model** — each combining an indicator-gathering layer (price/volume, sentiment, news, fundamentals as relevant to that timeframe) with an analysis/scoring layer that recommends a trade structure (long/short equity, calls, puts, spreads) based on risk/reward.

The two models are separated because the relevant indicators, data cadence, and infrastructure needs differ significantly between day trading and swing trading.

**Important framing:** this is a decision-support tool, not an autonomous trading system. No component should be trusted to execute trades without backtesting and human review.

---

## Niche Focus & Starter Watchlists

Both models are niche-focused rather than broad-market, so indicator thresholds stay meaningful and backtesting results are coherent (a threshold tuned for semiconductors won't behave the same for utilities).

### Swing Model — Semiconductor Sector

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

### Day Model — High-Liquidity / Mega-Cap Basket

**Rationale:** Day trading indicators (VWAP, opening range, relative volume) require high liquidity, tight spreads, and reliable intraday volatility — sector theme matters less than volume/liquidity profile here.

**Starter watchlist:**
| Ticker | Notes |
|---|---|
| AAPL | Mega-cap, highly liquid |
| NVDA | High liquidity, large intraday range, rich options flow data |
| TSLA | High-beta, large intraday ranges |
| MSFT | Mega-cap, highly liquid |
| SPY | Index ETF — most liquid instrument, good for testing model logic without single-stock idiosyncrasies |
| QQQ | Tech-heavy index ETF |

**Note on overlap:** NVDA appears in both watchlists. This is fine — the two models operate on different timeframes and indicator sets, so there's no signal conflict between them.

---

## System Architecture

Each model (swing and day) follows the same two-layer pattern, with timeframe-appropriate data and logic:

1. **Indicator Layer** — pulls and computes all relevant metrics (technical, sentiment, news, fundamentals) for that model's timeframe
2. **Analysis/Decision Layer** — consumes indicator data, scores opportunities, and recommends a trade structure optimized for risk/reward

Decision logic starts rules-based (explicit, tunable conditions) for transparency and backtestability; ML components (e.g., sentiment classification) can be layered in for specific sub-problems later.

---

## File Structure (StockAnalysis project — current, as built)

```
StockAnalysis/
├── README.md                          # Project overview, setup instructions, how to run each model
├── Project_Scope.md                   # This document
├── .env.example                       # Template showing which API keys are needed (no real keys)
├── .gitignore                         # Excludes .env, data/raw, data/historical from version control
├── requirements.txt                   # Python dependencies for the whole project
│
├── config/
│   ├── global_config.yaml             # Shared settings: API base URLs, rate limits, output formats
│   ├── swing_config.yaml              # SWING-ONLY: semiconductor watchlist, SMH/SOXX benchmark, swing thresholds
│   └── day_config.yaml                # DAY-ONLY: mega-cap/liquid basket watchlist, day thresholds
│
├── shared/
│   ├── api_clients/
│   │   ├── market_data_client.py      # SHARED: wraps yfinance — both models pull price data through this (BUILT)
│   │   └── sentiment_client.py        # SHARED: wraps StockTwits/StockGeist — for sentiment layer (not yet built)
│   │
│   ├── indicators/
│   │   └── technical_common.py        # SHARED: MA, breakout, RS, RSI, ATR, MACD — math used by both models (BUILT)
│   │
│   └── utils/
│       ├── logger.py                  # SHARED: logging setup
│       └── risk_reward.py             # SHARED: R:R ratio calculation, stop/target math (not yet built)
│
├── swing_model/
│   ├── indicator_pipeline.py          # SWING-ONLY: orchestrates technical data pull for semiconductor watchlist (in progress)
│   ├── sentiment_layer.py             # SWING-ONLY: multi-day sentiment trend scoring (not yet built)
│   ├── scoring.py                     # SWING-ONLY: confidence scoring — combines technical + sentiment + news (next step)
│   ├── trade_selector.py              # SWING-ONLY: picks trade structure based on confidence + IV regime (not yet built)
│   └── run_swing_model.py             # SWING-ONLY: entry point — generates daily swing recommendations (not yet built)
│
├── day_model/
│   ├── indicator_pipeline.py          # DAY-ONLY: orchestrates intraday data pull (not yet built)
│   ├── intraday_indicators.py         # DAY-ONLY: VWAP, opening range, relative volume (not yet built)
│   ├── options_flow.py                # DAY-ONLY: unusual options activity, IV, put/call ratio (not yet built)
│   ├── scoring.py                     # DAY-ONLY: confidence scoring, intraday-weighted (not yet built)
│   ├── trade_selector.py              # DAY-ONLY: picks trade structure based on confidence (not yet built)
│   └── run_day_model.py               # DAY-ONLY: entry point for intraday recommendations (not yet built)
│
├── backtesting/
│   ├── backtest_engine.py             # SHARED ENGINE: runs either model's scoring logic against historical data
│   ├── metrics.py                     # SHARED: win rate, R:R, drawdown, Sharpe — also where confidence calibration gets measured
│   ├── run_backtest_swing.py          # SWING-ONLY entry point
│   └── run_backtest_day.py            # DAY-ONLY entry point
│
├── data/
│   ├── raw/                           # Cached raw API responses (gitignored)
│   ├── processed/                     # Cleaned indicator data (gitignored)
│   └── historical/                    # Historical data for backtesting (gitignored)
│
├── output/
│   ├── swing_recommendations/         # SWING-ONLY: daily ranked CSV/JSON output
│   └── day_recommendations/           # DAY-ONLY: intraday ranked CSV/JSON output
│
└── tests/
    ├── test_shared_indicators.py
    ├── test_swing_scoring.py
    └── test_day_scoring.py
```

**Organizing principle:** `shared/` holds timeframe-agnostic logic used by both models. `swing_model/` and `day_model/` never import from each other — only from `shared/`. Each model's `config/*.yaml` is the single source of truth for that model's watchlist and thresholds.

**Build status note:** `market_data_client.py` and `technical_common.py` (with MA, breakout, RS, RSI, ATR, MACD) are complete and tested. `swing_model/indicator_pipeline.py` is in progress. Everything else is scoped but not yet implemented.

---

## Swing Trading Model

**Timeframe:** Holding periods of days to weeks.

**Cadence:** Indicator layer runs once (or a few times) daily, typically after market close.

### Indicator Layer (Swing)

| Category | Indicators | Source |
|---|---|---|
| Technical | 20/50-day MAs, 20/50-day breakout levels, 20-day avg volume, relative strength vs. SMH/SOXX (sector benchmark) | yfinance / Alpha Vantage / Polygon |
| Social/Sentiment | Mention volume, bullish/bearish ratio, multi-day rate of change | StockTwits API / StockGeist.ai |
| News/Fundamental (Phase 2) | Earnings trends, analyst sentiment shifts, sector news | Alpha Vantage News & Sentiment |

### Confidence Scoring (Swing — replaces simple point scoring)

Rather than a flat point system, each ticker gets a **confidence score (0-100)** in each direction (bullish/bearish), built from weighted signal categories. The weighting reflects how reliable each category is — price/volume data is observable and hard to fake, sentiment is noisier and gameable, news is fastest-moving but least validated.

| Signal Category | Weight | Why this weight |
|---|---|---|
| Technical (breakout, trend, RS, RSI/ATR/MACD) | 50-60% | Most reliable — directly observable price/volume behavior |
| Social/Sentiment | 20-25% | Useful but gameable (bots, coordinated hype) — must be cross-checked against price |
| News | 15-20% | Fastest signal but often already priced in, and least validated in isolation |

**Example confidence breakdown for a single ticker:**
| Component | Contribution |
|---|---|
| Breakout confirmed (price + volume) | +25 |
| Trend intact (price > 50-day MA, 20 > 50 MA) | +15 |
| Relative strength positive vs. SMH | +15 |
| RSI in healthy range (not overbought) | +5 |
| Sentiment building over 3-5 days (not single-day spike) | +10 |
| Relevant bullish news, not yet fully reflected in price | +5 |
| **Total bullish confidence** | **75/100** |

Output per ticker: a confidence score in each direction, plus a breakdown of which components contributed — so the reasoning is always visible and adjustable, never a black box.

**Critical caveat:** a confidence score reflects how much evidence aligns, not a calibrated probability of the trade working out. Early on, "75/100" means "most signals point bullish," not "75% chance of profit." Calibration — whether a 75 score actually corresponds to a ~75% historical win rate — can only be established through backtesting against real outcomes over time (see Phase 4).

### Trade Structure Selection (Swing)

Confidence score and current volatility regime (e.g., IV percentile on the underlying) together determine both the trade structure AND the position sizing — higher confidence can justify more aggressive structures or larger size; lower confidence should mean smaller size or a more conservative, defined-risk structure (or no trade at all).

| Scenario | Likely Structure |
|---|---|
| High bullish confidence (70+), low/normal IV | Long stock, or long calls (1-3 month expiry) |
| High bullish confidence, high IV (e.g., pre-earnings) | Bull call debit spread (reduces cost/vega exposure) |
| Moderate bullish confidence (50-70), range-bound expectation | Sell put credit spread below support |
| High bearish confidence, low/normal IV | Short stock, or long puts |
| High bearish confidence, high IV | Bear put debit spread |
| Low confidence or conflicting signals (e.g., sentiment up, price not confirming) | No trade / watchlist only |

Risk/reward calculation per candidate: define stop-loss level (e.g., below recent support) and target (e.g., next resistance or measured move), compute R:R ratio, and only surface candidates above a minimum threshold (e.g., 1:2).

---

## Day Trading Model

**Timeframe:** Intraday — positions typically closed same day.

**Cadence:** Indicator layer runs frequently — real-time to minute-level during market hours.

### Indicator Layer (Day)

| Category | Indicators | Source |
|---|---|---|
| Intraday Technical | VWAP, opening range high/low, relative volume (vs. same time yesterday), short-term momentum (1-5 min) | Polygon.io / Alpaca / IEX (real-time feeds) |
| Options Flow | Implied volatility, unusual options activity, put/call ratio, gamma exposure | Tradytics, CBOE data, or broker-provided flow data |
| News/Catalyst | Real-time news alerts, halt flags, earnings surprises released intraday | Alpha Vantage News, Benzinga Pro, or similar real-time feed |
| Social (secondary) | Sudden mention spikes (not multi-day trend) | StockTwits real-time stream |

### Confidence Scoring (Day — same framework, faster cadence, different weights)

Same 0-100 confidence approach as the swing model, but weighted differently — intraday technical/options-flow signals dominate, since sentiment and news need time to "build" that a same-day trade doesn't have.

| Signal Category | Weight | Why this weight |
|---|---|---|
| Intraday Technical (VWAP, opening range, relative volume) | 60-70% | Most directly relevant to same-day price action |
| Options Flow (unusual activity, IV expansion) | 20-25% | Strong confirmation signal when aligned with price |
| News/Catalyst | 10-15% | Only matters if it's a same-day catalyst; stale news is ignored |
| Social (sudden spikes) | 5-10% | Lowest weight — single-day spikes are the least reliable signal type, prone to manipulation |

**Critical caveat (same as swing model):** confidence reflects evidence alignment, not a calibrated probability — especially important for the day model given its higher overfitting risk (see Key Risks).

### Trade Structure Selection (Day)

| Scenario | Likely Structure |
|---|---|
| High bullish confidence, fast clean move expected | Long stock (most responsive, no theta decay risk) |
| High bullish confidence, want leverage on a sharp move | Short-dated (0-2 day) long calls — only if move is expected to be large enough to overcome theta |
| High bearish confidence | Short stock or short-dated long puts |
| High confidence but high IV (earnings-day type move) | Debit spread to reduce cost basis |
| Low confidence / choppy conditions | No trade |

Given theta decay risk, the day model should weight straight equity positions more heavily than the swing model, reserving options for cases with strong directional conviction and a clear, fast catalyst.

---

## Implementation Roadmap

| Phase | Scope | Key Deliverables |
|---|---|---|
| **Phase 1** | Swing model — technical indicator layer | Python module pulling daily OHLCV (yfinance), computing MA/breakout/RS indicators, scoring watchlist, output to CSV |
| **Phase 2** | Swing model — social layer + scoring integration | Integrate StockTwits API, compute sentiment trend, merge with technical score into composite swing score |
| **Phase 3** | Swing model — trade selector | Implement trade structure logic table above; compute stop/target/R:R per candidate |
| **Phase 4** | Backtesting (swing) | Validate swing scoring rules and trade selector against historical data across multiple market regimes |
| **Phase 5** | Day model — intraday indicator layer | Real-time data feed integration (Polygon/Alpaca), VWAP/opening range/relative volume calculations |
| **Phase 6** | Day model — options flow + scoring | Integrate options flow data, implement day scoring rules and trade selector |
| **Phase 7** | Backtesting (day) | Validate day model against historical intraday data; evaluate overfitting risk carefully |
| **Phase 8 (future)** | Fundamental/news layer | Add slower-cadence fundamental filter (Alpha Vantage News & Sentiment) to swing model |
| **Phase 9 (future)** | Execution integration | Only after extensive backtesting on both models — connect to broker API (e.g., Alpaca) for semi-automated or manual-confirm execution |

**Recommendation:** Build and validate the swing model fully (Phases 1-4) before starting the day model — swing data is cheaper, simpler, and serves as a proof of concept for the rules-based scoring + trade selector approach before tackling the higher-cost, higher-complexity day trading infrastructure.

---

## Key Risks & Open Questions

- **Backtesting is mandatory before any live use** for both models. All confidence weights, scoring components, and trade-structure rules above are starting hypotheses, not validated rules.
- **Confidence scores are not calibrated probabilities until proven otherwise** — a 75/100 score means "most signals align," not "75% win rate." Calibration must be established empirically via backtesting (Phase 4/7) before confidence scores should influence position sizing in any meaningful way.
- **Trade structure selection carries real financial risk if wrong** — picking calls vs. spreads vs. shorting based on flawed logic can produce asymmetric losses. This makes transparency (rules-based) and thorough backtesting especially important here.
- **Day model data costs** — real-time/intraday data feeds (Polygon, options flow data) are significantly more expensive than the daily-bar data the swing model needs. Confirm budget before scoping Phase 5+.
- **Social data quality** — coordinated/bot-driven sentiment can produce false signals; cross-validation with price action is essential in both models.
- **Overfitting risk is higher for the day model** given more granular data and more parameters — extra caution needed in Phase 7.
- **No live execution until both models are backtested** — system remains a research/decision-support tool until Phase 9.

---

## Open Decisions for Team Discussion

1. Confirm initial watchlist for each model — fixed list vs. broad scanning?
2. Confirm data source budget — especially for day model's real-time/options flow needs
3. Define backtesting period and success metrics (win rate, R:R, max drawdown) for each model before relying on output
4. Decide on output format/interface (CSV, dashboard, Discord/Slack alerts, etc.)
5. Define minimum R:R threshold for a candidate to be surfaced (e.g., 1:2)
