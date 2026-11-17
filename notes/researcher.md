# Researcher notes

## 2026-11-17 — special-dividend-drift-long (planned, check+smoke pass)
- research/special-dividend-drift-long/ + strategies/. Family `8k_8_01` (used only 2005-2013 screen →
  2014+ clean). LONG an 8-K item 8.01 whose TEXT matches a FROZEN special-div regex
  `special\s+(?:cash\s+|one[-\s]?time\s+|year[-\s]?end\s+)?dividend` (case-insens, body+exhibit). First
  idea using rd.filing_text to SPLIT an event by what it says. Ahn 2024 ~120 bps over days +2..+20.
- Day-0 close entry (entry_session), hold 20, hedged per index. 5 variants CONFIGS dict
  name→(entry_mode,univ,hold); chosen PRE-REG `all_sp1500_h20`. midsmall + sp500(PIT) + h10 + e1 robustness.
- WINDOWS CHOSEN FOR POWER (deviates from card's 2014-20/21-26): train 2014-2019, holdout 2020-2026-10-24
  → holdout/train ≈1.14 (a LONGER train would LOWER the ratio and hurt expected holdout t). 2012 fiscal-
  cliff surge excluded from both; COVID+post-COVID in holdout (conservative). cluster MONTH (hold>10).
- Smoke 2014 (low-special year): all_sp1500 24 trades, midsmall 17, sp500 6 — regex NOT catching junk.
  Over 6y ≈150-200 events/72 month-clusters. Power is train-t-dependent; harness buries if <25%.
- PROMOTABLE day-0 (edgar_live built). strategy.py: edgar_live.filings_asof + text_asof for today's
  8.01 text; falls back to archive text parts (data/edgar/text) for the rare prior-session-after-cutoff
  accession. NO cross-filing dedup (only ticker/day) so research==paper; reminder 8-Ks dilute = conservative.
  metric real_hedged_bps (runner hedges SPY only — research per-index; noted). pass_mean_bps 30, t 2.0.

## 2026-11-17 — activist-13d-long-day0 (planned, check+smoke pass)
- research/activist-13d-long-day0/ + strategies/. Family `activist_13d` (train 2001-2015 REUSED from the dead
  activist-13d-long; holdout 2016-2026 CLEAN — the dead idea auto-died at train). Day-0 re-proposal per the audit:
  ONLY change vs the dead idea = enter at the CLOSE of entry_session (day 0) instead of the close AFTER
  first_session. Everything else mirrors it (week cluster, cost 25, universe sp1500+sp500 PIT) for a clean e0-vs-e1
  comparison; family's prior 6 variants count in the luck bar automatically.
- LONG initial Schedule 13D on the TARGET (13D is SUBJECT-indexed). INITIAL filter = `form.map(rd.form_std)=="SC
  13D"` — NOT the raw form (the dead idea used raw `=="SC 13D"` and missed EVERY post-2024 initial, now named
  "SCHEDULE 13D"; TEAM.md). form_std maps SCHEDULE 13D→SC 13D, SCHEDULE 13D/A→SC 13D/A, so ==SC 13D = initial only.
- 5 variants CONFIGS dict name→(entry_mode,univ,hold): e0=entry_session close, e1=first_session+1 close (=dead
  idea, should be ~0). chosen PRE-REG `e0_sp1500_h3`. Per-index hedge (SPY/IJH/IJR). Smoke: e0_sp1500 170 trades/yr,
  sp500 66 — ample power.
- CENTRAL risk for Skeptic/Director: the audit's +51 bps t 5.6 is RAW/un-hedged/un-clustered full-sample; the day-0
  move happened DURING the session, before the close we buy at — so even the day-0-close entry may capture only the
  residual next-day drift (same ~0 the dead idea found). e0_h1 vs e1_h3 is the direct test; if e0_h1≈0 the premium
  is intraday-only and untradeable at any close.
- PROMOTABLE now (unlike material-impairment's note): day-0 paper IS built (same_close + run_day0 + edgar_live).
  strategy.py uses entry_at "same_close", imports edgar_live, replicates _entry_session (signal when an initial
  13D's entry_session==today). metric real_hedged_bps (runner hedges vs SPY only — research is per-index; noted).

## 2026-11-14 — material-impairment-short (planned, check+smoke pass)
- Five files in research/material-impairment-short/ + strategies/. Family `8k_2_06` (SHORT + holdout 2014-2026
  clean; the 2005-2013 screen used only the LONG direction, 3 search variants booked → luck counts 9+3=12, t~2.23).
  Reused seo-short skeleton (SEC-filing SHORT close→close hedged); swapped 424B filter for filings(forms=["8-K"],
  items=["2.06"]); added day-0 entry + per-index hedge + drop/noearn diagnostics.
- Signal: 8-K item 2.06 (goodwill/asset impairment). SHORT. chosen PRE-REGISTERED = `e0_sp1500_h3`: enter at the
  CLOSE of `entry_session` (DAY 0 — the audit fix; drift wanted is +1..+3 after that close), cover close+3.
- 9 variants, explicit CONFIGS dict name→(entry_mode,univ,hold,flag). e0=entry_session close; e1=session after
  first_session close (what the after-close paper runner can actually fill). flags: drop=short only if day-0
  reaction<0 (materiality); noearn=exclude 2.06 co-filed with item 2.02 (earnings-miss confound, card risk #1).
- Train 2004-09-01..2013-12-31 (item codes from 2004-08), holdout 2014-01-01..2026-10-24. cluster week, hold_days 5,
  cost 25 (sp600 close floor 22 + impact), metric hedged, universe ["sp500","sp400","sp600"].
- sp500 variant uses rd.pit_filter(ev,"entry_session") (REQUIRED — _universes() calls universe("sp500") which
  triggers the pit static check). sp1500/sp46 no PIT list: current-membership bias HELPS a short (worst impairments
  delisted → absent) so a pass is conservative — opposite of the LONG ideas.
- Smoke (2004-09..2005-09): e0_sp1500_h3 68 trades/37wk, sp500 32, sp46 31 — ample power.
- CENTRAL read for Skeptic/Director: e0 vs e1. If e1≈0 but e0 strong → edge REAL but UNTRADEABLE today (day-0
  close needs the intraday EDGAR feed ~12:45 PT, NOT built; Director requests it on a holdout pass). strategy.py is
  the e1 best-effort short, marked DO NOT PROMOTE AS-IS (gate must not treat e1 paper as the e0 chosen edge).
- Other risks: (1) survivorship (above, conservative for a short); (2) noearn collapse = it's the earnings miss not
  the impairment; (3) borrow — real_hedged_bps prices spread not borrow, Director confirms before real money.

## 2026-11-12 — proxy-contest-long (planned, check+smoke pass)
- research/proxy-contest-long/ + strategies/. Family `proxy_contest` (NEW clean). LONG on dissident proxy material:
  DFAN14A (non-mgmt additional = opening shot) + DEFC14A (definitive contested). NOT DEFA14A (that's MANAGEMENT's).
  14A is SUBJECT-indexed → filings(tickers=sp1500) returns the TARGET directly (smoke confirms DFAN14A counts).
- CAMPAIGN DEDUP (reusable): dissidents file many DFAN14A; _first_in_campaign keeps only the FIRST per ticker, a new
  event only after >90 quiet days. strategy.py mirrors it. chosen PRE-REG = `dfan_sp46_h3`. SC 14N excluded (Rule
  14a-11 vacated 2011 → empty variant would raise the luck bar). Earnings-exclusion filter omitted (conservative).
- Train 2001-2015, holdout 2016-2026-10-24, cluster week, cost 25, metric hedged. POWER WATCH: ~3-8 trades/yr early
  EDGAR → slow paper (~10-12 mo to 20 scored). Same small/mid-cap LONG inversion that killed activist-13d etc.

## 2026-11-11 — issuer-self-tender-long (planned, check+smoke pass)
- research/issuer-self-tender-long/ + strategies/. Family `self_tender` (NEW clean). LONG on INITIAL SC TO-I (issuer
  buys own shares at premium; Peyer-Vermaelen 2009). filter raw form=="SC TO-I" (drops /A). FILER=issuer so
  filings(tickers=sp1500) returns the right names. close of first_session+1, exit close+H. chosen `sp1500_h3`.
  Train 2001-2015, holdout 2016-2026. ~17/yr sp1500 → PAPER SLOW (~14 mo to 20 scored).

## 2026-11-11 — pre-earnings-premium (planned, check+smoke pass)
- research/pre-earnings-premium/ + strategies/. Family `pre_earnings` (NEW). First idea using rd.earnings (not
  filings). LONG close A-2 → exit close A-1 (hold 1, FLAT before the number = zero surprise risk). Distinct from V4
  EPRE (holds THROUGH). SP500-ONLY deliberate (one cost floor = worst index; a 1-day premium can't pay sp400/sp600).
  chosen `h1_sp500`. cluster "day". CENTRAL RISK: scheduling look-ahead (entering A-2 assumes date A known 2 sessions
  ahead; some Yahoo dates "estimated"/shift). strategy.py reads V4's nightly earnings_calendar.csv.
- rd.earnings(tickers)→dict ticker→df, col "Earnings Date" (tz-aware UTC). Normalize to ET date, require a real SPY
  session (searchsorted SPY calendar), dedupe per ticker.

## 2026-11-09 — seo-short (planned; the reusable SHORT skeleton)
- Family `seo_offering`. SHORT on 424B4/424B5 (SEO pricing disclosure). close of first_session+1, cover close+H,
  SPY-hedged. chosen `both_sp1500_h3`. Train 2001-2015, holdout 2016-2026. b4 is also the IPO form + no PIT → leak
  risk. material-impairment-short reused this skeleton.

## Earlier planned ideas (one line each)
- activist-13d-long (DIED 11-07): `activist_13d`. LONG initial SC 13D (raw=="SC 13D"), 13D SUBJECT-indexed → target.
- early-10q-drift (planned): `10q_timing`. LONG 10-Q filed ≥N cal days earlier than prior-yr. OPEN entry.
- restructuring-bounce (planned): `8k_2_05`. LONG 8-K item 2.05, OPEN+2 entry (enter open of session AFTER
  first_session). strategy emits when first_session==today → runner enters next open. paper_runner exit_at="open"+
  hold>0 uses SPY open for the hedge exit too (advance():159) — matches research open→open hedge.
- analyst-initiation-buy (planned): analyst_ratings. NOT PROMOTABLE (ratings = one-time yfinance snapshot, no feed).

## Data facts learned (reuse)
- filings(forms,items,tickers) cols: ticker cik form filing_date accepted items accession primary_doc description
  first_session entry_session. items = comma-separated 8-K codes. forms match /A too (8-K matches 8-K/A).
  first_session = first OPEN after public; entry_session (2026-11-13) = first session whose CLOSE is still buyable
  (SEC accepted before 15:30 ET that day, else next). Use entry_session for DAY-0 close entry.
- Hedge per index: rd.index_of(tickers)→{tkr:'sp500'|'sp400'|'sp600'} (largest index it's in); rd.hedge_ticker(ix)
  →SPY/IJH/IJR. Load the funds in rd.daily(syms+["SPY","IJH","IJR"]). Hedged SHORT close→close gross =
  (hedge_ret - stock_ret)*1e4.
- pit_filter(df,date_col,ticker_col="ticker"): keeps rows whose ticker was a real S&P 500 member on date_col.
  REQUIRED whenever code calls universe("sp500") OR plan universe==["sp500"] (jobs.pit_problems static-checks for
  the literal "pit_filter(" in test.py). Only sp500 has a PIT list; sp400/sp600/'all' don't.
- rd.daily archive cols LOWERCASE open/high/low/close/volume; SPY/IJH/IJR present. rd.daily index may not be exactly
  normalized → normalize both sides + positional iloc, don't trust label equality.
- rd.splits(None) cols: ticker ex_date ratio(>1 fwd,<1 rev) announced announce_form announce_accession found_by
  first_session entry_session (NaT if no announcement). ~812 of 3189 fwd splits have an announcement.
- rd.ratings(tickers)→dict ticker→df: GradeDate(date-only), Firm, ToGrade, FromGrade, Action(up/down/main/init/reit).
  Archive = one-time yfinance snapshot, NOT live-updatable.
- Insider parquet: ACCESSION_NUMBER TRANS_DATE TRANS_CODE(P/S) TRANS_SHARES TRANS_PRICEPERSHARE
  TRANS_ACQUIRED_DISP_CD(A/D) FILING_DATE(%d-%b-%Y) ISSUERTRADINGSYMBOL DOCUMENT_TYPE RPTOWNERCIK
  RPTOWNER_RELATIONSHIP RPTOWNER_TITLE. Source = SEC quarterly bulk (months lag) → NOT paper-promotable.
- Paper runner auto-adds SPY (paper_runner:51), builds sessions from bars["SPY"].index (:244), computes the hedge
  itself — strategy.py only needs SPY for the session calendar. bars indexed by datetime.date, not Timestamp.
  strategy.py (NOT static-scanned) reads data/edgar/*.parquet via parents[2]/data/edgar.
- jobs.py FORBIDDEN scans test.py ONLY: \byfinance\b requests urllib http subprocess os.environ read_parquet
  read_csv \bopen\( StockAnalysis Path( eval( exec( importlib pickle shutil. Column string "open" (no paren) is fine.

## Resolved — don't repeat
- Pre-register `chosen` deterministically (explicit CONFIGS dict, no name parsing) so strategy.py can match without
  a train-time pick. Smoke prints "chosen None" — harness quirk (res['chosen'] only set when phase=='train'/
  'holdout'), NOT a bug.
- Reusing a prior SEARCH/train window is allowed; only the HOLDOUT must be a period the family never used.
- Entering the close AFTER first_session = a day late (the 2026-11-13 audit's #1 cause of 0/14 survivors). Use
  entry_session for day-0. Trade-off: day-0 close is NOT reachable by the after-close dispatch → such a strategy is
  research-only until the intraday EDGAR feed is built (Director's call on a holdout pass).
