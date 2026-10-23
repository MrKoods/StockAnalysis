"""Nightly earnings-calendar refresh (~1,490 tickers, ~30 min at Yahoo's pace).

For each stock: the next unreported earnings event, its time of day, and where that time came from.
Yahoo often shows a placeholder time (15:00 or 00:00) for future reports; then the company's own habit
(time of its last 4 reports) decides before-open vs after-close, and the row is marked 'history'.
"""

from __future__ import annotations

import logging
import time
from datetime import date

import pandas as pd

from .config import BMO_CUTOFF_MIN, CALENDAR, ETFS, INDEXES, TZ, UNCONFIRMED_TIMES, UNIVERSE_DIR

log = logging.getLogger("epre.calendar")
COLS = ["ticker", "index", "report_day", "minute", "time_source", "bmo", "refreshed"]


def universe() -> dict[str, str]:
    out: dict[str, str] = {}
    for name in INDEXES:
        for t in pd.read_csv(UNIVERSE_DIR / f"{name}.csv")["ticker"]:
            if t not in ETFS:
                out.setdefault(t, name)
    return out


def earnings_frame(ticker: str, limit: int = 8) -> pd.DataFrame:
    """Yahoo earnings dates as (ts ET, minute of day, reported?)."""
    import yfinance as yf
    e = yf.Ticker(ticker.replace(".", "-")).get_earnings_dates(limit=limit)
    if e is None or e.empty:
        return pd.DataFrame(columns=["ts", "minute", "reported"])
    ts = pd.to_datetime(e.index, utc=True).tz_convert(TZ)
    return pd.DataFrame({"ts": ts, "minute": ts.hour * 60 + ts.minute,
                         "reported": e["Reported EPS"].notna().to_numpy()}).sort_values("ts")


def next_event(ticker: str, today: date) -> dict | None:
    f = earnings_frame(ticker)
    if f.empty:
        return None
    fut = f[~f["reported"] & (f["ts"].dt.date >= today)]
    if fut.empty:
        return None
    ev = fut.iloc[0]
    past = f[f["reported"] & ~f["minute"].isin(UNCONFIRMED_TIMES)].tail(4)
    if ev["minute"] not in UNCONFIRMED_TIMES:
        minute, source = int(ev["minute"]), "yahoo"
    elif len(past):
        # company habit: before the open if most of its recent reports were
        minute = 8 * 60 if (past["minute"] < BMO_CUTOFF_MIN).mean() > 0.5 else 16 * 60
        source = "history"
    else:
        return None                     # time of day unknown -> skipped, as in the research
    return {"report_day": str(ev["ts"].date()), "minute": minute, "time_source": source,
            "bmo": minute < BMO_CUTOFF_MIN}


def refresh(limit: int | None = None) -> pd.DataFrame:
    today = pd.Timestamp.now(tz=TZ).date()
    rows, errors = [], 0
    for i, (t, idx) in enumerate(list(universe().items())[:limit]):
        for attempt in range(3):
            try:
                ev = next_event(t, today)
                if ev:
                    rows.append({"ticker": t, "index": idx, **ev, "refreshed": str(today)})
                break
            except Exception as exc:  # noqa: BLE001 - Yahoo throttling/network; retry, then skip
                if attempt == 2:
                    errors += 1
                    log.warning("%s: %s", t, exc)
                time.sleep(5 * (attempt + 1))
        time.sleep(0.3)
        if i % 250 == 0:
            log.info("%d tickers checked", i)
    cal = pd.DataFrame(rows, columns=COLS)
    if len(cal) < 0.5 * len(universe()) and limit is None:
        # a mostly-failed refresh must not replace a good calendar
        raise RuntimeError(f"only {len(cal)} events found ({errors} errors) - keeping the previous calendar")
    CALENDAR.parent.mkdir(parents=True, exist_ok=True)
    cal.to_csv(CALENDAR, index=False)
    log.info("calendar: %d upcoming events, %d errors, %d from company history", len(cal), errors,
             int((cal["time_source"] == "history").sum()))
    return cal
