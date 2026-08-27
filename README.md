# StockAnalysis — V3

A research project testing whether a systematic equity strategy has a real,
measurable edge, before any code is written to trade it.

**This does not trade, and does not recommend trades.** It is a research rig.

---

## Why V3 exists

V2 (branch `Version-1`, ~110 versions, Jun-Aug 2026) built a complete trading
system — five scoring categories, 42 trade structures, four sectors, ~150 config
keys — on top of hypotheses that had never been individually tested. It never
passed its own go-live gate. Its final measurement: the real, non-proxy part of
the score had an Information Coefficient of −0.01 (p=0.77), statistically
indistinguishable from noise, on 10 qualifying trades across 13 years.

The failure was the order of operations, not the code. V3 inverts it.

> **Signal before architecture:** prove a single hypothesis predicts returns, on
> a sample large enough to mean it, out-of-sample, net of costs — and only then
> build anything around it.

The full trap list is in [`docs/v2_postmortem.md`](docs/v2_postmortem.md). Read
it before adding anything to this repo.

---

## Current hypothesis

Classic **cross-sectional momentum with a trend filter**: rank a large liquid
universe on the return from t−252 to t−21 (skipping the most recent month to
avoid short-term reversal), hold the top quintile, rebalance monthly, and
overlay a 200-day trend filter at the name level, the market level, or both.

Chosen because it is the most independently replicated anomaly in the equity
literature, it is cheap to test, and — unlike sentiment, V2's fatal dependency —
there is real point-in-time history to test it against.

**Honest caveat:** the robust form of this effect holds for weeks-to-months. At a
1-15 day horizon the dominant documented effect is short-term *reversal*, not
momentum. Phase 5 maps where the edge actually lives, and the strategy's cadence
follows the data rather than the project's original name.

---

## Phases

| # | Phase | Pass bar |
|---|---|---|
| 0 | Strip-down & scaffold | Repo builds, kept tests pass — **done** |
| 1 | Data assembly | Panel reconciles; returns match an external reference |
| 2 | Replicate classic momentum | Reproduces the published sign and rough magnitude |
| 3 | Trend / regime filter | Beats baseline Sharpe *and* cuts drawdown |
| 4 | Cost & implementation reality at $15k | Net-of-cost Sharpe holds; executable by hand |
| 5 | Horizon exploration | Exploratory — no bar |
| 6 | Out-of-sample & walk-forward gate | See `research/config.py`, `GATE_*` |

Progress and verdicts: [`RESEARCH_LOG.md`](RESEARCH_LOG.md).

---

## Quick start

```bash
pip install -r requirements.txt

python -m research.panel --download    # Phase 1: fetch + cache (slow, network)
python -m research.panel --verify      # structural checks on the cached panel

pytest                                 # test suite
ruff check .                           # lint
```

---

## Layout

```
research/          Phase scripts. config.py holds every shared constant.
backtesting/       metrics.py — the statistical lab (IC, bootstrap CIs,
                   Benjamini-Hochberg, deflated Sharpe, drawdown/Sortino/Ulcer).
shared/            market data client, logging, atomic IO, robust z-score,
                   fill simulation.
docs/              v2_postmortem.md — the rules this rebuild runs on.
data/panel/        Cached parquet panel (gitignored).
CHANGELOG.md       V2's full history, retained as the archive.
```

---

## Rules of the road

1. **Out-of-sample data (2019-2026) stays sealed until Phase 6.** If you look at
   it, record that in `RESEARCH_LOG.md` — it stops being out-of-sample.
2. **Write the hypothesis and the pass bar before the run**, not after seeing the
   result.
3. **Correct for multiple testing.** Report `bh_significant` and a bootstrap CI,
   never a bare p-value. Report the deflated Sharpe whenever a sweep preceded
   the headline number.
4. **No shared constant is defined locally.** It is imported from
   `research/config.py` or it does not exist.
5. **New ideas go in the `RESEARCH_LOG.md` backlog, not the code**, until the
   current hypothesis has a verdict.
6. **"No edge" is a valid, expected outcome.** Kill criteria are written down
   before each phase, and honored.

---

## Status

Phase 0 complete. Nothing has been validated. There is no strategy here yet, and
no capital — real or simulated — is at risk.
