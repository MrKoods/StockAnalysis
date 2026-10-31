# split-announcement-drift — pre-registered PLAN

## Hypothesis
A **forward** stock-split announcement is a positive signal; the stock drifts UP over the next few
sessions. Go LONG at the open of the first tradable session after the announcement, exit at the close
a few sessions later. SPY-hedged, so we measure the event drift, not the market.

## Mechanism (who is on the other side)
1. Management-confidence signal — boards split when they expect continued appreciation.
2. Retail-accessibility demand — a lower per-share price draws new retail buyers between the
   announcement and the effective date.
3. Analyst-attention reset — splits trigger coverage/target revisions over the following 1–2 weeks.
Short-term "buy-the-rumor-sell-the-news" traders sell the announcement pop; longer-horizon retail and
institutional buyers absorb it gradually → a few days of drift. Evidence: Grinblatt-Masulis-Titman
(1984), Ikenberry-Rankine-Stice (1996, effect larger for smaller firms), McNichols-Dravid (1990),
Desai-Jain (1997). All pre-2010 → post-publication arbitrage has likely compressed the long-horizon
component; the short-window (<5d) drift is harder to arbitrage, so the holdout (2018–2026) is a fair,
hard test of whether anything survives into the modern regime.

## Data (only tools/research_data.py)
- `rd.splits(None)` — one row per split: `ticker`, `ex_date`, `ratio` (>1 forward, <1 reverse),
  `announced` (timestamp the first "stock split" 8-K/press-release became public), `first_session`
  (the **leak-free** first session whose 09:30 open is after `announced`; NaT when no announcement was
  found — those rows are dropped). Announcement found for ~812 splits (2001+).
- `rd.daily(tickers)` — OHLCV 1999-01 .. 2026-10-06 for returns and the SPY hedge.

## Exact rule
- Universe: every S&P 1500 name with price history (implicit — `rd.daily` only returns those).
- Signal: a **forward** split (`ratio > 1`, variant tiers below) with a known `first_session`.
- Entry: LONG at the **open of `first_session`**. Exit: at the **close H sessions later**.
- One trade per (ticker, first_session). Return = SPY-hedged GROSS bps
  `(close/open − 1)·1e4 − (SPY close/open − 1)·1e4`; the harness subtracts `cost_bps`.
- NOT implemented: "exit at the effective date if sooner" — the ex-date is normally weeks after the
  announcement, so for H ≤ 4 it is almost never sooner; mixing it in would turn this into a multi-week
  hold (a different family). Kept to a clean fixed hold.

## Variants (6) and `chosen`
Grid: hold H ∈ {2, 4} sessions × ratio tier ∈ {`r1` = all forward (>1), `r2` = ≥2:1, `r3` = ≥3:1}.
`chosen` is **PRE-REGISTERED = `h4_r2`** (hold 4 sessions ≈ one trading week, forward splits ≥ 2:1 —
the idea's stated rule and the best-powered single hypothesis). The other 5 configs are a robustness
map for the Skeptic only and are NEVER carried to the holdout. Pre-registering `chosen` deterministically
keeps the holdout a single hypothesis and lets `strategy.py` match it exactly. Luck bar: `luck_t(6)` ≈
1.9; the holdout bar is the family floor **3.0** (`tools/budget.py bar corporate_events`).

## Windows (the corporate_events family has used no period — whole history clean)
- Train: 2001-01-01 .. 2017-12-31 (announcements begin ~2001).
- Holdout: 2018-01-01 .. 2026-10-06 (most recent, the arbitraged/high-priced-tech era; daily data
  ends 2026-10-06). One look only.

## Costs / clustering
- `cost_bps` = 20 round trip — the universe spans large-cap splitters (~10 bps) and mid/small caps
  (20–40 bps); 20 is a conservative blend.
- `cluster` = **week** (multi-day hold).

## What would kill it
- Holdout `chosen` t < 3.0 or mean ≤ 0 → dead (one look, no re-run).
- The announcement-day pop fully prices the drift → near-zero hedged return open→close from day 1.
- Effect concentrated pre-2010 and arbitraged away → fails in the 2018–2026 holdout.
- Too few events for power (forward splits are rare, ~30/yr across the S&P 1500) → wide t, no signal.

## Known biases (for the Skeptic)
- **Survivorship**: the universe is today's S&P 1500; splitters that later delisted are missing. This
  biases a LONG split signal UP — flagged.
- **Announcement coverage**: only ~812 of ~3,189 forward splits have a found announcement; the rest
  (NaT `first_session`) are dropped, which could bias toward better-documented (larger) events.

## Paper-test feasibility
PROMOTABLE (unlike insider-cluster-buys). Forward-split 8-K/press-release announcements are public the
same day and the team's `data/edgar/splits.parquet` (rebuilt by `tools/edgar.py` each dispatcher run)
carries `announced` — so `strategy.py` can detect a new announcement and enter at the next open live.
Caveat: forward splits are rare, so a 20–40 trading-day paper window accumulates only a handful of
signals; reaching `min_days` = 20 distinct exit dates will take many months. Frozen paper rule
(`strategy.py`/`spec.json`) = `chosen` `h4_r2`, metric `real_hedged_bps`, pass mean ≥ 10 bps and
day-t ≥ 2 over 20–40 days.
