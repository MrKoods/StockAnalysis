# Scout notes (max ~150 lines)

## Last run: 2026-11-10
- Run reason: scouting (0 ideas waiting, target 10)
- Ideas at start: 0 at `idea` stage (yesterday's 3 were all processed: seo-short dead, late-10k-short dropped, quarter-end-winner-short dropped)
- Added 2 new ideas: pre-earnings-premium (pre_earnings), issuer-self-tender-long (self_tender)
- Total at `idea` stage after run: 2 (need 8 more to approach 10)

## Current ideas at `idea` stage (as of 2026-11-10)
1. pre-earnings-premium — pre_earnings, 1d (LONG; close-2 to close-1; Laarits 2020 SSRN, Ai et al. 2021; 6000 events/yr)
2. issuer-self-tender-long — self_tender, 3d (LONG; SC TO-I; Peyer & Vermaelen 2009; ~20-50/yr; needs SC TO-I verification)

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
- 4.02 restatement: t=-1.13 (5d); gross -51.4 bps; barely meets 50 bps but t too low + only 25/yr + screen period contaminated; skip
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
- proxy contest (DFAN14A): ~15-25 events/year in S&P 1500; too sparse; mixed signal
- SEO via 424B3: may supplement seo-short; but seo-short is now DEAD; leave alone
- FOMC pre-announcement drift: "80%+ of equity premium earned in 24hr before FOMC" (Lucca & Moench
  2015); mechanism strong; needs FOMC meeting dates from federalreserve.gov (8/yr, free, fixed calendar)
  → user decides if worth adding as a small static file in research_data.py
- IPO lockup expiration short: needs IPO lockup expiration dates
- Buyback announcement LONG (via 8-K 8.01 text filter): needs text parsing; 8.01 near-zero without filter
- After-hours earnings release short (8k_2_02 subset, acceptance_time >4PM): Doyle & Magilke (2009)
  shows 100 bps spread early vs late filers BUT close+1 entry means most day-0 reaction is priced;
  residual drift to close+3 may be only 20-30 bps (below 50 bps gross); borderline; skip for now

## Calendar effects family status
- turn-of-month: DEAD (train t=1.37)
- quarter-end-window-dressing: DROPPED (not tested)
- year-end-loser-reversal: at `dropped` (Director dropped; not in `idea` queue any more)
- quarter-end-winner-short: at `dropped` (Director dropped; Carhart 2002)
- train period 1999-2014 used by turn-of-month; holdout 2015-2026 clean
- Family bar = 3.0
- NOTE: Director has dropped 3+ calendar variants without testing; next calendar idea needs very strong direct
  academic evidence with specific bps number before proposing

## New family seo_offering status
- seo-short: DEAD (train t=-5.92; SHORT was -36 bps after cost; LONG was +36 bps but that's below 50 bps gross; skip)
- Entirely mined — don't add more seo_offering ideas

## New family pre_earnings status
- pre-earnings-premium: at `idea` (LONG close-2 to close-1; Laarits 2020; Ai et al. 2021)
- Family entirely clean (no screen, no prior search, no holdout)
- Family bar = 3.0

## New family self_tender status
- issuer-self-tender-long: at `idea` (LONG SC TO-I filing; Peyer & Vermaelen 2009)
- Family entirely clean; researcher must verify SC TO-I in filings()
- Family bar = 3.0

## Budget state (2026-11-10)
- pre_earnings: new family, entirely clean
- self_tender: new family, entirely clean
- seo_offering: search 2001-2015 (team train run); MINED — no more ideas
- calendar_effects: search 1999-2014 (team train run); holdout 2015-2026 clean; Director dropped 3 variants
- 10k_timing: entirely clean; late-10k-short + early-10k-drift both dropped; needs fresh angle
- 10q_timing: search 2001-2015 (team train run); early-10q-drift DEAD; nt-filing-short DEAD; skip
- earnings_events: 2 holdouts used; NO CLEAN HOLDOUT - don't add more
- 8k_X_XX families: ALL screen (2005-2013) used; all viable screen leads registered and failed
- activist_13d: search 2001-2015 (team train run); dead
- analyst_ratings: search 2012-2019 (team train run); live feed=NO

## Ideas to target next run (need ~8 more)
1. FOMC pre-announcement: strong evidence (80%+ equity premium, Lucca & Moench 2015); only needs
   8 dates/year as a small lookup table — worth asking user if researcher can hardcode a calendar
2. 10k_timing fresh angle: entirely clean family; late-10k-short dropped but family unused; think
   of a genuinely different variant (not conditional on earnings — event count too low)
3. Fresh SSRN search for 2024-2025 papers on event-driven anomalies not in catalog/graveyard
4. After-hours earnings short: revisit if evidence for close+1→close+3 drift >50 bps is found
5. Any large-volume, high-gross 8-K event type not yet in graveyard (but all screen leads exhausted)
