"""
C6 forward test trajectory analysis.
Q: How close to the t <= -2 abort threshold is C6, and at what pace?
Method: Day-clustered t-stat trajectory; project sessions-to-threshold assuming mean/std hold.
"""
import pandas as pd
import numpy as np
from scipy import stats

df = pd.read_csv("C:/Users/user/Documents/Git/StockAnalysis-V3/data/forward/c6_forward_trades.csv")
df["day"] = pd.to_datetime(df["day"])
df = df.sort_values("day")

# Day-level means
day_means = df.groupby("day")["r_net"].mean().reset_index()
day_means.columns = ["day", "mean_r"]
day_means = day_means.sort_values("day").reset_index(drop=True)

print("=== C6 forward: day-by-day means ===")
print(day_means.to_string())
print()

# Cumulative t-stat (day-clustered) at each session
print("=== Cumulative t-stat by session ===")
for i in range(2, len(day_means) + 1):
    sub = day_means["mean_r"].iloc[:i]
    n = len(sub)
    mean = sub.mean()
    sem = sub.std(ddof=1) / np.sqrt(n)
    t = mean / sem if sem > 0 else np.nan
    flag = " <-- FLAG t <= -2" if t <= -2 else ""
    print(f"  n={i:2d}  mean={mean:+.3f}R  t={t:+.2f}{flag}")

print()
# Project: if mean & std hold at current values, sessions until t <= -2
n_now = len(day_means)
mean_now = day_means["mean_r"].mean()
std_now = day_means["mean_r"].std(ddof=1)

print(f"Current: n={n_now}, mean={mean_now:+.3f}R, std={std_now:.3f}R")
print()
print("=== Projection: sessions to t = -2.0 (assuming mean/std hold) ===")
print("Note: this is a pure extrapolation; each new session changes both mean & std.\n")
for n in range(n_now, n_now + 20):
    if std_now > 0:
        t_proj = mean_now / (std_now / np.sqrt(n))
        print(f"  n={n:2d}  projected t={t_proj:+.2f}", end="")
        if t_proj <= -2.0:
            print("  <-- THRESHOLD")
            break
        else:
            print()
