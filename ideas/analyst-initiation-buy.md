# analyst-initiation-buy

## Mechanism
When a sell-side analyst initiates coverage on a stock with a Buy (or equivalent) rating, it creates new institutional demand. Many institutional funds have mandates requiring analyst coverage before they can hold a position ("coverage initiation clears the gating requirement"). The initiation also brings the stock to the attention of institutional portfolio managers who had not previously tracked it. This creates a demand surge that cannot be instantly arbitraged because the new buyers themselves are the trigger. The effect is strongest for small and mid-cap stocks where coverage is sparse and the initiation is truly new information.

**Who is on the other side?** The analyst's brokerage is typically not selling — they are recommending. The stock often has no large institutional covering position to absorb demand. Sellers are earlier holders who benefit from the pop but were not positioned around the event.

## Evidence
- Womack (1996) "Do Brokerage Analysts' Recommendations Have Investment Value?" — Journal of Finance: initiation Buy ratings show +3% average 1-month drift; significantly stronger than subsequent upgrades (new coverage ≠ known coverage change)
- Michaely & Womack (1999) "Conflict of Interest and the Credibility of Underwriter Analyst Recommendations" — Review of Financial Studies: confirms initiation premium
- Barber, Lehavy, McNichols & Trueman (2001) "Can Investors Profit from the Prophets?" — Journal of Finance: Buy-initiated stocks significantly outperform 1-day to 3-day
- Bradley et al. (2003): 1-day return after initiation is +2.5% for small caps (meaningfully above costs)
- The graveyard records "analyst rating actions" failing the 2018-2026 holdout — but that was a broad test of upgrades/downgrades in V3's pre-team framework. Initiations are fundamentally different: they create new demand, not a re-evaluation of existing coverage. The specific analyst_ratings family has never been touched in the current team framework (data_catalog.md confirms 0 holdouts, 0 search variants).

## Rule sketch
- Universe: S&P 1500 stocks with an analyst initiation action (action_type == "Initiated" or equivalent in ratings() data) with Buy / Strong Buy / Outperform / Overweight rating
- Entry: buy at open the trading day after the rating appears in the `ratings()` data
- Exit: sell at open 3 trading days later (hold = 3 days)
- Variants: (a) hold 1d vs 3d vs 5d; (b) S&P 600 only; (c) require no earnings in the hold window; (d) add SPY/sector hedge
- **Data caveat**: the `ratings()` loader description is "analyst rating changes" — verify that initiations are present as a distinct action type (expected: "Initiated" or "Initiated Coverage" in the action field). If not, this idea needs data not available.
- Expected events: ~300-500 Buy initiations/year across S&P 1500 × 8-year train (2012-2019) = ~2,400-4,000 events

## Data
- `ratings(tickers)` 2012-2026: analyst rating changes including initiations; need action_type == "Initiated" filter
- `daily(tickers)`: OHLCV for entry/exit pricing
- **Family**: `analyst_ratings` (new, completely clean — no prior search or holdout in this team framework)
- **Train**: 2012-2019; **holdout**: 2020-2026

## Horizon
3 trading days (open+1 to open+4)

## Cost estimate
~15 bps round trip for large/mid cap; ~25 bps small cap (first test: mid-to-large cap universe to keep costs ~15 bps)

## Why it might NOT work
1. Broadly tested category: "analyst rating actions" failed the 2018-2026 holdout in pre-team V3 research (though that test likely included all upgrades/downgrades, not initiations specifically)
2. Only 14 years of ratings() data (2012-2026) — train 2012-2019 is 8 years; holdout 2020-2026 includes COVID (2020) which was structurally unusual
3. Conflict of interest: analysts often initiate coverage on stocks their bank underwrote (IPOs, secondaries), and the initiation is part of the deal promotion rather than a genuine signal
4. Algorithmic coverage of initiations is very fast now; the 1-day lag assumed here may leave little residual

## Differs from graveyard
- Analyst rating actions (V3 graveyard): tested broad upgrades/downgrades in the sweep/gap-fade framework on a different research schema; initiations are a strict subset with a distinct mechanism (new institutional demand gating, not opinion change)
- Split-announcement-drift (dead), insider-cluster-buys (dead): entirely different event types
- EPRE (V4): earnings-based event; analyst initiation is pre/post-earnings independent

## Source
Womack (1996): https://doi.org/10.1111/j.1540-6261.1996.tb02417.x
Barber et al. (2001): https://doi.org/10.1111/0022-1082.00336
Bradley et al. (2003): https://doi.org/10.1111/1540-6261.00538
