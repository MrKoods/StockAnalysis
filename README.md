# StockAnalysis agent team

An automated research team that monitors the live paper tests, looks for new short-horizon strategies, tests
them under pre-registered rules, and runs promising ones as paper tests. **It never places orders.**
Charter, roles and hard limits: [TEAM.md](TEAM.md).

## How it runs
One scheduled task, `StockAnalysis_Team_Dispatch` (Mon-Sat 14:50 PT), runs `python tools/dispatch.py`:

1. **Paper runner** (script): trades the team's active strategies on paper, scores them.
2. **Ops Monitor** (script): every StockAnalysis_* task ran? data fresh? -> one line to #agent-ops.
3. **Triggers** (script): decides which Claude roles have a reason to run. Quiet day = **zero Claude usage**.
4. **Roles** (Claude headless): each with its own model, effort, turn cap, timeout and permission file
   (`team/roles.json`, `team/settings/<role>.json`). Output in `outbox/<role>.txt` is posted to its channel.
5. **Commit**: only the dispatcher commits (agents have no git), so commit times prove plan-before-results.

## Usage controls
- Roles launch only on triggers (Scorekeeper: failure to diagnose / checkpoint / Friday scorecard).
- `weekly_claude_run_cap` in `team/roles.json` (default 12) - past it, roles are skipped and #agent-ops is told.
- Cheap models for routine roles; Opus only for Researcher/Skeptic/Director/Auditor. Backtests run as plain Python.
- `state/usage.csv`: every Claude run - turns, minutes, API-equivalent cost.

## Discord channels (webhooks in the V2 `.env`)
| Key | Channel | Posts |
|---|---|---|
| `DISCORD_OPS_WEBHOOK_URL` | #agent-ops | heartbeat, alerts, diagnoses (scripts only, no Claude usage) |
| `DISCORD_RESEARCH_WEBHOOK_URL` | #agent-research | Scout ideas, research results, Skeptic verdicts |
| `DISCORD_DIRECTOR_WEBHOOK_URL` | #agent-director | decisions, tests started/stopped, scorecards, what you need to know |

Missing keys fall back to `DISCORD_AGENT_WEBHOOK_URL` (never the general scan channel).

## Controls
- **Pause everything**: create an empty file `STOP` in this folder (paper exits still evaluate; no new signals,
  no Claude roles). Delete it to resume.
- **Run by hand**: `python tools/dispatch.py --dry-run` (prints, sends nothing) | `--force scorekeeper` |
  `--no-claude`.
- **Gate**: `python tools/gate.py list | check <id>`. **Budget**: `python tools/budget.py`.
- **Turn a role on/off**: `enabled` in `team/roles.json`.

## Permission files - note
`Edit(...)` rules govern the Write tool too; `Write(...)` allow rules alone are ignored (verified 2026-10-27).
Every role denies all Webull order/revoke/post tools; unlisted tools are refused (dontAsk mode).

## When each role runs
| Role | Trigger |
|---|---|
| Scorekeeper | a task failure to diagnose, a frozen checkpoint reached, Friday scorecard |
| Scout | Tue + Thu, if fewer than 5 ideas are waiting |
| Director | Saturday review; Wednesday if the pipeline is idle; any paper verdict or holdout pass |
| Researcher | an idea was queued (or its script needs fixing) - same dispatch as the Director |
| Skeptic | a train result is waiting for review - same dispatch |
| Holdout Keeper | (script) right after a Skeptic PASS - same dispatch, exactly once per idea |
| Auditor | Saturday, after everyone else (exempt from the weekly cap; read-only; posts to #agent-director) |
A role that already finished today is not relaunched (except Researcher/Skeptic, which work per idea).

## Research safeguards
- Research scripts load data only via `tools/research_data.py`, which cuts at the plan's train end; a static
  scan rejects scripts that import yfinance/requests, read files, or touch the cutoff variable.
- The harness, not the script, computes stats: subtracts the plan's cost, clusters by day/week, reports the
  best-of-N luck t. `plan.lock` kills an idea whose plan changes after commit. Holdouts run once, ever.
- Promotion fingerprints the strategy; the paper runner refuses a strategy whose files changed.

## Status
2026-10-27: phases 1 + 2 built, all roles enabled. Permissions probed per role. 17 tests.
Workspace: worktree `C:\Users\user\Documents\Git\StockAnalysis-Team`, orphan branch `team` (local, not pushed).
