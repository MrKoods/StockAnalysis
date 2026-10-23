# Review agent

An unattended Claude Code session that reviews the V2, V3 and V4 paper-testing data on a schedule and
posts a summary to Discord. It **watches, researches and proposes**; it never changes a live model.

| Task | When (Pacific) | What |
|---|---|---|
| `StockAnalysis_Agent_DailyReview` | Mon-Fri 2:45 PM | Health check, the day's trades, progress vs each pass/fail rule, bug fixes prepared for approval |
| `StockAnalysis_Agent_WeeklyResearch` | Sat 9:00 AM | Week in review, 1-3 research questions on historical data, proposals for approval |

**Where it works:** its own git worktree `C:\Users\user\Documents\Git\StockAnalysis-agent` on
branch `agent`. It reads the live folders but is denied write access to them
(`agent_settings.json`), can't push/merge/checkout, and can't run the live pipelines. Each run
starts by rebasing `agent` onto `Version-1`.

**Its output:** `agent/reports/<date>-daily.md` / `-weekly.md` and a Discord message.
`agent/NOTES.md` is its memory between runs. Run logs: `agent/logs/` in the worktree (not tracked).

**Approving a proposal:** proposed fixes are commits on `agent` whose message starts
`PROPOSED FIX:`. In a normal Claude chat in the main folder, say e.g. "review and merge the agent's
proposed fix from <date>". Nothing reaches Version-1 otherwise.

**Run by hand:** `powershell -NoProfile -ExecutionPolicy Bypass -File agent\run_agent.ps1 -Mode daily`
from the worktree (or the main folder — the script uses absolute paths).

**Turn off:** disable the two scheduled tasks (Task Scheduler) — nothing else depends on them.
