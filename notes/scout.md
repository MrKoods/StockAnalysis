# Scout notes (max ~150 lines)

## Last run: 2026-11-05
- Run reason: scouting (4 ideas waiting, target 10)
- Ideas at start: 4 (turn-of-month, restructuring-bounce, quarter-end-window-dressing, early-10k-drift)
- Added 3 new ideas: early-10q-drift (10q_timing), debt-acceleration-bounce (8k_2_04), nt-filing-short (nt_filing)
- Total at `idea` stage after run: 7
- Still 3 short of target 10; next run should add up to 3 more

## Current ideas at `idea` stage (as of 2026-11-05)
1. turn-of-month — calendar_effects, 4d
2. restructuring-bounce — 8k_2_05, 3d
3. quarter-end-window-dressing — calendar_effects, 2d
4. early-10k-drift — 10k_timing, 3d
5. early-10q-drift — 10q_timing, 3d (10-Q timeliness; Chambers & Penman; 4x more events than 10-K)
6. debt-acceleration-bounce — 8k_2_04, 3d (screen t=+1.99; distress-resolution bounce)
7. nt-filing-short — nt_filing, 3d (NT filing = negative signal; short S&P 500 large-cap only)

## 2026-10-30 (set by the user's session, not a Scout run)
Rule tightened in prompts/scout.md: only ideas testable with research_data.py alone AND with an untouched
holdout window. Dropped: split-announcement-drift, sp-reconstitution (need scrapes), insider-officer-buys
(insider family has no clean period left). Remaining: turn-of-month, earnings-contagion.
earnings-contagion also DROPPED (user, 2026-10-30): earnings_events searched 2000-2017 and held out
2018-2026 twice (EPRE, ESUR) - no clean window. Don't add more earnings_events ideas.

## 2026-10-30: SEC company-event data added (see state/data_catalog.md)
rd.filings() = every SEC filing + 8-K item codes since 2004 (officer changes, deals, restatements,
buybacks...); rd.splits() = splits with announcement dates. Each 8-K event type is a NEW family
with its whole history clean except screen (2005-2013) already used.

## Needs data (not registered - the user decides if the data is worth getting)
- sp-reconstitution: S&P 400/600 addition announcement dates (spglobal.com press releases)
- any insider idea: a clean insider period no longer exists in the 2006+ SEC data
- analyst-upgrade-on-pullback: ratings() has no live feed (ratings source is NO); if live feed added,
  train 2012-2019 / holdout 2020-2026 clean; mechanism: Jegadeesh et al. (2004) show upgrades most
  informative in cold stocks
- 5.02 officer departure vs appointment: needs text parsing to separate departure from appointment direction
- dividend capture: needs a dividend ex-date calendar (not in catalog)
- options expiration pinning reversal: needs options open interest data (not in catalog)
- SC 13G new blockholder: initial SC 13G filing = passive 5%+ holder; mechanism weaker than 13D
  (activist); February filing cluster is a paper-runner concern; needs "first-ever vs amendment" logic;
  Edmans (2009) shows 13D (activist) is strong but 13G (passive) is weak; deferred

## What is left in 8-K space (for future runs)
Screen results summary (best-of-57 luck t ~2.84 — no type is a lead at that threshold):
- 7.01 Reg FD: t=2.31 → registered (now DEAD); small-cap tilt ran negative
- 2.04 debt acceleration trigger: t=1.99 (3d) → registered as debt-acceleration-bounce
- 2.05 restructuring: t=1.79 (3d) → registered as restructuring-bounce
- 3.03 shareholders' rights change: t=-1.98 (1d); short side, thin after costs; skip
- 3.02 unregistered equity sale: t=-1.70 (3d); -37.9 bps but after 20bps costs = +17.9 → short, expensive
- All other types: t < 1.5, skip
- 8k_5_01 (change in control): NOT in screen; 384 events/20yr = ~19/yr → ~180 holdout events; too sparse

## Calendar effects family status
- turn-of-month: at `idea` stage
- quarter-end-window-dressing: at `idea` stage
- Both: 0 holdouts used, 0 search variants; family bar = 3.0

## Budget state (2026-11-05)
- 10q_timing: new family, entirely clean
- nt_filing: new family, entirely clean
- 8k_2_04: search 2005-2013 (screen); holdout 2014-2026 clean; 0 researcher variants
- 8k_2_05: search 2005-2013 (screen); holdout 2014-2026 clean
- 10k_timing: new family, entirely clean
- calendar_effects: 0 holdouts, 0 variants
- analyst_ratings: search 2012-2019 (train run); live feed=NO → no more ideas
- 8k_7_01: fully mined (screen + train run); small-cap effect ran opposite; don't add more
- earnings_events: 2 holdouts used; NO CLEAN HOLDOUT - don't add more
- corporate_events: 1 holdout used (fail)
- insider: 2 holdouts used; bar = 3.00 (no clean period)

## Ideas to target next run (need ~3 more to approach 10)
1. Any fresh SSRN/arXiv ideas using filings() that don't overlap with the above families:
   - CORRESP filing (SEC scrutiny signal): filings(forms=['CORRESP']); mechanism is speculative (response vs. notice); deferred pending clearer mechanism evidence
   - Multiple 8-K items in same filing as opacity signal: 2.05 + 5.02 together as "captain jumping ship";
     would need filings() item co-occurrence logic (researcher could do it)
2. 10-K late filer short (family 10k_timing): complement to early-10k-drift; same researcher test
3. DEF 14A timing: proxy statement timing; mechanism unclear; skip unless literature found
4. Additional calendar effects: year-end tax-loss harvesting reversal (buy beaten-down Dec stocks for
   January bounce) — but january-small-cap-reversal was already dropped; check if data-driven

## Areas/sources checked 2026-11-05
- Academic: Chambers & Penman (1984), Begley & Fischer (1998) [10-Q timeliness]
  Engelberg, Reed & Ringgenberg (2012) [short-seller resolution bounce]
  Ettredge, Lee & Scholz (2000), Kinney & McDaniel (1989) [NT filings = bad news]
  Ohlson (1980) [distress resolution bounce]
  Edmans (2009), Clifford (2008) [13D/13G blockholder disclosures]
- Screen: re-read screen.md; 2.04 is the last remaining lead (t=1.99)
- Catalog: verified 10q_timing and nt_filing are clean new families
- Graveyard: no conflicts found for any new idea

## Watch for next run
- Did Director queue early-10q-drift, debt-acceleration-bounce, nt-filing-short?
- Was V3 G2 day-20 checkpoint scored today (2026-11-05)? Check context.md
- Need ~3 more ideas to reach target 10
- SC 13G idea deferred (passive 13G mechanism too weak vs 13D)
- nt-filing-short needs researcher to verify paper_runner.py short direction support
