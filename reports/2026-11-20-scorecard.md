# Scorecard 2026-11-20 - written by the dispatcher (script, no Claude)

## Live tests (snapshot.py)
• **V3 ON1 paper** - day 26 · mean +1.5 bps · t 0.06
  ↳ PASS at day 40 needs +104 bps/day over the next 14 days
• **V4 EPRE** - 1,037/3,000 trades · hedged +27.7 bps · t 1.20
  ↳ checkpoint at 3,000 trades: B - FAIL if < 0; small real money OK if >= +10 bps, t >= 1, date accuracy >= 90%
• **V2 rank** - 99/100 trades · -0.022R after costs (GO needs +0.15)
  ↳ GO needs +17.18R/trade for the last 1; NO-GO if they average below +2.18R
• V2 random control - 78 trades · -0.267R (the baseline rank must beat)

## Real Webull prices
• Quotes captured: open 0/73 (failed) · close 0/98 (failed)
• **ON1 at real prices** - COLLECTING · day 7/15 · real -85.4 bps vs paper +1.5 on the same trades · t -1.6
• EPRE at real prices - 452 trades · real hedged +91.7 bps vs paper +92.3 · t 1.48

## Outlook (what each next decision needs - snapshot.py)
```
Outlook: what each next decision still needs (tools/outlook.py) ===
  V2 rank go/no-go: 99/100, mean -0.022R after costs. To reach GO (+0.15) the last 1 trade(s) must average +17.178R; to avoid NO-GO (< 0) +2.178R.
  G2 paper: day 21/40, mean -27.8 bps/day (sd 81). For day 40: not FAIL (mean >= 0) -> the next 19 day(s) must average +30.7 bps/day; PASS (mean >= +5 and day-t >= 2, at this sd = mean >= +25.5) -> must average +84.3 bps/day. Best single day so far +110.7.
  ON1 paper: day 26/40, mean +1.3 bps/day (sd 117). For day 40: not FAIL (mean >= 0) -> the next 14 day(s) can average as low as -2.4 bps/day; PASS (mean >= +5 and day-t >= 2, at this sd = mean >= +37.2) -> must average +103.8 bps/day. Best single day so far +264.5.
```

## Self-running (tools/autonomy.py - the user's goal: the team gets there on its own)
• You stepped in **8×** this week (last week 5× - worse): 3 change(s) from your sessions, 5 day(s) with a needs-you alert
• Team fixed itself **0×**, couldn't **11×** (11-16 Scan Operator gave up on Team_QuoteOpen; 11-16 Scan Operator gave up on Team_QuoteClose; 11-17 Scan Operator gave up on Team_QuoteOpen)
• Open requests the team can't do itself (5): director: 8-K / press-release text parsing (NLP) on the SEC archive we already hold - high | director: A live analyst-ratings feed (ratings source is currently NO) - unlocks analyst-u | director: FOMC meeting dates (8/yr, free, hardcodable - no API) - unlocks FOMC pre-announc

Your sessions' changes:
  11-14 8-K text, day-0 paper trading, FOMC dates, Engineer build mode (user 2026-11-14)
  11-14 Self-running measure (user's goal 2026-11-14) + roles see their exact allowed commands
  11-14 TEAM.md goal: the edge AND the team reaching it on its own (user, 2026-11-14)
Needs-you alert days:
  2026-11-16: Team_QuoteClose ran Mon 11-16 12:56 but FAILED (result 1) - check its log.
  2026-11-17: Team_QuoteClose ran Tue 11-17 12:56 but FAILED (result 1) - check its log.
  2026-11-18: Team_QuoteClose ran Wed 11-18 12:56 but FAILED (result 1) - check its log.
  2026-11-19: Team_QuoteClose ran Thu 11-19 12:56 but FAILED (result 1) - check its log.
  2026-11-20: Team_QuoteClose ran Fri 11-20 12:56 but FAILED (result 1) - check its log.
Team fixed itself:
  none
Couldn't fix itself:
  11-16 Scan Operator gave up on Team_QuoteOpen
  11-16 Scan Operator gave up on Team_QuoteClose
  11-17 Scan Operator gave up on Team_QuoteOpen
  11-17 Scan Operator gave up on Team_QuoteClose
  11-18 Scan Operator gave up on Team_QuoteOpen
  11-18 Scan Operator gave up on Team_QuoteClose
  11-19 Scan Operator gave up on Team_QuoteOpen
  11-19 Scan Operator gave up on V4_EPRE_Signals
  11-19 Scan Operator gave up on Team_QuoteClose
  11-20 Scan Operator gave up on Team_QuoteOpen
  11-20 Scan Operator gave up on Team_QuoteClose
Asked you for:
  director: 8-K / press-release text parsing (NLP) on the SEC archive we already hold - highest leverage, no new API.
  director: A live analyst-ratings feed (ratings source is currently NO) - unlocks analyst-upgrade-on-pullback
  director: FOMC meeting dates (8/yr, free, hardcodable - no API) - unlocks FOMC pre-announcement drift (Lucca-Moench).
  engineer: Fix the EPRE zero-entry crash (one line, V4). In StockAnalysis-V4\epre\paper.py:233, wrap the
  engineer: Re-auth the Webull MCP and confirm it survives a scheduled launch (4th day dark). Re-authing in an

## Research pipeline
- idea: buyback-announcement-long, acquirer-stock-deal-short, antitakeover-adoption-short
