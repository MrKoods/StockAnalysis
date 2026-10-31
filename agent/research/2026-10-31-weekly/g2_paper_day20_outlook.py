"""
G2 paper: trajectory analysis at n=16 + day-20 outlook.
Hypothesis: at n=16, mean=-19.563 bps, day-t=-1.36, can it reach mean>0 and t>=2 in 4 more days?
Verdict rule: PASS if mean >= +5 bps AND day-clustered t >= 2.0 at day 20.
                FAIL if mean < 0 at day >= 20.
Run from agent workspace root.
"""
import numpy as np
import pandas as pd
from scipy.optimize import brentq

LEDGER = "C:/Users/user/Documents/Git/StockAnalysis-V3/data/paper/g2_paper_ledger.csv"

led = pd.read_csv(LEDGER)
scored = led.dropna(subset=["bps_at_0932_entry"])

# Day-by-day means
per_day = scored.groupby("day")["bps_at_0932_entry"].mean().sort_index()
print("=== G2 paper: day-by-day scored means (9:32 entry) ===")
for day, m in per_day.items():
    print(f"  {day}: {m:+7.2f} bps")

n = len(per_day)
mean_of_days = per_day.mean()
std_of_days = per_day.std(ddof=1)
se = std_of_days / np.sqrt(n)
t_now = mean_of_days / se if se > 0 else 0.0
print(f"\nCurrent: {n} days, mean-of-days {mean_of_days:+.2f} bps, std {std_of_days:.2f}, t {t_now:.3f}")

trade_mean = scored["bps_at_0932_entry"].mean()
trade_std = scored["bps_at_0932_entry"].std(ddof=1)
print(f"Trade-level: {len(scored)} trades, mean {trade_mean:+.2f} bps, std {trade_std:.2f}")

# Day 20 is 4 days away
days_remaining = 20 - n

print(f"\n=== Day-20 projection ({days_remaining} days remaining) ===")

# Scenario analysis
for X_daily in [-60, -20, 0, 20, 60, 100, 150, 200]:
    new_days = pd.Series([X_daily] * days_remaining)
    combined = pd.concat([per_day, new_days], ignore_index=True)
    m20 = combined.mean()
    s20 = combined.std(ddof=1)
    t20 = m20 / (s20 / np.sqrt(20)) if s20 > 0 else 0.0
    if m20 >= 5 and t20 >= 2:
        verdict = "PASS"
    elif m20 < 0:
        verdict = "FAIL"
    else:
        verdict = "inconclusive"
    print(f"  If next 4 days avg {X_daily:+5.0f} bps: mean_20={m20:+6.1f}, std_20={s20:.1f}, t_20={t20:.2f} -> {verdict}")

# What daily mean keeps mean_20 = 0 (breakeven for FAIL threshold)?
# (n * mean_n + 4 * X) / 20 = 0  =>  X = -n * mean_n / 4
X_breakeven_mean = -n * mean_of_days / days_remaining
print(f"\nFor mean_20 = 0 (FAIL boundary), need avg daily mean over 4 days: {X_breakeven_mean:+.1f} bps")
print(f"For mean_20 = +5 bps (PASS floor), need avg daily mean: {(-n * mean_of_days + 20 * 5) / days_remaining:+.1f} bps")

# Numerically find X for t_20 = 2.0
def t20_minus_threshold(X, per_day_current, days_rem, target_t=2.0):
    new_days = pd.Series([X] * days_rem)
    combined = pd.concat([per_day_current, new_days], ignore_index=True)
    m20 = combined.mean()
    s20 = combined.std(ddof=1)
    t20 = m20 / (s20 / np.sqrt(len(combined))) if s20 > 0 else 0.0
    return t20 - target_t

try:
    X_for_t2 = brentq(t20_minus_threshold, -500, 2000, args=(per_day, days_remaining))
    print(f"\nFor t_20 = 2.0 (PASS t-threshold), need avg daily mean: {X_for_t2:+.1f} bps")
except Exception as e:
    print(f"\nBrentq for t=2.0: {e}")

# Historical context: is this possible?
print(f"\nHistorical per-day range: min {per_day.min():+.1f}, max {per_day.max():+.1f}, mean {mean_of_days:+.1f}")
print(f"Best 4-consecutive-day sum in history: {per_day.rolling(4).sum().max():+.1f} bps (avg: {per_day.rolling(4).sum().max()/4:+.1f}/day)" if n >= 4 else "not enough days for rolling 4")

# Summary
print("\n=== Summary ===")
print(f"Current: {n} days, mean-of-days {mean_of_days:+.2f} bps, t {t_now:.2f}")
print(f"Pass threshold at day 20: mean >= +5 bps AND t >= 2.0")
print(f"FAIL threshold at day 20: mean < 0")
print(f"Days to day-20: {days_remaining} (approx Thu Nov 5 2026)")
