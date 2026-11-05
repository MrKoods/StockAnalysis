# Researcher notes

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

## 2026-11-03 — reg-fd-small-cap-disclosure (planned, check+smoke pass)
- Five files in research/reg-fd-small-cap-disclosure/ + strategies/reg-fd-small-cap-disclosure/.
- Family `8k_7_01` (used only screen 2005-2013). Windows: train 2005-01-01..2013-12-31, holdout
  2014-01-01..2026-10-30 (clean; daily+filings end 2026-11-02, buffer for 1d exit). Bar 3.00.
- Signal: 8-K with item 7.01 (Reg FD) by a universe ticker; LONG at `first_session` OPEN, exit CLOSE
  H sessions later. SPY-hedged gross; cost 30 bps (small-cap); cluster "day".
- 6 variants: universe {sp600, sp400, sp46=400+600} × hold {1,3}. chosen PRE-REGISTERED = `sp600_h1`
  (smallest cap = strongest mechanism; hold 1 = screen best-t). Others = Skeptic robustness only.
- Smoke (2005 only): sp600_h1 683 trades/222 day-periods, sp46_h1 1221 — ample sample.
- PROMOTABLE: 7.01 8-Ks are same-day public; filings.parquet rebuilt each dispatcher run → strategy.py
  reads it live. spec hold_sessions=1, metric real_hedged_bps, pass_mean_bps 5, pass_t 2.0, 20-40 days.
- Reused split-drift's test.py/strategy.py skeleton. Runner auto-adds SPY to universe (paper_runner:51),
  builds sessions from bars["SPY"].index (:244) and computes the hedge (spy_bps) itself — strategy.py
  only needs SPY for the session calendar. filings.parquet cols incl accepted, items, form, ticker.

## 2026-10-31 — split-announcement-drift (planned, check+smoke pass)
- Five files in research/split-announcement-drift/ + strategies/split-announcement-drift/.
- Family `corporate_events` (NOT in catalog's used-periods table → whole history clean). Bar 3.00.
- Windows: train 2001-01-01..2017-12-31, holdout 2018-01-01..2026-10-06 (most recent = arbitraged
  era, the hard/honest test). Daily ends 2026-10-06; announcements begin ~2001.
- Signal: FORWARD split (ratio>1), entry at OPEN of rd.splits `first_session` (leak-free), exit CLOSE
  H sessions later. SPY-hedged gross; cost 20 bps; cluster "week".
- 6 variants: H∈{2,4} × ratio tier {r1>1, r2≥2, r3≥3}. chosen PRE-REGISTERED = `h4_r2`.
- Smoke (2001 only): h4_r2 11 trades/10 wk; h*_r3 0 (3:1 rare early) — fine, r3 is robustness only.
- PROMOTABLE (unlike insider): split 8-Ks are same-day public; splits.parquet rebuilt each dispatcher
  run → strategy.py reads it live. BUT forward splits ~30/yr → paper min_days=20 takes many months.

### Data facts learned (reuse next time)
- rd.splits(None) cols: ticker, ex_date, ratio(>1 fwd,<1 rev), announced, announce_form,
  announce_accession, found_by, first_session (NaT if no announcement found). ~812 of 3189 fwd splits
  have an announcement. first_session already leak-free (first open after `announced`, cut at cutoff).
- rd.daily index may not be exactly normalized → normalize both sides + use positional iloc, don't
  trust label equality. Pattern used in test.py _trades.
- strategy.py (NOT static-scanned) reads data/edgar/splits.parquet via parents[2]/data/edgar. bars
  index in paper_runner are datetime.date, not Timestamp.

## 2026-10-27 — insider-cluster-buys (planned, check+smoke pass)
- Five files written in research/insider-cluster-buys/ and strategies/insider-cluster-buys/.
- Windows: train 2006-01-01..2013-12-31, holdout 2014-01-01..2017-12-31. Insider family already
  spent its one holdout on 2018-2026 (v3-insider-buys), so that window is OFF LIMITS for this family.
  Insider data starts 2006 → 2014-2017 is the most recent still-free holdout.
- Signal: >=2 distinct RPTOWNERCIK open-market Form-4 purchases (TRANS_CODE 'P'), each >=$25k, within
  a 5-CALENDAR-DAY window by FILING_DATE (filing-date window = leak-free), total >=$75k. Long next
  open, exit close H sessions later. SPY-hedged gross bps; cost 20 bps; cluster "week".
- `chosen` is PRE-REGISTERED = n2_h5_m75k (not best-of-train). Other 11 configs reported for Skeptic
  robustness only. Keeps holdout a single hypothesis; luck bar = floor 3.0 (K=2).
- Smoke (2006 only): 62-74 trades, 33-37 weekly periods per variant → sample is fine.

### Data facts learned (reuse next time)
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
