"""RULES.md amendment 2026-11-04: no signal on a stock that stopped trading; such trades are voided, not left open."""
from datetime import date

import pandas as pd

from epre import paper


def _q(*tickers):
    return pd.DataFrame({"ticker": list(tickers)})


def test_tradable_drops_dead_and_bought_out(monkeypatch):
    day = date(2026, 11, 3)
    bars = {"SPY": day, "LIVE": day, "STALE": date(2026, 10, 22), "GONE": day}
    monkeypatch.setattr(paper, "_recent_bars", lambda t, d: {k: v for k, v in bars.items() if k in t})
    monkeypatch.setattr(paper, "_recently_acquired", lambda d: {"GONE"})
    kept = paper.tradable(_q("LIVE", "STALE", "GONE", "NODATA"), day)
    assert list(kept["ticker"]) == ["LIVE"]


def test_tradable_keeps_all_when_the_download_is_broken(monkeypatch):
    monkeypatch.setattr(paper, "_recent_bars", lambda t, d: {})                # Yahoo down: SPY missing too
    monkeypatch.setattr(paper, "_recently_acquired", lambda d: set())
    assert len(paper.tradable(_q("A", "B", "C"), date(2026, 11, 3))) == 3


def test_buyout_needs_form25_and_change_in_control(monkeypatch, tmp_path):
    f = pd.DataFrame({
        "ticker": ["ACA", "ACA", "MCK", "IBOC", "IBOC", "OLD", "OLD"],
        "form": ["8-K", "25-NSE", "25-NSE", "8-K", "25", "8-K", "25-NSE"],
        "filing_date": pd.to_datetime(["2026-10-23", "2026-10-23", "2026-10-30", "2026-10-06", "2026-10-16",
                                       "2026-08-01", "2026-08-01"]),
        "items": ["1.02,2.01,3.01,5.01,9.01", None, None, "3.01,7.01", None, "2.01,5.01", None]})
    p = tmp_path / "filings.parquet"
    f.to_parquet(p)
    monkeypatch.setattr(paper, "TEAM_FILINGS", p)
    assert paper._recently_acquired(date(2026, 11, 3)) == {"ACA"}   # bond / exchange switch / too old: kept
    assert paper._recently_acquired(date(2026, 10, 22)) == set()     # nothing from the future


def _ledger(rows):
    led = pd.DataFrame(rows)
    for c in paper.COLS:
        if c not in led:
            led[c] = pd.NA
    return led[paper.COLS].astype(object)


def _series(days, v=100.0):
    return pd.Series([v] * len(days), index=days)


def test_evaluate_voids_a_stock_with_no_price_and_scores_the_rest(monkeypatch):
    sessions = [date(2026, 10, 28), date(2026, 10, 29), date(2026, 10, 30), date(2026, 11, 2), date(2026, 11, 3)]
    led = _ledger([
        {"entry_day": "2026-10-28", "exit_day": "2026-10-30", "ticker": "ACA", "index": "sp600", "posted": True},
        {"entry_day": "2026-10-28", "exit_day": "2026-10-30", "ticker": "OK", "index": "sp500", "posted": False},
        {"entry_day": "2026-11-03", "exit_day": "2026-11-05", "ticker": "NEW", "index": "sp500", "posted": False},
    ])
    saved, posts = {}, []
    monkeypatch.setattr(paper, "load_ledger", lambda: led)
    monkeypatch.setattr(paper, "save_ledger", lambda x: saved.setdefault("led", x.copy()))
    monkeypatch.setattr(paper, "post", lambda text, dry: posts.append(text))
    monkeypatch.setattr(paper, "_date_ok", lambda t, d: True)
    px = {h: _series(sessions) for h in paper.HEDGE} | {"OK": _series(sessions), "NEW": _series(sessions)}
    monkeypatch.setattr(paper, "_closes", lambda t, s, e: {k: v for k, v in px.items() if k in t})
    monkeypatch.setattr(paper.pd.Timestamp, "now", classmethod(lambda cls, tz=None: pd.Timestamp("2026-11-03 17:00", tz=tz)))
    paper.evaluate()
    out = saved["led"].set_index("ticker")
    assert "no price on entry day" in out.at["ACA", "void"] and pd.isna(out.at["ACA", "hedged_bps"])
    assert out.at["OK", "hedged_bps"] == -6.0 and pd.isna(out.at["OK", "void"])     # 2 x 3 bps costs
    assert pd.isna(out.at["NEW", "void"]) and pd.isna(out.at["NEW", "hedged_bps"])  # too early to judge
    assert "VOIDED" in posts[0] and "ACA" in posts[0]
    assert "1 closed trades" in paper.verdict(saved["led"])                          # void is not a closed trade
