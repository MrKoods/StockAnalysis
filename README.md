# StockAnalysis — V2 swing model (branch `Version-1`)

A multi-sector swing-trading **signal** model (hold 1-15 trading days). It scores 48 stocks in four
sectors (semiconductors, regional banks, healthcare, consumer discretionary) on technicals, sentiment,
news, fundamentals and positioning, and logs the trades it would take to **paper** ledgers. It never
places orders. Current model version: top entry of [CHANGELOG.md](CHANGELOG.md) (v2.2.134).

> **Naming note:** this branch is called `Version-1` for historical reasons, but the model on it is V2
> (versions 2.x in the CHANGELOG). Other models live on other branches — see
> [Other branches](#other-branches-and-folders).

**Status (2026-10-30):** paper only. No edge established yet. The rank track has a pre-registered
go/no-go at 100 closed trades (`paper_trading/rank_verdict.py`). Trades are shares only
(`shares_only: true` in the config).

## What runs every day

All times Pacific, Mon-Fri, via Windows Task Scheduler. Each task runs from this folder.

| Task | Time | Command |
|---|---|---|
| `StockAnalysis_PaperRunner_PreMarket` | 05:30 | `python -m paper_trading.paper_runner --scan-type pre_market` |
| `StockAnalysis_PaperUpdater` | 08:07 | `python -m paper_trading.paper_updater` (closes/scores open paper trades) |
| `StockAnalysis_PaperRunner_MidSession` | 09:00 | `python -m paper_trading.paper_runner --scan-type mid_session` |
| `StockAnalysis_PaperRunner` | 13:30 | `python -m paper_trading.paper_runner --scan-type post_close` |
| `StockAnalysis_WeeklyDashboard` | Sun 18:00 | `python -m monitoring.performance_dashboard` |

Task output goes to `data/logs/*_task.log`. Results are posted to Discord (`DISCORD_WEBHOOK_URL`).

**Do not rename or move** `paper_trading/paper_runner.py`, `paper_trading/paper_updater.py`,
`monitoring/performance_dashboard.py`, or the paper ledgers (`paper_trading/*.csv`): the scheduled tasks,
the review agent and the agent team all reference them by path.

## Folder map

| Folder | What's in it |
|---|---|
| `swing_model/` | The model: data pipeline, the five scoring layers, `scoring.py`, trade selection, portfolio rules. `run_swing_model.py` is the full scan. |
| `paper_trading/` | Live paper testing. `paper_runner.py` (scans + logs signals), `paper_updater.py` (resolves outcomes), the ledgers (`paper_trades.csv` threshold track, `rank_trades.csv` rank track, `random_trades.csv` random control, `options_positions.csv`), `rank_verdict.py` (go/no-go), and diagnostics. |
| `shared/` | Code used everywhere. `api_clients/` = every external data source (all HTTP goes through here, with caching and rate limiting); `indicators/` = technical math; `utils/` = risk, sizing, gates, alerts, logging. |
| `backtesting/` | Historical replay (`backtest_engine.py`, `run_backtest.py`, `walk_forward.py`, `stress_test.py`) plus one-off research sweeps/diagnostics (`*_sweep.py`, `*_diagnostic.py`). Their output is in `backtesting/reports/`. Several of these are imported by the live code, so treat them as part of the codebase, not scratch. |
| `monitoring/` | Weekly performance dashboard. |
| `app_ui/` | Optional desktop app (PySide) for running scans by hand: `python -m app_ui.main`. |
| `agent/` | The scheduled review agent (Claude Code, headless). See [agent/README.md](agent/README.md). Its reports live on the `agent` branch. |
| `config/` | `swing_config.yaml` (watchlist, sectors, thresholds, every model setting) and `global_config.yaml` (API/infrastructure). |
| `data/` | `processed/` live model state, `logs/` audit trail and task logs, `historical_news/` and `panel/` research datasets. Raw downloads and caches are gitignored. |
| `scripts/` | CI guard checks (`check_*.py`), one-time ledger migrations/backfills, and `download_historical_news.py`. |
| `tests/` | pytest suite (~1,800 tests). |
| `docs/` | Original design documents: `Project_Scope.md` (full spec), `PROJECT_OVERVIEW.md`, `App_UI_Scope.md`. Useful background; the CHANGELOG is the authoritative record of what changed since. |
| `output/` | Scan recommendation files (`config/global_config.yaml` → `output.recommendations_dir`). |

## Setup

```bash
pip install -r requirements.txt          # requirements.lock.txt = exact versions CI uses
python -m spacy download en_core_web_sm
cp .env.example .env                     # then fill in the keys
```

Main `.env` keys: `ALPHA_VANTAGE_API_KEY`, `FINNHUB_API_KEY`, `RAPIDAPI_KEY`, `SEC_EDGAR_USER_AGENT`,
`DISCORD_WEBHOOK_URL` (plus `DISCORD_AGENT_WEBHOOK_URL` and the team webhooks; see `.env.example`).
The other worktrees (V3, V4, team, agent) read this same `.env`.

## Running things by hand

```bash
python -m paper_trading.paper_runner --scan-type post_close   # a paper scan (what the task runs)
python -m paper_trading.paper_updater --summary               # paper performance summary
python swing_model/run_swing_model.py                         # full model scan
python backtesting/run_backtest.py [--sensitivity]            # backtest
python -m monitoring.performance_dashboard                    # weekly dashboard
python -m app_ui.main                                         # desktop app
```

## Checks (same as CI)

```bash
ruff check .
pytest
python scripts/check_config_coverage.py
python scripts/check_confidence_threshold_duplication.py
python scripts/check_no_raw_http.py
python scripts/check_rank_track_slot_budget.py
```

CI (`.github/workflows/ci.yml`) also runs `scripts/check_version_bump.py`. Any change to
`config/swing_config.yaml` or `swing_model/scoring.py` must come with a new top version entry in
`CHANGELOG.md`, including comment-only edits.

## Other branches and folders

This one GitHub repo holds several separate projects, one per branch. Each branch is checked out in
its own folder (a git worktree) next to this one:

| Branch | Local folder | What it is |
|---|---|---|
| `Version-1` | `StockAnalysis` (this) | V2 swing model, paper testing |
| `Version-3` | `StockAnalysis-V3` | Research lab + G2 gap-fade and ON1 overnight paper tests |
| `Version-4` | `StockAnalysis-V4` | EPRE earnings-premium paper model |
| `team` | `StockAnalysis-Team` | Automated agent team (dispatcher, quotes, scan ops) |
| `agent` | `StockAnalysis-agent` | Review-agent reports. Rebased onto `Version-1` every run, so push it with `git push --force-with-lease origin agent` |
| `main` | — | Landing page: the map of all of the above |

The status and pass/fail rule of every running test is in `MODULES.md` on the `Version-4` branch.
