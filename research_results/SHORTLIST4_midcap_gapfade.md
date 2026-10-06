# Midcap confirmation of the gap fade — pre-registered 2026-10-06, BEFORE downloading any midcap data

Config G2 (exact, no changes): GAP fade, gap >= 0.25 daily ATR (open vs prev close), enter at the
09:30 open, target = previous close, no stop, exit at the close of the 12:30 hourly bar (~13:30),
only when the trade direction agrees with the 20-day trend (prev close vs SMA20).

Data: S&P 400 MidCap constituents (none used anywhere before), yfinance hourly, full ~2 years.
Costs: 1 cent/side headline; also report 2 bps/side.

PASS: mean net (1c/side) > 0 with day-clustered t >= 2.0, longs and shorts both > 0,
positive in both years (sessions before / from 2025-07-01), and mean still > 0 at 2 bps/side.
