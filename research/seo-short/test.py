"""seo-short -- TRAIN/HOLDOUT test (data ONLY via research_data as rd).

Hypothesis: when an already-public S&P 1500 company prices a seasoned equity offering it files a 424B4 (final
prospectus) or 424B5 (shelf prospectus supplement) on EDGAR. Myers-Majluf (1984) adverse selection says equity
is issued when managers think the stock rich; Loughran-Ritter (1997), D'Mello-Ferris (2000), Spiess-Affleck-
Graves (1995) measure ~-150 to -300 bps over the first 3-5 trading days post-offering. We SHORT at the CLOSE of
the session AFTER the first tradable session (= the earliest a once-daily after-close dispatch can actually
fill -- one session after the first reaction) and cover at the CLOSE H sessions later. Returns are SPY-hedged
GROSS bps on the SHORT side (spy_ret - stock_ret, close->close); the harness subtracts cost_bps. This matches
paper_runner's short-hedged defn (real_bps - sgn*spy_bps).

Variants (12): form-set in {b4=['424B4'], b5=['424B5'], both=['424B4','424B5']} x universe in
{sp1500 (sp500+sp400+sp600), sp46 (sp400+sp600)} x hold H in {3, 5}. `chosen` is PRE-REGISTERED =
'both_sp1500_h3' (the idea card's primary rule: any 424B4/424B5, full S&P 1500, the ~3-day academic horizon --
see PLAN.md). The other 11 configs are a robustness map for the Skeptic only and are never carried to holdout.
Central robustness read (NOT a switch of chosen): b4 vs b5. 424B4 is the form IPOs also use, and we lack
point-in-time membership, so a now-member's old IPO 424B4 can leak in; 424B5 (shelf takedown) is almost never
an IPO but is diluted by investment-grade DEBT shelves. If b4 >> b5 suspect IPO first-day contamination; if
both collapse the blended SEO signal is debt-diluted noise.
"""
from __future__ import annotations

import math

import pandas as pd

import research_data as rd

COST_BPS = 25.0                       # MUST equal plan.json cost_bps (ranks variants in train only)
HOLD_GRID = (3, 5)
UNIV_GRID = ("sp1500", "sp46")
FORM_SETS = {"b4": ["424B4"], "b5": ["424B5"], "both": ["424B4", "424B5"]}
PREREGISTERED = "both_sp1500_h3"
MAX_MOVE = 0.50                       # drop bars with |stock move| > 50% (bad-bar / unadjusted guard)


def _members() -> dict[str, set]:
    sp500 = set(rd.universe("sp500"))
    sp400 = set(rd.universe("sp400"))
    sp600 = set(rd.universe("sp600"))
    return {"sp1500": sp500 | sp400 | sp600, "sp46": sp400 | sp600}


def _events(tickers) -> pd.DataFrame:
    """Every 424B4/424B5 prospectus with a known first tradable session, one row per
    (ticker, form, first_session). Columns: ticker, form, first_session (Timestamp)."""
    f = rd.filings(forms=["424B4", "424B5"], tickers=sorted(tickers))
    if f.empty:
        return f
    f = f[f["first_session"].notna()].copy()
    f["form"] = f["form"].astype(str).str.replace("/A", "", regex=False).str.strip()
    f["first_session"] = pd.to_datetime(f["first_session"]).dt.normalize()
    f = f.drop_duplicates(["ticker", "form", "first_session"])
    return f[["ticker", "form", "first_session"]]


def _trades(ev: pd.DataFrame, members: set, prices: dict, spy: pd.DataFrame, hold: int) -> list[dict]:
    spy_idx = pd.DatetimeIndex(spy.index).normalize()
    spy_close = spy["close"].to_numpy()
    out = []
    for tkr, fs in ev[["ticker", "first_session"]].itertuples(index=False):
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
        gross = (sc_x / sc_e - 1) * 1e4 - (cx / ce - 1) * 1e4   # SPY-hedged, SHORT, close->close
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


def _config(name: str, ev, members, prices, spy):
    fkey, univ, htag = name.split("_")
    h = int(htag[1:])
    forms = FORM_SETS[fkey]
    sub = ev[ev["form"].isin(forms)]
    return _trades(sub, members[univ], prices, spy, h)


def run(start: str, end: str, phase: str, chosen: str | None) -> dict:
    members = _members()
    all_syms = members["sp1500"]
    ev = _events(all_syms)
    syms = sorted(ev["ticker"].astype(str).unique()) if len(ev) else []
    prices = rd.daily(syms + ["SPY"])
    spy = prices.get("SPY")
    if spy is None:
        raise RuntimeError("SPY daily bars missing from the archive -- required for the hedge")

    if phase == "holdout":
        return {"variants": 1, "chosen": chosen,
                "trades": {chosen: _config(chosen, ev, members, prices, spy)}}

    names = [f"{fk}_{u}_h{h}" for fk in FORM_SETS for u in UNIV_GRID for h in HOLD_GRID]
    trades = {n: _config(n, ev, members, prices, spy) for n in names}
    best = max(trades, key=lambda k: _rank_t(trades[k]))     # reported for the Skeptic only
    print(f"train: {len(trades)} variants; best-looking (NOT chosen) = {best}; "
          f"pre-registered chosen = {PREREGISTERED}")
    return {"variants": len(trades), "chosen": PREREGISTERED, "trades": trades}
