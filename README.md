# StockAnalysis

Research and **paper-testing** of stock-trading models. Nothing here places orders. No real money goes in
until a model passes a pass/fail test that was written down before its data came in.

**This `main` branch is only the map.** The code lives on the branches below. Each branch is a separate
project with its own README, and each is checked out in its own folder (a git worktree) on the machine
that runs it.

| Branch | Local folder | What it is | Status (2026-11-01) |
|---|---|---|---|
| [`Version-1`](../../tree/Version-1) | `StockAnalysis` | **V2 swing model.** Multi-sector (48 stocks, 4 sectors) 1-15-day swing signals scored on technicals, sentiment, news, fundamentals, positioning. Branch name is historical; the model is V2 (v2.2.x). | Paper. Rank track go/no-go at 100 closed trades (~Dec 2026). |
| [`Version-3`](../../tree/Version-3) | `StockAnalysis-V3` | **Research lab** + day-trading paper tests: G2 gap fade, ON1 overnight. | Paper. Verdicts ~Nov-Dec 2026. |
| [`Version-4`](../../tree/Version-4) | `StockAnalysis-V4` | **EPRE earnings-announcement premium**, the only idea so far to pass a pre-registered out-of-sample test. Also holds `MODULES.md`, the status and pass/fail rule of every running test. | Paper since 2026-10-26. First checkpoint (1,000 trades) ~mid-Nov 2026; earnings season is dense. |
| [`team`](../../tree/team) | `StockAnalysis-Team` | **Automated agent team**: runs and checks every scan, posts the daily health check + numbers, captures real Webull quotes, and researches new strategies (Scout, Researcher, Skeptic, Director, Auditor). | Running. |
| [`agent`](../../tree/agent) | `StockAnalysis-agent` | **Old review agent's reports** (2026-10-13 to 10-31). Replaced by the agent team. | Retired 2026-11-01, frozen. |

There is no V2 branch: the V2 model lives on `Version-1`.

## Where to start

1. Read the `Version-1` README. It holds the shared `.env` and the most code.
2. Read `MODULES.md` on `Version-4` for what is being tested and how each test is judged.
3. The daily health check and numbers are posted by the team's Ops Monitor; the team's reports (scorecards,
   Director and Auditor reviews) are on the `team` branch in `reports/`.

## Archived

| Tag | What |
|---|---|
| `archive/original-prototype` | The June 2026 first prototype (swing + day model) that used to be on `main`. |
| `archive/v3-quant-lab` | Early V3 deep-analysis work (price panel build). |

Restore either with `git checkout -b <name> <tag>`.
