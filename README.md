# AI-Assisted Swing Trading Signal System

## Section 1 — What This Project Does

A swing trading decision-support system for the semiconductor sector (NVDA, AMD, AVGO, TSM, MU, ASML). It pulls technical, sentiment, and news data for 6 semiconductor stocks, combines them into a statistically-grounded confidence score (0-100), evaluates all 42 trade structures by expected value, and delivers ranked trade recommendations via Discord alerts. Every recommendation requires your review and manual execution — this is not an autonomous trading system. Starting capital: $15,000 | Holding period: 5-15 trading days.

---

## Section 2 — Quick Start

1. Clone the repo: `git clone <repo-url> && cd StockAnalysis`
2. Install dependencies: `pip install -r requirements.txt`
3. Install spaCy English model: `python -m spacy download en_core_web_sm`
4. Copy env template: `cp .env.example .env` — fill in your API keys
5. Run the swing model: `python swing_model/run_swing_model.py`
6. Check Discord for output (configure `DISCORD_WEBHOOK_URL` in `.env` first)

---

## Section 3 — API Keys Required

| Key | Where to Get It | `.env` Variable |
|---|---|---|
| Alpha Vantage | [alphavantage.co](https://www.alphavantage.co/support/#api-key) — free tier | `ALPHA_VANTAGE_API_KEY` |
| StockTwits + Seeking Alpha Finance (RapidAPI) | [rapidapi.com](https://rapidapi.com) — paid subscription, shared key for both (Sentiment layer) | `RAPIDAPI_KEY` |
| Finnhub | [finnhub.io](https://finnhub.io) — free tier; used for `/company-news` headlines only (social-sentiment requires a paid plan) | `FINNHUB_API_KEY` |
| Discord Webhook | Discord server → Edit Channel → Integrations → Webhooks | `DISCORD_WEBHOOK_URL` |

---

## Section 4 — Project Structure

| Folder | Purpose |
|---|---|
| `shared/` | All reusable logic: API clients, indicator math, utilities (used by swing model and backtesting) |
| `swing_model/` | Pipeline, scoring, trade selection, and portfolio management for the semiconductor swing strategy |
| `backtesting/` | Historical replay engine, metrics, walk-forward validation, stress testing |
| `paper_trading/` | Forward-testing with real-time data and simulated fills (no real capital) |
| `monitoring/` | Weekly performance dashboard sent to Discord |
| `data/` | `raw/` (gitignored API cache), `processed/` (position state, live weights), `historical/` (gitignored), `logs/` (audit, override, validation, fill, trade outcomes, performance) |
| `config/` | `global_config.yaml` (infrastructure settings) + `swing_config.yaml` (watchlist, all thresholds) |
| `output/` | Daily ranked CSV/JSON recommendations |
| `tests/` | pytest test suites for indicators, scoring, and stress scenarios |

---

## Section 5 — Current Build Status

**Phase: Scaffolding complete — Phase 1 (market data + technical indicators) in progress.**

| Phase | Status | Description |
|---|---|---|
| 1 | 🔄 In progress | `market_data_client.py`, `technical_common.py` with z-score normalization |
| 2 | ⏳ Pending | `indicator_pipeline.py` |
| 3 | ⏳ Pending | Macro context layer (regime, rotation, earnings, seasonality, macro overlay) |
| 4 | ⏳ Pending | Sentiment + news layer |
| 5 | ⏳ Pending | Volume profile + cross-ticker analysis |
| 6 | ⏳ Pending | Confidence scoring (`scoring.py`) |
| 7 | ⏳ Pending | EV-based trade selector (42 structures) |
| 8 | ⏳ Pending | Signal decay + portfolio management |
| 9 | ⏳ Pending | Risk mitigation layer |
| 10 | ⏳ Pending | Discord alerts + notification routing + `run_swing_model.py` |
| 11 | ⏳ Pending | Model versioning + CHANGELOG enforcement |
| 12 | ⏳ Pending | Backtesting (70/30, walk-forward, stress test) |
| 13 | ⏳ Pending | Paper trading (60-90 trading days minimum) |
| 14 | ⏳ Pending | Feedback loop + performance monitoring |
| 15 | 🔮 Future | Live execution (after Phase 13 paper trading passes) |
| 16 | 🔮 Ongoing | Continuous improvement |

**Event Severity Gate (v2.1.0):** ✅ Built and tested — `shared/utils/event_gate.py`, wired into `news_layer.py`/`scoring.py`/`run_swing_model.py`. Binary veto (not a scoring category) that suppresses signal surfacing on critical, thesis-opposed news until the next post-close scan completes after the event. See `CHANGELOG.md` v2.1.0 and `Project_Scope.md` → "Event Severity Gate". **Not yet backtested** — same not-live-eligible status as the rest of the model until a passing backtest is logged.

---

## Section 6 — How to Run Each Component

```bash
# Run daily swing model scan
python swing_model/run_swing_model.py

# Run full backtest
python backtesting/run_backtest.py

# Run sensitivity analysis only
python backtesting/run_backtest.py --sensitivity

# Run stress test
python backtesting/stress_test.py

# Run paper trading engine
python paper_trading/paper_trade_engine.py

# Run performance dashboard (generate weekly summary)
python monitoring/performance_dashboard.py
```

---

## Section 7 — Configuration

**`config/swing_config.yaml`** — strategy-level settings:
- `watchlist.tickers` — add/remove tickers here; `benchmark` sets the RS reference (SMH)
- `confidence.min_threshold` — default 90; adjust only after re-backtesting
- `scoring_weights` — technical/sentiment/news max contributions (must sum to 100)
- `modifier_bounds` — per-modifier min/max; calibrated during Phase 12 backtesting
- `position_sizing.tiers` — risk % per confidence tier; `max_capital_pct` caps per-trade size
- `circuit_breakers` — yellow/orange/red drawdown levels
- `options_approval_level` — set to your actual brokerage approval level (1/2/3)
- `event_severity_gate` — enable/disable flag, sector-wide/ticker trigger keyword lists, principal sources, minimum source credibility (news veto, not a scoring category)

**`config/global_config.yaml`** — infrastructure settings:
- API base URLs, rate limits, retry backoff parameters
- Scan schedule (pre-market 8:30am ET, mid-session 12pm ET, post-close 4:30pm ET)
- Log file paths, notification routing rules

---

## Section 8 — Warnings

- **Backtesting required before live use.** The $15,000 must not go live until Phase 12 backtesting confirms 80% win rate + 1:3 R:R + 90/100 minimum confidence across multiple market regimes, including at least one high-volatility period (VIX > 30).
- **Not financial advice.** This system is a decision-support tool. Every recommendation requires your review and manual execution. Past backtested performance does not guarantee future results.
- **Paper trading gate.** Even after backtesting passes, the $15,000 must not go live until Phase 13 paper trading sustains 80% win rate + 1:3 R:R + slippage within 10% of modeled estimates over a minimum of 60 trading days (~3 calendar months).
