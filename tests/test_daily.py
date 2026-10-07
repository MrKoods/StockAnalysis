from datetime import date, timedelta

import numpy as np
import pytest

from daytrade.research.daily import DPanel, cal, gapd, nw_t, rev


def _panel(C, O=None, H=None, L=None, start=date(2020, 1, 1)):
    C = np.asarray(C, float)
    O = C.copy() if O is None else np.asarray(O, float)
    H = np.fmax(O, C) if H is None else np.asarray(H, float)
    L = np.fmin(O, C) if L is None else np.asarray(L, float)
    days, d = [], start
    while len(days) < C.shape[1]:
        if d.weekday() < 5:
            days.append(d)
        d += timedelta(days=1)
    return DPanel([f"T{i}" for i in range(C.shape[0])], np.array(days), O, H, L, C, np.ones_like(C) * 1e6)


def test_hedge_benchmark_equals_a_common_move():
    # every stock rises 1% a day (open == close): the equal-weight index rises 1% close to close
    C = np.tile(100 * 1.01 ** np.arange(30), (5, 1))
    O = np.concatenate([C[:, :1], C[:, :-1] * 1.004], axis=1)      # 0.4% overnight, rest intraday
    P = _panel(C, O)
    for d_in, d_out in [(3, 5), (10, 11)]:
        assert P.bench(2 * d_in + 1, 2 * d_out + 1) == pytest.approx(1.01 ** (d_out - d_in) - 1)
    assert P.bench(2 * 10 + 1, 2 * 11) == pytest.approx(0.004)          # close -> next open


def test_rev_buys_yesterdays_loser_and_scores_vs_universe():
    C = np.full((5, 6), 100.0)
    C[0, 2] = 90.0             # T0 falls 10% on day 2 ...
    C[0, 3:] = 99.0            # ... and recovers to 99 by day 3
    d = rev(_panel(C), (1, 0.2, "rev", 1, "close"))
    sel = (d["sign"] > 0) & (d["day"] == _panel(C).dates[2])
    assert sel.sum() == 1
    r = 99 / 90 - 1
    bench = np.mean([r, 0, 0, 0, 0])
    assert d["raw"][sel][0] == pytest.approx(r * 1e4 - 4)
    assert d["hedged"][sel][0] == pytest.approx((r - bench) * 1e4 - 4)


def test_gap_fade_hits_previous_close_target():
    C = np.full((2, 25), 100.0)
    O, H, L = C.copy(), C.copy() + 1, C.copy() - 1
    O[0, 20], H[0, 20], L[0, 20], C[0, 20] = 95.0, 100.5, 94.5, 97.0   # gaps down 5 (= 2.5 ATR), refills
    O[0, 21] = L[0, 21] = 97.0                                          # no second gap the next day
    d = gapd(_panel(C, O, H, L), (1.0, "fade", "none", "c0", "pc"))
    assert len(d["raw"]) == 1
    assert d["sign"][0] == 1
    assert d["raw"][0] == pytest.approx((100 / 95 - 1) * 1e4 - 4)


def test_turn_of_month_window():
    P = _panel(np.tile(np.linspace(100, 110, 60), (1, 1)))
    d = cal(P, ("tom", 1, 1))   # in at the last close of the month, out at the first close of the next
    for di, do in zip(d["p_in"] // 2, d["p_out"] // 2):
        assert P.dates[di].month != P.dates[do].month
        assert do - di == 1


def test_nw_t_matches_plain_t_without_autocorrelation():
    rng = np.random.default_rng(1)
    x = rng.normal(0.1, 1, 4000)
    plain = x.mean() / (x.std(ddof=0) / np.sqrt(len(x)))
    assert nw_t(np.arange(len(x)), x, lag=0) == pytest.approx(plain, rel=1e-6)
    assert abs(nw_t(np.arange(len(x)), x, lag=5) - plain) < 0.5


def test_open_entry_features_use_only_the_prior_close():
    """Regression: an open-entry trade's filter features must not see that session's close."""
    C = np.full((3, 260), 100.0)
    C[0, 250] = 50.0                     # session 250 closes far below its 200-day average
    P = _panel(C)
    d = rev(P, (1, 0.34, "rev", 1, "open"))
    on_250 = d["day"] == P.dates[250]    # entered at the open of 250 (signal from 249)
    assert on_250.any()
    assert np.all(d["trend"][on_250] == 0)   # prior close == its average -> neutral, not "below"
