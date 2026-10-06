import numpy as np
import pytest

from daytrade.research.families2 import XPanel
from daytrade.research.families3 import _pick, _rvol, sip


def test_rvol_uses_only_prior_sessions():
    v = np.ones((1, 20))
    v[0, -1] = 5.0
    rv = _rvol(v)
    assert rv[0, -1] == pytest.approx(5.0)
    assert rv[0, 15] == pytest.approx(1.0)
    assert np.isnan(rv[0, 5])                        # not enough history yet


def test_pick_top_k_per_day():
    rv = np.array([[1.0], [3.0], [2.0]])
    assert _pick(rv, "top1")[:, 0].tolist() == [False, True, False]
    assert _pick(rv, "ge2")[:, 0].tolist() == [False, True, True]


def test_sip_momentum_trade_on_in_play_name():
    nT, nD = 2, 16
    O = np.full((nT, nD, 7), 100.0)
    C = O.copy()
    V = np.ones((nT, nD, 7))
    V[0, -1, 0] = 10.0                                # ticker 0 is in play on the last day
    C[0, -1, 0] = 101.0                               # first hour up
    O[0, -1, 1:] = 101.0
    C[0, -1, 1:] = 102.0                              # keeps going: close 102
    H, L = np.maximum(O, C) + 0.01, np.minimum(O, C) - 0.01
    X = XPanel(["A", "B"], np.arange(nD), O, H, L, C, np.ones((nT, nD)), np.full((nT, nD), 100.0),
               np.ones((nT, nD)), [], V)
    d = sip(X, ("top1", "mom", "none", "none", 6))
    last = d["day"] == nD - 1
    assert last.sum() == 1
    assert d["sign"][last][0] == 1
    assert d["bps"][last][0] == pytest.approx((102 - 101) / 101 * 1e4 - 4)
