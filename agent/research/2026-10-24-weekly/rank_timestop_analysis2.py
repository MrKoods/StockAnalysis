"""
V2 rank time-stop vs loss: deeper feature analysis.
Hypothesis: VIX, RSI, or score components differ between time-stop and loss groups.
"""
import pandas as pd
import numpy as np
from scipy import stats

LEDGER = 'C:/Users/user/Documents/Git/StockAnalysis/paper_trading/rank_trades.csv'
df = pd.read_csv(LEDGER)

# Focus on time_stop vs loss only (n~50, exclude 3 wins as rare)
ts_loss = df[df['outcome'].isin(['time_stop', 'loss'])].copy()
ts_loss['is_tstop'] = (ts_loss['outcome'] == 'time_stop').astype(int)
print(f"time_stop n={ts_loss['is_tstop'].sum()}, loss n={(ts_loss['is_tstop']==0).sum()}")
print()

# Features to test: vix_at_signal, rsi_14, rs_zscore, mom_5d, technical_score, confidence
features = ['vix_at_signal', 'rsi_14', 'rs_zscore', 'mom_5d',
            'technical_score', 'confidence']

print("Feature means by outcome (time_stop vs loss):")
print(ts_loss.groupby('outcome')[features].mean().round(3).to_string())
print()

# Mann-Whitney U test for each feature (non-parametric, robust to small n)
print("Mann-Whitney p-values (two-sided, H0: no difference):")
print(f"{'Feature':<20} {'ts_mean':>9} {'loss_mean':>10} {'U':>8} {'p-val':>8}")
ts = ts_loss[ts_loss['outcome'] == 'time_stop']
ls = ts_loss[ts_loss['outcome'] == 'loss']
for feat in features:
    ts_vals = ts[feat].dropna()
    ls_vals = ls[feat].dropna()
    if len(ts_vals) < 3 or len(ls_vals) < 3:
        continue
    u, p = stats.mannwhitneyu(ts_vals, ls_vals, alternative='two-sided')
    print(f"  {feat:<20} {ts_vals.mean():>9.3f} {ls_vals.mean():>10.3f} {u:>8.0f} {p:>8.4f}")

print()
# Direction effect: bearish time_stop wins the most?
print("Bearish direction count by outcome:")
print(ts_loss.groupby(['outcome', 'direction']).size().unstack())
print()

# Bearish-only analysis
bear = ts_loss[ts_loss['direction'] == 'bearish']
bull = ts_loss[ts_loss['direction'] == 'bullish']
print(f"Bearish time_stop rate: {bear['is_tstop'].mean():.3f} ({bear['is_tstop'].sum()}/{len(bear)})")
print(f"Bullish time_stop rate: {bull['is_tstop'].mean():.3f} ({bull['is_tstop'].sum()}/{len(bull)})")
if len(bear) >= 5 and len(bull) >= 5:
    u, p = stats.mannwhitneyu(bear['is_tstop'], bull['is_tstop'], alternative='two-sided')
    print(f"  Direction vs time_stop-rate: p={p:.4f}")

print()
# Holdings days
print("Holding days by outcome:")
print(ts_loss.groupby('outcome')['holding_days'].describe().round(2))
