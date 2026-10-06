import numpy as np
import pytest

from daytrade.config import DATA_DIR
from daytrade.research.families import grid, run_cfg, simulate
from daytrade.research.hourly import Panel, load_panel

INF = np.inf


def _one(O, H, L, C):
    return [np.array([v], float) for v in (O, H, L, C)]


def test_long_target_stop_close():
    O, H, L, C = _one([10, 10.2, 10.4, 10.5, 10.6, 10.7, 10.8], [10.3, 10.5, 10.6, 10.7, 10.8, 10.9, 11.0],
                      [9.9, 10.1, 10.3, 10.4, 10.5, 10.6, 10.7], [10.2, 10.4, 10.5, 10.6, 10.7, 10.8, 10.9])
    O, H, L, C = (a.reshape(1, 7) for a in (O, H, L, C))
    one = lambda **k: simulate(O, H, L, C, np.array([1.0]), np.array([k.get("e", 1)]),  # noqa: E731
                               np.array([k.get("x", 6)]), np.array([k.get("stop", -INF)]),
                               np.array([k.get("tp", INF)]), np.array([1.0]))[0]
    assert one() == pytest.approx(10.9 - 10.2 - 0.02)                 # held to the close
    assert one(tp=10.65) == pytest.approx(10.65 - 10.2 - 0.02)        # target hit at 12:30 (high 10.7)
    assert one(stop=10.15) == pytest.approx(10.1 - 10.2 - 0.02 + 0.05)  # stop 10.15 hit in slot 1 (low 10.1)
    assert one(x=3) == pytest.approx(10.6 - 10.2 - 0.02)              # exit at 12:30 bar close


@pytest.mark.skipif(not (DATA_DIR / "1h" / "SPY.parquet").exists(), reason="no hourly data")
def test_mirror_invariance_all_families():
    P = load_panel("SPY")
    c = 2 * np.nanmax(P.H)
    M = Panel(P.ticker, P.days, c - P.O, c - P.L, c - P.H, c - P.C, P.atr, c - P.pdl, c - P.pdh,
              c - P.l2, c - P.h2, -P.trend, -P.gap, c - P.pc)
    n = 0
    for cfg in list(grid())[::7]:
        a, b = run_cfg(P, cfg), run_cfg(M, cfg)
        if a is None:
            assert b is None
            continue
        for s in (1, -1):
            x = np.sort(a["r"][a["sign"] == s])
            y = np.sort(b["r"][b["sign"] == -s])
            assert x == pytest.approx(y, abs=1e-9), cfg
        n += 1
    assert n > 30
