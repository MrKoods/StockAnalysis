# Researcher notes

## 2026-11-11 — pre-earnings-premium (planned, check+smoke pass)
- Five files in research/pre-earnings-premium/ + strategies/pre-earnings-premium/. Family `pre_earnings`
  (NEW, whole history clean). LONG idea. EARNINGS-based (first team idea using rd.earnings, not filings).
- Mechanism: pre-announcement RISK PREMIUM (Laarits 2020; Ai-Bansal-Han 2021: 72% of earnings-period
  excess return accrues BEFORE release). LONG close A-2 -> exit close A-1 (hold 1), flat before the
  number => ZERO surprise risk. Distinct from V4 EPRE (holds THROUGH the announcement).
- Train 2003-01-01..2015-12-31, holdout 2016-01-01..2026-10-24 (recent arbitraged/post-publication era
  = the decay test; earnings data ends 2026-11-02, daily 2026-11-06, buffer ok). cluster "day" (earnings
  cluster into seasons -> many names share an exit date). metric hedged (firm-specific; staggered dates).
- SP500 ONLY, deliberate: plan has ONE cost floor = worst index; close RT ~6.4(sp500)/12(sp400)/22(sp600);
  a ~1-day premium can't survive sp400/sp600, and adding them over-charges every sp500 trade. cost_bps 8
  (floor 6.4 + impact). "too small for sp4/6 costs" is a documented outcome, not an untested gap.
- 4 variants: h1_sp500 (chosen, PRE-REGISTERED), h2_sp500 (hold 2 = close A-3->A-1), h1_mom_sp500 (prior
  5-sess ret>0), h1_raw_sp500 (unhedged diagnostic). luck_t~1.67. chosen NOT best-t. Reads (not switches):
  raw>>hedged => market beta not firm premium; h2>>h1 => edge not in final 24h; mom>>h1 => momentum.
- Smoke (2003): h1 1270 trades/176 day-clusters, mom 651/143 — ample power.
- KEY DATA FACT: rd.earnings(tickers) -> dict ticker->df, col "Earnings Date" (tz-aware UTC). Normalize to
  ET date, require it be a real SPY session (searchsorted on SPY calendar), dedupe per ticker. Built the
  session calendar from SPY daily index (close->close hedge uses spy close by session). df["close"] lower.
- CENTRAL RISK for Skeptic: scheduling LOOK-AHEAD — entering A-2 assumes date A was known 2 sessions
  ahead; usually confirmed but some Yahoo dates are "estimated" and shift; no flag in data => cannot fully
  remove in backtest (paper is leak-free: live calendar only shows scheduled date). Also survivorship
  (current sp500 only) biases a LONG UP — a pass is NOT conservative there.
- PROMOTABLE: strategy.py reads V4's nightly earnings_calendar.csv (data/calendar/, same feed EPRE trades;
  cols ticker,index,report_day,minute,time_source,bmo,refreshed), emits LONG when report_day == 3rd NYSE
  session after asof -> runner enters close(asof+1)=A-2, hold 1, exit close A-1. Future sessions counted on
  a self-contained NYSE calendar (reused turn-of-month's _easter/_nth_weekday/_nyse_holidays). spec
  entry_at=close, exit_at=close, hold_sessions=1, metric real_hedged_bps, pass 5 bps/t 2.0, 20-40 days,
  max_signals_per_day 25 (peak earnings days under-sampled; clerk can't quote more).

## 2026-11-09 — seo-short (planned, check+smoke pass)
- Five files in research/seo-short/ + strategies/seo-short/. Family `seo_offering` (NEW, whole history clean).
  Bar via budget (floor 3.0). SHORT idea. Reused pipe-short skeleton (SEC-filing SHORT close→close hedged),
  swapped 8-K item-3.02 filter for forms=["424B4","424B5"], dropped the ex-event map.
- Train 2001-01-01..2015-12-31, holdout 2016-01-01..2026-10-24 (recent arbitraged era; daily ends 11-06,
  buffer for close+5 exit). cluster "week". cost 25 (sp600 close floor ~22 + impact). metric hedged.
- Signal: 424B4 (final prospectus) / 424B5 (shelf supplement) = SEO pricing-day disclosure. SHORT at CLOSE of
  session AFTER first_session (entry_pos=pos+1), cover CLOSE +H. 424B ticker = ISSUER (own prospectus), unlike
  13D — so filings(tickers=sp1500) returns the right names directly.
- 12 variants: form {b4,b5,both} × univ {sp1500, sp46} × hold {3,5}. chosen PRE-REGISTERED = `both_sp1500_h3`
  (idea card primary). luck_t~2.23. names `<form>_<univ>_h<H>`, parsed name.split("_").
- Smoke (2001): b4_sp1500_h3 46 trades/32 wk, b5_sp1500_h3 288/52 → both ≈330/yr. b5 ≫ b4 (shelf takedowns
  incl. lots of DEBT). Ample power. b4 alone ~46/yr near the card's 50 floor.
- CENTRAL RISKS flagged for Skeptic + kill conditions: (1) one-session-late entry (first_session+1 close) may
  eat the front-loaded post-offering drift → untradeable for this user if +1→+3/+5 window ≈0. (2) 424B4 is also
  the IPO form + NO point-in-time membership → a current member's old IPO 424B4 can leak in (IPO pops positive
  → HURT a short → conservative, but a b4≫b5 result is contamination not SEO). (3) b5 diluted by investment-grade
  debt shelves → if both collapse the blend is debt noise. ROBUSTNESS read b4-vs-b5 is a verdict, NOT a switch.
- COST/BORROW: real_hedged_bps prices SPREAD not BORROW; SEO issuers skew mid/small-cap, some hard-to-borrow →
  Director MUST confirm borrow before real money; pass_mean_bps 15 leaves room. Survivorship biases a SHORT
  AGAINST us (delisted worst-cases absent) → a pass is conservative on that axis.
- PROMOTABLE: 424B same-day public; filings.parquet rebuilt each dispatch → strategy.py reads live, emits short
  when first_session==today → runner enters next close = first_session+1, hold 3. spec entry_at=close,
  exit_at=close, metric real_hedged_bps, pass 15 bps/t 2.0, 20-40 days.

## 2026-11-07 — pipe-short (planned, check+smoke pass)
- Five files in research/pipe-short/ + strategies/pipe-short/. Family `8k_3_02` (screen used 2005-2013 →
  holdout 2014-2026 CLEAN). Bar via budget (floor 3.0). SHORT idea.
- Train 2005-01-01..2013-12-31 (same region the screen searched = a train look), holdout
  2014-01-01..2026-10-24 (clean; daily ends 11-02, buffer for close+5 exit). cluster "week".
- Signal: 8-K item 3.02 (unregistered equity sale = completed PIPE). SHORT at CLOSE of session AFTER
  first_session (entry_pos=pos+1), cover CLOSE +H. SPY-hedged SHORT gross = spy_ret−stock_ret close→close.
  cost 25 (sp1500 close floor ~21.6 + impact). metric hedged.
- 7 variants: univ {sp1500=500+400+600, sp46=400+600} × hold {1,3,5} + sp1500_h3_ex (drop 3.02 within ±2
  cal days of an 8-K 2.02 OR 1.01). chosen PRE-REGISTERED = `sp1500_h3` (idea card's primary rule, ~3d
  screen horizon). luck_t~1.97.
- Smoke (2005): sp1500_h3 114 trades/47 wk, sp46_h3 84/45 — ample power year 1, item-code filter confirmed
  retrievable.
- CENTRAL RISKS flagged for Skeptic + as kill conditions: (1) screen t only −1.70 (marginal); (2)
  one-session-late entry (first_session+1 close) may eat the front-loaded PIPE drift → signature = hold-1 ≪
  hold-3/5; (3) if sp1500_h3_ex collapses it was co-incident earnings/deal news not dilution; (4) if sp1500
  flat but sp46 strong, it's a small-cap signal (research verdict, NOT a switch of chosen — large-cap 3.02s
  are often benign benefit-plan/private placements).
- COST/BORROW CAVEATS: sp600 close floor over-charges sp500 names in sp1500 (conservative). SURVIVORSHIP
  (current members, no delisted) biases a SHORT AGAINST us → a pass is conservative on that axis. real_hedged_bps
  prices SPREAD not BORROW; distressed small-caps hard-to-borrow → Director MUST confirm borrow before real
  money; pass_mean_bps 15 leaves room.
- PROMOTABLE: 3.02 same-day public; filings.parquet rebuilt each dispatch → strategy.py reads live (sp500_new
  +sp400+sp600 csvs, items col split on "," == "3.02"), emits short when first_session==today → runner enters
  next close = first_session+1 close, hold 3. spec entry_at=close, exit_at=close, metric real_hedged_bps, pass
  15 bps/t 2.0, 20-40 days. Reused nt-filing-short skeleton (SHORT close→close hedged + ex-event filter) +
  restructuring item-code filter in strategy.py. BUT 3.02 uncommon in sp1500 → paper may take many months.

## 2026-11-07 — activist-13d-long (planned, check+smoke pass)
- Five files in research/activist-13d-long/ + strategies/activist-13d-long/. Family `activist_13d` (NEW,
  whole history clean). Bar via budget (floor 3.0). LONG idea.
- Train 2001-01-01..2015-12-31, holdout 2016-01-01..2026-10-24 (recent arbitraged era; daily ends 11-02,
  buffer for hold-5 close exit). cluster "week".
- Signal: INITIAL SC 13D accepted (rd.filings(forms=["SC 13D"]) then filter RAW form=="SC 13D" to drop
  SC 13D/A amendments). LONG at CLOSE of session AFTER first_session (entry_pos=pos+1), exit CLOSE +H.
  SPY-hedged LONG gross = stock_ret−spy_ret close→close. cost 25 (sp600 close floor 21.8 + impact). 
- 6 variants: univ {sp1500=500+400+600, sp500} × hold {1,3,5}. chosen PRE-REGISTERED = `sp1500_h3`
  (full activist universe, few-day drift). luck_t~1.89.
- KEY DATA FACT (idea's central risk, RESOLVED FAVORABLY): EDGAR indexes SCHEDULE filings (13D/13G) under
  the SUBJECT company, so rd.filings(tickers=sp1500) returns 13Ds where our ticker is the TARGET, not the
  filer. Confirmed: SC 13G is in catalog top-forms indexed by universe tickers; smoke found 154 sp1500 /
  81 sp500 SC 13D trades in year 1 (2001). Ample power. filings(forms=["SC 13D"]) matches "SC 13D" AND
  "SC 13D/A" (/A stripped both sides) → MUST filter raw form=="SC 13D" for initial-only.
- CENTRAL RISK flagged for Skeptic + as kill condition: entering first_session+1 (one session late, dispatch
  after-close + next-weekday index lag) may miss Brav's front-loaded announcement return → tradable residual
  ~0. Signature = hold-1 much weaker than hold-3/5 in train.
- COST CAVEAT: one shared floor = sp600 close (21.8) over-charges sp500-only variant (real ~6.6) → biases
  AGAINST sp500 result (conservative). SURVIVORSHIP biases a LONG UP (current members only, no delisted) →
  a pass is NOT conservative on that axis; Skeptic should weight it.
- PROMOTABLE: 13D same-day public; filings.parquet rebuilt each dispatch → strategy.py reads live (sp500_new
  +sp400+sp600 csvs), emits long when first_session==today → runner enters next close = first_session+1
  close, hold 3. spec entry_at=close, exit_at=close, metric real_hedged_bps, pass 15 bps/t 2.0, 20-40 days.
  Reused nt-filing-short skeleton (SEC-filing, close→close, hedged); flipped to LONG, dropped ex202 map.

## 2026-11-06 — nt-filing-short (planned) [narrative pruned 2026-11-11]
- `nt_filing` (NEW clean). SHORT on NT 10-K/10-Q, close→close hedged, entry first_session+1, chosen
  sp54_h3. paper_runner handles side="short" (hedged = real_bps − sgn·spy_bps). sp600 excluded (borrow).

## 2026-11-06 — turn-of-month (planned) [narrative pruned 2026-11-07]
- calendar_effects (whole history clean). LONG sp500 EW at month-end close, RAW (not hedged — TOM is
  market-level). chosen tom_h3 vs mid_h3 PLACEBO (beta confound). PROMOTABLE BUT IMPRACTICAL: ~1 cluster/
  month → 20 days ≈ 20 months. strategy.py has a self-contained NYSE holiday calendar. One cost floor →
  can't mix indexes, scoped sp500 only.

## 2026-11-05 — early-10q-drift (planned) [narrative pruned 2026-11-09]
- `10q_timing` (NEW clean). LONG original 10-Q filed >=N cal days earlier than prior-yr 10-Q (prior-filing-gap
  match, not calendar quarter → handles odd fiscal yrs). OPEN entry at first_session, exit OPEN+3, hedged. chosen
  sp1500_t7_long. CAVEAT: SEC daily-index lag can slip same-session filing 1 day in paper. df["open"] (no paren)
  is NOT a FORBIDDEN `\bopen\(` hit.

## 2026-11-05 — restructuring-bounce (planned) [narrative pruned 2026-11-09]
- `8k_2_05` (screen 2005-2013). LONG on 8-K item 2.05, OPEN+2 entry (enter open of session AFTER first_session,
  exit open+H), hedged open->open, cost 35, chosen sp600_h3. 2.05 RARE in sp600 → paper may take months. KEY: for
  open+2 entry, strategy emits when first_session==today → runner enters next open. paper_runner exit_at="open" +
  hold>0 uses SPY open for the hedge exit too (advance():159) — matches research open->open hedge.

## 2026-11-04 — analyst-initiation-buy (planned) [narrative pruned 2026-11-07]
- analyst_ratings (whole history clean). LONG on ratings Action=="init" + bullish ToGrade, OPEN entry
  strictly after GradeDate (leak-free), exit close+H. chosen sp600_h3. NOT PROMOTABLE: ratings archive is
  a one-time yfinance snapshot (no live feed) — strategy.py says DO NOT PROMOTE (same blocker as insider).

### Data facts learned (reuse next time)
- rd.ratings(tickers) → dict ticker→df, cols: GradeDate(date-only, no intraday), Firm, ToGrade,
  FromGrade, Action. Action codes are yfinance short forms: up/down/main/init/reit. "init" =
  coverage initiation (confirmed vs V3 events.load_ratings). ToGrade = the (initiated) rating text.
  Loader clips by GradeDate<=cutoff and sorts. Verified ToGrade present via smoke (182 trades).
- Ratings archive: StockAnalysis-V3/data/events/ratings/{ticker}.parquet. From yfinance
  upgrades_downgrades, fetched ONCE (events_fetch skips existing) → stale, not live-updatable.

### Data facts learned (reuse next time)
- Paper runner: auto-adds SPY to universe (paper_runner:51), builds sessions from bars["SPY"].index (:244),
  computes the hedge (spy_bps) itself — strategy.py only needs SPY for the session calendar. filings.parquet
  cols: accepted, items, form, ticker, cik, filing_date, accession, primary_doc, description.
- rd.splits(None) cols: ticker, ex_date, ratio(>1 fwd,<1 rev), announced, announce_form,
  announce_accession, found_by, first_session (NaT if no announcement found). ~812 of 3189 fwd splits
  have an announcement. first_session already leak-free (first open after `announced`, cut at cutoff).
- rd.daily index may not be exactly normalized → normalize both sides + use positional iloc, don't
  trust label equality. Pattern used in test.py _trades.
- strategy.py (NOT static-scanned) reads data/edgar/splits.parquet via parents[2]/data/edgar. bars
  index in paper_runner are datetime.date, not Timestamp.

### Data facts learned (reuse next time) [insider-cluster-buys 2026-10-27 narrative pruned]
- Insider parquet cols: ACCESSION_NUMBER, TRANS_DATE, TRANS_CODE(P/S), TRANS_SHARES,
  TRANS_PRICEPERSHARE, TRANS_ACQUIRED_DISP_CD(A/D), FILING_DATE(%d-%b-%Y), ISSUERTRADINGSYMBOL,
  DOCUMENT_TYPE, RPTOWNERCIK, RPTOWNER_RELATIONSHIP(contains 'Officer'/'Director'), RPTOWNER_TITLE.
  One reporting owner per accession (drop_duplicates in the fetch). V3 blueprint: StockAnalysis-V3/
  daytrade/research/events.py load_insider/ins.
- rd.daily() archive columns are LOWERCASE: open/high/low/close/volume. SPY.parquet exists in daily_max.
- rd.insider(start) loads year>=start.year files and filters FILING_DATE in [start, cutoff].
- jobs.py FORBIDDEN scans test.py only (regex includes `\bopen\(`, read_parquet, Path(, StockAnalysis,
  requests/http). Column string "open" is fine (no paren). strategy.py is NOT scanned.

### Gotchas / watch
- PAPER PROMOTION BLOCKED: only insider source is SEC QUARTERLY bulk files (months of lag) → a 3-5d
  hold cannot trade live off it. strategy.py encodes the rule for the record but says DO NOT PROMOTE
  until a near-real-time Form-4 feed exists. Director should not promote even on a holdout pass.
- Survivorship: only CURRENT sp500/sp400 membership available (no point-in-time). Biases a long
  signal UP; flagged in PLAN for the Skeptic.
- Chicken/egg: strategy.py must equal `chosen`, but chosen is picked during the train run AFTER commit.
  Solved by pre-registering chosen deterministically (n2_h5_m75k) so strategy.py can match exactly.
  Use this pattern for future ideas unless a selection-by-t is truly needed.
- Smoke prints "chosen None" — harness quirk (res['chosen'] only set when phase literally == 'train'/
  'holdout', not 'smoke'). Not a bug.
