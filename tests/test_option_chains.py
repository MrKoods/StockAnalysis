import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import option_chains as oc  # noqa: E402

TODAY = date(2026, 11, 23)


def _payload(last_trade="2026-11-23T16:00:00"):
    opts = [{"option": f"SPY{e}{cp}{int(k * 1000):08d}", "bid": 1.0, "ask": 1.1, "iv": 0.3, "delta": -0.2,
             "open_interest": 10, "volume": 5}
            for e in ("261127", "270320") for cp in "CP" for k in (500, 690, 700, 900)]
    return {"timestamp": "2026-11-23 21:00:00", "data": {"current_price": 690.0, "last_trade_time": last_trade,
                                                          "options": opts}}


def test_tidy_keeps_near_expiries_and_strikes_only():
    rows, stamp = oc.tidy(_payload(), TODAY, "SPY")
    assert stamp.startswith("2026-11-23")
    assert set(rows["expiry"].astype(str)) == {"2026-11-27"}          # 2027-03 is > 60 days out
    assert set(rows["strike"]) == {690.0, 700.0}                         # 500 / 900 are > 20% from spot
    assert {"bid", "ask", "iv", "delta", "dte", "type", "spot"} <= set(rows.columns)


def test_spx_uses_tighter_limits():
    p = _payload()
    p["data"]["options"] = [dict(o, option=o["option"].replace("SPY", "SPXW")) for o in p["data"]["options"]]
    p["data"]["options"] += [{"option": "SPXW261127P00600000", "bid": 1, "ask": 2}]   # 13% OTM: kept for SPY, not SPX
    rows, _ = oc.tidy(p, TODAY, "SPX")
    assert 600.0 not in set(rows["strike"])


def test_stale_page_is_not_saved(tmp_path, monkeypatch):
    monkeypatch.setattr(oc, "OUT", tmp_path)
    monkeypatch.setattr(oc, "fetch", lambda sym: _payload("2026-11-20T16:00:00"))
    msg = oc.capture(TODAY)
    assert "stale" in msg and not list(tmp_path.glob("*.gz"))
    monkeypatch.setattr(oc, "fetch", lambda sym: _payload())
    assert "saved SPY" in oc.capture(TODAY) and len(list(tmp_path.glob("*.gz"))) == len(oc.UNDERLYINGS)


def test_due_only_in_window_and_until_saved(tmp_path, monkeypatch):
    from datetime import datetime
    monkeypatch.setattr(oc, "OUT", tmp_path)
    assert oc.due(datetime(2026, 11, 23, 12, 30)) and not oc.due(datetime(2026, 11, 23, 12, 55))
    assert not oc.due(datetime(2026, 11, 28, 12, 40))
    for s in oc.UNDERLYINGS:
        (tmp_path / f"2026-11-23_{s}.csv.gz").write_text("x")
    assert not oc.due(datetime(2026, 11, 23, 12, 40))


def test_cboe_loader_clips_to_the_cutoff(monkeypatch, tmp_path):
    import research_data as rd
    (tmp_path / "VIX.csv").write_text("date,close\n2017-12-29,11.0\n2018-01-02,9.8\n")
    monkeypatch.setattr(rd, "CBOE", tmp_path)
    monkeypatch.setenv("TEAM_DATA_END", "2017-12-31")
    d = rd.cboe("VIX")
    assert list(d["VIX"]) == [11.0]
