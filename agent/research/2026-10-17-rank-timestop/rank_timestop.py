"""
V2 rank track: time-stop attribution.
Q: Is the rank track's mean R driven by 15-day time-stop exits, or is there broader edge?
Hypothesis (pre-stated): time_stop exits contribute positively while stop-loss exits
drag; net mean R is near zero. If time stops are the only positive outcome type, the
model has no real edge — it's just "hold long enough and mean-revert."
Method: Group closed rank trades by outcome, compute mean achieved_rr per group.
Also compute mean R without time_stop rows to isolate the non-time-stop contribution.
"""
import pandas as pd
import numpy as np
from scipy import stats

df = pd.read_csv("C:/Users/user/Documents/Git/StockAnalysis/paper_trading/rank_trades.csv")

CLOSED_OUTCOMES = {"time_stop", "loss", "win", "earnings_exit"}
closed = df[df["outcome"].isin(CLOSED_OUTCOMES)].copy()
closed["achieved_rr"] = pd.to_numeric(closed["achieved_rr"], errors="coerce")

print(f"Closed rank trades: {len(closed)}")
print()

# Per-outcome breakdown
print("=== Mean achieved_rr by outcome ===")
grp = closed.groupby("outcome")["achieved_rr"].agg(["count", "mean", "std"]).rename(
    columns={"count": "n", "mean": "mean_R", "std": "std_R"}
)
grp["sem"] = grp["std_R"] / np.sqrt(grp["n"])
grp["t"] = grp["mean_R"] / grp["sem"]
print(grp.to_string())
print()

# Mean R with and without time_stop
all_mean = closed["achieved_rr"].mean()
no_ts = closed[closed["outcome"] != "time_stop"]["achieved_rr"]
ts_only = closed[closed["outcome"] == "time_stop"]["achieved_rr"]

print(f"All closed: mean R = {all_mean:+.3f} (n={len(closed)})")
print(f"Time-stop exits only: mean R = {ts_only.mean():+.3f} (n={len(ts_only)})")
print(f"Non-time-stop exits: mean R = {no_ts.mean():+.3f} (n={len(no_ts)})")
print()

# Contribution decomposition: time_stop share of total R
total_r = closed["achieved_rr"].sum()
ts_r = ts_only.sum()
non_ts_r = no_ts.sum()
print(f"Total R sum: {total_r:+.3f}")
print(f"  from time_stops: {ts_r:+.3f} ({100*ts_r/total_r:.0f}%)")
print(f"  from others:     {non_ts_r:+.3f} ({100*non_ts_r/total_r:.0f}%)")
print()

# Direction breakdown for time_stop exits
ts = closed[closed["outcome"] == "time_stop"]
if "direction" in ts.columns:
    print("=== Time-stop exits by direction ===")
    print(ts.groupby("direction")["achieved_rr"].agg(["count", "mean"]).to_string())
    print()

# Holding days for time_stop exits
if "holding_days" in ts.columns:
    hd = pd.to_numeric(ts["holding_days"], errors="coerce")
    print(f"Time-stop holding days: mean={hd.mean():.1f}, min={hd.min():.0f}, max={hd.max():.0f}")
