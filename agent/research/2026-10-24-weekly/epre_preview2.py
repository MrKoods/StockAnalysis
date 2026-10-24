"""
V4 EPRE preview: signals expected on first run (Monday 2026-10-26).
Calendar columns: ticker, index, report_day, minute, time_source, bmo, refreshed
bmo=True: before market open; bmo=False: after market close.
minute: 960 = 16:00 ET (AMC), 0 = 00:00 (BMO usually ~6-8 AM).
Reaction session:
  bmo=True  -> reaction = report_day (opens can reflect the report)
  bmo=False -> reaction = next trading day after report_day
Entry = 2 sessions before reaction session.
"""
import pandas as pd
from pandas.tseries.offsets import BDay

cal = pd.read_csv('C:/Users/user/Documents/Git/StockAnalysis-V4/data/calendar/earnings_calendar.csv')
cal['report_day'] = pd.to_datetime(cal['report_day'])

# Compute reaction session
# bmo=True: reaction = report_day; bmo=False: reaction = report_day + 1 business day
cal['reaction_day'] = cal.apply(
    lambda r: r['report_day'] if r['bmo'] else r['report_day'] + BDay(1),
    axis=1
)

# Entry day = reaction - 2 business days
cal['entry_day'] = cal['reaction_day'] - 2 * BDay()

print("Entry day distribution (first 10 days):")
entry_dist = cal.groupby('entry_day').size().reset_index(name='count')
print(entry_dist[entry_dist['entry_day'] >= '2026-10-24'].head(10).to_string())
print()

# Monday 2026-10-26 signals
mon = cal[cal['entry_day'] == '2026-10-26']
print(f"Monday 2026-10-26 entries: {len(mon)}")
if len(mon) > 0:
    print(mon[['ticker', 'index', 'report_day', 'bmo', 'reaction_day']].sort_values('ticker').to_string())
print()

# Also Friday 2026-10-24 (if the signal script ran today, would there be any?)
fri = cal[cal['entry_day'] == '2026-10-24']
print(f"Friday 2026-10-24 entries: {len(fri)}")
if len(fri) > 0:
    print(fri[['ticker', 'index', 'report_day', 'bmo', 'reaction_day']].sort_values('ticker').head(20).to_string())
