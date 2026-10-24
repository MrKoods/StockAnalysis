"""
V4 EPRE preview: how many signals to expect Monday 2026-10-26?
Buy two sessions before reaction session. For reports before 09:30 ET on Mon Oct 27
(or Tue Oct 28), entry is Fri Oct 24.
For reports after 09:30 ET on Mon Oct 27, entry is Mon Oct 26.
"""
import pandas as pd

cal = pd.read_csv('C:/Users/user/Documents/Git/StockAnalysis-V4/data/calendar/earnings_calendar.csv')
print("Calendar columns:", cal.columns.tolist())
print("Shape:", cal.shape)
print()

# The signals task runs at 12:38 PT (15:38 ET) on Monday Oct 26
# It buys stocks that report before 09:30 ET on Oct 28 (reaction = Oct 28)
# or stocks that report after 09:30 ET on Oct 27 (reaction = Oct 28)
# Entry = close of Monday Oct 26

# Reaction session is the first session whose open can reflect the report.
# Before 09:30 ET -> same day open, so reaction = that day.
# After 09:30 ET -> next session, so reaction = next trading day.

# For Monday entry (2026-10-26 close): exit on 2026-10-28
# That means reporting after 09:30 ET on Oct 27 OR before 09:30 ET on Oct 28.

# For Friday entry (2026-10-24): exit on Mon Oct 27 (reaction = Mon Oct 27)
# That means reporting before 09:30 ET on Oct 27.

# Actually the signals script runs at 12:38 PT on the day of entry.
# Entry = that trading day's close.
# The script picks stocks with reaction sessions 2 days out.

# Let's just look at what reports are scheduled Oct 27-28
if 'report_date' in cal.columns:
    date_col = 'report_date'
elif 'date' in cal.columns:
    date_col = 'date'
else:
    print("No report_date column. Columns:", cal.columns.tolist())
    print(cal.head(3).to_string())
    exit()

print("Upcoming report dates near Oct 26-28:")
cal[date_col] = pd.to_datetime(cal[date_col], errors='coerce')
nearby = cal[(cal[date_col] >= '2026-10-25') & (cal[date_col] <= '2026-10-30')]
print(f"Reports Oct 25-30: {len(nearby)}")
by_date = nearby.groupby(date_col).size()
print(by_date)
print()

# First Monday signals (entry Oct 26): reaction sessions around Oct 28
# These are companies reporting before 09:30 ET on Oct 28 or after 09:30 ET on Oct 27
if 'time' in cal.columns or 'report_time' in cal.columns:
    time_col = 'time' if 'time' in cal.columns else 'report_time'
    print(f"Time column: {time_col}")
    print(nearby[[date_col, 'ticker', time_col]].sort_values(date_col).head(30).to_string())
else:
    print("No time column — cannot split by BMO/AMC")
    print("Sample rows from Oct 27-28:")
    oct2728 = nearby[nearby[date_col].isin(pd.to_datetime(['2026-10-27', '2026-10-28']))]
    print(oct2728[[date_col, 'ticker'] + [c for c in oct2728.columns if c not in [date_col, 'ticker']][:3]].head(20).to_string())
print()
print("Refreshed:", cal['refreshed'].max() if 'refreshed' in cal.columns else "n/a")
