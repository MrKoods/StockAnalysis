"""
V2 rank go/no-go trajectory: what needs to happen over remaining 43 trades
to reach mean +0.15R after costs at n=100?
"""
import pandas as pd
import numpy as np
from scipy import stats

RANK_CSV = 'C:/Users/user/Documents/Git/StockAnalysis/paper_trading/rank_trades.csv'
df = pd.read_csv(RANK_CSV)

# Load the cost model from rank_verdict
import sys
sys.path.insert(0, 'C:/Users/user/Documents/Git/StockAnalysis')
try:
    from paper_trading.rank_verdict import compute_verdict
    from pathlib import Path
    v = compute_verdict(
        cfg=None,
        rank_csv=Path('C:/Users/user/Documents/Git/StockAnalysis/paper_trading/rank_trades.csv'),
        random_csv=Path('C:/Users/user/Documents/Git/StockAnalysis/paper_trading/random_trades.csv')
    )
    print("Verdict text:")
    print(v['text'])
    print()
    if 'mean_r_after_costs' in v:
        current_mean = v['mean_r_after_costs']
        n_closed = v['n_closed']
    else:
        print("Verdict keys:", v.keys())
        current_mean = -0.048
        n_closed = 57
except Exception as e:
    print(f"Could not import rank_verdict: {e}")
    current_mean = -0.048
    n_closed = 57

TARGET_MEAN = 0.15
TARGET_N = 100
remaining = TARGET_N - n_closed

# Required total R
current_total = current_mean * n_closed
required_total = TARGET_MEAN * TARGET_N
required_remaining_total = required_total - current_total
required_mean_remaining = required_remaining_total / remaining

print(f"Current: {n_closed} closed, mean after costs {current_mean:.3f}R")
print(f"Total R so far: {current_total:.2f}R")
print(f"Required total at n=100: {required_total:.2f}R")
print(f"Remaining trades needed: {remaining}")
print(f"Required mean per remaining trade: {required_mean_remaining:.3f}R")
print()

# Closed outcomes distribution
closed = df[df['outcome'].isin(['time_stop', 'loss', 'win', 'earnings_exit'])]
# Get after-costs mean from closed trades
print("Closed trades outcomes:")
print(closed['outcome'].value_counts())
print()

# If future trades mirror current (excluding open/pending)
ts_closed = closed[closed['outcome'] == 'time_stop']['achieved_rr']
loss_closed = closed[closed['outcome'] == 'loss']['achieved_rr']
win_closed = closed[closed['outcome'] == 'win']['achieved_rr']

# The snapshot uses after-costs adjustment — snapshot shows -0.048 vs raw +0.010
# Assume ~0.058 cost per trade on average (from the difference)
cost_per_trade = 0.058  # rough estimate

p_ts = len(ts_closed) / len(closed)
p_loss = len(loss_closed) / len(closed)
p_win = len(win_closed) / len(closed)
proj_mean_raw = p_ts * ts_closed.mean() + p_loss * loss_closed.mean() + p_win * win_closed.mean()
proj_mean_after_costs = proj_mean_raw - cost_per_trade
print(f"If future mirrors current mix: {p_ts:.2%} time-stop / {p_loss:.2%} loss / {p_win:.2%} win")
print(f"  Projected raw mean: {proj_mean_raw:.3f}R")
print(f"  Projected after-costs mean (approx): {proj_mean_after_costs:.3f}R")

proj_final_mean = (current_mean * n_closed + proj_mean_after_costs * remaining) / TARGET_N
print(f"  Projected final mean at n=100: {proj_final_mean:.3f}R")
print(f"  Required for GO: +0.150R — {'REACHABLE' if proj_final_mean >= 0.15 else 'UNREACHABLE at current rate'}")
print()
print(f"Required mean per remaining trade: {required_mean_remaining:.3f}R")
print(f"Best observed time-stop mean: {ts_closed.mean():.3f}R")
print(f"For reference: 100% time-stop future would give final mean: "
      f"{(current_mean * n_closed + (ts_closed.mean() - cost_per_trade) * remaining) / TARGET_N:.3f}R")
