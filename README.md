# AI-Assisted Trading Signal System

Decision-support tool for swing and day trading signals across a niche semiconductor watchlist (swing)
and high-liquidity mega-cap basket (day). Not an autonomous trading system — all output requires human
review and must be backtested before use.

## Project Structure

- `swing_model/` — Daily indicator pipeline and scoring for semiconductor tickers
- `day_model/` — Intraday indicator pipeline and scoring for mega-cap/liquid tickers
- `shared/` — Timeframe-agnostic utilities, API clients, and indicator math used by both models
- `backtesting/` — Shared backtesting engine and metrics; model-specific entry points
- `config/` — Global settings plus one config file per model (single source of truth per model)

## Setup

1. Copy `.env.example` to `.env` and fill in your API keys (never commit `.env`)
2. Install dependencies: `pip install -r requirements.txt`
3. Review `config/global_config.yaml`, `config/swing_config.yaml`, and `config/day_config.yaml`

## Running the Models

**Swing model** (run after market close, daily):
```
python swing_model/run_swing_model.py
```

**Day model** (run during market hours, intraday):
```
python day_model/run_day_model.py
```

**Backtesting:**
```
python backtesting/run_backtest_swing.py
python backtesting/run_backtest_day.py
```

## Output

- `output/swing_recommendations/` — Ranked CSV/JSON output for swing candidates
- `output/day_recommendations/` — Ranked CSV/JSON output for intraday candidates

## Important

All scoring thresholds are starting hypotheses. Backtest both models thoroughly before relying on any output.
