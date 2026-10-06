import numpy as np
import pandas as pd
import pytest

from daytrade import data
from daytrade.config import DEFAULT, TZ
from daytrade.levels import Level, build_5m, day_levels
from daytrade.strategy import scan_day, swing_lows

DAY = pd.Timestamp("2026-09-15").date()


def _bars(path):
    """1m bars from a list of (open, high, low, close) starting 09:30."""
    idx = pd.date_range(pd.Timestamp("2026-09-15 09:30", tz=TZ), periods=len(path), freq="1min")
    return pd.DataFrame(path, index=idx, columns=["open", "high", "low", "close"]).assign(volume=1000)


def _lv(name, side, price):
    return Level(name, side, price, pd.Timestamp("2026-09-15 09:30", tz=TZ),
                 pd.Timestamp("2026-09-15 16:00", tz=TZ))


def _flat(px, n):
    return [(px, px + 0.02, px - 0.02, px)] * n


def _short_day():
    """Drift under PDH=101, sweep to 101.30 and reclaim in one 5m bar, swing low at 09:45,
    CHoCH at 09:49 with a bearish FVG (09:47/09:49), red candle wicks into it and closes below,
    enter 09:52, drop to PDL=98."""
    path = _flat(100.50, 10)                                    # 09:30-09:39
    path += [(100.60, 100.80, 100.55, 100.75),                  # 09:40 5m bar starts
             (100.75, 101.30, 100.70, 101.10),                  # 09:41 sweep, extreme 101.30
             (101.10, 101.15, 100.90, 100.95),
             (100.95, 101.00, 100.85, 100.88),
             (100.88, 100.90, 100.80, 100.82)]                  # 09:44 5m close 100.82 < 101
    path += [(100.82, 100.86, 100.72, 100.80),                  # 09:45 swing low 100.72
             (100.80, 100.88, 100.76, 100.86),                  # 09:46
             (100.86, 100.90, 100.78, 100.80),                  # 09:47 bar1 low 100.78
             (100.80, 100.81, 100.66, 100.74),                  # 09:48
             (100.74, 100.75, 100.40, 100.45)]                  # 09:49 bar3 high 100.75 -> FVG, CHoCH
    path += [(100.45, 100.70, 100.40, 100.68),                  # 09:50
             (100.68, 100.77, 100.60, 100.65),                  # 09:51 red, wick into zone, close below -> trigger
             (100.60, 100.62, 100.30, 100.35)]                  # 09:52 entry at open 100.60
    px = 100.35
    for _ in range(20):
        path.append((px, px + 0.05, px - 0.15, px - 0.12))
        px -= 0.12
    path += _flat(97.50, 360)
    return _bars(path)


def test_swing_lows_strict_fractal():
    low = np.array([5, 4, 3, 4, 5, 3, 3, 4, 5])
    assert swing_lows(low, 2).tolist() == [False, False, True] + [False] * 6  # tie at 5/6 isn't a swing


def test_textbook_short_setup():
    m1 = _short_day()
    levels = [_lv("PDH", "high", 101.0), _lv("PDL", "low", 98.0)]
    s = next(x for x in scan_day("TEST", DAY, m1, levels, DEFAULT) if x.direction == "short")
    assert s.status == "candidate"
    assert s.extreme == pytest.approx(101.30)
    assert s.zone_kind == "fvg" and (s.zone_lo, s.zone_hi) == pytest.approx((100.75, 100.78))
    assert s.entry == pytest.approx(100.60)
    assert s.stop == pytest.approx(101.32)
    assert s.tp == pytest.approx(98.0) and s.exit_reason == "tp"
    assert s.r_gross == pytest.approx((100.60 - 98.0) / 0.72)
    assert s.r_net == pytest.approx((100.60 - 98.0 - 0.02) / 0.72)


def test_min_r_filter():
    levels = [_lv("PDH", "high", 101.0), _lv("PDL", "low", 99.6)]  # (100.60-99.6)/0.72 < 1.5
    s = next(x for x in scan_day("TEST", DAY, _short_day(), levels, DEFAULT) if x.direction == "short")
    assert s.status == "below_min_r"


def test_gap_beyond_level_is_not_a_sweep():
    m1 = _bars(_flat(102.0, 390))
    s = scan_day("TEST", DAY, m1, [_lv("PDH", "high", 101.0)], DEFAULT)
    assert [x.status for x in s] == ["broken_from_outside"]


def test_stop_wins_when_both_hit_same_bar():
    m1 = _short_day()
    i = m1.index.get_loc(pd.Timestamp("2026-09-15 09:52", tz=TZ))
    m1.iloc[i] = [100.60, 101.40, 97.90, 98.0, 1000]           # one bar spans stop and TP
    levels = [_lv("PDH", "high", 101.0), _lv("PDL", "low", 98.0)]
    s = next(x for x in scan_day("TEST", DAY, m1, levels, DEFAULT) if x.direction == "short")
    assert s.exit_reason == "stop" and s.r_gross == pytest.approx(-1.0)


def test_rising_candle_into_zone_is_not_a_trigger():
    m1 = _short_day()
    i = m1.index.get_loc(pd.Timestamp("2026-09-15 09:51", tz=TZ))
    m1.iloc[i] = [100.55, 100.77, 100.50, 100.70, 1000]        # green: touches zone, closes below it
    m1.iloc[i + 1] = [100.70, 100.72, 100.62, 100.64, 1000]    # red, already touched -> trigger here
    levels = [_lv("PDH", "high", 101.0), _lv("PDL", "low", 98.0)]
    s = next(x for x in scan_day("TEST", DAY, m1, levels, DEFAULT) if x.direction == "short")
    assert s.trigger_ts == pd.Timestamp("2026-09-15 09:52", tz=TZ)


def test_new_extreme_before_choch_extends_it():
    m1 = _short_day()
    i = m1.index.get_loc(pd.Timestamp("2026-09-15 09:46", tz=TZ))
    m1.iloc[i] = [100.80, 101.40, 100.76, 100.86, 1000]        # spikes past 101.30 pre-CHoCH
    levels = [_lv("PDH", "high", 101.0), _lv("PDL", "low", 98.0)]
    s = next(x for x in scan_day("TEST", DAY, m1, levels, DEFAULT) if x.direction == "short")
    assert s.extreme == pytest.approx(101.40)
    assert s.extreme_ts == pd.Timestamp("2026-09-15 09:46", tz=TZ)


def test_mirror_long_matches_short():
    m1 = _short_day()
    mir = m1.copy()
    mir["open"], mir["close"] = 200 - m1["open"], 200 - m1["close"]
    mir["high"], mir["low"] = 200 - m1["low"], 200 - m1["high"]
    levels = [_lv("PDL", "low", 99.0), _lv("PDH", "high", 102.0)]
    s = next(x for x in scan_day("TEST", DAY, mir, levels, DEFAULT) if x.direction == "long")
    assert s.status == "candidate" and s.entry == pytest.approx(99.40)
    assert s.r_net == pytest.approx((100.60 - 98.0 - 0.02) / 0.72)


# ---- invariance checks on the real archive (skipped if no data downloaded) ----

def _real_days(tickers=("SPY", "NVDA", "TSLA", "JPM", "AMD")):
    for t in tickers:
        m1 = data.load(t, "1m")
        if not len(m1):
            continue
        levels = day_levels(build_5m(m1, data.load(t, "5m")))
        for day, g in m1.groupby(m1.index.date):
            if day in levels:
                yield t, day, g, levels[day]


@pytest.mark.skipif(not len(data.load("SPY", "1m")), reason="no archived data")
def test_no_lookahead_truncation():
    """Cutting the session right after entry must reproduce the identical setup."""
    checked = 0
    for t, day, g, lv in _real_days():
        for s in scan_day(t, day, g, lv, DEFAULT):
            if s.status != "candidate":
                continue
            cut = g[g.index <= s.entry_ts]
            s2 = next(x for x in scan_day(t, day, cut, lv, DEFAULT)
                      if x.level_name == s.level_name and x.direction == s.direction)
            for f in ("sweep_start", "extreme", "choch_ts", "zone_lo", "zone_hi", "entry_ts",
                      "entry", "stop", "tp"):
                assert getattr(s2, f) == getattr(s, f), (t, day, f)
            checked += 1
    assert checked > 5


@pytest.mark.skipif(not len(data.load("SPY", "1m")), reason="no archived data")
def test_mirror_invariance_real_data():
    """Flip each real session upside down: every long becomes the same short, and vice versa."""
    checked = 0
    for t, day, g, lv in _real_days():
        c = 2 * float(g["high"].max())
        mir = g.copy()
        mir["open"], mir["close"] = c - g["open"], c - g["close"]
        mir["high"], mir["low"] = c - g["low"], c - g["high"]
        mlv = [Level(x.name, "low" if x.side == "high" else "high", c - x.price, x.active_from, x.active_to)
               for x in lv]
        a = {(s.level_name, s.direction): s for s in scan_day(t, day, g, lv, DEFAULT)}
        b = {(s.level_name, s.direction): s for s in scan_day(t, day, mir, mlv, DEFAULT)}
        flip = {"short": "long", "long": "short"}
        assert {(k[0], flip[k[1]]) for k in a} == set(b)
        for (name, dirn), s in a.items():
            m = b[(name, flip[dirn])]
            assert m.status == s.status, (t, day, name, dirn)
            if s.r_net is not None:
                assert m.r_net == pytest.approx(s.r_net, abs=1e-6)
                checked += 1
    assert checked > 5
