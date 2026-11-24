# Researcher notes

## 2026-11-24 — vrp-spy-long (planned, check+smoke pass) — FIRST cboe()/ETF idea
- Family `cboe_vrp` (NEW, whole history clean). Variance-risk-premium timing on SPY. VRP = VIX −
  annualized 20-sess realized vol of SPY; z = (VRP − trailing mean)/std over zwin sessions.
- KEY DESIGN CALL: tested LONG/SHORT, NOT long-only as the card asked. Reason: SPY has no hedge
  (hedge SPY with SPY = 0) → paper metric must be real_bps = RAW SPY return → long-only "passes" on
  the equity premium (unconditional monthly t≈2.2, no signal). Long high-VRP / short low-VRP is
  beta-neutral: under the null the legs cancel, E[gross]=0, so a positive mean IS the VRP edge. Also
  the ONLY way this is promotable (long-only demeaned rule can't be expressed in real_bps). Documented
  prominently in PLAN for Skeptic/Director. Short SPY overnight = tradeable on Webull margin (20-sess
  hold, no PDT, no options).
- Entry at NEXT session's close (not signal-day close) to dodge VIX's 16:15 ET close look-ahead
  (cboe() docstring). Overlapping DAILY entries (not non-overlap monthly) so paper accrues ~1 exit/day
  — a monthly rule gives ~1 trade/month and could never reach min_days in 20-45d. cluster=month (hold
  20>10) handles overlap in research.
- COST TRAP (reuse): SPY isn't in sp500/400/600, but `universe` only sets the cost floor. `["sp500"]`
  alone FORCES pit_filter (jobs static-checks the literal) which DELETES SPY (not a member). So used
  `["sp500","sp400"]` → floor 12 bps RT (overcharges SPY ~6-12×; true ~1-2 bps). Conservative; paper
  charges SPY's real captured spread. cost_bps 2 (my est; dominated by the 12-bp floor).
- 6 variants k∈{0,.5,1}×zwin∈{126,252}; CHOSEN pre-registered = k0_z126 (median split, 6-mo window;
  252 needs 272 sessions but paper download is only ~275 cal days ≈275 sess → 126 is the safe choice).
  strategy.py mirrors k0_z126. Not best-of-train; others are robustness.
- Windows train 2000-2013 / holdout 2014-2026-10-31. ratio≈0.92 → exp holdout t≈train t×0.96; need
  train t≥~2.43 to clear the underpower gate. Expect holdout death even on a good train (winner's
  curse). Adjacency risk DISCLOSED: pre-team "VIX timing" died on 2018-26 holdout; VRP≠VIX-level and
  cboe_vrp is new, but my holdout overlaps 2018-26 — false-PASS risk flagged for Skeptic.
- Smoke (2000): k0_z126 252 trades/12 periods, scales down with k and up-warm-up with zwin. Good.

## 2026-11-20 — antitakeover-adoption-short (planned, check+smoke pass)
- research/antitakeover-adoption-short/ + strategies/. Family `8k_5_03` (used only 2005-2013 screen, 3
  variants → 2014+ clean). SHORT an 8-K item 5.03 that ADOPTS a stockholder rights plan / poison pill
  (Ryngaert 1988 ~-150 bps CAR; Gompers-Ishii-Metrick G-index underperformance → post-announce drift).
  Day-0 close entry (entry_session), hold 15, hedged per index, month cluster. Reused special-div
  skeleton (text filter) + material-impairment SHORT sign `(hedge_ret - stock_ret)*1e4`.
- FROZEN filter = require BOTH PILL_RE (`rights (plan|agreement)|poison pill`) AND ADOPT_RE
  (`\badopt | enter(ed) into | declar… dividend`). The declare-a-dividend-of-rights arm is ESSENTIAL —
  the canonical pill PR is "declared a dividend of one preferred share purchase right", NOT "adopted".
  A tight adopt-adjacency regex I tried first MISSED it (2 vs 18 sp1500 events in smoke 2005) — fixed at
  pre-reg (counts only, no perf). NO negative keyword list: terminat/expir/amend/redeem all appear in
  genuine adoptions (5.03 = bylaw amendment; adoptions describe expiry/termination/redemption provisions).
  Positive-indicator design keeps out terminations; residual amendment/termination contamination is
  CONSERVATIVE for a short (amend ~neutral, terminate bullish → both worsen the measured short).
- Windows: train 2005-2013 (REUSED screen window, has 2008-09 pill wave), holdout 2014-2026-10-24 CLEAN
  (has 2020 COVID crisis-pill wave). ratio ≈1.42 (good power). 5.03 item codes exist from 2004-08.
- 6 variants CONFIGS name→(entry_mode,univ,hold): e0_sp1500_h15 CHOSEN; h10/h5 horizon; midsmall; sp500
  PIT; e1 (a session late). Smoke 2005: sp1500 18, midsmall 9, sp500 5 — sp1500 ample, sub-cuts thinner.
- CENTRAL risk for Skeptic/Director: most of the -150 is priced by day-0 close (we short AFTER the
  intraday drop) → betting on ~50-80 bps residual; if ≤ cost dies at train. e0-vs-e1 + h5/h10/h15 are the
  reads. Survivorship AMBIGUOUS for this short (down-leavers absent=conservative; acquired-up leavers
  absent=too-favorable) → prefer sp500-PIT read. Borrow NOT priced by real_hedged_bps (Director checks).
- PROMOTABLE day-0 SHORT (edgar_live built). strategy.py mirrors PILL+ADOPT; metric real_hedged_bps
  (runner hedges SPY only — research per-index; noted). pass_mean_bps 30, t 2.0.

## 2026-11-20 — buyback-announcement-long (planned, check+smoke pass)
- Family `8k_8_01`. LONG 8-K 8.01 open-market SHARE REPURCHASE authorization (Peyer-Vermaelen 2009).
  FROZEN filter strips `repurchase agreements?` THEN requires BUYBACK_RE (tighter than card's bare
  "repurchase"). Train 2014-2019 (reused special-div), holdout 2020-2026-10-24 clean. Day-0 close, hold
  20, month cluster. 5 variants; chosen all_sp1500_h20. Risk: 30yr-published large-cap effect → decay;
  day-0 close is after the pop. metric real_hedged_bps, pass 30/t2.0.

## 2026-11-17 — special-dividend-drift-long (the TEXT-filter skeleton; check+smoke pass)
- Family `8k_8_01`. LONG 8-K 8.01 matching FROZEN special-div regex. First idea using rd.filing_text to
  SPLIT an event by what it says. Day-0 close, hold 20, hedged per index, month cluster. Train 2014-2019
  / holdout 2020-2026-10-24 (chosen for power: ratio ≈1.14; longer train would LOWER ratio). chosen
  all_sp1500_h20. strategy.py: edgar_live.filings_asof + text_asof, archive-text fallback for post-cutoff
  prior-session accessions. NO cross-filing dedup (research==paper). metric real_hedged_bps, 30/t2.0.

## 2026-11-17 — activist-13d-long-day0 (check+smoke pass)
- Family `activist_13d` (train 2001-2015 reused from dead activist-13d-long; holdout 2016-2026 clean).
  Day-0 re-proposal per audit: ONLY change vs dead idea = enter at CLOSE of entry_session (day 0) not
  the close after first_session. LONG initial SCHEDULE 13D on TARGET; filter form_std=="SC 13D" (NOT raw
  — raw missed every post-2024 "SCHEDULE 13D"). chosen e0_sp1500_h3. e0-vs-e1 is the direct read; if
  e0_h1≈0 the premium is intraday-only. PROMOTABLE day-0. metric real_hedged_bps.

## 2026-11-14 — material-impairment-short (the SHORT skeleton; check+smoke pass)
- Family `8k_2_06` (SHORT; holdout 2014-2026 clean, 2005-2013 screen was LONG only). SHORT 8-K item 2.06
  (goodwill/asset impairment). chosen e0_sp1500_h3: short at CLOSE of entry_session, cover close+3. 9
  variants incl drop (short only if day-0 reaction<0) + noearn (exclude co-filed 2.02). cluster week,
  hold 5, cost 25, metric hedged, univ sp500/sp400/sp600. sp500 uses pit_filter. Survivorship HELPS a
  short (worst delisted → absent = conservative). strategy.py was e1 best-effort marked DO-NOT-PROMOTE
  (day-0 feed not built THEN — now it IS, 2026-11-14). Hedged SHORT gross = (hedge_ret - stock_ret)*1e4.

## Earlier planned ideas (one line each)
- proxy-contest-long: `proxy_contest`. LONG DFAN14A+DEFC14A (dissident, 14A subject-indexed→target). First-
  in-campaign dedup (>90 quiet days). ~3-8/yr early → slow paper. Train 2001-2015 / holdout 2016-2026.
- issuer-self-tender-long: `self_tender`. LONG initial SC TO-I (raw form, drops /A). ~17/yr → slow paper.
- pre-earnings-premium: `pre_earnings`. LONG close A-2 → exit close A-1 (FLAT before number). sp500-only.
  Uses rd.earnings (not filings); risk = scheduling look-ahead (Yahoo estimated dates shift).
- seo-short: `seo_offering`. SHORT 424B4/424B5. close of first_session+1. b4 also IPO form + no PIT → leak.
- activist-13d-long (DIED 11-07): raw form=="SC 13D" missed post-2024 initials.
- restructuring-bounce: `8k_2_05`. LONG 8-K 2.05, OPEN+2 entry.
- analyst-initiation-buy: analyst_ratings. NOT PROMOTABLE (ratings = one-time yfinance snapshot).

## Data facts learned (reuse)
- filings(forms,items,tickers) cols: ticker cik form filing_date accepted items accession primary_doc
  description first_session entry_session. items = comma-sep 8-K codes. forms match /A too. 8-K item
  codes from 2004-08. first_session = first OPEN after public; entry_session = first session whose CLOSE
  is still buyable (SEC accepted before 15:30 ET that day, else next). Use entry_session for DAY-0 close.
- filing_text(df) adds text + exhibit + has_text. 5.03 coverage 5849/11300 ≈52%; 8.01 83802; 2.06 447.
  has_text False = not downloaded (skip). Split an event by WHAT it says via a FROZEN regex on
  text.fillna("")+" "+exhibit.fillna(""). Freeze the regex at pre-reg; a tuned keyword list = a variant.
- Hedge per index: rd.index_of(tickers)→{tkr:'sp500'|'sp400'|'sp600'}; rd.hedge_ticker(ix)→SPY/IJH/IJR.
  Load funds in rd.daily(syms+["SPY","IJH","IJR"]). Hedged SHORT gross=(hedge_ret-stock_ret)*1e4;
  LONG=(stock_ret-hedge_ret)*1e4.
- pit_filter(df,date_col,ticker_col="ticker"): keeps rows whose ticker was a real S&P 500 member on
  date_col. REQUIRED whenever code calls universe("sp500") OR plan universe==["sp500"] (jobs static-
  checks for literal "pit_filter(" in test.py). Only sp500 has a PIT list; sp400/sp600/'all' don't.
- rd.daily archive cols LOWERCASE open/high/low/close/volume; SPY/IJH/IJR present. Index may not be
  normalized → normalize both sides + positional iloc, don't trust label equality.
- rd.splits(None): ticker ex_date ratio(>1 fwd,<1 rev) announced announce_form announce_accession
  found_by first_session entry_session. ~812 of 3189 fwd splits have an announcement.
- rd.earnings(tickers)→dict ticker→df col "Earnings Date" (tz-aware UTC); normalize to ET date, require
  a real SPY session. rd.ratings → one-time yfinance snapshot, NOT live. rd.fomc() → FOMC dates.
- Insider parquet NOT paper-promotable (SEC quarterly bulk, months lag).
- Paper runner auto-adds SPY, builds sessions from bars["SPY"].index, computes the hedge itself (SPY
  only) — strategy.py only needs SPY for the calendar. bars indexed by datetime.date. strategy.py (NOT
  static-scanned) may read data/edgar/*.parquet via parents[2]/data/edgar.
- jobs.py FORBIDDEN scans test.py ONLY: \byfinance\b requests urllib http subprocess os.environ
  read_parquet read_csv \bopen\( StockAnalysis Path( eval( exec( importlib pickle shutil. Column string
  "open" (no paren) is fine.

## Resolved — don't repeat
- Pre-register `chosen` deterministically (explicit CONFIGS dict, no name parsing) so strategy.py matches
  without a train-time pick. Smoke prints "chosen None" — a harness quirk (res['chosen'] only set when
  phase=='train'/'holdout'), NOT a bug.
- Reusing a prior SEARCH/train window is allowed; only the HOLDOUT must be a period the family never used.
- Entering the close AFTER first_session = a day late (audit's #1 cause of 0/14). Use entry_session for
  day-0. Day-0 paper IS built (2026-11-14: edgar_live + run_day0 + same_close) → day-0 ideas promotable.
- Day-0 close entry means we buy/short AFTER the intraday announcement move → design for the RESIDUAL
  drift, not the full CAR; make e0-vs-e1 a variant to show the entry timing earns its keep.
