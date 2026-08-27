"""
Phase 1 pass bar — reconcile the cached panel against facts sourced from
outside it.

verify_panel() checks that the panel is structurally sane: no duplicate dates,
no non-positive prices, columns aligned. That is necessary and not sufficient. A
panel can be perfectly well-formed and still be wrong — silently unadjusted for
a split, off by a dividend, or quietly truncated. Those errors do not announce
themselves; they show up much later as a momentum signal that "works", because a
4:1 split reads as a -75% return.

So this module checks the data against things known independently of it:

  1. Known split dates. A correctly adjusted series shows NO jump across a
     split. This is the highest-value check, because an unadjusted split is both
     the most likely corruption and the most damaging to a momentum signal.

  2. Published index returns. SPY's annual total returns are widely reported;
     the panel's own SPY series should reproduce them within a tolerance that
     allows for dividend-reinvestment timing differences.

  3. An independent fetch path. The panel is built with yf.download(); spot
     tickers are re-fetched with yf.Ticker().history() and compared. Same
     vendor, different code path — this catches batching and column-extraction
     bugs, not vendor error.

What this cannot check: whether the vendor itself is wrong. Detecting that needs
a second vendor, which is a Phase 6 upgrade alongside point-in-time index
membership, and only if the signal proves real.

Usage:
    python -m research.reconcile
"""

from __future__ import annotations

import sys

import pandas as pd

from research import config
from research.panel import load_panel
from shared.utils.logger import get_logger

logger = get_logger(__name__)

# Split events, from public corporate-action records. Format:
# ticker -> (effective date, ratio). A correctly adjusted close shows no jump.
KNOWN_SPLITS: list[tuple[str, str, float]] = [
    ("AAPL", "2014-06-09", 7.0),
    ("AAPL", "2020-08-31", 4.0),
    ("NVDA", "2021-07-20", 4.0),
    ("NVDA", "2024-06-10", 10.0),
    ("TSLA", "2020-08-31", 5.0),
    ("TSLA", "2022-08-25", 3.0),
    ("AMZN", "2022-06-06", 20.0),
    ("GOOGL", "2022-07-18", 20.0),
]

# SPY calendar-year total returns (dividends reinvested), from published index
# performance tables. Measured against the PRIOR year's final close, which is
# what a published calendar-year return means — measuring from the first close
# of the year instead silently drops the first trading day. That error made 2013
# read as +29.0% against a published +32.3%, because 2 January 2013 alone was
# +2.56%; every other year was understated the same way, just less visibly.
SPY_ANNUAL_TOTAL_RETURN: dict[int, float] = {
    2008: -0.368,
    2013: 0.323,
    2017: 0.217,
    2020: 0.184,
    2022: -0.182,
}

SPOT_CHECK_TICKERS = ["AAPL", "MSFT", "JNJ", "XOM", "PG"]

_SPLIT_JUMP_TOLERANCE = 0.25   # |1-day return| that would betray an unadjusted split
# 0.5pp, not the 2pp a "catch an off-by-a-factor error" check would need. Once
# measured correctly the panel reproduced all five published years to within
# 0.07pp, so a loose tolerance would just be hiding future drift.
_SPY_RETURN_TOLERANCE = 0.005
_SPOT_PRICE_TOLERANCE = 0.01   # 1% on matched closes


def check_splits(prices: pd.DataFrame) -> list[dict]:
    """
    For each known split, look at the one-day return across the effective date.
    An adjusted series shows an ordinary move; an unadjusted one shows a drop of
    roughly (1 - 1/ratio) — e.g. -75% for a 4:1.
    """
    results = []
    for ticker, date_str, ratio in KNOWN_SPLITS:
        row: dict = {"ticker": ticker, "date": date_str, "ratio": ratio}
        if ticker not in prices.columns:
            results.append({**row, "status": "skipped", "detail": "not in panel"})
            continue

        series = prices[ticker].dropna()
        split_date = pd.Timestamp(date_str)
        after = series.loc[series.index >= split_date]
        before = series.loc[series.index < split_date]
        if after.empty or before.empty:
            results.append({**row, "status": "skipped", "detail": "date outside coverage"})
            continue

        prev_close = float(before.iloc[-1])
        next_close = float(after.iloc[0])
        move = (next_close - prev_close) / prev_close
        unadjusted_move = (1.0 / ratio) - 1.0

        if abs(move) > _SPLIT_JUMP_TOLERANCE:
            near_unadjusted = abs(move - unadjusted_move) < 0.05
            results.append({
                **row,
                "status": "FAIL",
                "detail": (
                    f"{move:+.1%} across split"
                    + (" — matches an UNADJUSTED split" if near_unadjusted else "")
                ),
            })
        else:
            results.append({**row, "status": "pass", "detail": f"{move:+.2%} across split"})
    return results


def check_spy_annual_returns(context: pd.DataFrame) -> list[dict]:
    """Compare the panel's own SPY series against published annual total returns."""
    results = []
    if config.BENCHMARK not in context.columns:
        return [{"year": "-", "status": "FAIL", "detail": f"{config.BENCHMARK} missing from context panel"}]

    spy = context[config.BENCHMARK].dropna()
    for year, published in SPY_ANNUAL_TOTAL_RETURN.items():
        window = spy.loc[str(year)]
        if len(window) < 200:
            results.append({
                "year": year, "status": "skipped",
                "detail": f"only {len(window)} bars in {year}",
            })
            continue

        # Start from the prior year's final close, not this year's first close.
        prior = spy.loc[: window.index[0] - pd.Timedelta(days=1)]
        if prior.empty:
            results.append({
                "year": year, "status": "skipped",
                "detail": "no prior-year close to measure from",
            })
            continue
        actual = float(window.iloc[-1] / prior.iloc[-1] - 1.0)
        delta = actual - published
        results.append({
            "year": year,
            "status": "pass" if abs(delta) <= _SPY_RETURN_TOLERANCE else "FAIL",
            "detail": f"panel {actual:+.1%} vs published {published:+.1%} (delta {delta:+.1%})",
        })
    return results


def check_independent_fetch(prices: pd.DataFrame, tickers: list[str] | None = None) -> list[dict]:
    """
    Re-fetch a few tickers through yf.Ticker().history() — a different code path
    from the batched yf.download() the panel is built with — and compare closes
    on the dates both cover.
    """
    import yfinance as yf

    results = []
    for ticker in (tickers or SPOT_CHECK_TICKERS):
        if ticker not in prices.columns:
            results.append({"ticker": ticker, "status": "skipped", "detail": "not in panel"})
            continue
        try:
            reference = yf.Ticker(ticker).history(
                start="2015-01-01", end="2016-01-01", auto_adjust=True
            )["Close"]
        except Exception as exc:  # noqa: BLE001 — a vendor failure is a skip, not a panel defect
            results.append({"ticker": ticker, "status": "skipped", "detail": f"fetch failed: {exc}"})
            continue

        if reference.empty:
            results.append({"ticker": ticker, "status": "skipped", "detail": "reference empty"})
            continue

        panel_series = prices[ticker].dropna()
        # Both sides carry their own tz/precision; compare on normalized dates.
        reference.index = pd.to_datetime(reference.index).tz_localize(None).normalize()
        panel_idx = pd.to_datetime(panel_series.index).tz_localize(None).normalize()
        panel_series = pd.Series(panel_series.to_numpy(), index=panel_idx)

        common = panel_series.index.intersection(reference.index)
        if len(common) < 100:
            results.append({
                "ticker": ticker, "status": "skipped",
                "detail": f"only {len(common)} overlapping dates",
            })
            continue

        rel_diff = ((panel_series.loc[common] - reference.loc[common]).abs()
                    / reference.loc[common])
        worst = float(rel_diff.max())
        results.append({
            "ticker": ticker,
            "status": "pass" if worst <= _SPOT_PRICE_TOLERANCE else "FAIL",
            "detail": f"max relative difference {worst:.4%} over {len(common)} dates",
        })
    return results


def run_reconciliation(skip_network: bool = False) -> dict:
    """Run every check and return a report plus an overall pass/fail."""
    panel = load_panel("full")
    prices, context = panel["prices"], panel["context"]

    report = {
        "splits": check_splits(prices),
        "spy_annual_returns": check_spy_annual_returns(context),
        "independent_fetch": (
            [] if skip_network else check_independent_fetch(prices)
        ),
    }

    all_checks = [c for group in report.values() for c in group]
    failures = [c for c in all_checks if c["status"] == "FAIL"]
    skipped = [c for c in all_checks if c["status"] == "skipped"]

    report["summary"] = {
        "total": len(all_checks),
        "passed": len(all_checks) - len(failures) - len(skipped),
        "failed": len(failures),
        "skipped": len(skipped),
        "passed_overall": len(failures) == 0,
    }
    return report


def _print_group(title: str, rows: list[dict]) -> None:
    print(f"\n{title}")
    print("-" * len(title))
    if not rows:
        print("  (none run)")
        return
    for row in rows:
        label = row.get("ticker") or row.get("year")
        mark = {"pass": "  ok  ", "FAIL": " FAIL ", "skipped": " skip "}[row["status"]]
        date = f" {row['date']}" if "date" in row else ""
        print(f"{mark} {label}{date}: {row['detail']}")


def main(argv: list[str] | None = None) -> int:
    skip_network = "--offline" in (argv if argv is not None else sys.argv[1:])
    report = run_reconciliation(skip_network=skip_network)

    _print_group("Known splits (adjusted series should show no jump)", report["splits"])
    _print_group("SPY annual total returns vs published", report["spy_annual_returns"])
    _print_group("Independent fetch path (yf.Ticker.history)", report["independent_fetch"])

    s = report["summary"]
    print(f"\n{s['passed']} passed, {s['failed']} failed, {s['skipped']} skipped")
    print("PHASE 1 RECONCILIATION: " + ("PASS" if s["passed_overall"] else "FAIL"))
    return 0 if s["passed_overall"] else 1


if __name__ == "__main__":
    sys.exit(main())
