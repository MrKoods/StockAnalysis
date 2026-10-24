"""
ON1 paper day-by-day consistency analysis.
Q: Is the day-t +2.19 driven by a few outlier days or consistent?
"""
import pandas as pd
import numpy as np
from scipy import stats

df = pd.read_csv('C:/Users/user/Documents/Git/StockAnalysis-V3/data/paper/on1_paper_ledger.csv')
print("ON1 paper ledger columns:", df.columns.tolist())
print("Shape:", df.shape)
print()

# Day-by-day breakdown
by_day = df.groupby('day').agg(
    n_trades=('bps', 'count'),
    mean_bps=('bps', 'mean'),
    std_bps=('bps', 'std'),
    total_bps=('bps', 'sum')
).reset_index()
print("Day-by-day:")
print(by_day.to_string())
print()

# Drop zero-trade days (no data yet)
by_day = by_day[by_day['n_trades'] > 0].reset_index(drop=True)

# Day-level stats (what the frozen rule uses)
day_means = by_day['mean_bps'].values
print(f"Day means: {day_means}")
print(f"Day-level mean: {day_means.mean():.3f} bps")
print(f"Day-level std: {day_means.std(ddof=1):.3f} bps")
n = len(day_means)
t_stat = day_means.mean() / (day_means.std(ddof=1) / np.sqrt(n))
print(f"Day-level t-stat: {t_stat:.3f} (n={n})")
print()

# Distribution stats
print(f"Individual trade grand mean: {df['bps'].mean():.3f} bps")
print(f"Individual trade grand std: {df['bps'].std():.3f} bps")
print(f"Win rate (bps > 0): {(df['bps'] > 0).mean():.3f}")
print()

# Skewness / outliers in day means
print(f"Max day mean: {day_means.max():.1f} bps")
print(f"Min day mean: {day_means.min():.1f} bps")
print(f"Positive days: {(day_means > 0).sum()} / {n}")

# Drop-one analysis for robustness
for i in range(n):
    subset = np.delete(day_means, i)
    t_drop = subset.mean() / (subset.std(ddof=1) / np.sqrt(len(subset)))
    print(f"  Drop day {i+1} ({by_day.iloc[i]['day']}): t={t_drop:.2f}")
