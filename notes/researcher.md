# Researcher notes

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

## 2026-11-06 — nt-filing-short (planned, check+smoke pass)
- Five files in research/nt-filing-short/ + strategies/nt-filing-short/. Family `nt_filing` (NEW, whole
  history clean). Bar 3.00. SHORT idea.
- Train 2005-01-01..2017-12-31 (8-K item codes from 2004-08, needed for ex202 variant), holdout
  2018-01-01..2026-10-24 (recent arbitraged era; daily ends 11-02, buffer for close+3 exit).
- Signal: NT 10-K / NT 10-Q accepted (forms=["NT 10-K","NT 10-Q"]). SHORT at CLOSE of session AFTER
  first_session (entry_pos=pos+1), cover CLOSE +H. SPY-hedged gross SHORT = spy_ret−stock_ret
  close→close. cost 30 (close floor ~12 + borrow/slippage buffer). cluster "week".
- 5 variants: univ {sp500, sp54=sp500+sp400} × hold {2,3} + sp54_h3_ex202 (exclude NT within ±2 cal days
  of an 8-K 2.02 earnings release). chosen PRE-REGISTERED = `sp54_h3` (broad tradable univ, ~3d drift).
  luck_t~1.79. sp600 EXCLUDED (borrow prohibitive).
- CLOSE fills forced: edge ~50-70 bps CAR < ~80 bps open round trip → open untradable for this user.
  Cost of entering 1 session late = central risk, flagged for Skeptic + as kill condition.
- Smoke (2005): sp54_h3 73 trades/17 wk, sp500_h3 27/13, ex202 52/13 — NT forms CONFIRMED retrievable
  (idea's gate), ample power, ~29% of NT coincide with earnings (ex202 drop).
- PROMOTABLE: NT filings same-day public; filings.parquet rebuilt each dispatch → strategy.py reads live
  (reads sp500_new.csv + sp400.csv). strategy emits short when first_session==today → runner enters next
  session close = first_session+1 close, hold 3, exit close. spec entry_at=close, metric real_hedged_bps,
  pass 15 bps/t 2.0, 20-40 days. CAVEAT: real_hedged_bps prices SPREAD not BORROW → pass_mean_bps 15
  leaves borrow room; Director must confirm borrow before real money. Survivorship biases a SHORT AGAINST
  us (delisted worst-cases absent) → a pass is conservative.
- KEY: SEC form stored raw ("NT 10-K"/"NT 10-Q"), NT not in SKIP_FORMS (edgar.py). paper_runner handles
  side="short" (sgn in _bps + real_price; hedged = real_bps − sgn·spy_bps). Reused restructuring skeleton;
  close→close hedge uses spy close both legs (advance exit_at=close). df["close"] lowercase in rd.daily.

## 2026-11-06 — turn-of-month (planned, check+smoke pass)
- Five files in research/turn-of-month/ + strategies/turn-of-month/.
- Family `calendar_effects` (NOT in catalog used-periods table → whole history clean). Bar 3.00.
  Train 1999-01-01..2014-12-31, holdout 2015-01-01..2026-10-31 (recent arbitraged era; daily ends
  2026-11-02 → +3 exit buffer; Oct-2026 turn forms no trade, fine).
- Signal: LONG whole sp500 EW at CLOSE of last NYSE session of month (T), exit CLOSE of H-th new-month
  session. RAW (unhedged) close→close bps — TOM is MARKET-LEVEL so SPY-hedge would CANCEL it. cost 10
  (floor sp500 close→close 6.6). cluster "week" = ~1 cluster/month (all names share one exit date).
- 4 variants: tom_h1/h2/h3 + mid_h3 PLACEBO (enter middle session of month, hold 3 = same beta, no TOM).
  chosen PRE-REGISTERED = `tom_h3` (canonical McConnell-Xu window). luck_t~1.67.
- BETA CONFOUND flagged for Skeptic: raw 4-day long earns ~16bps equity premium regardless of TOM →
  tom_h3 must EXCEED mid_h3 placebo, not just be >0. Harness scores configs separately (no diff test).
- Smoke (1999): tom_h* 3368 trades/11 wk, mid_h3 3675/12 — ample power year 1.
- PROMOTABLE BUT IMPRACTICAL: strategy.py uses self-contained NYSE holiday calendar (_easter/Good Friday,
  Memorial last-Mon-May can be 5/31, Juneteenth≥2022, NYSE keeps Dec31 open when 1/1=Sat) to detect
  month-end; emits on 2nd-to-last session so runner enters month-end close. BUT 1 cluster/month → min_days
  20 ≈ 20 months, max_days 40 ≈ 3+yr. Effectively research-only; flagged for Director. metric real_bps
  (raw, NOT hedged), pass 15 bps/t 2.0, hold 3, entry+exit close, max_signals 520 (whole sp500 one day).
- KEY: plan carries ONE cost floor, so can't mix sp500/sp400/sp600 (would mis-charge) → scoped to sp500
  only + documented. daily cols lowercase close. rd.universe("sp500")=V3 sp500_new.csv (current members →
  survivorship, flagged). month-end from SPY session calendar = NOT look-ahead (calendar known in advance).

## 2026-11-05 — early-10q-drift (planned, check+smoke pass)
- Five files in research/early-10q-drift/ + strategies/early-10q-drift/.
- Family `10q_timing` (NEW, entirely clean). Train 2001-01-01..2015-12-31, holdout 2016-01-01..2026-10-28
  (recent = arbitraged era; daily ends 11-02 → buffer for open+3 exit; filings end 11-04). Bar floor 3.0.
- Signal: original 10-Q (form=="10-Q", drop /A) filed >= N calendar days earlier than this ticker's prior
  10-Q accepted 300-430 days before (closest to 365 = same fiscal quarter a yr ago; excludes 91/182/273/456).
  days_early=(prior_acc+1yr)-this_acc. LONG at first_session OPEN, exit OPEN+3. SPY-hedged open->open; cost 20
  (S&P1500 large/mid); cluster "week". 5 trading days ≈ 7 cal, 10 ≈ 14.
- 6 variants: univ {sp1500, sp46=sp400+sp600} × thr {7,14} long + late-filer SHORT (de<=-7) {sp1500,sp46}.
  chosen PRE-REGISTERED = `sp1500_t7_long` (broad universe academic result is on, base thr, long).
  luck_t~1.9. Hold fixed 3.
- Smoke (2001 only): sp1500_t7_long 137 trades/28 wk, sp1500_t7_short 142/24 — ample power year 1.
- PROMOTABLE (with caveat): 10-Qs same-day public; filings.parquet has full 10-Q history for prior-yr match;
  strategy.py reads it live, universe = sp500_new+sp400+sp600 CSVs. CAVEAT: SEC daily index reaches parquet
  next weekday → same-session filing can slip 1 day in paper (research uses clean first_session). Flagged for
  Director. spec hold_sessions=3, exit open, metric real_hedged_bps, pass 5 bps/t 2.0, 20-40 days.
- KEY: prior-year match by actual prior-filing gap (not calendar quarter) → handles non-calendar fiscal yrs.
  Reused restructuring/reg-fd skeleton; reg-fd's "first tradable session is NEXT session" emit = first_session
  open entry. df["open"] does NOT trip FORBIDDEN `\bopen\(` (no paren). pd.DateOffset(years=1) for anniversary.

## 2026-11-05 — restructuring-bounce (planned, check+smoke pass)
- Five files in research/restructuring-bounce/ + strategies/restructuring-bounce/.
- Family `8k_2_05` (used only screen 2005-2013). Train 2005-01-01..2013-12-31, holdout
  2014-01-01..2026-10-28 (clean; daily ends 2026-11-02, buffer for open+5 exit). Bar 3.00.
- Signal: 8-K item 2.05 (exit/restructuring costs). LONG at OPEN of the session AFTER `first_session`
  (= open+2 from event — skip the open+1 first-reaction day), exit at OPEN H sessions later. SPY-hedged
  gross open->open; cost 35 (small-cap, BOTH legs at open auction); cluster "week".
- 4 variants: univ {sp600, sp46=sp400+sp600} × hold {3,5}. chosen PRE-REGISTERED = `sp600_h3`
  (smallest cap + screen's 3d horizon = open+2→open+5). Others = Skeptic robustness only. luck_t~1.67.
- Smoke (2005 only): sp600_h3 33 trades/25 wk, sp46_h5 51 — ample even in year 1, power is fine.
- PROMOTABLE: 2.05 8-Ks same-day public; filings.parquet rebuilt each dispatch → strategy.py reads live.
  BUT 2.05 RARE in sp600 → paper min_days=20 may take many months (flagged for Director).
- KEY timing trick for open+2 entry: runner enters at the open of the session AFTER signal_date and exits
  hold_sessions later at open. So strategy emits when the event's first tradable session == TODAY (asof):
  runner then enters next open (=open+2), exits 3 sessions later (=open+5). spec hold_sessions=3,
  exit_at="open", metric real_hedged_bps, pass 5 bps / t 2.0, 20-40 days.
- Reused reg-fd-small-cap skeleton (test.py + strategy.py); changed items→2.05, entry_pos=pos+1,
  open->open exit, hedge open->open, cluster week, cost 35. paper_runner exit_at="open" + hold>0 uses
  SPY open for the hedge exit too (advance():159) — matches research open->open hedge. Verified.

## 2026-11-04 — analyst-initiation-buy (planned, check+smoke pass)
- Five files in research/analyst-initiation-buy/ + strategies/analyst-initiation-buy/.
- Family `analyst_ratings` (whole history clean). Train 2012-09-12..2019-12-31, holdout
  2020-01-01..2026-10-15 (ratings end 2026-10-20, daily 2026-11-02 → buffer for 3-5d exit). Bar
  via budget (floor 3.0). cost 25 bps, cluster "week", metric hedged.
- Signal: ratings Action=="init" + bullish ToGrade (buy/outperform/overweight/positive/
  accumulate/conviction). LONG at OPEN of first session STRICTLY AFTER GradeDate (date-only → no
  same-day trade = leak-free), exit CLOSE H sessions later. SPY-hedged gross.
- 6 variants: univ {sp600, sp46=sp400+sp600} × hold {1,3,5}. chosen PRE-REGISTERED = sp600_h3
  (smallest cap + 3d drift window). Others = Skeptic robustness only.
- Smoke (2012-09..2013-09): sp600_h3 182 trades/48 wk, sp46_h3 376 — ample even in year 1.
- NOT PROMOTABLE: ratings archive is a one-time yfinance snapshot (files last fetched ~10-23;
  events_fetch.py skips existing files) — no near-real-time point-in-time feed. strategy.py says
  DO NOT PROMOTE until a fresh feed exists (same blocker as insider). spec hold_sessions=3,
  exit close, metric real_hedged_bps, pass 5 bps / t 2.0, 20-40 days.

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
