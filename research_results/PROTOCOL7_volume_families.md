# Round 2: volume ("stocks in play") families — protocol pre-registered 2026-10-06, BEFORE any scan

Families (hourly bars + hourly volume; RVOL = volume / its own average over the prior 14 sessions):
- SIP  first-hour RVOL selection (top 5/10/20 per day, or RVOL >= 2 / 3); trade with (mom) or against
       (rev) the first-hour candle from the 10:30 open; stop none / other side of first hour / 0.5 ATR;
       target none / 1R / 2R; exit at the 13:30 bar close or the 16:00 close
- GAPV gap >= 0.25 / 0.5 / 1.0 ATR split by volume (high = RVOL >= 2, low = RVOL < 1, or top 10/day),
       measured either as previous-day RVOL (enter at the open) or first-hour RVOL (enter 10:30);
       go with or fade the gap; target previous close (fade only) or none; exit 12:30 bar or close
- ONV  overnight (close -> next open) on last-hour losers/winners (bottom/top 5/10/20%) restricted
       to high (>= 2) or low (< 1) last-hour RVOL, or unrestricted; rev or mom

Same stages and bars as PROTOCOL5 (2 bps/side; search S&P 500 < 2025-07-01; shortlist top 2 per
family with n >= 2,000 and distinct core params; Stage 3 holdout t >= 2.6, both halves, both sides;
Stage 4 midcaps AND small caps t >= 2.0; at most 3 selected, one per family), with one fix:
candidates whose search trades are identical (same n and mean) to an earlier pick are skipped.
