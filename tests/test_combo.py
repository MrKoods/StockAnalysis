import numpy as np
import pytest

from daytrade.research.combo import WINDOWS, eligible, prepare, random_models, signals
from daytrade.research.families2 import XPanel


def _random_xpanel(nT=30, nD=60, seed=0):
    rng = np.random.default_rng(seed)
    base = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, (nT, nD * 7)), axis=1)).reshape(nT, nD, 7)
    O = base * (1 + rng.normal(0, 0.002, base.shape))
    C = base
    H = np.maximum(O, C) * 1.003
    L = np.minimum(O, C) * 0.997
    V = rng.uniform(1e5, 1e6, base.shape)
    pc = np.concatenate([np.full((nT, 1), np.nan), C[:, :-1, 6]], axis=1)
    atr = np.full((nT, nD), 1.5)
    return XPanel([str(i) for i in range(nT)], np.arange(nD), O, H, L, C, atr, pc, np.ones((nT, nD)), [], V)


@pytest.mark.parametrize("window", WINDOWS)
def test_signals_do_not_see_data_after_entry(window):
    X = _random_xpanel()
    d = 40
    Z0 = signals(X)
    # wipe out everything that happens after this window's entry on day d (and all later days)
    X2 = _random_xpanel()
    start = {"o-1030": 0, "o-1330": 0, "o-c": 0, "1030-1330": 1, "1030-c": 1, "1230-c": 3}.get(window)
    rng = np.random.default_rng(99)
    for arr in (X2.O, X2.H, X2.L, X2.C, X2.V):   # random, per-value perturbation of the future
        if start is None:                     # close entries: everything up to day d's close is known
            arr[:, d + 1:] *= rng.uniform(0.5, 1.5, arr[:, d + 1:].shape)
        else:
            arr[:, d, start:] *= rng.uniform(0.5, 1.5, arr[:, d, start:].shape)
            arr[:, d + 1:] *= rng.uniform(0.5, 1.5, arr[:, d + 1:].shape)
    if start is not None:
        X2.O[:, d, start] = X.O[:, d, start]  # the entry price itself is known at entry
        if start == 0:
            X2.O[:, d, 0] = X.O[:, d, 0]
    Z1 = signals(X2)
    for f in eligible(window):
        assert np.allclose(Z0[f][:, d], Z1[f][:, d], equal_nan=True), (window, f)


def test_random_models_respect_eligibility_and_are_reproducible():
    a, b = random_models(500), random_models(500)
    assert a == b
    for m in a:
        assert set(m.feats) <= set(eligible(m.window))
        assert 2 <= len(m.feats) <= 4


def test_excess_is_zero_mean_per_session():
    P = prepare(_random_xpanel())
    for w in WINDOWS:
        m = np.nanmean(P.excess[w], axis=0)
        assert np.allclose(m[~np.isnan(m)], 0, atol=1e-12)
