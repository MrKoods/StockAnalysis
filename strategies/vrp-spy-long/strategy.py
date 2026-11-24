"""vrp-spy-long paper strategy: long/short SPY on the variance risk premium (chosen k0_z126).

Trades SPY; uses ^VIX for the signal. Each session: long if the standardized VRP is above zero,
short if below. The runner enters at the NEXT session's close (spec entry_at "close"), so today's
VIX close is already known before entry - no look-ahead. Hold 20 sessions, exit at close.
Mirrors research/vrp-spy-long/test.py config k0_z126 exactly.
"""
import numpy as np
import pandas as pd

RV_WIN = 20
ZWIN = 126
K = 0.0


def universe():
    return ["SPY", "^VIX"]


def signals(asof, bars):
    spy = bars.get("SPY")
    vix = bars.get("^VIX")
    if spy is None or vix is None or len(spy) < ZWIN + RV_WIN + 2:
        return []
    close = spy["Close"].astype(float)
    close.index = pd.to_datetime(close.index)
    close = close.sort_index()
    v = vix["Close"].astype(float)
    v.index = pd.to_datetime(v.index)
    v = v.sort_index().reindex(close.index).ffill()
    ret = np.log(close / close.shift(1))
    rv = ret.rolling(RV_WIN).std() * np.sqrt(252) * 100.0
    vrp = v - rv
    z = (vrp - vrp.rolling(ZWIN).mean()) / vrp.rolling(ZWIN).std()
    zt = z.iloc[-1]
    if not np.isfinite(zt) or zt == 0:
        return []
    return [{"ticker": "SPY", "side": "long" if zt > K else "short"}]
