"""proxy-contest-long -- TRAIN/HOLDOUT test (data ONLY via research_data as rd).

Hypothesis: when an activist escalates to a contested director election / shareholder proposal, the DISSIDENT
files proxy soliciting material with the SEC -- DFAN14A (non-management additional soliciting material; the
first public shot) and later DEFC14A (the dissident's definitive contested proxy statement). Fos (2017) finds
targets earn ~6.5% CAR around proxy-contest announcements; for S&P 400/600 names the DFAN14A often IS the first
public disclosure (news does not pre-leak the way it does for large caps). We go LONG the TARGET (the S&P-1500
name the material is filed AGAINST -- EDGAR indexes 14A soliciting material under the subject company, so
rd.filings(tickers=universe) returns the target, as for 13D) and hold a few days.

CAMPAIGN DEDUP: a dissident files MANY DFAN14A pieces per contest (letters, decks, press releases). We keep only
the FIRST filing of a campaign per ticker -- a filing is a new event only if there was NO prior filing of the
same form for that ticker in the preceding 90 calendar days. This isolates the campaign-opening disclosure and
avoids entering the same contest a dozen times.

Entry timing is paper-matchable and leak-free: enter at the CLOSE of the session AFTER the first tradable
session (first_session+1). The once-daily runner fires after the close and the SEC daily index reaches our
archive the next weekday, so the earliest close we could actually fill is first_session+1 -- one session after
the first public reaction. Exit at the CLOSE H sessions later. Returns are SPY-hedged GROSS bps, LONG side
(stock_ret - spy_ret, close->close); the harness subtracts cost_bps. Matches paper_runner's long hedged
definition (real_bps - sgn*spy_bps with sgn=+1).

Variants (12): form in {DFAN14A, DEFC14A} x universe in {sp46 (sp400+sp600), sp1500} x hold H in {1, 3, 5}.
`chosen` is PRE-REGISTERED = 'dfan_sp46_h3' -- the earliest contest signal (DFAN14A), the mid/small-cap universe
the mechanism actually predicts (the filing IS the announcement there), and the evidence's few-day drift horizon.
The other eleven configs are a robustness map for the Skeptic only and never go to the holdout. SC 14N (Rule
14a-11 shareholder nominations) was considered and EXCLUDED: Rule 14a-11 was vacated in 2011 (Business Roundtable
v. SEC), so the form is essentially unused -- it would add an empty variant and raise the luck bar for no signal.
NOTE: the shared cost floor is the most-expensive index in the plan universe (sp600 close->close), so the sp1500
variant (which includes cheaper sp500 names) is over-charged -- a conservative bias documented in PLAN.md.
"""
from __future__ import annotations

import math

import pandas as pd

import research_data as rd

COST_BPS = 25.0                       # MUST equal plan.json cost_bps (ranks variants in train only)
GAP_DAYS = 90                         # a filing starts a new event only after >90 quiet days (campaign dedup)
MAX_MOVE = 0.50                       # drop bars with |stock move| > 50% (bad-bar / unadjusted guard)

FORMS = {"dfan": "DFAN14A", "defc": "DEFC14A"}        # name tag -> exact SEC form string
UNIVS = ("sp46", "sp1500")
HOLDS = (1, 3, 5)
CONFIGS = {f"{fk}_{uk}_h{h}": (fv, uk, h)
           for fk, fv in FORMS.items() for uk in UNIVS for h in HOLDS}
PREREGISTERED = "dfan_sp46_h3"


def _members() -> dict[str, set]:
    sp500 = set(rd.universe("sp500"))
    sp400 = set(rd.universe("sp400"))
    sp600 = set(rd.universe("sp600"))
    return {"sp46": sp400 | sp600, "sp1500": sp500 | sp400 | sp600}


def _first_in_campaign(f: pd.DataFrame) -> pd.DataFrame:
    """Keep only the campaign-opening filing per ticker: a row survives only if the same ticker had no earlier
    kept-or-skipped filing within GAP_DAYS. Sliding window on every filing so a continuous drip collapses to
    one event and a new contest (>90 quiet days later) re-triggers."""
    f = f.sort_values(["ticker", "first_session"])
    keep, last = [], {}
    for tkr, fs in f[["ticker", "first_session"]].itertuples(index=False):
        prev = last.get(tkr)
        if prev is None or (fs - prev).days > GAP_DAYS:
            keep.append((tkr, fs))
        last[tkr] = fs                                 # always advance the window
    return pd.DataFrame(keep, columns=["ticker", "first_session"])


def _events(form: str, tickers) -> pd.DataFrame:
    """Campaign-opening proxy-solicitation filings of `form` with a known first tradable session.
    Columns: ticker, first_session (Timestamp). EDGAR indexes 14A soliciting material under its SUBJECT
    company, so a universe ticker here is the TARGET of the contest."""
    f = rd.filings(forms=[form], tickers=sorted(tickers))
    if f.empty:
        return f
    f = f[f["form"].astype(str).str.strip() == form]              # exact form -> drop any /A amendments
    f = f[f["first_session"].notna()].copy()
    f["first_session"] = pd.to_datetime(f["first_session"]).dt.normalize()
    f = f.drop_duplicates(["ticker", "first_session"])
    return _first_in_campaign(f)


def _trades(ev: pd.DataFrame, members: set, prices: dict, spy: pd.DataFrame, hold: int) -> list[dict]:
    spy_idx = pd.DatetimeIndex(spy.index).normalize()
    spy_close = spy["close"].to_numpy()
    out = []
    for tkr, fs in ev.itertuples(index=False):
        if tkr not in members:
            continue
        df = prices.get(tkr)
        if df is None:
            continue
        idx = pd.DatetimeIndex(df.index).normalize()
        pos = int(idx.searchsorted(fs, side="left"))
        if pos >= len(idx) or idx[pos] != fs:          # first_session must be a real bar for this ticker
            continue
        entry_pos = pos + 1                             # CLOSE of the session AFTER first_session
        exit_pos = entry_pos + hold
        if exit_pos >= len(idx):
            continue
        entry_day, exit_day = idx[entry_pos], idx[exit_pos]
        se = int(spy_idx.searchsorted(entry_day, side="left"))
        sx = int(spy_idx.searchsorted(exit_day, side="left"))
        if (se >= len(spy_idx) or sx >= len(spy_idx)
                or spy_idx[se] != entry_day or spy_idx[sx] != exit_day):
            continue
        ce, cx = float(df["close"].iloc[entry_pos]), float(df["close"].iloc[exit_pos])   # close->close hold
        sc_e, sc_x = float(spy_close[se]), float(spy_close[sx])
        if not (ce > 0 and cx > 0 and sc_e > 0 and sc_x > 0):
            continue
        if abs(cx / ce - 1) > MAX_MOVE:                # bad-bar guard
            continue
        gross = (cx / ce - 1) * 1e4 - (sc_x / sc_e - 1) * 1e4   # SPY-hedged, LONG, close->close
        out.append({"date": exit_day, "gross_bps": gross})
    return out


def _rank_t(trades) -> float:
    """Week-clustered net t, used only to report which variant looked best in train."""
    if not trades:
        return float("-inf")
    df = pd.DataFrame(trades)
    net = df["gross_bps"].astype(float) - COST_BPS
    per = net.groupby(pd.to_datetime(df["date"]).dt.to_period("W")).mean()
    n = len(per)
    if n < 2:
        return float("-inf")
    sd = per.std(ddof=1)
    return float(per.mean() / (sd / math.sqrt(n))) if sd > 0 else 0.0


def _config(name: str, ev_by_form: dict, members: dict, prices: dict, spy: pd.DataFrame):
    form, uk, h = CONFIGS[name]
    return _trades(ev_by_form[form], members[uk], prices, spy, h)


def run(start: str, end: str, phase: str, chosen: str | None) -> dict:
    members = _members()
    ev_by_form = {fv: _events(fv, members["sp1500"]) for fv in sorted(set(FORMS.values()))}
    syms = sorted({t for ev in ev_by_form.values() if len(ev) for t in ev["ticker"].astype(str)})
    prices = rd.daily(syms + ["SPY"])
    spy = prices.get("SPY")
    if spy is None:
        raise RuntimeError("SPY daily bars missing from the archive -- required for the hedge")

    if phase == "holdout":
        return {"variants": 1, "chosen": chosen,
                "trades": {chosen: _config(chosen, ev_by_form, members, prices, spy)}}

    trades = {n: _config(n, ev_by_form, members, prices, spy) for n in CONFIGS}
    best = max(trades, key=lambda k: _rank_t(trades[k]))     # reported for the Skeptic only
    print(f"train: {len(trades)} variants; best-looking (NOT chosen) = {best}; "
          f"pre-registered chosen = {PREREGISTERED}")
    return {"variants": len(CONFIGS), "chosen": PREREGISTERED, "trades": trades}
