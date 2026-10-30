import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import research_data as rd  # noqa: E402

SESSIONS = pd.DatetimeIndex(["2024-05-22", "2024-05-23", "2024-05-24", "2024-05-28"])  # Mon 05-27 holiday


def test_first_session_timing():
    ts = pd.Series(pd.to_datetime([
        "2024-05-22 08:00",   # before the open -> same day
        "2024-05-22 16:21",   # after the close (NVDA split 8-K) -> next session
        "2024-05-22 10:00",   # during the session -> next session (the open already happened)
        "2024-05-22 00:00",   # no time given (old filing) -> treated as after the close
        "2024-05-24 18:00",   # Friday evening -> Tuesday (Monday holiday)
        "2024-05-28 17:00",   # after the last known session -> unknown, never a guessed date
    ]))
    got = rd._first_session(ts, SESSIONS)
    want = pd.to_datetime(["2024-05-22", "2024-05-23", "2024-05-23", "2024-05-23", "2024-05-28", None])
    assert list(got) == list(want)


def test_filings_cutoff_and_filters(tmp_path, monkeypatch):
    df = pd.DataFrame({
        "ticker": ["A", "A", "B", "B"], "cik": [1, 1, 2, 2], "form": ["8-K", "8-K/A", "10-Q", "8-K"],
        "filing_date": pd.to_datetime(["2024-05-22", "2024-05-23", "2024-05-23", "2024-05-29"]),
        "accepted": pd.to_datetime(["2024-05-22 16:21", "2024-05-23 07:00", "2024-05-23 12:00", "2024-05-29 09:00"]),
        "items": ["2.02,8.01", "5.02", "", "5.02"], "accession": list("wxyz"), "primary_doc": "", "description": ""})
    df.to_parquet(tmp_path / "filings.parquet")
    monkeypatch.setattr(rd, "EDGAR", tmp_path)
    monkeypatch.setattr(rd, "_sessions", lambda end: SESSIONS[SESSIONS <= end])
    monkeypatch.setenv("TEAM_DATA_END", "2024-05-24")
    out = rd.filings()
    assert list(out["accession"]) == ["w", "x", "y"]                 # the 05-29 filing is after the cutoff
    assert list(rd.filings(forms=["8-K"])["accession"]) == ["w", "x"]   # 8-K matches 8-K/A
    assert list(rd.filings(items=["5.02"])["accession"]) == ["x"]
    assert out.loc[out.accession == "w", "first_session"].item() == pd.Timestamp("2024-05-23")


def test_splits_hide_unannounced_future(tmp_path, monkeypatch):
    sp = pd.DataFrame({"ticker": ["N", "M", "Q"], "ex_date": pd.to_datetime(["2024-06-10", "2024-06-10", "2024-05-01"]),
                       "ratio": [10.0, 2.0, 3.0],
                       "announced": pd.to_datetime(["2024-05-22 16:21", None, None]),
                       "announce_form": ["8-K", None, None], "announce_accession": ["w", None, None],
                       "found_by": ["full_text_search", "not_found", "not_found"]})
    sp.to_parquet(tmp_path / "splits.parquet")
    monkeypatch.setattr(rd, "EDGAR", tmp_path)
    monkeypatch.setattr(rd, "_sessions", lambda end: SESSIONS[SESSIONS <= end])
    monkeypatch.setenv("TEAM_DATA_END", "2024-05-24")
    out = rd.splits()
    # N: announced before the cutoff -> visible; M: no announcement and not yet effective -> hidden; Q: effective
    assert sorted(out["ticker"]) == ["N", "Q"]
