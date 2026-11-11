# Scout notes (max ~150 lines)

## Last run: 2026-11-11
- Run reason: scouting (2 ideas waiting, target 10)
- Ideas at start: 2 (pre-earnings-premium, issuer-self-tender-long)
- Added 3 new ideas: pre-earnings-beat-streak (pre_earnings), proxy-contest-long (proxy_contest), earnings-announcement-risk-premium (announcement_premium)
- Total at `idea` stage after run: 5 (need 5 more to approach 10)

## Current ideas at `idea` stage (as of 2026-11-11)
1. pre-earnings-premium — pre_earnings, 1d (LONG; close-2 to close-1; Laarits 2020 SSRN 3660814; ~8000/yr)
2. issuer-self-tender-long — self_tender, 3d (LONG; SC TO-I; Peyer & Vermaelen 2009; ~20-50/yr; needs SC TO-I verification)
3. pre-earnings-beat-streak — pre_earnings, 1d (LONG; close-2→close-1, conditional on 4+ consecutive EPS beats; Laarits 2020 + Gao/Hu/Zhang 2020 SSRN 3595953; ~3000-5000/yr)
4. proxy-contest-long — proxy_contest, 3d (LONG; DFAN14A filing; Fos 2017 SSRN 1705707; 6.5% event-window; ~20-25/yr S&P 400+600; sparse risk)
5. earnings-announcement-risk-premium — announcement_premium, 1d (LONG; close-1→close; Savor & Wilson 2016 JFE ~200 bps; Frazzini & Lamont 2007 JFE; ~8000-10000/yr)

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
  → researcher could hardcode the calendar directly in a small lookup table in research_data.py;
  NO API needed; just 8 dates/year publicly available; strongly worth adding
- special dividend announcement LONG: Hyun Ahn (SSRN 7249419) "The Special-Dividend Drift" finds
  ~1.2% abnormal return over days +2→+20 post-announcement; needs special dividend announcement
  identification from 8-K text (8.01 or press release) → needs text parsing or a dividend calendar
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
- pre-earnings-beat-streak: at `idea` (LONG close-2 to close-1, 4+ consecutive beat filter; Laarits 2020 + Gao et al. 2020)
- Family entirely clean (no screen, no prior search, no holdout)
- Family bar = 3.0

## New family self_tender status
- issuer-self-tender-long: at `idea` (LONG SC TO-I filing; Peyer & Vermaelen 2009)
- Family entirely clean; researcher must verify SC TO-I in filings()
- Family bar = 3.0

## New family proxy_contest status
- proxy-contest-long: at `idea` (LONG DFAN14A filing for S&P 400+600; Fos 2017)
- Family entirely clean; researcher must verify DFAN14A count in filings() (~20-25/yr estimate)
- Sparsity risk: if fewer than ~15/yr in S&P 400+600, holdout may be underpowered
- Family bar = 3.0

## New family announcement_premium status
- earnings-announcement-risk-premium: at `idea` (LONG close-1→close; Savor & Wilson 2016 ~200 bps)
- Family entirely clean; not related to earnings_events (different mechanism: systematic risk premium, not drift)
- Family bar = 3.0

## Budget state (2026-11-11)
- pre_earnings: new family, entirely clean (2 ideas registered)
- self_tender: new family, entirely clean (1 idea registered)
- proxy_contest: new family, entirely clean (1 idea registered; event count unverified)
- announcement_premium: new family, entirely clean (1 idea registered)
- seo_offering: search 2001-2015 (team train run); MINED — no more ideas
- calendar_effects: search 1999-2014 (team train run); holdout 2015-2026 clean; Director dropped 3 variants
- 10k_timing: entirely clean; late-10k-short + early-10k-drift both dropped; NO fresh angle found
- 10q_timing: search 2001-2015 (team train run); early-10q-drift DEAD; nt-filing-short DEAD; skip
- earnings_events: 2 holdouts used; NO CLEAN HOLDOUT - don't add more
- 8k_X_XX families: ALL screen (2005-2013) used; all viable screen leads registered and failed
- activist_13d: search 2001-2015 (team train run); dead
- analyst_ratings: search 2012-2019 (team train run); live feed=NO

## Ideas to target next run (need ~5 more)
1. FOMC pre-announcement: strong evidence (80%+ equity premium, Lucca & Moench 2015); only needs
   8 dates/year as a small lookup table — advocate to user/Director that researcher can hardcode
   the calendar directly in research_data.py (federalreserve.gov, completely free, no API needed)
2. Special dividend drift: Hyun Ahn (SSRN 7249419) finds 1.2% abnormal return over days +2→+20
   after special dividend announcement; needs special dividend announcement identification (8-K 8.01
   text parsing or separate calendar) → currently in Needs Data
3. After-hours earnings short: Doyle & Magilke (2009); revisit only if evidence for first 3 days
   post-announcement is specifically >50 bps; current evidence suggests only 20-30 bps residual
4. 10k_timing fresh angle: family still entirely clean; no viable academic angle found in 2026-11-11
   search; defer until a specific paper with >=50 bps short-horizon effect is found
5. SC TO-T target drift: when acquirer files SC TO-T, the target has residual drift post-filing;
   needs 14D-9 form count in filings() to be verified; likely sparse (~30-50/yr for S&P 1500 targets)
