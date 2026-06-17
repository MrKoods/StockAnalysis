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

## Proposed File Structure (VS Code / local project)

```
trading-signal-system/
├── README.md
├── .env.example                  # API key placeholders (never commit real .env)
├── .gitignore
├── requirements.txt
├── config/
│   ├── config.yaml                # global settings (API endpoints, general thresholds)
│   ├── swing_config.yaml          # swing-specific thresholds, semiconductor watchlist + SMH/SOXX benchmark
│   └── day_config.yaml            # day-specific thresholds, mega-cap/liquid basket watchlist
│
├── data/
│   ├── raw/                        # cached raw API responses
│   ├── processed/                  # cleaned indicator data
│   └── historical/                 # historical data for backtesting
│
├── indicators/
│   ├── __init__.py
│   ├── base.py                     # shared indicator interfaces/utilities
│   ├── technical.py                # MAs, breakouts, RS, volume (used by both models)
│   ├── sentiment.py                # StockTwits/social sentiment fetch + scoring
│   ├── news.py                     # news/fundamental data fetch
│   ├── options_flow.py             # IV, put/call ratio, unusual activity (day model)
│   └── intraday.py                 # VWAP, opening range, relative volume (day model)
│
├── models/
│   ├── swing/
│   │   ├── __init__.py
│   │   ├── indicator_pipeline.py   # orchestrates indicator layer for swing model
│   │   ├── scoring.py              # rules-based scoring logic
│   │   └── trade_selector.py       # picks trade structure given score + risk/reward
│   │
│   └── day/
│       ├── __init__.py
│       ├── indicator_pipeline.py   # orchestrates indicator layer for day model
│       ├── scoring.py              # rules-based scoring logic (faster cadence)
│       └── trade_selector.py       # picks trade structure given score + risk/reward
│
├── backtesting/
│   ├── __init__.py
│   ├── backtest_engine.py          # runs scoring logic against historical data
│   ├── metrics.py                  # win rate, R:R, drawdown, Sharpe, etc.
│   └── reports/                    # backtest output reports
│
├── api/
│   ├── __init__.py
│   ├── market_data_client.py       # yfinance/Alpha Vantage/Polygon wrapper
│   ├── sentiment_client.py         # StockTwits/StockGeist wrapper
│   └── news_client.py              # Alpha Vantage News & Sentiment wrapper
│
├── scripts/
│   ├── run_swing_model.py          # daily entry point for swing model
│   ├── run_day_model.py            # intraday entry point for day model
│   └── run_backtest.py             # entry point for backtesting either model
│
├── output/
│   ├── swing_recommendations/      # daily ranked output (CSV/JSON)
│   └── day_recommendations/        # intraday ranked output (CSV/JSON)
│
└── tests/
    ├── test_indicators.py
    ├── test_swing_scoring.py
    └── test_day_scoring.py
```

**Notes on structure:**
- `indicators/` holds reusable indicator logic shared across both models where applicable (e.g., `technical.py`); model-specific indicators (options flow, intraday metrics) are separate modules
- `models/swing/` and `models/day/` each have their own pipeline, scoring, and trade selector — independent and tunable separately
- `config/` separates global settings from per-model thresholds so swing and day logic can be tuned independently without touching code
- `backtesting/` is shared infrastructure usable against either model's scoring logic
- `.env` (not `.env.example`) holds real API keys and should be in `.gitignore`

---

## Swing Trading Model

**Timeframe:** Holding periods of days to weeks.

**Cadence:** Indicator layer runs once (or a few times) daily, typically after market close.

### Indicator Layer (Swing)

| Category | Indicators | Source |
|---|---|---|
| Technical | 20/50-day MAs, 20/50-day breakout levels, 20-day avg volume, relative strength vs. SPY | yfinance / Alpha Vantage / Polygon |
| Social/Sentiment | Mention volume, bullish/bearish ratio, multi-day rate of change | StockTwits API / StockGeist.ai |
| News/Fundamental (Phase 2) | Earnings trends, analyst sentiment shifts, sector news | Alpha Vantage News & Sentiment |

### Scoring Logic (Swing — starting rules, require backtesting)

| Condition | Score |
|---|---|
| Close > 20-day high AND volume > 1.5x 20-day avg volume | +2 (bullish breakout) |
| Price > 50-day MA AND 20-day MA > 50-day MA | +1 (uptrend structure) |
| 20-day return outperforms SPY by 5%+ | +1 (relative strength) |
| Social mention volume + bullish ratio trending up over 3-5 days | +1 (building momentum) |
| Inverse of above conditions | Negative scores (bearish/short setups) |

### Trade Structure Selection (Swing)

Given a composite score and current volatility regime (e.g., IV percentile on the underlying), the trade selector picks a structure:

| Scenario | Likely Structure |
|---|---|
| Strong bullish score, low/normal IV | Long stock, or long calls (1-3 month expiry) |
| Strong bullish score, high IV (e.g., pre-earnings) | Bull call debit spread (reduces cost/vega exposure) |
| Moderate bullish score, range-bound expectation | Sell put credit spread below support |
| Strong bearish score, low/normal IV | Short stock, or long puts |
| Strong bearish score, high IV | Bear put debit spread |
| Conflicting signals (e.g., sentiment up, price not confirming) | No trade / watchlist only |

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

### Scoring Logic (Day — starting rules, require backtesting)

| Condition | Score |
|---|---|
| Price breaks above opening range high with relative volume > 2x | +2 (bullish momentum) |
| Price holds above VWAP after pullback | +1 (trend continuation) |
| Unusual call options activity + IV expansion on the move | +1 (confirmation) |
| News catalyst aligns with direction | +1 |
| Inverse of above conditions | Negative scores (bearish/short setups) |

### Trade Structure Selection (Day)

| Scenario | Likely Structure |
|---|---|
| Strong bullish score, fast clean move expected | Long stock (most responsive, no theta decay risk) |
| Strong bullish score, want leverage on a sharp move | Short-dated (0-2 day) long calls — only if move is expected to be large enough to overcome theta |
| Strong bearish score | Short stock or short-dated long puts |
| High conviction but high IV (earnings-day type move) | Debit spread to reduce cost basis |
| Low conviction / choppy conditions | No trade |

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

- **Backtesting is mandatory before any live use** for both models. All scoring thresholds and trade-structure rules above are starting hypotheses, not validated rules.
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
