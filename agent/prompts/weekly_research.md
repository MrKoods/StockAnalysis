# Weekly research (runs Saturdays ~9:00 AM Pacific)

Follow `agent/prompts/common.md` exactly. Date and task status: `agent/state/context.txt`.
You have more time this run (budget roughly 1-2 hours of work). Spend it on the highest-value
questions, not on covering everything.

## Steps

1. Read `agent/NOTES.md` (especially research already done and open questions) and the week's
   `agent/reports/*-daily.md`.
2. **Week in review.** Run `python agent/tools/snapshot.py`. For each V2 track and V3 strategy: the
   week's results, cumulative results, progress toward its frozen rule, and an honest read (on
   track / too early / looking weak). Compare the V2 rank track with the random-pick control and its
   sector ETFs once there is enough control data.
3. **Research (pick 1-3 questions).** Choose from: open questions in NOTES.md; weaknesses the data
   suggests (e.g. which part of the V2 score actually predicts R; exit rules; sectors; V3 cost
   sensitivity); or new strategy ideas worth testing. Work in `agent/research/<date>-<topic>/` on
   HISTORICAL data (V2: `data/historical*`, yfinance daily history; V3: the archives under the V3
   folder's `data/`). Read-only use of live code is fine (import it), but write only in your
   workspace. Pre-state your hypothesis and test before looking at results, keep a holdout, count
   variants, include realistic costs.
4. **Engineering review (short).** Note any real inefficiency, fragility or duplicated logic you hit
   — ranked by impact, with file:line references. Prepare a `PROPOSED FIX:` commit only for clear
   bugs.
5. **Write the report** to `agent/reports/<date>-weekly.md`:
   - Summary (5 lines, plain English).
   - Scorecard table: each track/strategy, status, progress vs its rule.
   - Research done: question, method, variants tried, result, verdict.
   - **Proposals for the user to approve** — each with: what changes, why, evidence, risk, and
     whether it touches a running experiment (if so, propose it as a NEW track instead).
   - Engineering notes.
6. **Write `agent/reports/discord.txt`** (max 1,500 characters): first line
   `📊 Weekly research <date>: <one-line headline>`, then the scorecard in a few lines and the
   proposals awaiting approval (numbered) — or "no proposals this week".
7. Update `agent/NOTES.md` (research done + conclusions + next questions), then commit on `agent`.

It is fine — often correct — to conclude "nothing should change this week".
