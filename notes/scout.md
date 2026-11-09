# Scout notes (max ~150 lines)

## Last run: 2026-11-09
- Run reason: scouting (1 idea waiting, target 10)
- Ideas at start: 1 at `idea` stage (late-10k-short)
- Added 2 new ideas: seo-short (seo_offering), quarter-end-winner-short (calendar_effects)
- Total at `idea` stage after run: 3 (target 10; still 7 short — need more next runs)
- Exhausted all viable 8-K screen leads; pivoted to non-8K academic ideas

## Current ideas at `idea` stage (as of 2026-11-09)
1. late-10k-short — 10k_timing, 3d (SHORT; close entry; Ettredge et al. 2000)
2. seo-short — seo_offering, 3d (SHORT; close entry; Loughran & Ritter 1997, ~300 bps)
3. quarter-end-winner-short — calendar_effects, 3d (SHORT; close entry; Carhart et al. 2002, ~90 bps)

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

## 8-K space: ALL VIABLE SCREEN LEADS EXHAUSTED
Screen results summary (best-of-57 luck t ~2.84 — no type is a lead at that threshold):
- 7.01 Reg FD: t=2.31 → registered (now DEAD); small-cap tilt ran negative
- 2.04 debt acceleration trigger: t=1.99 (3d) → registered as debt-acceleration-bounce (dropped)
- 2.05 restructuring: t=1.79 (3d) → registered (now DEAD)
- 3.02 unregistered equity sale: t=-1.70 (3d) → registered as pipe-short (now DEAD; wrong direction)
- 3.03 shareholders' rights change: t=-1.98 (1d); gross -24.9 bps; below 50 bps threshold; skip
- 3.01 delisting notice: t=-1.47 (3d); gross -42.6 bps; below 50 bps threshold; skip
- 4.02 restatement: t=-1.13 (5d); gross -51.4 bps; barely meets 50 bps but t too low; skip
- 5.02 director/officer change: t=-1.45 (1d); gross -3.3 bps; way below 50 bps; skip
- 4.01 auditor change: t=-0.26 to -0.45; near-zero; skip
- All other types: t < 1.5 or below 50 bps gross, skip
- 8k_5_01 (change in control): NOT in screen; 384 events/20yr = ~19/yr → ~180 holdout events; too sparse

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
  (activist); February filing cluster is a paper-runner concern; Edmans (2009) shows 13D is strong but
  13G (passive) is weak; deferred
- SEC comment letter short (UPLOAD form): academic support mixed — revenue recognition letters are
  negative but other 10-K letters are positive (Ryans 2019, Lee et al. 2023); direction contaminated
  without text parsing; skip unless NLP added
- rights-plan-short (8k_3_03): screen -41.5 bps at 5d (below 50 bps threshold); Ryngaert (1988) avg
  only -34 bps (discriminatory pills -109 bps); direction ambiguous (adoption vs. removal); skip
- proxy contest (DFAN14A): ~15-25 events/year in S&P 1500; too sparse; mixed signal (contests vs.
  routine shareholder proposals both use DFAN14A without text parsing)
- SEO via 424B3: may supplement seo-short; researcher should check event counts on 424B3 as well
  (424B3 covers shelf offerings including debt — mixed direction)

## Calendar effects family status
- turn-of-month: DEAD (train t=1.37)
- quarter-end-window-dressing: DROPPED (not tested)
- year-end-loser-reversal: at `dropped` (Director dropped; not in `idea` queue any more)
- quarter-end-winner-short: at `idea` (SHORT top-30d momentum at quarter-end close; Carhart 2002)
- train period 1999-2014 used by turn-of-month; holdout 2015-2026 clean
- Family bar = 3.0

## New family seo_offering status
- seo-short: at `idea` (SHORT after 424B4/424B5 pricing prospectus; Loughran & Ritter 1997)
- Entirely clean (no screen, no search, no holdout)
- Family bar = 3.0

## Budget state (2026-11-09)
- seo_offering: new family, entirely clean
- calendar_effects: search 1999-2014 (turn-of-month train run); holdout clean (2015-2026)
- 10k_timing: entirely clean (early-10k-drift dropped before test; late-10k-short at idea)
- 10q_timing: search 2001-2015 (team train run); holdout 2016-2026 clean
- nt_filing: search 2005-2017 (team train run); 0 holdouts
- 8k_3_02: search 2005-2013 (screen + team train run); 0 holdouts
- 8k_7_01: fully mined (screen + train run); small-cap effect ran opposite; don't add more
- earnings_events: 2 holdouts used; NO CLEAN HOLDOUT - don't add more
- corporate_events: 1 holdout used (fail)
- insider: 2 holdouts used; bar = 3.00 (no clean period)
- analyst_ratings: search 2012-2019 (train run); live feed=NO → no more ideas
- activist_13d: search 2001-2015 (team train run); 0 holdouts; dead idea; skip adding more

## Ideas to target next run (need ~7 more to approach 10)
1. Fresh SSRN/arXiv search for 2022-2025 papers on short-horizon event studies — WebSearch
   especially: post-spinoff drift, tender offer post-announcement drift, rights offering short
2. 424B3 as supplement to seo-short: researcher should check if 424B3 shelf offering events
   from S&P 1500 are mostly common equity vs debt (if equity, add to seo-short or as variant)
3. New forms not yet explored: SC 13E-3 (going-private; too sparse ~10-20/yr S&P 1500)
4. Any fresh calendar effect not in graveyard: pre-earnings-announcement drift? (earnings_events
   family is exhausted but a pure calendar rule using daily() and earnings() might be new family)
5. FOMC-week effect: stocks that react most to Fed decisions; systematic but may need sector conditioning

## Areas/sources checked 2026-11-09
- Screen: re-read all 57 variants; confirmed all viable leads already registered or below 50 bps
- data_catalog: confirmed seo_offering and calendar_effects family status; 424B4/424B5 accessible
- Academic: Loughran & Ritter (1997), D'Mello & Ferris (2000) [SEO short]; Carhart et al. (2002),
  Duong & Meschke (2020) [quarter-end reversal]; Ryngaert (1988) [rights plan — rejected below threshold]
- WebSearch: SEC comment letter returns mixed (revenue recognition = negative, other = positive);
  M&A termination returns mixed; rights plan returns below 50 bps threshold
- fill_costs.json: confirmed close fills SP500=6.4bps, SP400=12.0bps, SP600=21.8bps RT

## Watch for next run
- Did Director queue any of today's 2 ideas?
- seo-short key risk: researcher must verify event counts (424B4+424B5 from S&P 1500); if < 50/year → power concern
- quarter-end-winner-short: effect may have attenuated post-2015; researcher should check by decade
- Need ~7 more ideas to approach target 10; consider 424B3 shelf equity, fresh SSRN search
- year-end-loser-reversal: check if still at `idea` or dropped by Director (last seen at `dropped`)
