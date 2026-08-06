"""
Mines the exclusion_summary and ev_outlier_z columns paper_runner.py has been
persisting to ticker_results since the fix-2/fix-6 work — data that was
already being computed per scan but, before those fixes, thrown away right
after the top-ranked structure was read. On its own, one scan's
exclusion_summary just explains why one ticker got no recommended structure;
aggregated across every scan logged so far, it answers a different, more
useful question: is some filter (R:R floor, capital %, Greeks, liquidity)
systematically zeroing out an entire sector's structures, or is a specific
structure a repeat outlier offender rather than a one-off?

Usage: python -m paper_trading.ev_outlier_and_exclusion_diagnostic
"""

import re
from collections import Counter
from pathlib import Path
from typing import Optional

import pandas as pd

from app_ui import db as app_db

# Matches build_discord_exclusion_summary's own output format exactly
# (swing_model/trade_selector.py) — "{count} structures excluded — {reason}"
# pairs joined by "; ". Parsing the Discord-facing string back apart is a bit
# lossy (only the top 5 reasons per row survive that function's
# counts.most_common(5)) but avoids a second, parallel storage format just for
# this diagnostic.
_EXCLUSION_PATTERN = re.compile(r"(\d+) structures excluded — ([\w ]+)")

_MIN_ROWS_FOR_MEANINGFUL_READ = 30


def collect_exclusion_rows(db_path: Optional[Path] = None) -> pd.DataFrame:
    """
    Every logged ticker_result with a non-null exclusion_summary (i.e. it
    cleared STRUCTURE_EVAL_DIAGNOSTIC_THRESHOLD and structure ranking ran),
    alongside its sector, ticker, structures_eligible_after_filters, and
    whichever structure (if any) was actually recommended.
    """
    conn = app_db.get_connection(db_path)
    try:
        rows = conn.execute(
            """
            SELECT ticker, sector, trade_structure, structures_eligible_after_filters, exclusion_summary
            FROM ticker_results
            WHERE exclusion_summary IS NOT NULL
            """
        ).fetchall()
    finally:
        conn.close()
    return pd.DataFrame([dict(r) for r in rows])


def collect_ev_outlier_rows(db_path: Optional[Path] = None) -> pd.DataFrame:
    """Every logged ticker_result with a non-null ev_outlier_z."""
    conn = app_db.get_connection(db_path)
    try:
        rows = conn.execute(
            """
            SELECT ticker, sector, trade_structure, expected_value, ev_outlier_z
            FROM ticker_results
            WHERE ev_outlier_z IS NOT NULL
            """
        ).fetchall()
    finally:
        conn.close()
    return pd.DataFrame([dict(r) for r in rows])


def aggregate_exclusion_reasons(df: pd.DataFrame, group_by: Optional[str] = None) -> pd.DataFrame:
    """
    Parse every row's exclusion_summary string and sum reason counts, either
    overall (group_by=None) or split by a column (e.g. "sector", "ticker").

    Returns a DataFrame with one row per (group, reason) — or just per reason
    when group_by is None — sorted by count descending within each group.
    """
    if df.empty:
        return pd.DataFrame(columns=["reason", "count"])

    records = []
    for _, row in df.iterrows():
        group_key = row[group_by] if group_by else "_all"
        for count_str, reason in _EXCLUSION_PATTERN.findall(str(row["exclusion_summary"])):
            records.append({"group": group_key, "reason": reason.strip(), "count": int(count_str)})

    if not records:
        return pd.DataFrame(columns=["reason", "count"])

    parsed = pd.DataFrame(records)
    agg = parsed.groupby(["group", "reason"], as_index=False)["count"].sum()
    agg = agg.sort_values(["group", "count"], ascending=[True, False]).reset_index(drop=True)
    if group_by is None:
        agg = agg.drop(columns=["group"])
    else:
        agg = agg.rename(columns={"group": group_by})
    return agg


def find_zero_eligible_repeat_offenders(df: pd.DataFrame, min_occurrences: int = 3) -> pd.DataFrame:
    """
    Tickers where structures_eligible_after_filters == 0 has happened at least
    `min_occurrences` times — the TSM/AMZN/PFE pattern (clears the diagnostic
    threshold repeatedly but never gets a recommended structure at all), now
    detectable directly instead of noticed by hand comparing scan logs.
    """
    if df.empty:
        return pd.DataFrame(columns=["ticker", "zero_eligible_count"])
    zero = df[df["structures_eligible_after_filters"] == 0]
    counts = zero.groupby("ticker").size().reset_index(name="zero_eligible_count")
    return counts[counts["zero_eligible_count"] >= min_occurrences].sort_values(
        "zero_eligible_count", ascending=False
    ).reset_index(drop=True)


def summarize_ev_outliers(df: pd.DataFrame, threshold: float = 3.5) -> pd.DataFrame:
    """
    Per-structure outlier rate: how many logged readings for that structure
    were flagged (|ev_outlier_z| >= threshold) out of how many total, plus the
    largest single |z| seen — a structure with a high flagged-rate is a repeat
    offender (worth checking its EV formula), not just an unlucky one-off.
    """
    if df.empty:
        return pd.DataFrame(columns=["trade_structure", "total_readings", "flagged_count", "max_abs_z"])
    df = df.copy()
    df["flagged"] = df["ev_outlier_z"].abs() >= threshold
    summary = df.groupby("trade_structure").agg(
        total_readings=("ev_outlier_z", "size"),
        flagged_count=("flagged", "sum"),
        max_abs_z=("ev_outlier_z", lambda s: s.abs().max()),
    ).reset_index()
    summary["flagged_rate"] = (summary["flagged_count"] / summary["total_readings"]).round(3)
    return summary.sort_values("flagged_count", ascending=False).reset_index(drop=True)


def main() -> None:
    exclusion_df = collect_exclusion_rows()
    outlier_df = collect_ev_outlier_rows()

    if exclusion_df.empty and outlier_df.empty:
        print("No logged exclusion_summary or ev_outlier_z data yet — nothing to mine.")
        return

    report_dir = Path("paper_trading/reports")
    report_dir.mkdir(parents=True, exist_ok=True)

    if not exclusion_df.empty:
        n = len(exclusion_df)
        print(f"\n=== Exclusion reason mining — {n} logged rows with structure ranking ===\n")
        if n < _MIN_ROWS_FOR_MEANINGFUL_READ:
            print(
                f"Only {n} rows logged so far (< {_MIN_ROWS_FOR_MEANINGFUL_READ}) — treat every "
                "reading below as a placeholder, not a real answer yet.\n"
            )

        overall = aggregate_exclusion_reasons(exclusion_df)
        print("Top exclusion reasons overall:")
        print(overall.head(10).to_string(index=False))

        by_sector = aggregate_exclusion_reasons(exclusion_df, group_by="sector")
        print("\nTop exclusion reason per sector:")
        for sector in by_sector["sector"].dropna().unique():
            top = by_sector[by_sector["sector"] == sector].head(3)
            print(f"  {sector}:")
            for _, r in top.iterrows():
                print(f"    {r['reason']}: {r['count']}")

        offenders = find_zero_eligible_repeat_offenders(exclusion_df)
        if not offenders.empty:
            print("\nTickers repeatedly clearing the diagnostic threshold with ZERO eligible "
                  "structures (the TSM/AMZN/PFE pattern):")
            print(offenders.to_string(index=False))
        else:
            print("\nNo repeat zero-eligible-structure tickers found yet.")

        overall.to_csv(report_dir / "exclusion_reasons_overall.csv", index=False)
        by_sector.to_csv(report_dir / "exclusion_reasons_by_sector.csv", index=False)
        offenders.to_csv(report_dir / "zero_eligible_repeat_offenders.csv", index=False)

    if not outlier_df.empty:
        print(f"\n=== EV outlier mining — {len(outlier_df)} logged rows with ev_outlier_z ===\n")
        outlier_summary = summarize_ev_outliers(outlier_df)
        print(outlier_summary.to_string(index=False))
        outlier_summary.to_csv(report_dir / "ev_outlier_summary_by_structure.csv", index=False)

    print(f"\nSaved reports to {report_dir}/")


if __name__ == "__main__":
    main()
