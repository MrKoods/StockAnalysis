import numpy as np
import pytest

from daytrade import data
from daytrade.research.engine import Det, Universe, detect, simulate
from daytrade.research.mass import exit_grid, fast_exit, pbo_cscv

pytestmark = pytest.mark.skipif(not len(data.load("SPY", "1m")), reason="no archived data")


@pytest.mark.parametrize("base,det", [("1m", Det()), ("1m", Det(trigger="limit_edge")),
                                      ("5m", Det(base="5m", trigger="close_out"))])
def test_fast_exit_matches_reference_simulator(base, det):
    U = Universe(tickers=["SPY", "NVDA", "TSLA", "JPM", "AMD", "XOM", "BA", "GS"], base=base)
    ents = detect(U, det)
    assert len(ents) > 10
    checked = 0
    for ex in exit_grid(base):
        for en in ents:
            ref = simulate(U, en, ex)
            got = fast_exit(U, en, ex)
            assert (ref is None) == (got is None), (ex, en.key)
            if ref is None:
                continue
            assert got[0] == pytest.approx(ref["r_net"], abs=1e-9), (ex, en.key, got, ref)
            assert got[2] == ref["exit_bar"] and got[3] == ref["reason"], (ex, en.key, got, ref)
            checked += 1
    assert checked > 500


def test_pbo_detects_pure_noise_and_real_edge():
    rng = np.random.default_rng(0)
    noise = rng.normal(0, 1, (500, 60))
    assert pbo_cscv(noise, S=10)["pbo"] > 0.3
    edge = noise.copy()
    edge[7] += 1.5
    assert pbo_cscv(edge, S=10)["pbo"] < 0.05
