"""
G2 paper: is the recent negative drift a trend or noise?
Days 9-11 all negative. Check running mean, trend, and compare to earlier days.
"""
import pandas as pd
import numpy as np
from scipy import stats

df = pd.read_csv('C:/Users/user/Documents/Git/StockAnalysis-V3/data/paper/g2_paper_ledger.csv')
print("G2 paper ledger columns:", df.columns.tolist())
print("Shape:", df.shape)
print()

# Figure out the bps column
bps_col = None
for c in ['bps', 'hedged_bps', 'ret_bps', 'return_bps']:
    if c in df.columns:
        bps_col = c
        break
if bps_col is None:
    print("No bps column found. Columns:", df.columns.tolist())
else:
    print(f"Using bps column: {bps_col}")
    by_day = df.groupby('day').agg(
        n=('bps', 'count'),
        mean_bps=('bps', 'mean'),
    ).reset_index()
    by_day = by_day[by_day['n'] > 0]
    print(by_day.to_string())
    print()
    day_means = by_day['mean_bps'].values
    print(f"Overall day-level mean: {day_means.mean():.3f} bps")
    print(f"Day-level t-stat: {day_means.mean() / (day_means.std(ddof=1) / np.sqrt(len(day_means))):.3f} (n={len(day_means)})")
    print()
    # Early vs late half
    mid = len(by_day) // 2
    early = day_means[:mid]
    late = day_means[mid:]
    print(f"Early days (1-{mid}): mean {early.mean():.1f} bps")
    print(f"Late days ({mid+1}-{len(by_day)}): mean {late.mean():.1f} bps")
