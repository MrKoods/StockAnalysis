"""
ON1 paper: day-by-day analysis at n=13 + day-20 projection.
Hypothesis: is day-t likely to stay >= 2.0 by day 20 given the recent dip to 1.91?
Verdict rule: PASS if mean >= +5 bps AND day-clustered t >= 2.0 at day 20.
Run from agent workspace root.
"""
import numpy as np
import pandas as pd
from scipy import stats

LEDGER = "C:/Users/user/Documents/Git/StockAnalysis-V3/data/paper/on1_paper_ledger.csv"

led = pd.read_csv(LEDGER)
scored = led.dropna(subset=["bps"])

# Day-by-day means
per_day = scored.groupby("day")["bps"].mean().sort_index()
print("=== ON1 paper: day-by-day scored means ===")
for day, m in per_day.items():
    print(f"  {day}: {m:+7.2f} bps")

n = len(per_day)
mean_of_days = per_day.mean()
std_of_days = per_day.std(ddof=1)
se = std_of_days / np.sqrt(n)
t_now = mean_of_days / se if se > 0 else 0.0
print(f"\nCurrent: {n} days, mean-of-days {mean_of_days:+.2f} bps, std {std_of_days:.2f}, t {t_now:.3f}")

# Trade-level stats
trade_mean = scored["bps"].mean()
trade_std = scored["bps"].std(ddof=1)
print(f"Trade-level: {len(scored)} trades, mean {trade_mean:+.2f} bps, std {trade_std:.2f}")

# Day 20 projection: what average of next 7 days (days 14-20) gets t >= 2.0?
# Formula: t_20 = mean_20 / (std_20 / sqrt(20))
# We need to find what 7-day-block mean X satisfies t_20 = 2.0
# mean_20 = (n * mean_of_days + 7 * X) / 20
# std_20 ≈ assuming same std (it will shift but this is a first-order estimate)
# We iterate: try a range of X and compute t_20 assuming std stays near current
print("\n=== Day-20 projection ===")
days_remaining = 20 - n  # 7

# Scenario analysis: what daily mean over next 7 days gives t_20 = 2.0?
# t_20 = mean_20_of_days / (std_20 / sqrt(20))
# With combined mean_20 = (n * mean_of_days + 7 * X) / 20
# and combined std_20 computed from pooling current days + 7 hypothetical X days
# Simplest: scan over X and compute t_20 using current variance estimate
# (std of combined 20 points is path-dependent, so we use two scenarios)

for X_daily in [-50, -20, 0, 20, 40, 53, 70, 90]:
    new_days = pd.Series([X_daily] * days_remaining)
    combined = pd.concat([per_day, new_days], ignore_index=True)
    m20 = combined.mean()
    s20 = combined.std(ddof=1)
    t20 = m20 / (s20 / np.sqrt(20)) if s20 > 0 else 0.0
    verdict = "PASS" if m20 >= 5 and t20 >= 2 else ("FAIL" if m20 < 0 else "inconclusive")
    print(f"  If next 7 days avg {X_daily:+5.0f} bps: mean_20={m20:+6.1f}, std_20={s20:.1f}, t_20={t20:.2f} -> {verdict}")

# How many consecutive down days would cause t to drop below 2.0 (holding mean ~50 bps)?
print("\n=== Sensitivity: how far can ON1 drop before evaluation fails? ===")
# The FAIL early trigger is mean < 0 at day >= 20.
# PASS requires mean >= +5 AND t >= 2.0.
# At current mean +53 bps (trade-level), FAIL via mean < 0 requires massive deterioration.
# The primary risk is t < 2 while mean > 5 (inconclusive → collect to 40 days).

# Drop-one-day sensitivity at n=13
print("\nDrop-one-day t-stats (which day, if removed, most affects t):")
for drop_day in per_day.index:
    reduced = per_day.drop(drop_day)
    m_r = reduced.mean()
    s_r = reduced.std(ddof=1)
    t_r = m_r / (s_r / np.sqrt(len(reduced))) if s_r > 0 else 0.0
    print(f"  drop {drop_day}: t={t_r:.3f}, mean={m_r:+.1f}")

# Break-even mean for each of next 7 days (threshold where day average barely keeps t >= 2)
print("\n=== Required mean for each added day to maintain t >= 2 at day 20 ===")
# This is the X that gives t_20 = 2.0 (solve quadratic)
# Numerically find X
from scipy.optimize import brentq

def t20_minus_threshold(X, per_day_current, days_rem=7, target_t=2.0):
    new_days = pd.Series([X] * days_rem)
    combined = pd.concat([per_day_current, new_days], ignore_index=True)
    m20 = combined.mean()
    s20 = combined.std(ddof=1)
    t20 = m20 / (s20 / np.sqrt(len(combined))) if s20 > 0 else 0.0
    return t20 - target_t

try:
    breakeven = brentq(t20_minus_threshold, -200, 200, args=(per_day,))
    print(f"  Constant daily mean needed over next 7 days to hit t=2.0 at day 20: {breakeven:+.1f} bps")
    print(f"  (Current 13-day mean = {mean_of_days:+.1f} bps)")
    print(f"  Historical trade-level per-day range: min {per_day.min():+.1f}, max {per_day.max():+.1f}")
except Exception as e:
    print(f"  Brentq failed: {e}")

# Summary
print("\n=== Summary ===")
print(f"Current: {n} days, mean-of-days {mean_of_days:+.2f} bps, t {t_now:.2f}")
print(f"Pass threshold at day 20: mean >= +5 bps AND t >= 2.0")
print(f"FAIL early trigger: mean < 0 at day >= 20")
print(f"Days to day-20 eval: {days_remaining} (approx Nov 9 2026)")
