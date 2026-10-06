import numpy as np
import pytest

from daytrade.config import DATA_DIR
from daytrade.research.hourly import HDet, HExit, Panel, events, exits, load_panel


def _panel(O, H, L, C, pdh=101.0, pdl=95.0):
    a = lambda x: np.array([x], float)  # noqa: E731
    return Panel("T", np.array(["d"]), a(O), a(H), a(L), a(C), a(2.0), a(pdh), a(pdl), a(pdh), a(pdl),
                 a(1.0), a(0.0))


def test_textbook_hourly_short():
    # 09:30 inside, 10:30 sweeps 101 to 101.8 and closes back below, 11:30 entry, falls to 99.4 at close
    O = [100.0, 100.5, 100.6, 100.2, 100.0, 99.8, 99.6]
    H = [100.6, 101.8, 100.8, 100.4, 100.1, 99.9, 99.7]
    L = [99.8, 100.4, 100.1, 99.9, 99.7, 99.5, 99.4]
    C = [100.5, 100.6, 100.2, 100.0, 99.8, 99.6, 99.4]
    ev = events(_panel(O, H, L, C), HDet())
    s = ev["sign"] == 1
    assert s.sum() == 1
    assert ev["e"][s][0] == 2 and ev["ext"][s][0] == pytest.approx(101.8)
    R = 101.82 - 100.6
    r_none = exits(ev, HExit(target="none"))[s][0]
    assert r_none == pytest.approx((100.6 - 99.4 - 0.02) / R)
    r_1 = exits(ev, HExit(target="R", k=1.0))[s][0]          # tp 99.38 never reached -> close
    assert r_1 == pytest.approx(r_none)
    r_half = exits(ev, HExit(target="R", k=0.5))[s][0]       # tp 99.99 hit at 13:30 (low 99.7)
    assert r_half == pytest.approx((0.5 * R - 0.02) / R)


def test_stop_first_when_both_hit():
    O = [100.0, 100.5, 100.6, 100.2, 100.0, 99.8, 99.6]
    H = [100.6, 101.8, 102.0, 100.4, 100.1, 99.9, 99.7]       # 11:30 bar takes the stop...
    L = [99.8, 100.4, 98.0, 99.9, 99.7, 99.5, 99.3]           # ...and the 1R target
    C = [100.5, 100.6, 100.2, 100.0, 99.8, 99.6, 99.4]
    ev = events(_panel(O, H, L, C), HDet())
    s = ev["sign"] == 1
    assert exits(ev, HExit(target="R", k=1.0))[s][0] == pytest.approx(-1 - 0.02 / 1.22)


@pytest.mark.skipif(not (DATA_DIR / "1h" / "NVDA.parquet").exists(), reason="no hourly data")
@pytest.mark.parametrize("det", [HDet(), HDet("2d", 0.1, 2, "break"), HDet("pd", 0.05, 2, "color")])
def test_mirror_invariance(det):
    P = load_panel("NVDA")
    c = 2 * np.nanmax(P.H)
    M = Panel(P.ticker, P.days, c - P.O, c - P.L, c - P.H, c - P.C, P.atr, c - P.pdl, c - P.pdh,
              c - P.l2, c - P.h2, -P.trend, -P.gap)
    a, b = events(P, det), events(M, det)
    for ex in [HExit(), HExit(0.1, "level", 0), HExit(0.05, "none", 0)]:
        ra, rb = exits(a, ex), exits(b, ex)
        for sgn in (1, -1):
            x = np.sort(ra[a["sign"] == sgn][~np.isnan(ra[a["sign"] == sgn])])
            y = np.sort(rb[b["sign"] == -sgn][~np.isnan(rb[b["sign"] == -sgn])])
            assert len(x) == len(y) > 20
            assert x == pytest.approx(y, abs=1e-9)
