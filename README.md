# StockAnalysis V3 — research lab + day-trading paper tests (branch `Version-3`)

This branch is where trading ideas are TESTED before any of them becomes a model. It is not itself a model.
It is checked out in its own folder, `StockAnalysis-V3`, next to the main `StockAnalysis` folder.
The map of all branches is in the `main` branch README.

- `daytrade/research/`: every search, protocol and holdout run (rounds 1-7, ~380k configs). Write-ups and
  pre-registered protocols are in `research_results/` (start with `RESEARCH_LOG.md`).
- An idea that passes a pre-registered holdout graduates to its OWN version branch with its own paper test
  and fixed pass/fail rule. First graduate: the earnings announcement premium -> `Version-4`
  (`../StockAnalysis-V4`, 2026-10-23).
- Still running here until their verdicts (~Nov-Dec 2026): G2 gap fade and ON1 overnight (forward + paper).
  If they fail they are archived and V3 keeps only the lab. Status of every module: `MODULES.md` on `Version-4`.
- Retired 2026-10-23: C6 sweep forward test, Dukascopy minute download, minute auto-research (tasks disabled,
  code and data kept).

## What runs every day

Mon-Fri, Pacific time, Windows Task Scheduler. Each task runs from this folder. Logs go to `data/logs/`.

| Task | Time | Command |
|---|---|---|
| `StockAnalysis_V3_G2Paper_Signals` | 06:34 | `python -m daytrade.g2_paper signals` (post today's 10 G2 paper trades) |
| `StockAnalysis_V3_ON1Paper_Evaluate` | 06:45 | `python -m daytrade.on1_paper evaluate` (score yesterday's ON1 picks) |
| `StockAnalysis_V3_G2Paper_Evaluate` | 10:45 | `python -m daytrade.g2_paper evaluate` |
| `StockAnalysis_V3_ON1Paper_Signals` | 12:40 | `python -m daytrade.on1_paper signals` |
| `StockAnalysis_V3_IntradayFetch` | 14:00 | `python -m daytrade fetch`, then `python -m daytrade forward` (G2/ON1 forward ledgers) |

Add `--dry-run` to the paper commands to print instead of posting or writing. Alerts go to the
`DISCORD_WEBHOOK_URL` in the main `StockAnalysis/.env`.

## Folder map

| Path | What's in it |
|---|---|
| `daytrade/` | Live code: `data.py` (bar archive), `forward.py` (forward-test ledgers), `g2_paper.py` / `on1_paper.py` (paper tests), `strategy.py` / `backtest.py` / `levels.py` (original sweep strategy), `dukascopy.py` (retired minute download), index lists `sp*.csv`. |
| `daytrade/research/` | The lab: one module per research round (`families*.py`, `combo*.py`, `daily*.py`, `events*.py`, `minute*.py`, ...). |
| `research_results/` | Protocols (`PROTOCOL*.md`), shortlists, and the CSV/log output of every run. `RESEARCH_LOG.md` is the index. |
| `data/forward/`, `data/paper/` | The forward-test and paper ledgers (tracked). |
| `data/intraday/`, `data/events/`, `data/logs/` | Bar archive, research event datasets, task logs (all gitignored). |
| `tests/` | pytest suite. |

Checks: `ruff check .` and `pytest`.
