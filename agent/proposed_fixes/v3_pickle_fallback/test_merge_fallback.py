"""
Test for the pickle-fallback fix in daytrade/data.py.
Run from StockAnalysis-V3 directory: python -m pytest agent/proposed_fixes/v3_pickle_fallback/test_merge_fallback.py -v
(or copy this file into StockAnalysis-V3/tests/ and run: python -m pytest tests/test_merge_fallback.py -v)
"""
import sys
import importlib
import tempfile
from pathlib import Path
from unittest import mock

import pandas as pd
import pytest


def make_bars(n: int = 5) -> pd.DataFrame:
    idx = pd.date_range("2026-01-01", periods=n, freq="D", tz=None)
    return pd.DataFrame(
        {"open": 1.0, "high": 1.1, "low": 0.9, "close": 1.0, "volume": 100},
        index=idx,
    )


@pytest.fixture()
def tmp_data_dir(tmp_path, monkeypatch):
    """Point DATA_DIR at a temp directory for the test."""
    import daytrade.data as dm
    monkeypatch.setattr(dm, "DATA_DIR", tmp_path)
    return tmp_path


def test_fresh_archive_writes_parquet(tmp_data_dir):
    import daytrade.data as dm
    bars = make_bars(5)
    n = dm._merge_into_archive("AAPL", "1d", bars)
    assert n == 5
    assert (tmp_data_dir / "1d" / "AAPL.parquet").exists()


def test_second_write_merges_and_deduplicates(tmp_data_dir):
    import daytrade.data as dm
    bars1 = make_bars(5)
    bars2 = make_bars(8)  # overlaps days 0-4 with bars1
    dm._merge_into_archive("AAPL", "1d", bars1)
    n = dm._merge_into_archive("AAPL", "1d", bars2)
    assert n == 8  # dedup keeps the latest, no double-counting


def test_falls_back_to_pickle_when_parquet_blocked(tmp_data_dir):
    import daytrade.data as dm
    bars = make_bars(5)
    # Simulate pyarrow DLL blocked: both read_parquet and to_parquet raise ImportError
    with mock.patch("pandas.DataFrame.to_parquet", side_effect=ImportError("DLL blocked")):
        with mock.patch("pandas.read_parquet", side_effect=ImportError("DLL blocked")):
            n = dm._merge_into_archive("AAPL", "1d", bars)
    assert n == 5
    pkl = tmp_data_dir / "1d" / "AAPL.pkl"
    assert pkl.exists(), "should write .pkl when parquet is blocked"


def test_load_prefers_pkl_over_parquet(tmp_data_dir):
    import daytrade.data as dm
    bars = make_bars(5)
    # Write via fallback (no parquet, only pkl)
    with mock.patch("pandas.DataFrame.to_parquet", side_effect=ImportError("DLL blocked")):
        with mock.patch("pandas.read_parquet", side_effect=ImportError("DLL blocked")):
            dm._merge_into_archive("AAPL", "1d", bars)
    # Now load — should find and return .pkl data
    result = dm.load("AAPL", "1d")
    assert len(result) == 5


def test_load_returns_empty_when_nothing_exists(tmp_data_dir):
    import daytrade.data as dm
    result = dm.load("FAKE", "1d")
    assert len(result) == 0
