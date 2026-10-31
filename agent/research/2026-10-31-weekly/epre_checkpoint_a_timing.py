"""
EPRE: checkpoint A arrival timing.
Q: When does 1,000 closed trades arrive? What is the current daily signal rate and exit-day pace?
Run from agent workspace root.
"""
import pandas as pd
import numpy as np

LEDGER = "C:/Users/user/Documents/Git/StockAnalysis-V4/data/paper/epre_ledger.csv"

led = pd.read_csv(LEDGER)
print(f"Total rows: {len(led)}, closed: {led['exit_day'].notna().sum()}, open: {led['exit_day'].isna().sum()}")

closed = led[led["exit_day"].notna()].copy()
open_ = led[led["exit_day"].isna()].copy()

# Signals per entry_day
by_entry = led.groupby("entry_day").size()
print("\n=== Signals per entry day ===")
for d, n in by_entry.items():
    print(f"  {d}: {n} signals")

# Closures per exit_day
by_exit = closed.groupby("exit_day").size()
print("\n=== Closures per exit day ===")
cumclosed = 0
for d, n in by_exit.items():
    cumclosed += n
    mean_h = closed[closed["exit_day"] == d]["hedged_bps"].mean()
    print(f"  {d}: {n} closures (cumulative {cumclosed}, hedged mean {mean_h:+.1f} bps)")

# Open positions: when will they close?
# Exit day is entry_day + 2 trading days
print(f"\nCurrently open: {len(open_)} positions entered on:")
print(open_.groupby("entry_day").size().to_string())

# When will open positions close?
# Entry Oct 29 -> exit Oct 31 (Fri) or Nov 3 (Mon)?
# Entry Oct 30 -> exit Nov 3 (Mon) or Nov 4?
# Typically exit_day = report_day + 1 trading day
# Since report days are tomorrow/Monday, these will close early next week.

# Projection
print(f"\n=== Checkpoint A projection ===")
print(f"Current closed: {len(closed)}")
print(f"Current open (will close ~Nov 3): {len(open_)}")
print(f"After Nov 3 exit day (est): ~{len(closed) + len(open_)} closed")
still_needed = 1000 - len(closed) - len(open_)
print(f"Still needed after that: ~{still_needed} more closures")

# Signal rate in last 3 days (peak earnings season)
recent_entries = by_entry[by_entry.index >= "2026-10-27"]
avg_daily_signals = recent_entries.mean() if len(recent_entries) > 0 else 0
print(f"\nRecent avg daily signal entry rate (Oct 27-30): {avg_daily_signals:.0f} signals/day")
print(f"These close 2 trading days later.")
print(f"At {avg_daily_signals:.0f} closures/day (2-day lag), approx {still_needed/avg_daily_signals:.1f} trading days to add {still_needed} closures")
print(f"=> Checkpoint A expected: around Nov 3-7 depending on Oct 31 and next-week signal volume")

# Hedged mean trajectory
print(f"\n=== EPRE hedged mean trajectory ===")
cumstats = []
cumtotal = []
cumsum = 0
cumn = 0
for d, grp in closed.groupby("exit_day"):
    h = grp["hedged_bps"]
    cumsum += h.sum()
    cumn += len(h)
    t_stat = (cumsum / cumn) / (closed[closed["exit_day"] <= d]["hedged_bps"].std(ddof=1) / np.sqrt(cumn)) if cumn > 1 else float("nan")
    print(f"  {d}: {len(h)} closes, exit-day mean {h.mean():+.1f} bps | cumulative n={cumn}, mean={cumsum/cumn:+.1f} bps, t={t_stat:.2f}")

print(f"\nBacktest expectation: ~+19 bps. At 3 exit days, this is noise (exit-day t -0.39).")
print("Checkpoint A (1k closed): FAIL if hedged mean < -20 bps.")
