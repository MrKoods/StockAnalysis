import copy

import numpy as np
import pytest

from daytrade.dukascopy import OUT
from daytrade.research.library import BUILDERS, Inst, LCfg, grid, simulate

pytestmark = pytest.mark.skipif(not (OUT / "SPY").exists(), reason="no Dukascopy data")
FAMILIES = sorted({c.family for c in grid()} - {"RS"})


@pytest.fixture(scope="module")
def spy():
    from daytrade.research.library import load
    I = load("SPY")
    sl = slice(300, 420)                      # 120 sessions keep the test fast
    return Inst(I.sym, I.days[sl], I.O[sl], I.H[sl], I.L[sl], I.C[sl], I.atr[sl], I.pc[sl], I.pdh[sl],
                I.pdl[sl], I.trend20[sl], I.cost_bps)


def _mirror(I: Inst) -> Inst:
    c = 2 * float(np.nanmax(I.H))
    return Inst(I.sym, I.days, c - I.O, c - I.L, c - I.H, c - I.C, I.atr, c - I.pc, c - I.pdl, c - I.pdh,
                -I.trend20, I.cost_bps)


def _price_pnl(I, ev):
    ret = simulate(I, ev["rows"], ev["sign"], ev["e"], ev["x"], ev["stop"], ev["tp"], ev["fill"])
    entry = np.where(np.isnan(ev["fill"]), I.O[ev["rows"], ev["e"]], ev["fill"])
    return ret * np.abs(entry)


def _sample(family, k=6):
    cfgs = [c for c in grid() if c.family == family]
    idx = np.linspace(0, len(cfgs) - 1, min(k, len(cfgs))).astype(int)
    return [cfgs[i] for i in idx]


@pytest.mark.parametrize("family", FAMILIES)
def test_mirror_long_short_symmetry(spy, family):
    M = _mirror(spy)
    for cfg in _sample(family):
        a, b = BUILDERS[family](spy, cfg.p), BUILDERS[family](M, cfg.p)
        if a is None:
            assert b is None or not len(b["rows"]), cfg
            continue
        pa, pb = _price_pnl(spy, a), _price_pnl(M, b)
        ka = sorted(zip(a["rows"], a["e"], a["sign"], np.round(np.nan_to_num(pa, nan=9e9), 6)))
        kb = sorted(zip(b["rows"], b["e"], -b["sign"], np.round(np.nan_to_num(pb, nan=9e9), 6)))
        assert ka == kb, cfg


@pytest.mark.parametrize("family", FAMILIES)
def test_entries_do_not_depend_on_the_future(spy, family):
    rng = np.random.default_rng(7)
    for cfg in _sample(family, 4):
        ev = BUILDERS[family](spy, cfg.p)
        if ev is None:
            continue
        for i in rng.choice(len(ev["rows"]), size=min(15, len(ev["rows"])), replace=False):
            r, e = ev["rows"][i], ev["e"][i]
            J = copy.deepcopy(spy)
            # market entry at the open of e: everything in bar e except its open is future;
            # stop-order fill inside bar e: bar e triggers the fill, so only bars after e are future
            cut = e if np.isnan(ev["fill"][i]) else e + 1
            noise = rng.uniform(0.97, 1.03, (len(J.days) - r, 390))
            for arr in (J.H, J.L, J.C):
                arr[r:, cut:] *= noise[:, cut:]
            J.O[r:, e + 1:] *= noise[:, e + 1:]
            J.H[r, e] = max(J.H[r, e], J.O[r, e])
            J.L[r, e] = min(J.L[r, e], J.O[r, e])
            J.__post_init__()
            ev2 = BUILDERS[family](J, cfg.p)
            same = (ev2["rows"] == r) & (ev2["sign"] == ev["sign"][i])
            assert same.any(), (cfg, r)
            j = np.flatnonzero(same)[0]
            assert ev2["e"][j] == e, (cfg, r)
            assert ev2["stop"][j] == pytest.approx(ev["stop"][i]), (cfg, r)


def test_stop_order_fill_checks_only_the_stop_on_the_fill_bar(spy):
    I = copy.deepcopy(spy)
    r = 0
    I.O[r, 10:], I.H[r, 10:], I.L[r, 10:], I.C[r, 10:] = 100.0, 100.5, 99.5, 100.0
    I.H[r, 10] = 103.0                                      # fill bar also reaches the target
    ret = simulate(I, np.array([r]), np.array([1.0]), np.array([10]), np.array([389]),
                   np.array([99.0]), np.array([102.0]), np.array([100.2]))
    assert ret[0] == pytest.approx(100.0 / 100.2 - 1)      # no target credit on the fill bar; close exit


def test_grid_size():
    assert len(list(grid())) > 2500
    assert LCfg("ORB", (5,)) != LCfg("ORB", (15,))


@pytest.mark.parametrize("family", FAMILIES)
def test_filter_features_do_not_depend_on_the_future(spy, family):
    """Regression (2026-10-07): the or30 filter read the first 30 minutes for entries before 10:00."""
    from daytrade.research.library import features
    rng = np.random.default_rng(11)
    for cfg in _sample(family, 3):
        ev = BUILDERS[family](spy, cfg.p)
        if ev is None:
            continue
        f0 = features(spy, ev)
        for i in rng.choice(len(ev["rows"]), size=min(10, len(ev["rows"])), replace=False):
            r, e = ev["rows"][i], ev["e"][i]
            J = copy.deepcopy(spy)                     # perturb ONE trade's future at a time
            for arr in (J.H, J.L, J.C):
                arr[r, e:] *= rng.uniform(0.9, 1.1, 390 - e)
            f1 = features(J, ev)
            for k in f0:
                assert np.allclose(np.asarray(f0[k][i], float), np.asarray(f1[k][i], float), equal_nan=True), (cfg, k)


def test_holding_minutes_are_actual_not_planned(spy):
    """Regression (2026-10-08): drift adjustment must use the actual exit minute."""
    from daytrade.research.library import run
    I = copy.deepcopy(spy)
    r = 5
    I.O[r, :], I.H[r, :], I.L[r, :], I.C[r, :] = 100.0, 100.05, 99.95, 100.0
    I.H[r, 100] = 101.0                                     # stop for a short entered earlier is hit here
    ret, xk = simulate(I, np.array([r]), np.array([-1.0]), np.array([40]), np.array([389]),
                       np.array([100.5]), np.array([-np.inf]), np.array([np.nan]), return_exit=True)
    assert xk[0] == 100
    t = run(I, LCfg("ORB", (60, "touch", "atr", "1R", "close", (14, 0))))
    if t is not None:
        assert np.all(t["minutes"] <= 390) and np.all(t["minutes"] >= 1)
