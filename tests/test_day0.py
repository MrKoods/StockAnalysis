"""2026-11-14: day-0 entries (paper_runner same_close + run_day0, tools/edgar_live.py), 8-K text, FOMC dates,
SEC's 13D/13G rename."""
import json
import sys
from datetime import date, datetime
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import edgar_live  # noqa: E402
import edgar_text  # noqa: E402
import paper_runner as pr  # noqa: E402
import research_data as rd  # noqa: E402

D = [date(2026, 10, 19), date(2026, 10, 20), date(2026, 10, 21), date(2026, 10, 22)]


def frame(rows):
    return pd.DataFrame(rows, columns=["Open", "High", "Low", "Close", "Volume"], index=D[: len(rows)])


BARS = {"SPY": frame([[100, 101, 99, 100, 1]] * 4),
        "UP": frame([[50, 51, 49, 50, 1], [100, 104, 99, 103, 1], [103, 106, 102, 105, 1], [105, 110, 104, 108, 1]])}
DAY0 = {"entry_at": "same_close", "hold_sessions": 1, "exit_at": "close", "cost_bps": 10}


def row(sig="2026-10-20"):
    return {"strategy": "x", "signal_date": sig, "ticker": "UP", "side": "long", "status": "pending"}


def test_same_close_buys_the_signal_days_close():
    r = pr.advance(row(), DAY0, BARS, D)
    assert r["entry_date"] == "2026-10-20" and r["entry_px"] == 103          # signal day's own close
    assert r["exit_date"] == "2026-10-21" and r["exit_px"] == 105


def test_next_close_mode_unchanged():
    r = pr.advance(row(), DAY0 | {"entry_at": "close"}, BARS, D)
    assert r["entry_date"] == "2026-10-21" and r["entry_px"] == 105


@pytest.fixture
def team(tmp_path, monkeypatch):
    (tmp_path / "strategies" / "d0").mkdir(parents=True)
    (tmp_path / "strategies" / "nx").mkdir(parents=True)
    code = ("seen = {}\n"
            "def universe():\n    return ['UP']\n"
            "def signals(asof, bars):\n    seen['last_bar'] = bars['UP'].index[-1]\n"
            "    return [{'ticker': 'UP', 'side': 'long'}]\n")
    for sid, entry in (("d0", "same_close"), ("nx", "close")):
        (tmp_path / "strategies" / sid / "strategy.py").write_text(code, encoding="utf-8")
        (tmp_path / "strategies" / sid / "spec.json").write_text(json.dumps(DAY0 | {"entry_at": entry,
                                                                              "rule": {}}), encoding="utf-8")
    reg = tmp_path / "strategies" / "registry.json"
    reg.write_text(json.dumps({"strategies": {"d0": {"status": "active"}, "nx": {"status": "active"}}}))
    monkeypatch.setattr(pr, "TEAM", tmp_path)
    monkeypatch.setattr(pr, "REGISTRY", reg)
    monkeypatch.setattr(pr, "PAPER", tmp_path / "paper")
    monkeypatch.setattr(pr, "stopped", lambda: False)
    calls = []
    monkeypatch.setattr(pr, "download", lambda uni, asof: calls.append(asof) or BARS)
    return SimpleNS(calls=calls)


class SimpleNS:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def test_run_day0_only_same_close_and_never_today(team):
    out = pr.run_day0(date(2026, 10, 21))
    assert out == {"d0": 1}                                   # the next-close strategy is not touched
    assert team.calls == [date(2026, 10, 20)]                 # yesterday's (complete) bars, yesterday's cache key
    rows = pr.read_ledger("d0")
    assert [r["signal_date"] for r in rows] == ["2026-10-21"] and rows[0]["status"] == "pending"
    assert pr.run_day0(date(2026, 10, 21)) == {"d0": 0}       # once per day


def test_after_close_run_makes_no_day0_signals(team, monkeypatch):
    monkeypatch.setattr(pr, "score", lambda rows, rule: {})
    import quotes
    monkeypatch.setattr(quotes, "load_quotes", lambda: {})
    st = pr.run_one("d0", date(2026, 10, 21), {}, dry_run=True)
    assert st["new_signals"] == 0


FEED = """<feed><entry>
<title>8-K - ACME CORP (0000012345) (Filer)</title>
<summary type="html"> &lt;b&gt;Filed:&lt;/b&gt; 2026-11-13 &lt;b&gt;AccNo:&lt;/b&gt; 0000012345-26-000001 &lt;b&gt;Size:&lt;/b&gt; 1 MB
&lt;br&gt;Item 8.01: Other Events
&lt;br&gt;Item 9.01: Financial Statements and Exhibits</summary>
<updated>2026-11-13T15:12:00-05:00</updated>
<category scheme="https://www.sec.gov/" label="form type" term="8-K"/>
</entry></feed>"""


def test_feed_parse_gives_archive_columns_in_et():
    r = edgar_live.parse(FEED)[0]
    assert r["cik"] == 12345 and r["form"] == "8-K" and r["items"] == "8.01,9.01"
    assert r["accepted"] == pd.Timestamp("2026-11-13 15:12:00")


def test_filings_asof_drops_after_cutoff_and_dedupes(tmp_path, monkeypatch):
    arch = pd.DataFrame([{"ticker": "A", "cik": 1, "form": "8-K", "filing_date": pd.Timestamp("2026-11-12"),
                          "accepted": pd.Timestamp("2026-11-12 10:00"), "items": "8.01", "accession": "a1",
                          "primary_doc": "x.htm", "description": ""}])
    arch.to_parquet(tmp_path / "f.parquet")
    live = pd.DataFrame([dict(arch.iloc[0]) | {"accession": "l1", "accepted": pd.Timestamp("2026-11-13 15:10")},
                         dict(arch.iloc[0]) | {"accession": "l2", "accepted": pd.Timestamp("2026-11-13 15:45")}])
    (tmp_path / "live").mkdir()
    live.to_parquet(tmp_path / "live" / "2026-11-13.parquet")
    monkeypatch.setattr(edgar_live.edgar, "FILINGS", tmp_path / "f.parquet")
    monkeypatch.setattr(edgar_live, "LIVE", tmp_path / "live")
    got = edgar_live.filings_asof(date(2026, 11, 13))
    assert sorted(got["accession"]) == ["a1", "l1"]           # l2 came after 15:30 ET
    assert sorted(edgar_live.filings_asof(date(2026, 11, 13), None)["accession"]) == ["a1", "l1", "l2"]


def test_capture_due_window(tmp_path, monkeypatch):
    monkeypatch.setattr(edgar_live, "LIVE", tmp_path)
    assert edgar_live.due(datetime(2026, 11, 13, 12, 41))
    assert not edgar_live.due(datetime(2026, 11, 13, 12, 30))
    assert not edgar_live.due(datetime(2026, 11, 13, 12, 58))         # too late for the 12:56 quotes
    assert not edgar_live.due(datetime(2026, 11, 14, 12, 41))         # Saturday
    (tmp_path / "2026-11-13.parquet").write_text("x")
    assert not edgar_live.due(datetime(2026, 11, 13, 12, 50))         # already captured


def test_text_body_drops_cover_page_and_hidden_xbrl():
    raw = ('<html><body><div style="display:none"><ix:header>0001 false</ix:header></div>'
           "<p>UNITED STATES SECURITIES AND EXCHANGE COMMISSION</p><p>FORM 8-K</p>"
           "<p>Item 8.01 Other Events.</p><p>On May 1 the Board authorized a $500&nbsp;million repurchase.</p>")
    body = edgar_text.body_of(edgar_text.to_text(raw))
    assert body.startswith("Item 8.01") and "$500 million repurchase" in body and "0001" not in body


def test_filing_text_merges_and_flags_missing(tmp_path, monkeypatch):
    (tmp_path / "text").mkdir()
    pd.DataFrame([{"accession": "a1", "ticker": "A", "group": "8.01", "status": "ok", "text": "Item 8.01 buyback",
                   "exhibit": ""}]).to_parquet(tmp_path / "text" / "part-00000-1.parquet")
    monkeypatch.setattr(rd, "TEXT", tmp_path / "text")
    out = rd.filing_text(pd.DataFrame({"accession": ["a1", "a2"], "ticker": ["A", "B"]}))
    assert out["has_text"].tolist() == [True, False] and out.loc[0, "text"] == "Item 8.01 buyback"
    assert out.loc[1, "text"] == ""


def test_fomc_calls_hidden_until_they_happen(monkeypatch):
    monkeypatch.setenv("TEAM_DATA_END", "2008-01-15")
    f = rd.fomc()
    assert pd.Timestamp("2008-01-21") not in set(f[f["kind"] == "call"]["date"])      # unscheduled: not yet known
    assert pd.Timestamp("2008-01-30") in set(f[f["kind"] == "meeting"]["date"])       # scheduled: published ahead
    assert pd.Timestamp("2008-01-09") in set(f["date"])


def test_13d_rename_matches_both_spellings():
    assert rd.form_std("SCHEDULE 13D") == "SC 13D" and rd.form_std("SCHEDULE 13G/A") == "SC 13G/A"
    assert rd.form_std("8-K") == "8-K"


# ---------- Engineer build mode (tools/lab/) ----------

import engineer  # noqa: E402


def _changes(tmp_path, monkeypatch, files: dict[str, str], status="??"):
    monkeypatch.setattr(engineer, "TEAM", tmp_path)
    for rel, text in files.items():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(text, encoding="utf-8")
    return [engineer.Change(rel, status) for rel in files]


def test_lab_module_pure_function_accepted(tmp_path, monkeypatch):
    ch = _changes(tmp_path, monkeypatch, {
        "tools/lab/text8k.py": '"""Classify 8-K text."""\nimport re\n\ndef buyback(text):\n    return bool(re.search("repurchase", text))\n',
        "tests/test_lab_text8k.py": "def test_x():\n    assert True\n"})
    assert engineer.review(ch) == []


def test_lab_module_may_not_touch_data(tmp_path, monkeypatch):
    ch = _changes(tmp_path, monkeypatch, {"tools/lab/leak.py": "import pandas as pd\nx = pd.read_parquet('h.parquet')\n"
                                                                "import research_data\n"})
    probs = engineer.review(ch)
    assert any("read_" in p for p in probs) and any("research_data" in p for p in probs)


def test_lab_module_frozen_once_a_locked_plan_uses_it(tmp_path, monkeypatch):
    (tmp_path / "research" / "idea1").mkdir(parents=True)
    (tmp_path / "research" / "idea1" / "plan.lock").write_text("x")
    (tmp_path / "research" / "idea1" / "test.py").write_text("from lab import text8k\n")
    ch = _changes(tmp_path, monkeypatch, {"tools/lab/text8k.py": '"""v1"""\n'}, status=" M")
    monkeypatch.setattr(engineer, "_lines", lambda c: (["x = 1"], []))
    assert any("FROZEN" in p and "research/idea1" in p for p in engineer.review(ch))
    ch2 = _changes(tmp_path, monkeypatch, {"tools/lab/text8k_v2.py": '"""v2"""\n'})
    assert engineer.review(ch2) == []                         # a new version is fine


def test_build_requests_parsed_from_director_report(tmp_path):
    r = tmp_path / "2026-11-16-director.md"
    r.write_text("## Data requests\n1. options history\n\n## Build requests\n1. classify 8.01 buybacks\n"
                 "2. flag CEO departures\n\n## Next\n1. no\n", encoding="utf-8")
    assert engineer.build_requests(r) == ["classify 8.01 buybacks", "flag CEO departures"]
