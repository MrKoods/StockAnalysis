"""Bulk event screen - script only, zero Claude tokens. Writes state/screen.md for the Scout and Director.

    python tools/screen.py [--force]

A cheap first look at every 8-K event type in the SEC archive (tools/edgar.py): after the event becomes public,
buy at the next session's open, hold 1 / 3 / 5 sessions, minus SPY over the same days and minus the stock's own
average drift vs SPY (today's S&P 1500 are survivors, so almost any long "beats" SPY). Gross bps, clustered by
week. It only points research at event types where SOMETHING moves; it is not a test and never promotes
anything - a lead still goes idea -> Director -> Researcher (plan, train, Skeptic) -> one holdout.

Honesty rules, same as research:
  * data only through research_data, cut at SCREEN_END: the screen never sees 2014+, so every 8-K family keeps
    2014-2026 as a clean holdout (family name `8k_<item>`, e.g. 8k_5_02);
  * every screened variant is logged in registry/trials.csv as a search in its family, once;
  * the universe is today's S&P 1500 (survivorship bias) and bars are not split-adjusted (|move| > 50% dropped).
Re-runs at most every RERUN_DAYS (the window is fixed, so results change only as the EDGAR archive fills in).
"""
from __future__ import annotations

import os
import sys
from datetime import date, timedelta

import pandas as pd

import budget
import jobs
import research_data as rd
from common import STATE, load_json, log, save_json

SCREEN_START, SCREEN_END = "2005-01-01", "2013-12-31"

OUT = STATE / "screen.md"
STATEF = STATE / "screen.json"
HORIZONS = (1, 3, 5)
MAX_MOVE_BPS = 5000          # bigger = a split or bad bar in the unadjusted archive
MIN_EVENTS = 200             # fewer = too thin to screen (and to hold out later)
COST_BPS = 20                # round trip used for the "after costs" column
RERUN_DAYS = 28
NOTE = "screen (tools/screen.py)"


def family(item: str) -> str:
    return "8k_" + item.replace(".", "_")


def panels() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Open and close, sessions x tickers, through SCREEN_END."""
    bars = rd.daily(rd.universe("all"))
    opens = pd.DataFrame({t: d["open"] for t, d in bars.items()})
    closes = pd.DataFrame({t: d["close"] for t, d in bars.items()})
    opens.index = closes.index = pd.to_datetime(opens.index).normalize()
    return opens.sort_index(), closes.sort_index()


def drift_bps(closes: pd.DataFrame) -> "pd.Series":
    """Each stock's average daily return minus SPY's over the screen window, in bps (the survivor baseline)."""
    r = closes.loc[SCREEN_START:SCREEN_END].pct_change(fill_method=None)
    r = r.where(r.abs() <= MAX_MOVE_BPS / 1e4)
    return ((r.sub(r["SPY"], axis=0)).mean() * 1e4).fillna(0.0)


def event_returns(ev: pd.DataFrame, opens: pd.DataFrame, closes: pd.DataFrame, h: int,
                  drift) -> pd.DataFrame:
    """Open of first_session -> close h-1 sessions later, minus SPY and the stock's drift; one row per event."""
    sessions = closes.index
    ev = ev[ev["ticker"].isin(closes.columns) & ev["first_session"].notna()]
    i = sessions.searchsorted(ev["first_session"].to_numpy())
    j = i + h - 1
    ok = (i < len(sessions)) & (j < len(sessions))
    ev, i, j = ev[ok], i[ok], j[ok]
    cols = closes.columns.get_indexer(ev["ticker"])
    spy = closes.columns.get_loc("SPY")
    o, c = opens.to_numpy(), closes.to_numpy()
    raw = (c[j, cols] / o[i, cols] - 1) * 1e4
    mkt = (c[j, spy] / o[i, spy] - 1) * 1e4
    out = pd.DataFrame({"date": sessions[j], "raw": raw, "gross_bps": raw - mkt - h * drift[cols]})
    return out[out["raw"].abs() <= MAX_MOVE_BPS].dropna()


def screen() -> pd.DataFrame:
    """The cutoff is set only for this call (the dispatcher process must not keep it)."""
    before = os.environ.get("TEAM_DATA_END")
    os.environ["TEAM_DATA_END"] = SCREEN_END
    try:
        return _screen()
    finally:
        if before is None:
            os.environ.pop("TEAM_DATA_END", None)
        else:
            os.environ["TEAM_DATA_END"] = before


def _screen() -> pd.DataFrame:
    opens, closes = panels()
    drift = drift_bps(closes).reindex(closes.columns).to_numpy()
    k8 = rd.filings(forms=["8-K"])
    k8 = k8[(k8["first_session"] >= SCREEN_START) & (k8["first_session"] <= SCREEN_END)]
    rows = []
    for item, what in rd.EIGHT_K_ITEMS.items():
        codes = k8["items"].fillna("").str.split(",")
        ev = k8[codes.apply(lambda c: item in [x.strip() for x in c])]
        ev = ev.drop_duplicates(["ticker", "first_session"])
        for h in HORIZONS:
            tr = event_returns(ev, opens, closes, h, drift)
            if len(tr) < MIN_EVENTS:
                continue
            s = jobs.stats(tr, 0, "week", SCREEN_START, SCREEN_END)
            rows.append({"item": item, "what": what, "family": family(item), "hold": h, "events": s["n_trades"],
                         "weeks": s["n_periods"], "mean_bps": s["mean_bps"], "week_t": s["t"]})
    return pd.DataFrame(rows)


def report(res: pd.DataFrame) -> str:
    n = len(res)
    luck = jobs.luck_t(n)
    res = res.assign(net=res["mean_bps"].abs() - COST_BPS).sort_values("week_t", key=abs, ascending=False)
    res["lead"] = (res["week_t"].abs() >= max(luck, 2.0)) & (res["net"] > 0)
    lines = [f"# Event screen - {date.today()} (tools/screen.py, script only)", "",
             f"Every 8-K event type, {SCREEN_START[:4]}-{SCREEN_END[:4]} ONLY: buy at the open after the filing is "
             f"public, hold 1/3/5 sessions, minus SPY and the stock's own drift. {n} variants; best-of-{n} luck t ~ {luck}.",
             "Negative = the stock lagged (a short idea - shorts cost more). This is a pointer, not a result.", "",
             "**How to use it (Scout / Director):** a LEAD is an event type worth an idea card IF there is a "
             "mechanism for it. Its family is the `family` column; its train period must stay inside "
             f"{SCREEN_START[:4]}-{SCREEN_END[:4]} and its holdout in 2014-2026 (still clean - the screen never "
             "loaded it). Don't add a card for a non-lead just because it's here.", "",
             f"| item | event | family | hold | events | excess bps (week avg) | week t | after {COST_BPS} bps | lead |",
             "|---|---|---|---|---|---|---|---|---|"]
    for r in res.itertuples():
        lines.append(f"| {r.item} | {r.what} | {r.family} | {r.hold}d | {r.events:,} | {r.mean_bps:+.1f} | "
                     f"{r.week_t:+.2f} | {r.net:+.1f} | {'**LEAD**' if r.lead else ''} |")
    lines += ["", "Caveats: today's S&P 1500 only (survivorship); one 8-K often carries several items (e.g. "
              "2.02 with 9.01), so types overlap; unadjusted bars, moves > 50% dropped; no size/liquidity filter."]
    return "\n".join(lines) + "\n"


def log_trials(res: pd.DataFrame) -> int:
    done = {r["family"] for r in budget.rows() if r.get("note") == NOTE}
    added = 0
    for fam, g in res.groupby("family"):
        if fam in done:
            continue
        best = g.loc[g["week_t"].abs().idxmax()]
        budget.append({"date": str(date.today()), "idea_id": "screen", "family": fam, "stage": "search",
                       "variants": len(g), "data": f"{SCREEN_START}..{SCREEN_END}", "result_t": best["week_t"],
                       "result_bps": best["mean_bps"], "verdict": "", "note": NOTE})
        added += 1
    return added


def run(force: bool = False) -> str:
    st = load_json(STATEF, {})
    if not force and OUT.exists() and st.get("date", "") > str(date.today() - timedelta(days=RERUN_DAYS)):
        return f"screen: up to date ({st['date']})"
    res = screen()
    OUT.write_text(report(res), encoding="utf-8")
    added = log_trials(res)
    leads = int(((res["week_t"].abs() >= max(jobs.luck_t(len(res)), 2.0))
                 & (res["mean_bps"].abs() > COST_BPS)).sum())
    save_json(STATEF, {"date": str(date.today()), "variants": len(res), "leads": leads})
    msg = f"screen: {len(res)} variants, {leads} lead(s), {added} famil(ies) logged in trials.csv"
    log(msg, "dispatch")
    return msg


if __name__ == "__main__":
    print(run(force="--force" in sys.argv))
