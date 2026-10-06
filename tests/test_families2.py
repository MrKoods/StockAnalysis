import numpy as np
import pytest

from daytrade.research.families2 import XPanel, mr, on, per, xs


def _xp(open_, close_by_slot, n_days=3):
    """4 tickers; every bar of ticker i on day d opens at open_[i][d]; closes from close_by_slot."""
    nT = len(open_)
    O = np.zeros((nT, n_days, 7))
    C = np.zeros_like(O)
    for i in range(nT):
        for d in range(n_days):
            O[i, d, :] = open_[i][d]
            C[i, d, :] = close_by_slot[i][d]
    H, L = np.maximum(O, C) + 0.01, np.minimum(O, C) - 0.01
    one = np.ones((nT, n_days))
    return XPanel([f"T{i}" for i in range(nT)], np.arange(n_days), O, H, L, C, one * 1.0, one * 100.0,
                  one, [])


def test_xs_reversal_buys_worst_morning_and_pnl():
    # closes are constant per day here, so the morning return = close/open - 1 for each ticker
    opens = [[100] * 3] * 4
    closes = [[90] * 3, [99] * 3, [101] * 3, [110] * 3]
    X = _xp(opens, closes)
    d = xs(X, ("h1", "raw", 0.25, "rev", 6))
    # q=0.25 of 4 names -> one long (T0, the worst) and one short (T3, the best) per day
    assert sorted(d["sign"].tolist()) == [-1] * 3 + [1] * 3
    # entry at the slot-1 open (100), exit at the slot-6 close: long T0 = -10%, short T3 = -10%
    assert np.allclose(d["bps"], -1000 - 4)


def test_on_uses_next_session_open_and_drops_last_day():
    opens = [[100, 105, 100]] * 4
    closes = [[100, 100, 100]] * 4
    X = _xp(opens, closes)
    d = on(X, ("all_long", "raw", 0, "mom"))
    assert len(d["bps"]) == 4 * 2                      # last session has no next open
    assert np.allclose(sorted(d["bps"]), sorted([500 - 4] * 4 + [0 - 4] * 4))


def test_per_signal_excludes_today():
    rng = np.random.default_rng(0)
    nT, nD = 6, 30
    O = np.full((nT, nD, 7), 100.0)
    C = O * (1 + rng.normal(0, 0.01, (nT, nD, 7)))
    X = XPanel([str(i) for i in range(nT)], np.arange(nD), O, np.maximum(O, C), np.minimum(O, C), C,
               np.ones((nT, nD)), np.full((nT, nD), 100.0), np.ones((nT, nD)), [])
    a = per(X, (3, 5, 0.2, "mom"))
    C2 = C.copy()
    C2[:, -1, 3] *= 1.5  # change only today's slot-3 return
    b = per(XPanel(X.tickers, X.days, O, np.maximum(O, C2), np.minimum(O, C2), C2, X.atr, X.pc, X.trend, []),
            (3, 5, 0.2, "mom"))
    last = X.days[-1]
    # the same names are selected on the last day (signal uses only past days); only P&L differs
    assert np.array_equal(a["sign"][a["day"] == last], b["sign"][b["day"] == last])


def test_mr_fades_move_back_to_open():
    O = np.full((4, 1, 7), 100.0)
    C = O.copy()
    C[0, 0, 0] = 98.0                                   # T0 drops 2 (= 2 ATR) in the first hour
    O[0, 0, 1:] = 98.0
    C[0, 0, 1:] = 98.5
    H = np.maximum(O, C) + 0.01
    L = np.minimum(O, C) - 0.01
    H[0, 0, 3] = 100.2                                  # back above the open in slot 3 -> target
    X = XPanel(list("ABCD"), np.arange(1), O, H, L, C, np.ones((4, 1)), np.full((4, 1), 100.0),
               np.ones((4, 1)), [])
    d = mr(X, (0, "raw", 1.5, "rev", 6, "open", 0.0))
    assert len(d["bps"]) == 1 and d["sign"][0] == 1
    assert d["bps"][0] == pytest.approx((100 - 98) / 98 * 1e4 - 4)
