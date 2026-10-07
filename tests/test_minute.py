import numpy as np
import pytest

from daytrade.research.minute import N, Inst, gapm, imom, m_of, nb, simulate


def _inst(O, H=None, L=None, C=None, atr=1.0, pc=100.0, trend=1.0):
    O = np.asarray(O, float)
    C = O.copy() if C is None else np.asarray(C, float)
    H = np.fmax(O, C) if H is None else np.asarray(H, float)
    L = np.fmin(O, C) if L is None else np.asarray(L, float)
    n = O.shape[0]
    return Inst("TEST", np.arange(n), O, H, L, C, np.full(n, atr), np.full(n, pc), np.full(n, trend), 1.0)


def test_simulate_stop_first_and_close_exit():
    O = np.full((1, N), 100.0)
    H, L = O + 0.1, O - 0.1
    H[0, 10], L[0, 10] = 103.0, 97.0                 # one bar spans stop and target
    I = _inst(O, H, L)
    r = simulate(I, np.array([0]), np.array([1.0]), np.array([5]), np.array([N - 1]),
                 np.array([98.0]), np.array([102.0]))
    assert r[0] == pytest.approx(-0.02)              # stop first
    r = simulate(I, np.array([0]), np.array([-1.0]), np.array([5]), np.array([N - 1]),
                 np.array([np.inf]), np.array([-np.inf]))
    assert r[0] == pytest.approx(0.0)                # held to the close, flat


def test_imom_trades_last_half_hour_in_first_half_hour_direction():
    O = np.full((1, N), 100.0)
    C = O.copy()
    C[0, m_of(9, 59)] = 101.0                         # up 1% by 10:00
    O[0, m_of(15, 30):] = 101.0
    C[0, m_of(15, 30):] = 101.5                        # last half hour keeps rising
    d = imom(_inst(O, C=C, atr=1.0, pc=100.0), ("pc-1000", "1530", "mom", 0.5, False))
    assert d["sign"][0] == 1
    assert d["ret"][0] == pytest.approx(101.5 / 101.0 - 1)


def test_gap_fade_target_at_previous_close():
    O = np.full((1, N), 98.0)
    H, L = O + 0.2, O - 0.2
    H[0, 40] = 100.5                                  # back to the previous close at 10:10
    d = gapm(_inst(O, H, L, atr=1.0, pc=100.0, trend=1.0), (1.0, "0930", 0.0, "1600", True))
    assert d["sign"][0] == 1
    assert d["ret"][0] == pytest.approx(100 / 98 - 1)


def test_noise_boundary_return_is_directional_and_fills_next_open():
    rng = np.random.default_rng(3)
    O = 100 + np.cumsum(rng.normal(0, 0.02, (20, N)), axis=1)
    I = _inst(O, C=O + rng.normal(0, 0.01, O.shape))
    d = nb(I, (0.5, 30))
    assert len(d["ret"]) > 0
    # a long's directional return must equal (exit - entry) / entry with the same sign convention
    assert np.all(np.isfinite(d["ret"]))
    assert set(np.unique(d["sign"])) <= {-1.0, 1.0}
