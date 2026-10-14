"""Tests for paper_trading/options_pricer.py — real-quote options pricing of paper trades."""

import csv
import json
from datetime import date

import pandas as pd
import pytest

import paper_trading.options_pricer as op
from paper_trading.paper_runner import _CSV_COLUMNS
from shared.utils.options_math import resolve_structure_economics

CFG = {"positioning": {"min_dte": 5}}


class FakeMarket:
    """Spot + one call/put chain per expiry; tests move prices between runs."""

    def __init__(self):
        self.spot = 100.0
        self.expirations = ["2026-10-23", "2026-11-20"]
        self.call_mid = {}          # (expiry, strike) -> mid; spread is 0.10 wide
        self.closes = pd.DataFrame({"Close": [104.0]}, index=pd.to_datetime(["2026-10-23"]))

    def quotes(self, ticker, expiry):
        rows = []
        for k in (90.0, 94.0, 100.0, 106.0, 112.0):
            for kind in ("call", "put"):
                mid = self.call_mid.get((expiry, k, kind), 1.0)
                rows.append({"option_type": kind, "strike": k, "bid": mid - 0.05, "ask": mid + 0.05, "last": mid})
        return pd.DataFrame(rows)


@pytest.fixture
def market(tmp_path, monkeypatch):
    m = FakeMarket()
    monkeypatch.setattr(op, "fetch_spot", lambda t: m.spot)
    monkeypatch.setattr(op, "list_expirations", lambda t: m.expirations)
    monkeypatch.setattr(op, "fetch_quotes", m.quotes)
    monkeypatch.setattr(op, "fetch_ohlcv_since", lambda t, s: m.closes)
    monkeypatch.setattr(op, "POSITIONS_CSV", tmp_path / "pos.csv")
    monkeypatch.setattr(op, "POSITIONS_LOCK", tmp_path / "pos.lock")
    ledger = tmp_path / "rank.csv"
    monkeypatch.setitem(op.TRACKS, "rank", (ledger, tmp_path / "rank.lock"))
    m.ledger = ledger
    return m


def _write_trade(path, structure="long_call", fill="2026-10-15", outcome="", size="2"):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=_CSV_COLUMNS, extrasaction="ignore")
        w.writeheader()
        w.writerow({"signal_date": "2026-10-14", "ticker": "AAA", "direction": "bullish",
                    "position_type": "options", "structure_recommended": structure, "position_size": size,
                    "actual_dollar_risk": "400", "fill_date": fill, "outcome": outcome,
                    "achieved_rr": "1.5" if outcome else "", "pnl_dollars": "600" if outcome else ""})


def _positions():
    with open(op.POSITIONS_CSV, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def test_open_mark_close_lifecycle(market):
    _write_trade(market.ledger)
    market.call_mid[("2026-10-23", 100.0, "call")] = 3.00
    assert op.update_live("rank", date(2026, 10, 15), CFG)["opened"] == 1
    p = _positions()[0]
    legs = json.loads(p["legs"])
    assert [(l["type"], l["qty"], l["strike"], l["expiry"]) for l in legs] == [("call", 1, 100.0, "2026-10-23")]
    assert float(p["open_mid"]) == pytest.approx(3.00) and float(p["open_natural"]) == pytest.approx(3.05)

    market.call_mid[("2026-10-23", 100.0, "call")] = 4.00
    assert op.update_live("rank", date(2026, 10, 16), CFG)["marked"] == 1
    assert float(_positions()[0]["pnl_mid"]) == pytest.approx(200.0)          # (4-3) x 100 x 2

    _write_trade(market.ledger, outcome="time_stop")
    market.call_mid[("2026-10-23", 100.0, "call")] = 5.00
    assert op.update_live("rank", date(2026, 10, 19), CFG)["closed"] == 1
    p = _positions()[0]
    assert p["status"] == "closed"
    assert float(p["pnl_mid"]) == pytest.approx(400.0)                         # (5-3) x 100 x 2
    assert float(p["pnl_natural"]) == pytest.approx((4.95 - 3.05) * 200)       # sell bid, bought ask
    assert p["stock_rr"] == "1.5"


def test_leg_expired_before_close_settles_at_intrinsic(market):
    _write_trade(market.ledger)
    market.call_mid[("2026-10-23", 100.0, "call")] = 3.00
    op.update_live("rank", date(2026, 10, 15), CFG)
    _write_trade(market.ledger, outcome="time_stop")
    op.update_live("rank", date(2026, 10, 30), CFG)                            # expiry 10-23 close was 104
    p = _positions()[0]
    assert json.loads(p["legs"])[0]["settled"] == pytest.approx(4.0)
    assert float(p["pnl_mid"]) == pytest.approx((4.0 - 3.0) * 200)


def test_trade_closed_before_first_quote_is_missed(market):
    _write_trade(market.ledger, outcome="loss")
    assert op.update_live("rank", date(2026, 10, 15), CFG)["missed"] == 1
    assert _positions()[0]["status"] == "missed"


def test_fills_before_pricing_start_are_left_to_the_estimate(market):
    _write_trade(market.ledger, fill="2026-10-01")
    op.update_live("rank", date(2026, 10, 15), CFG)
    assert not op.POSITIONS_CSV.exists() or _positions() == []


def test_missing_quote_retries_instead_of_opening(market, monkeypatch):
    _write_trade(market.ledger, structure="long_strangle")
    monkeypatch.setattr(op, "fetch_quotes", lambda t, e: pd.DataFrame(columns=["option_type", "strike", "bid", "ask", "last"]))
    op.update_live("rank", date(2026, 10, 15), CFG)
    p = _positions()[0]
    assert p["status"] == "pending" and "retry" in p["note"]


def test_expiry_rule_matches_positioning_min_dte():
    near, far = op._pick_expiries(["2026-10-16", "2026-10-23", "2026-11-20", "2026-12-18"], date(2026, 10, 14), 5)
    assert near == "2026-10-23" and far == "2026-11-20"


@pytest.mark.parametrize("structure", sorted(op.LEG_SPECS))
def test_leg_specs_match_the_models_economics(structure):
    """Every leg spec must price to the same per-unit premium the model's own EV math uses."""
    entry, iv, dte = 100.0, 0.4, 10
    econ = resolve_structure_economics(structure, entry, 95.0, 115.0, iv, dte)
    T_near, T_far = dte / 365, (dte + op.FAR_LEG_EXTRA_DAYS) / 365
    value = sum(qty * op.black_scholes_price(entry, entry * (1 + off), T_near if which == "near" else T_far,
                                              0.04, iv, kind)
                for kind, qty, off, which in op.LEG_SPECS[structure])
    floor = entry * 0.005
    model_cost = econ["capital_required"] / 100
    assert value == pytest.approx(model_cost, rel=1e-6) or (model_cost == pytest.approx(floor) and value <= floor)
