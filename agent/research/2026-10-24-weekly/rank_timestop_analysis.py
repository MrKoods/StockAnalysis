"""
V2 rank time-stop vs loss: what distinguishes them?
Q: Direction, sector, VIX regime, or RSI at entry?
Note: cannot tune live experiment; this is for future track design insight.
"""
import pandas as pd
import numpy as np

LEDGER = 'C:/Users/user/Documents/Git/StockAnalysis/paper_trading/rank_trades.csv'
df = pd.read_csv(LEDGER)
print("Rank ledger columns:", df.columns.tolist())
print("Shape:", df.shape)

# Closed trades only (outcomes that have an achieved_rr)
closed = df[df['outcome'].isin(['time_stop', 'loss', 'win'])].copy()
print(f"\nClosed trades: {len(closed)}")
print(closed['outcome'].value_counts())
print()

# Direction breakdown by outcome
print("Outcome x direction:")
print(pd.crosstab(closed['outcome'], closed['direction']))
print()

# Mean achieved_rr by outcome x direction
print("Mean achieved_rr by outcome x direction:")
print(closed.groupby(['outcome', 'direction'])['achieved_rr'].agg(['mean', 'count']))
print()

# Check if 'sector' column exists
if 'sector' in closed.columns:
    print("Outcome by sector:")
    print(pd.crosstab(closed['outcome'], closed['sector']))
    print()
else:
    print("No sector column in rank ledger")

# Check available columns for analysis
print("All columns:", df.columns.tolist())
print()

# Date of entry: options-era vs shares-era
if 'signal_date' in closed.columns:
    closed['era'] = closed['signal_date'].apply(
        lambda x: 'shares' if str(x) >= '2026-10-14' else 'options'
    )
    print("Outcome by era:")
    print(pd.crosstab(closed['outcome'], closed['era']))
    print()
    print("Mean achieved_rr by outcome x era:")
    print(closed.groupby(['outcome', 'era'])['achieved_rr'].agg(['mean', 'count']))
