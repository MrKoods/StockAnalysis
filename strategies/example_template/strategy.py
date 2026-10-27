"""TEMPLATE ONLY - never promoted. Shows the strategy contract the paper runner expects.

Example rule: buy the two sector ETFs with the worst 1-day return, hold to the next session's close.
"""
SECTORS = ["XLB", "XLC", "XLE", "XLF", "XLI", "XLK", "XLP", "XLRE", "XLU", "XLV", "XLY"]


def universe():
    return SECTORS


def signals(asof, bars):
    # bars[t] holds daily OHLCV up to and including `asof` only - the runner truncates it.
    rets = {}
    for t in SECTORS:
        df = bars.get(t)
        if df is not None and len(df) >= 2 and df.index[-1] == asof:
            rets[t] = df["Close"].iloc[-1] / df["Close"].iloc[-2] - 1
    worst = sorted(rets, key=rets.get)[:2]
    return [{"ticker": t, "side": "long"} for t in worst]
