"""Event-driven + residual-reversal families, 0-5 session holds (PROTOCOL12_event_families.md).

Same point convention as daily.py: point 2d = open of session d, 2d+1 = close of session d.
Universe = S&P 500 + 400 + 600 pooled; cost per side is tiered by the ticker's index.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass

import numpy as np
import pandas as pd

from .daily import DDIR, DPanel, _shift, nw_t, universe
from .events_fetch import EDIR

COST = {"sp500": 3.0, "sp400": 5.0, "sp600": 8.0}
ETF_COST = 1.0
SECTOR_ETFS = ["XLF", "XLE", "XLK", "XLV", "XLI", "XLP", "XLY", "XLU", "XLB"]
SEARCH_END = pd.Timestamp("2017-12-31").date()
HOLD_START = pd.Timestamp("2018-01-01").date()
HOLD_END = pd.Timestamp("2026-10-06").date()


# ---------------------------------------------------------------- panel
def _load_frames(tickers, start):
    frames = {}
    for t in tickers:
        p = DDIR / f"{t}.parquet"
        if p.exists():
            df = pd.read_parquet(p)
            frames[t] = df[df.index >= start]
    return frames


def load_pooled(start="1999-01-01"):
    """Pooled stock panel + per-ticker universe label + sector ETF closes on the same calendar."""
    uni = {}
    for name in ("sp500", "sp400", "sp600"):
        for t in universe(name):
            uni.setdefault(t, name)
    uni = {t: u for t, u in uni.items() if t not in SECTOR_ETFS + ["SPY", "QQQ", "IWM", "DIA", "SMH"]}
    frames = _load_frames(uni, start)
    etf = _load_frames(SECTOR_ETFS + ["SPY", "QQQ", "IWM"], start)
    idx = sorted(set().union(*[f.index for f in frames.values()]))
    pos = {d: i for i, d in enumerate(idx)}

    def stack(fr):
        tick = list(fr)
        arr = {k: np.full((len(tick), len(idx)), np.nan, dtype=np.float64)
               for k in ("open", "high", "low", "close", "volume")}
        for i, t in enumerate(tick):
            ok = [d in pos for d in fr[t].index]
            j = np.array([pos[d] for d in fr[t].index[ok]])
            for k in arr:
                arr[k][i, j] = fr[t][k].to_numpy(float)[ok]
        return tick, arr

    tick, a = stack(frames)
    P = DPanel(tick, np.array([d.date() for d in idx]), a["open"], a["high"], a["low"], a["close"],
               a["volume"])
    P.uni = np.array([uni[t] for t in tick])
    P.cost = np.array([COST[u] for u in P.uni])
    etick, ea = stack(etf)
    P.etf_tick, P.etf_O, P.etf_C = etick, ea["open"], ea["close"]
    med = np.nanmedian(P.dvol20, axis=0)
    P.liquid = P.dvol20 >= med
    return P


def session_on_or_after(P, dates):
    """Index of the first session >= each date (datetime.date array); len(P.dates) if none."""
    return np.searchsorted(np.array(P.dates, dtype="datetime64[D]"),
                           np.array(dates, dtype="datetime64[D]"), side="left")


# ---------------------------------------------------------------- trade assembly
def mk_trades(P, ti, p_in, p_out, sign, hedge="universe", beta=None, etf_i=None, extra=None):
    nP = 2 * len(P.dates)
    ok = (p_out < nP) & (p_out > p_in) & (p_in >= 0)
    ti, p_in, p_out, sign = ti[ok], p_in[ok], p_out[ok], sign[ok].astype(float)
    r = P.price(ti, p_out) / P.price(ti, p_in) - 1
    good = np.isfinite(r)
    ti, p_in, p_out, sign, r = ti[good], p_in[good], p_out[good], sign[good], r[good]
    sel = np.flatnonzero(ok)[good]
    cost = 2 * P.cost[ti]
    out = {"day": P.dates[p_in // 2], "ti": ti, "p_in": p_in, "p_out": p_out, "sign": sign,
           "r": r, "raw": sign * r * 1e4 - cost, "uni": P.uni[ti]}
    if hedge == "universe":
        out["hedged"] = sign * (r - P.bench(p_in, p_out)) * 1e4 - cost
    else:  # sector ETF hedge with ex-ante beta
        b, e = beta[sel], etf_i[sel]
        eo = lambda p: np.where(p % 2 == 0, P.etf_O[e, p // 2], P.etf_C[e, p // 2])  # noqa: E731
        re = eo(p_out) / eo(p_in) - 1
        out["hedged"] = sign * (r - b * re) * 1e4 - cost - 2 * ETF_COST * np.abs(b)
        keep = np.isfinite(out["hedged"])
        out = {k: v[keep] for k, v in out.items()}
        sel = sel[keep]
    fd = np.where(out["p_in"] % 2 == 0, out["p_in"] // 2 - 1, out["p_in"] // 2).clip(0)
    out["liquid"] = P.liquid[out["ti"], fd]
    if extra:
        for k, v in extra.items():
            out[k] = v[sel]
    return out


def holdl_twin(P, d):
    """User overlay: a day trade (exit = entry-session close) that is losing at that close is held until
    a close back at/above entry, max 5 more sessions."""
    ti, p_in, sign = d["ti"], d["p_in"], d["sign"]
    entry = P.price(ti, p_in)
    d0 = d["p_out"] // 2
    nD = len(P.dates)
    exit_d = np.minimum(d0 + 5, nD - 1)
    done = sign * (P.C[ti, d0] - entry) >= 0
    exit_d = np.where(done, d0, exit_d)
    for j in range(1, 6):
        dj = np.minimum(d0 + j, nD - 1)
        hit = ~done & (sign * (P.C[ti, dj] - entry) >= 0)
        exit_d = np.where(hit, dj, exit_d)
        done |= hit
    return mk_trades(P, ti, p_in, 2 * exit_d + 1, sign)


# ---------------------------------------------------------------- earnings
def load_earnings(P):
    rows = []
    tpos = {t: i for i, t in enumerate(P.tickers)}
    for t in P.tickers:
        f = EDIR / "earnings" / f"{t}.parquet"
        if not f.exists():
            continue
        e = pd.read_parquet(f)
        if e.empty or "Earnings Date" not in e:
            continue
        ts = pd.to_datetime(e["Earnings Date"], utc=True).dt.tz_convert("America/New_York")
        hm = ts.dt.hour * 60 + ts.dt.minute
        df = pd.DataFrame({"ti": tpos[t], "date": ts.dt.date, "hm": hm,
                           "surp": pd.to_numeric(e.get("Surprise(%)"), errors="coerce"),
                           "rep": pd.to_numeric(e.get("Reported EPS"), errors="coerce")})
        df = df[(df.hm != 0) & df.rep.notna()]              # unknown time-of-day or not yet reported
        df = df.drop_duplicates("date")
        rows.append(df)
    E = pd.concat(rows, ignore_index=True)
    sess = session_on_or_after(P, E["date"].to_numpy())
    same = (sess < len(P.dates)) & (P.dates[np.minimum(sess, len(P.dates) - 1)] == E["date"].to_numpy())
    bmo = E["hm"].to_numpy() < 9 * 60 + 30
    E["d0"] = np.where(bmo, sess, np.where(same, sess + 1, sess))
    E = E[(E.d0 > 25) & (E.d0 < len(P.dates) - 1)].reset_index(drop=True)
    return E


def egap(P, E, p):
    g, mode, entry, exit_h, filt = p
    ti, d0 = E.ti.to_numpy(), E.d0.to_numpy()
    atr = P.atr[ti, d0 - 1]
    gap = (P.O[ti, d0] - P.C[ti, d0 - 1]) / atr
    m = np.abs(gap) >= g
    sign = np.sign(gap) * (1 if mode == "follow" else -1)
    if filt == "surp_agree":
        m &= np.sign(E.surp.to_numpy()) == np.sign(gap)
    if filt == "vol2x":       # close entries only (day-0 volume known at the close)
        m &= P.V[ti, d0] >= 2 * np.nanmean([P.V[ti, d0 - k] for k in range(1, 21)], axis=0)
    if filt == "close_conf":  # close entries only: day-0 close beyond open in gap direction
        m &= np.sign(P.C[ti, d0] - P.O[ti, d0]) == np.sign(gap)
    if filt == "close_rej":   # close entries only: day-0 close back against the gap
        m &= np.sign(P.C[ti, d0] - P.O[ti, d0]) == -np.sign(gap)
    ti, d0, sign = ti[m], d0[m], sign[m]
    p_in = {"o0": 2 * d0, "c0": 2 * d0 + 1, "o1": 2 * d0 + 2}[entry]
    p_out = 2 * (d0 + exit_h) + 1
    return mk_trades(P, ti, p_in, p_out, sign)


def esur(P, E, p):
    s, side, entry, h, filt = p
    ti, d0, su = E.ti.to_numpy(), E.d0.to_numpy(), E.surp.to_numpy()
    lo, sh = su >= s, su <= -s
    if s == 0:
        lo, sh = su > 0, su < 0
    sign = np.where(lo, 1.0, np.where(sh, -1.0, 0.0))
    if side == "long":
        sign[sign < 0] = 0
    elif side == "short":
        sign[sign > 0] = 0
    if filt == "gap_agree":
        gap = P.O[ti, d0] - P.C[ti, d0 - 1]
        sign[np.sign(gap) != sign] = 0
    if filt == "gap_against":   # good news but the stock gapped down (or vice versa)
        gap = P.O[ti, d0] - P.C[ti, d0 - 1]
        sign[np.sign(gap) != -sign] = 0
    m = sign != 0
    ti, d0, sign = ti[m], d0[m], sign[m]
    p_in = 2 * d0 + 1 if entry == "c0" else 2 * d0 + 2
    return mk_trades(P, ti, p_in, 2 * (d0 + h) + 1, sign)


def epre(P, E, p):
    k, exit_rule, filt = p
    ti, d0 = E.ti.to_numpy(), E.d0.to_numpy()
    dk = d0 - 1 - k                                    # enter at close of session d0-1-k
    if filt == "loser20":
        m = P.C[ti, dk] / P.C[ti, dk - 20] - 1 < 0
    elif filt == "winner20":
        m = P.C[ti, dk] / P.C[ti, dk - 20] - 1 > 0
    else:
        m = np.ones(len(ti), bool)
    ti, d0, dk = ti[m], d0[m], dk[m]
    p_out = 2 * (d0 - 1) + 1 if exit_rule == "pre" else 2 * d0 + 1
    return mk_trades(P, ti, 2 * dk + 1, p_out, np.ones(len(ti)))


# ---------------------------------------------------------------- insider
def load_insider(P):
    fr = []
    for f in sorted((EDIR / "insider").glob("*.parquet")):
        fr.append(pd.read_parquet(f))
    I = pd.concat(fr, ignore_index=True)
    I = I[I.DOCUMENT_TYPE.isin(["4", "4/A"])]
    I["sym"] = I.ISSUERTRADINGSYMBOL.str.upper().str.strip()
    tpos = {t: i for i, t in enumerate(P.tickers)}
    I = I[I.sym.isin(tpos)]
    I["fdate"] = pd.to_datetime(I.FILING_DATE, format="%d-%b-%Y", errors="coerce")
    I["tdate"] = pd.to_datetime(I.TRANS_DATE, format="%d-%b-%Y", errors="coerce")
    I["val"] = pd.to_numeric(I.TRANS_SHARES, errors="coerce") * pd.to_numeric(I.TRANS_PRICEPERSHARE,
                                                                                errors="coerce")
    I = I.dropna(subset=["fdate", "tdate", "val"])
    I = I[(I.val > 0) & ((I.fdate - I.tdate).dt.days.between(0, 30))]
    I["officer"] = I.RPTOWNER_RELATIONSHIP.fillna("").str.contains("Officer")
    I["ti"] = I.sym.map(tpos)
    I = I.drop_duplicates(["ACCESSION_NUMBER", "TRANS_DATE", "TRANS_SHARES", "TRANS_CODE"])
    # one event per (ticker, code, filing date): summed value, any-officer, distinct insiders in the
    # 10 calendar days up to and including the filing date
    out = []
    for (ti, code), g in I.groupby(["ti", "TRANS_CODE"]):
        g = g.sort_values("fdate")
        ev = g.groupby("fdate").agg(val=("val", "sum"), officer=("officer", "max")).reset_index()
        owners = g[["fdate", "RPTOWNERCIK"]].to_numpy()
        nins = []
        for fd in ev.fdate:
            w = owners[(owners[:, 0] <= fd) & (owners[:, 0] > fd - pd.Timedelta(days=10))]
            nins.append(len(set(w[:, 1])))
        ev["nins"], ev["ti"], ev["code"] = nins, ti, code
        out.append(ev)
    ev = pd.concat(out, ignore_index=True)
    s = session_on_or_after(P, (ev.fdate + pd.Timedelta(days=1)).dt.date.to_numpy())
    ev["d_in"] = s                                       # open of the first session after the filing date
    return ev[(ev.d_in > 25) & (ev.d_in < len(P.dates) - 1)].reset_index(drop=True)


def ins(P, IV, p):
    code, vmin, officer, ncl, prior, h = p
    m = (IV.code == code).to_numpy() & (IV.val >= vmin).to_numpy() & (IV.nins >= ncl).to_numpy()
    if officer:
        m &= IV.officer.to_numpy()
    ti, d = IV.ti.to_numpy()[m], IV.d_in.to_numpy()[m]
    if prior == "neg20":
        r20 = P.C[ti, d - 1] / P.C[ti, d - 21] - 1
        keep = r20 < 0 if code == "P" else r20 > 0
        ti, d = ti[keep], d[keep]
    sign = np.full(len(ti), 1.0 if code == "P" else -1.0)
    return mk_trades(P, ti, 2 * d, 2 * (d + h - 1) + 1, sign)


# ---------------------------------------------------------------- analyst
def load_ratings(P):
    rows = []
    tpos = {t: i for i, t in enumerate(P.tickers)}
    for t in P.tickers:
        f = EDIR / "ratings" / f"{t}.parquet"
        if not f.exists():
            continue
        r = pd.read_parquet(f)
        if r.empty or "GradeDate" not in r:
            continue
        df = pd.DataFrame({"ti": tpos[t], "date": pd.to_datetime(r.GradeDate).dt.date,
                           "act": r.Action, "firm": r.Firm,
                           "pt": pd.to_numeric(r.get("currentPriceTarget"), errors="coerce"),
                           "ppt": pd.to_numeric(r.get("priorPriceTarget"), errors="coerce")})
        rows.append(df)
    R = pd.concat(rows, ignore_index=True)
    R = R[R.act.isin(["up", "down", "init"])].drop_duplicates(["ti", "date", "firm"])
    R["ptchg"] = np.where((R.ppt > 0) & (R.pt > 0), R.pt / R.ppt - 1, np.nan)
    ncnt = R.groupby(["ti", "date", "act"]).firm.transform("count")
    R["nfirms"] = ncnt
    R["d_in"] = session_on_or_after(P, (pd.to_datetime(R.date) + pd.Timedelta(days=1)).dt.date.to_numpy())
    R = R[(R.d_in > 25) & (R.d_in < len(P.dates) - 1)]
    R = R.drop_duplicates(["ti", "d_in", "act"]).reset_index(drop=True)
    return R


def anl(P, R, E, p):
    act, ptf, cluster, exearn, h = p
    m = (R.act == act).to_numpy().copy()
    if ptf:
        pc = R.ptchg.to_numpy()
        m &= (pc >= 0.10) if act == "up" else (pc <= -0.10) if act == "down" else np.isfinite(pc)
    if cluster:
        m &= R.nfirms.to_numpy() >= 2
    ti, d = R.ti.to_numpy()[m], R.d_in.to_numpy()[m]
    if exearn:
        near = np.zeros(len(ti), bool)
        ek = pd.Series(1, index=pd.MultiIndex.from_arrays([E.ti, E.d0]))
        for off in range(-3, 4):
            near |= pd.MultiIndex.from_arrays([ti, d + off]).isin(ek.index)
        ti, d = ti[~near], d[~near]
    if act == "init":
        # initiations: direction from the rating text is unreliable -> long only
        sign = np.ones(len(ti))
    else:
        sign = np.full(len(ti), 1.0 if act == "up" else -1.0)
    return mk_trades(P, ti, 2 * d, 2 * (d + h - 1) + 1, sign)


# ---------------------------------------------------------------- residual reversal
def sector_map(P):
    """Monthly: for each stock, the SPDR with the highest daily-return correlation over the prior 252
    sessions, and the beta to it. Applied to sessions of the FOLLOWING month only."""
    rs = P.C / P.prevC - 1
    re = P.etf_C / _shift(P.etf_C, 1) - 1
    months = pd.to_datetime(pd.Series(P.dates)).dt.to_period("M").to_numpy()
    starts = np.flatnonzero(np.r_[True, months[1:] != months[:-1]])
    T, nD = rs.shape
    best = np.full((T, nD), -1, dtype=int)
    beta = np.full((T, nD), np.nan)
    for k, s0 in enumerate(starts):
        if s0 < 260:
            continue
        s1 = starts[k + 1] if k + 1 < len(starts) else nD
        X, Y = rs[:, s0 - 252:s0], re[:, s0 - 252:s0]
        Xm = X - np.nanmean(X, 1, keepdims=True)
        Ym = Y - np.nanmean(Y, 1, keepdims=True)
        Xz, Yz = np.nan_to_num(Xm), np.nan_to_num(Ym)
        cov = Xz @ Yz.T / 252
        sx = np.sqrt((Xz ** 2).mean(1))[:, None]
        sy = np.sqrt((Yz ** 2).mean(1))[None, :]
        with np.errstate(invalid="ignore", divide="ignore"):
            corr = cov / (sx * sy)
            bi = np.nanargmax(np.nan_to_num(corr, nan=-9), axis=1)
            b = cov[np.arange(T), bi] / (sy[0, bi] ** 2)
        valid = np.isfinite(X).sum(1) >= 200
        best[valid, s0:s1] = bi[valid, None]
        beta[valid, s0:s1] = b[valid, None]
    return best, beta


def rrv_prep(P):
    best, beta = sector_map(P)
    re = P.etf_C / _shift(P.etf_C, 1) - 1
    rs = P.C / P.prevC - 1
    T = rs.shape[0]
    bi = np.where(best >= 0, best, 0)
    rETF = re[bi, np.arange(rs.shape[1])[None, :].repeat(T, 0)]
    eps = np.where(best >= 0, rs - beta * rETF, np.nan)     # residual return of session d (known at its close)
    return best, beta, eps


def rrv(P, prep, p):
    k, q, h, entry, side = p
    best, beta, eps = prep
    sig = pd.DataFrame(eps.T).rolling(k, min_periods=k).sum().to_numpy().T
    rank = pd.DataFrame(sig.T).rank(axis=1, pct=True).to_numpy().T
    lo, hi = rank <= q, rank > 1 - q
    tl, dl = np.nonzero(lo)
    ts, ds = np.nonzero(hi)
    ti, d = np.concatenate([tl, ts]), np.concatenate([dl, ds])
    sign = np.r_[np.ones(len(tl)), -np.ones(len(ts))]
    if side == "long":
        ti, d, sign = ti[sign > 0], d[sign > 0], sign[sign > 0]
    elif side == "short":
        ti, d, sign = ti[sign < 0], d[sign < 0], sign[sign < 0]
    # beta/ETF fixed at signal time (session d belongs to a month whose map used prior data only)
    b, e = beta[ti, d], best[ti, d]
    p_in = 2 * d + 1 if entry == "close" else 2 * d + 2
    p_out = 2 * (d + h) + 1
    return mk_trades(P, ti, p_in, p_out, sign, hedge="etf", beta=b, etf_i=e)


# ---------------------------------------------------------------- ETF timing
def load_vix(P):
    import yfinance as yf
    f = EDIR / "vix.parquet"
    if not f.exists():
        v = yf.download(["^VIX", "^VIX3M"], start="1999-01-01", auto_adjust=False, progress=False)["Close"]
        v.to_parquet(f)
    v = pd.read_parquet(f)
    v.index = pd.to_datetime(v.index).date
    v = v.reindex(P.dates)
    return v["^VIX"].to_numpy(), v["^VIX3M"].to_numpy()


def mac(P, vix, p):
    sig, h = p
    vx, v3 = vix
    spy = P.etf_tick.index("SPY")
    rspy = P.etf_C[spy] / _shift(P.etf_C, 1)[spy] - 1
    with np.errstate(invalid="ignore"):
        s = {"ts1.00": vx / v3 > 1.0, "ts1.05": vx / v3 > 1.05,
             "vixjump10": vx / np.r_[np.nan, vx[:-1]] - 1 >= 0.10,
             "vixjump20": vx / np.r_[np.nan, vx[:-1]] - 1 >= 0.20,
             "vix30": vx >= 30, "spydown2": rspy <= -0.02, "spydown3": rspy <= -0.03,
             "contango_calm": (vx / v3 < 0.85)}[sig]
    d = np.flatnonzero(s)
    d = d[d + h < len(P.dates)]
    out = []
    for name in ("SPY", "QQQ", "IWM"):
        e = P.etf_tick.index(name)
        c = P.etf_C[e]
        r = c[d + h] / c[d] - 1
        allr = c[h:] / c[:-h] - 1
        base = np.array([np.nanmean(allr[(P.dates[:-h] >= lo) & (P.dates[:-h] <= hi)])
                         for lo, hi in [(P.dates[0], SEARCH_END), (HOLD_START, HOLD_END)]])
        period = (P.dates[d] >= HOLD_START).astype(int)
        raw = r * 1e4 - 2 * ETF_COST
        out.append(pd.DataFrame({"day": P.dates[d], "raw": raw, "hedged": raw - base[period] * 1e4,
                                 "sign": 1.0, "uni": name, "liquid": True}))
    df = pd.concat(out).dropna()
    return {k: df[k].to_numpy() for k in df}


# ---------------------------------------------------------------- grid
@dataclass(frozen=True)
class ECfg:
    family: str
    p: tuple
    filt: str = "none"          # post-filter: none / liquid / illiquid


def grid():
    for g, mode, entry, ex, f in itertools.product([0.5, 1, 2, 3], ["follow", "fade"], ["o0", "c0", "o1"],
                                                   [0, 1, 2, 3, 5],
                                                   ["none", "surp_agree", "vol2x", "close_conf", "close_rej"]):
        if entry == "c0" and ex == 0 or entry == "o1" and ex == 0:
            continue
        if f in ("vol2x", "close_conf", "close_rej") and entry == "o0":
            continue
        if f == "surp_agree" and entry == "o0":
            pass   # surprise is public before day-0 open by construction of d0
        for lf in ("none", "liquid", "illiquid"):
            yield ECfg("EGAP", (g, mode, entry, ex, f), lf)
    for s, side, entry, h, f in itertools.product([0, 5, 10, 25], ["both", "long", "short"], ["c0", "o1"],
                                                  [1, 2, 3, 5], ["none", "gap_agree", "gap_against"]):
        for lf in ("none", "liquid", "illiquid"):
            yield ECfg("ESUR", (s, side, entry, h, f), lf)
    for k, ex, f in itertools.product([1, 2, 3, 5], ["pre", "through"], ["none", "loser20", "winner20"]):
        for lf in ("none", "liquid", "illiquid"):
            yield ECfg("EPRE", (k, ex, f), lf)
    for code, v, off, ncl, pr, h in itertools.product(["P", "S"], [25e3, 1e5, 5e5, 1e6], [False, True], [1, 2, 3],
                                                      ["none", "neg20"], [1, 2, 3, 5]):
        for lf in ("none", "liquid", "illiquid"):
            yield ECfg("INS", (code, v, off, ncl, pr, h), lf)
    for act, ptf, cl, ex, h in itertools.product(["up", "down", "init"], [False, True], [False, True],
                                                 [False, True], [1, 2, 3, 5]):
        for lf in ("none", "liquid", "illiquid"):
            yield ECfg("ANL", (act, ptf, cl, ex, h), lf)
    for k, q, h, e, side in itertools.product([1, 2, 3, 5], [0.05, 0.10], [1, 2, 3, 5], ["close", "open"],
                                              ["both", "long", "short"]):
        for lf in ("none", "liquid", "illiquid"):
            yield ECfg("RRV", (k, q, h, e, side), lf)
    for s, h in itertools.product(["ts1.00", "ts1.05", "vixjump10", "vixjump20", "vix30", "spydown2",
                                   "spydown3", "contango_calm"], [1, 2, 3, 5]):
        yield ECfg("MAC", (s, h))


def max_lag(cfg):
    idx, add = {"EGAP": (3, 2), "ESUR": (3, 2), "EPRE": (0, 2), "INS": (5, 1), "ANL": (4, 1),
                "RRV": (2, 2), "MAC": (1, 1)}[cfg.family]
    return cfg.p[idx] + add


def stats(d, mask, lag):
    n = int(mask.sum())
    if n < 30:
        return {"n": n}
    h, raw = d["hedged"][mask], d["raw"][mask]
    return {"n": n, "mean": float(h.mean()), "raw": float(raw.mean()), "t": nw_t(d["day"][mask], h, lag),
            "win": float((h > 0).mean()), "days": int(len(np.unique(d["day"][mask])))}
