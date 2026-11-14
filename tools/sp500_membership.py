"""Build team/ref/sp500_membership.csv - point-in-time S&P 500 membership (who was in the index on which dates).

    python tools/sp500_membership.py <path to "S&P 500 Historical Components & Changes (Updated).csv">

Source: github.com/fja05680/sp500 (MIT licence, (c) Farrell J. Aultman), daily component lists since 1996, built from
Andreas Clenow's list + Wikipedia changes. Download the file by hand and re-run this every few months; the result
is committed (small) so every research run sees the same history.

Why: research_data.universe("sp500") is TODAY's members. 280 of 503 have price history from before they joined, and
companies usually join after a strong run - so an "sp500" backtest quietly buys future winners (survivorship /
look-ahead). research_data.pit_filter() drops event rows dated when the stock was not yet (or no longer) a member.

Tickers in the source are as-of each date, so a rename (FB -> META) looks like a removal + an addition. RENAMES maps
today's ticker to its earlier tickers (verified one by one: same company, Yahoo keeps the history under the new
ticker). A rename missing from this map only HIDES real member years of that company - lost data, not a flattering
bias.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

OUT = Path(__file__).resolve().parents[1] / "team" / "ref" / "sp500_membership.csv"
RENAMES = {
    "BALL": ["BLL"], "BKR": ["BHGE", "BHI"], "BNY": ["BK"], "COR": ["ABC"], "CPAY": ["FLT"], "DOC": ["PEAK", "HCP"],
    "EG": ["RE"], "ELV": ["ANTM", "WLP"], "GEN": ["NLOK", "SYMC"], "GL": ["TMK"], "J": ["JEC"], "LHX": ["HRS"],
    "META": ["FB"], "MRSH": ["MMC"], "RTX": ["UTX"], "RVTY": ["PKI"], "TFC": ["BBT"], "VTRS": ["MYL"],
    "WBD": ["DISCA"], "WTW": ["WLTW"],
}


def build(src: Path) -> pd.DataFrame:
    h = pd.read_csv(src, parse_dates=["date"]).sort_values("date")
    alias = {old: new for new, olds in RENAMES.items() for old in olds}
    sets = [{alias.get(t, t).replace(".", "-") for t in s.split(",")} for s in h["tickers"]]
    rows, open_ = [], {}
    for d, s in zip(h["date"], sets):
        for t in s - open_.keys():
            open_[t] = d
        for t in [t for t in open_ if t not in s]:
            rows.append((t, open_.pop(t), d))
    rows += [(t, d0, pd.NaT) for t, d0 in open_.items()]
    out = pd.DataFrame(rows, columns=["ticker", "start", "end"]).sort_values(["ticker", "start"])
    out.attrs["source_end"] = h["date"].iloc[-1]
    return out


def write(src: Path) -> str:
    out = build(src)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    end = out.attrs["source_end"].date()
    with open(OUT, "w", encoding="utf-8", newline="") as f:
        f.write(f"# S&P 500 point-in-time membership, source github.com/fja05680/sp500 (MIT), lists through {end}; "
                f"built by tools/sp500_membership.py. end = first date NOT a member (blank = member at {end}).\n")
        out.assign(start=out["start"].dt.date, end=out["end"].dt.date).to_csv(f, index=False)
    return f"{OUT}: {len(out)} membership spells, {out['ticker'].nunique()} tickers, lists through {end}"


if __name__ == "__main__":
    print(write(Path(sys.argv[1])))
