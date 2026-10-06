"""Mass variant search: hundreds of thousands of configs, scored per session.

Pipeline per detection config: detect once -> vectorized exits (`fast_exit`,
identical to `engine.simulate`, see tests) -> filters as boolean masks ->
per-session R sums via bincount. Per-stock daily limits are NOT applied in the
mass scan (each setup counts as a trade); finalists are re-scored exactly with
`engine.run`.

Overfitting is measured, not assumed away:
  * CSCV / probability of backtest overfitting (Bailey, Borwein, Lopez de Prado,
    Zhu 2015): split sessions into S blocks; for every half/half split pick the
    in-sample best config and record its out-of-sample rank.
  * Best-of-N null: bootstrap sessions from config returns demeaned to zero
    edge, and compare the observed best mean with the best mean found by chance.
"""

from __future__ import annotations

import itertools
import time
from math import comb

import numpy as np
import pandas as pd

from .engine import FLATTEN, TICK, Det, Exit, Universe, detect

# ---------- vectorized exits ----------


def _first(mask: np.ndarray, start: int = 0):
    idx = np.flatnonzero(mask[start:])
    return start + int(idx[0]) if len(idx) else None


def fast_exit(U: Universe, en, ex: Exit):
    """Same result as engine.simulate; returns (r_net, r_gross, exit_bar, reason) or None."""
    ctx = U.days[en.key]
    d = ctx[1 if en.direction == "short" else -1]
    stop0 = en.extreme + ex.stop_buf_ticks * TICK + ex.stop_buf_atr * ctx["atr"]
    entry = en.entry
    if entry >= stop0:
        return None
    R = stop0 - entry
    lv = [q for q, _ in en.targets if q < entry]
    if ex.target == "level":
        if not lv or (entry - lv[0]) / R < ex.min_r:
            return None
        tp = lv[0]
    elif ex.target == "R":
        tp = entry - ex.target_r * R
    elif ex.target == "level_cap":
        tp = max(lv[0], entry - ex.target_r * R) if lv else entry - ex.target_r * R
    else:
        tp = None

    e = en.e
    flat = ctx.setdefault(("flat", d.sign), _flat_idx(d))
    T = flat if flat >= e else e          # time-exit bar (absolute)
    if ex.max_hold is not None:
        T = min(T, e + max(ex.max_hold, 1))
    end = min(T, d.n)
    H, L, Op = d.h[e:end], d.l[e:end], d.o[e:end]
    off = 1 if en.fill_on_bar else 0

    def time_exit(pos, pnl):
        if T < d.n:
            return pnl + pos * (entry - d.o[T]), T, "time"
        return pnl + pos * (entry - d.c[-1]), d.n - 1, "end_of_data"

    s1 = _first(H >= stop0)
    p1 = _first(L <= tp, off) if tp is not None else None
    mv_r = ex.partial_at_r if ex.partial_at_r is not None else ex.be_at_r
    m1 = _first(L <= entry - mv_r * R, off) if mv_r is not None else None
    cands = [x for x in (s1, p1, m1) if x is not None]
    if not cands:
        pnl, xb, why = time_exit(1.0, 0.0)
    else:
        k = min(cands)
        if s1 == k:
            px = stop0 if (k == 0 and en.fill_on_bar) else max(Op[k], stop0)
            pnl, xb, why = entry - px, e + k, ("stop_gap" if Op[k] >= stop0 and not (k == 0 and en.fill_on_bar) else "stop")
        else:
            pos, pnl = 1.0, 0.0
            if ex.partial_at_r is not None and m1 == k:
                pnl, pos = 0.5 * ex.partial_at_r * R, 0.5
            if p1 == k:
                pnl, xb, why = pnl + pos * (entry - tp), e + k, "tp"
            else:  # stop -> breakeven from the next bar
                s2 = _first(H >= entry, k + 1)
                p2 = _first(L <= tp, k + 1) if tp is not None else None
                c2 = [x for x in (s2, p2) if x is not None]
                if not c2:
                    pnl, xb, why = time_exit(pos, pnl)
                else:
                    k2 = min(c2)
                    if s2 == k2:
                        why = "stop_gap" if Op[k2] >= entry else "breakeven"
                        pnl, xb = pnl + pos * (entry - max(Op[k2], entry)), e + k2
                    else:
                        pnl, xb, why = pnl + pos * (entry - tp), e + k2, "tp"
    slip = ex.slippage_ticks * TICK
    return (pnl - 2 * slip) / R, pnl / R, xb, why


def _flat_idx(d) -> int:
    idx = np.flatnonzero(np.array([t >= FLATTEN for t in d.ts.time]))
    return int(idx[0]) if len(idx) else d.n


# ---------- grids ----------

def det_grid(base: str):
    win = {"1m": [(20, 15), (40, 30)], "5m": [(8, 6), (20, 15)]}[base]
    for trig, zone, rec, sw, (cw, to) in itertools.product(
            ["rejection", "close_out", "choch", "limit_edge"], ["fvg_or_fib", "fib"],
            [1, 3, 6], [1, 2, 3], win):
        if trig == "choch" and zone == "fib":
            continue  # zone unused by a CHoCH-close entry
        yield Det(base=base, trigger=trig, zone=zone, reclaim_bars=rec, swing_n=sw,
                  choch_window=cw, entry_timeout=to)


def exit_grid(base: str):
    hold = 30 if base == "1m" else 6
    targets = [("level", 2.0, 1.0), ("level", 2.0, 1.5), ("R", 1.0, 1.5), ("R", 1.5, 1.5),
               ("R", 2.0, 1.5), ("R", 3.0, 1.5), ("level_cap", 2.0, 1.5), ("none", 0.0, 1.5)]
    for (tg, tr, mr), mgmt, buf, mh in itertools.product(
            targets, ["plain", "be1", "partial1"], [0.0, 0.05], [None, hold]):
        yield Exit(target=tg, target_r=tr, min_r=mr, stop_buf_atr=buf, max_hold=mh,
                   be_at_r=1.0 if mgmt == "be1" else None,
                   partial_at_r=1.0 if mgmt == "partial1" else None)


FILTERS = {
    "none": lambda f: np.ones(len(f), bool),
    "short": lambda f: f["direction"].to_numpy() == "short",
    "long": lambda f: f["direction"].to_numpy() == "long",
    "t<10:30": lambda f: f["tod"].to_numpy() < 630,
    "t>=10:00": lambda f: f["tod"].to_numpy() >= 600,
    "t<14:00": lambda f: f["tod"].to_numpy() < 840,
    "stretched_vwap": lambda f: f["vwap_dist_atr"].to_numpy() > 0,
    "pd_level": lambda f: f["level_kind"].to_numpy() == "pd",
    "4h_level": lambda f: f["level_kind"].to_numpy() == "4h",
    "fvg_zone": lambda f: f["zone_kind"].to_numpy() == "fvg",
    "deep_sweep": lambda f: f["sweep_depth_atr"].to_numpy() > 0.03,
    "risk>=0.3%": lambda f: f["risk_pct"].to_numpy() >= 0.3,
    "rvol>1.2": lambda f: f["rvol_sweep"].to_numpy() > 1.2,
    "not_gap_fade": lambda f: f["gap_atr"].to_numpy() <= 0,
}


# ---------- scan ----------

def scan(base: str, log=print):
    """Returns (meta DataFrame, session list, R-sum matrix [config x session], count matrix)."""
    U = Universe(base=base)
    sessions = U.sessions()
    s_ix = {d: i for i, d in enumerate(sessions)}
    exits = list(exit_grid(base))
    metas, sums, counts = [], [], []
    t0 = time.time()
    dets = list(det_grid(base))
    for di, det in enumerate(dets):
        ents = detect(U, det)
        if not ents:
            continue
        feats = pd.DataFrame([{**en.feats, "direction": en.direction, "zone_kind": en.zone_kind,
                               "day_i": s_ix[en.day]} for en in ents])
        fmasks = {k: f(feats) for k, f in FILTERS.items()}
        day_i = feats["day_i"].to_numpy()
        for xi, ex in enumerate(exits):
            r = np.full(len(ents), np.nan)
            for i, en in enumerate(ents):
                res = fast_exit(U, en, ex)
                if res is not None:
                    r[i] = res[0]
            ok = ~np.isnan(r)
            for fk, fm in fmasks.items():
                m = ok & fm
                n = int(m.sum())
                if n < 10:
                    continue
                sums.append(np.bincount(day_i[m], weights=r[m], minlength=len(sessions)).astype(np.float32))
                counts.append(np.bincount(day_i[m], minlength=len(sessions)).astype(np.int16))
                metas.append({"det_i": di, "exit_i": xi, "filter": fk, "n": n, "mean_r": float(r[m].mean())})
        log(f"[{base}] det {di + 1}/{len(dets)}  configs so far {len(metas)}  {time.time() - t0:.0f}s")
    meta = pd.DataFrame(metas)
    return U, dets, exits, meta, sessions, np.vstack(sums), np.vstack(counts)


# ---------- overfitting statistics ----------

def pbo_cscv(M: np.ndarray, S: int = 10, metric: str = "sharpe", max_combos: int = 2000, seed: int = 0):
    """Probability of backtest overfitting. M: configs x sessions (per-session R sums)."""
    T = M.shape[1]
    blocks = np.array_split(np.arange(T), S)
    combos = list(itertools.combinations(range(S), S // 2))
    if len(combos) > max_combos:
        rng = np.random.default_rng(seed)
        combos = [combos[i] for i in rng.choice(len(combos), max_combos, replace=False)]

    def score(X):
        mu = X.mean(axis=1)
        if metric == "mean":
            return mu
        sd = X.std(axis=1, ddof=1)
        return np.where(sd > 0, mu / sd, -np.inf)

    logits, oos_of_best = [], []
    for c in combos:
        is_cols = np.concatenate([blocks[i] for i in c])
        oos_cols = np.concatenate([blocks[i] for i in range(S) if i not in c])
        is_s, oos_s = score(M[:, is_cols]), score(M[:, oos_cols])
        b = int(np.argmax(is_s))
        rank = (oos_s < oos_s[b]).mean() + 0.5 * (oos_s == oos_s[b]).mean()
        rank = min(max(rank, 1e-6), 1 - 1e-6)
        logits.append(np.log(rank / (1 - rank)))
        oos_of_best.append(float(M[b, oos_cols].mean()))
    logits = np.array(logits)
    return {"pbo": float((logits <= 0).mean()), "n_splits": len(combos),
            "median_oos_rank_logit": float(np.median(logits)),
            "mean_oos_daily_R_of_IS_best": float(np.mean(oos_of_best)),
            "share_IS_best_positive_OOS": float((np.array(oos_of_best) > 0).mean())}


def best_of_n_null(M: np.ndarray, n_boot: int = 300, seed: int = 0, chunk: int = 20000):
    """Bootstrap the best per-session mean among all configs when no config has an edge."""
    rng = np.random.default_rng(seed)
    T = M.shape[1]
    obs = M.mean(axis=1)
    Z = (M - obs[:, None]).astype(np.float32)   # zero-edge version of every config
    W = np.zeros((n_boot, T), np.float32)
    for b in range(n_boot):
        W[b] = np.bincount(rng.integers(0, T, T), minlength=T) / T
    best = np.full(n_boot, -np.inf, np.float32)
    for i in range(0, len(Z), chunk):
        best = np.maximum(best, (W @ Z[i:i + chunk].T).max(axis=1))
    return {"observed_best_daily_R": float(obs.max()),
            "null_best_p50": float(np.median(best)), "null_best_p95": float(np.percentile(best, 95)),
            "p_value": float((best >= obs.max()).mean())}


def n_combos(S: int) -> int:
    return comb(S, S // 2)
