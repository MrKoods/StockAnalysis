# pipe-short — pre-registered PLAN

## Hypothesis
An 8-K **item 3.02** (sale of unregistered equity securities) is the completion of a PIPE (Private
Investment in Public Equity). PIPEs are priced at a discount, dilute existing holders, and the placement
agents / PIPE investors routinely **hedge by short-selling** the target around the closing. This creates a
documented, persistent **negative drift** in the days after the 8-K (Brophy-Ouimet-Sialm 2009;
Chaplinsky-Haushalter 2010). A systematic short of the filer after the event should earn that drift.

## Mechanism / who is on the other side
Retail and passive holders who don't parse 8-K item codes; earnings/balance-sheet screens that ignore 3.02;
the issuer itself (blacked out during the placement). The edge is a short-side pressure the hedging flow
creates, not a reaction to fundamentals we forecast.

## Signal, universe, timing
- **Universe:** S&P 1500 (sp500 ∪ sp400 ∪ sp600). PIPEs concentrate in smaller/cash-hungry names, so a
  small-cap-only cut (sp400 ∪ sp600 = `sp46`) is tested as a variant.
- **Signal:** acceptance of an 8-K carrying item **3.02** for a universe member (`rd.filings(forms=["8-K"],
  items=["3.02"])`). One trade per (ticker, `first_session`); `first_session` (first open after SEC accepted
  the filing) is the signal date, never `filing_date`.
- **Entry:** SHORT at the **CLOSE of the session AFTER `first_session`** (`entry_pos = pos+1`). This is one
  session later than the raw event — the earliest a live, after-close dispatch can actually fill (the
  detection-day close has already passed by the time the filing hits our EDGAR index and the runner wakes).
  Close fills are forced: the whole gross drift (~38 bps) is smaller than one S&P 600 open round trip
  (~250 bps), so an open fill is untradeable for this user.
- **Exit:** cover at the CLOSE **H** sessions later (H ∈ {1,3,5}).
- **Return:** SPY-hedged GROSS bps, SHORT side = `spy_ret − stock_ret` close→close. Harness subtracts cost.

## Variants (7; `max_variants` 8)
univ {`sp1500`, `sp46`} × hold {1,3,5} = 6, **plus** `sp1500_h3_ex` = `sp1500_h3` with any 3.02 whose
acceptance is within ±2 calendar days of an 8-K item **2.02** (earnings release) **or** item **1.01** (a
material agreement) EXCLUDED — a robustness check that the drift is the dilution, not a co-incident priced
event. best-of-N luck t ~ **1.97** (√(2·ln 7)).

**`chosen` PRE-REGISTERED = `sp1500_h3`** (the idea card's primary rule: full S&P 1500, the ~3-day drift
horizon the 2005-2013 screen measured). The other six configs are a robustness map for the Skeptic only and
are never carried to the holdout. Pre-registered deterministically so `strategy.py` can match exactly; `chosen`
is NOT picked by best train t.

## Windows
- Family `8k_3_02`. Used so far: **search 2005-2013** (tools/screen.py, 3 variants: 1d/3d/5d). 8-K item codes
  begin 2004-08.
- **Train 2005-01-01 .. 2013-12-31** (same region the screen searched — a train look, not a holdout).
- **Holdout 2014-01-01 .. 2026-10-24** — CLEAN for this family (never looked at). Recent = the arbitraged
  era, the hardest test. Daily bars end 2026-11-02, so the holdout_end leaves a buffer for a close+5 exit.
- `cluster` = **week** (multi-day holds share exit weeks).

## Costs
`cost_bps` = **25**. Real-spread floor for close→close over S&P 1500 is the S&P 600 close round trip ≈ 21.6
bps (team/fill_costs.json); 25 adds a few bps of impact. The harness charges max(25, floor) = 25.
- One shared floor = the worst index (sp600 close). It **over-charges** the sp500 names inside sp1500 (real
  close round trip ~6.6) → biases the result conservatively (against a pass).
- **Borrow is NOT in this number.** 3.02 filers skew small/distressed and can be hard-to-borrow; a real short
  pays borrow on top. `real_hedged_bps` in paper prices the spread, not borrow. `pass_mean_bps` is sized to
  leave borrow room, and the Director must confirm borrow availability/cost before any real-money step.

## What would kill it (state up front, for the Skeptic)
1. **Chosen t < 2.0 or mean ≤ 0 after cost** → auto-buried (no holdout spent). The screen t was only −1.70
   (marginal, luck bar ~1.5 at 3 variants), so this is a live risk.
2. **One-session-late entry eats the edge.** Brav/PIPE drift is front-loaded; entering `first_session+1`
   close (vs the screen's earlier entry) may leave ~0 tradable residual. Signature = hold-1 much weaker than
   hold-3/5 in train.
3. **It's co-incident news, not dilution.** If `sp1500_h3_ex` (drop 3.02 near a 2.02/1.01) collapses the
   signal, the drift was a priced earnings/deal event, not the PIPE → not our mechanism.
4. **Survivorship.** The universe is only today's S&P 1500 (no delisted names). Delisted PIPE filers are
   disproportionately the worst outcomes — their absence biases a SHORT **against** us → a pass here is
   conservative on this axis (unlike a long). Skeptic should still weight it.
5. **Large-cap contamination.** sp500 3.02s are often benign (benefit-plan / small private placements), not
   toxic PIPEs; if `sp1500_*` is flat but `sp46_*` is strong, the signal is a small-cap one and the chosen
   broad universe is the wrong framing (research verdict, not a switch of `chosen`).

## Promotability
3.02 8-Ks are public the same day; `data/edgar/filings.parquet` is rebuilt every dispatch with SEC's exact
acceptance time → this CAN trade live. `strategy.py` encodes `chosen` = `sp1500_h3`: emits a SHORT when a
member's 3.02 `first_session` is TODAY, the runner enters the next close (= first_session+1 close) and covers
3 sessions later. spec `entry_at`=close, `exit_at`=close, `hold_sessions`=3, metric **real_hedged_bps**,
pass 15 bps / t 2.0, 20-40 days. CAVEATS for the Director: (a) short borrow not modelled — confirm before real
money; (b) 3.02 in S&P 1500 is uncommon, so 20-40 trading days may take many months to fill.
