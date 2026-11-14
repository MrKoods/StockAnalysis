"""Point-in-time S&P 500 membership (research_data.pit_filter, tools/sp500_membership.py) - 2026-11-13."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import pandas as pd

import research_data as rd
import sp500_membership as sm


def test_known_join_dates():
    m = rd.sp500_member(["TSLA", "TSLA", "META", "META", "NVDA", "AAPL"],
                        ["2020-12-18", "2020-12-21", "2013-12-20", "2013-12-23", "2001-11-29", "1999-06-01"])
    assert m.tolist() == [False, True, False, True, False, True]


def test_renamed_company_keeps_its_member_years():
    # FB -> META (2022-06-09), ANTM -> ELV (2022-06-28), NLOK/SYMC -> GEN, BBT -> TFC
    m = rd.sp500_member(["META", "ELV", "GEN", "TFC"], ["2018-01-02", "2015-01-02", "2010-01-04", "2005-01-03"])
    assert m.all()


def test_left_and_never_member():
    spells, _ = rd._pit_spells()
    gone = spells[spells["end"].notna() & ~spells["ticker"].isin(spells[spells["end"].isna()]["ticker"])].iloc[0]
    after = gone["end"] + pd.Timedelta(days=5)
    assert not rd.sp500_member([gone["ticker"]], [after]).iloc[0]
    assert not rd.sp500_member(["NOTATICKER"], ["2015-01-02"]).iloc[0]


def test_after_source_end_uses_current_list():
    _, end = rd._pit_spells()
    later = end + pd.Timedelta(days=30)
    cur = rd.universe("sp500")
    assert rd.sp500_member([cur[0]], [later]).iloc[0]


def test_pit_filter_keeps_order_and_tz_dates():
    df = pd.DataFrame({"ticker": ["TSLA", "AAPL", "TSLA"],
                       "entry_session": pd.to_datetime(["2019-01-02", "2019-01-02", "2021-01-04"]).tz_localize(
                           "America/New_York")}, index=[7, 8, 9])
    out = rd.pit_filter(df)
    assert out.index.tolist() == [8, 9]


def test_builder_merges_renames(tmp_path):
    src = tmp_path / "h.csv"
    src.write_text('date,tickers\n2020-01-02,"AAA,FB"\n2021-01-04,"AAA,FB,BBB"\n2022-06-09,"META,BBB"\n',
                   encoding="utf-8")
    out = sm.build(src)
    meta = out[out.ticker == "META"]
    assert len(meta) == 1 and str(meta.start.iloc[0].date()) == "2020-01-02" and pd.isna(meta.end.iloc[0])
    aaa = out[out.ticker == "AAA"].iloc[0]
    assert str(aaa.end.date()) == "2022-06-09"


def test_harness_refuses_sp500_study_without_pit_filter(tmp_path):
    import jobs
    t = tmp_path / "test.py"
    t.write_text("ev = rd.filings(forms=['8-K'])\nu = rd.universe('sp500')\n", encoding="utf-8")
    assert jobs.pit_problems({"universe": ["sp500"]}, t)
    assert jobs.pit_problems({"universe": ["sp500", "sp400"]}, t)          # code asks for sp500 only
    t.write_text("ev = rd.pit_filter(ev, 'entry_session')\nu = rd.universe('sp500')\n", encoding="utf-8")
    assert jobs.pit_problems({"universe": ["sp500"]}, t) == []
    t.write_text("u = rd.universe('all')\n", encoding="utf-8")
    assert jobs.pit_problems({"universe": ["sp500", "sp400", "sp600"]}, t) == []
