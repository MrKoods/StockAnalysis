"""Round 4: multi-signal combination models (protocol: research_results/PROTOCOL9_combo_10k.md).

Every signal is built from data available before the window's entry, converted to a per-session
cross-sectional rank-z. A model = weighted sum of 2-4 signals -> long top q / short bottom q.
Scored market-hedged: sign x (window return - equal-weight universe window return), 2 bps/side.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .families2 import XPanel
from .families3 import _rvol

WINDOWS = ["o-1030", "o-1330", "o-c", "1030-1330", "1030-c", "1230-c", "c-o", "c-1030"]
START = {"o-1030": 0, "o-1330": 0, "o-c": 0, "1030-1330": 1, "1030-c": 1, "1230-c": 3, "c-o": 9, "c-1030": 9}
COMMON = ["gap", "r1", "r5", "ibs_prev", "lh_prev", "d20", "rvol_prev", "atrp"]
AFTER_1030 = ["h1", "rvol_h1"]
AFTER_1230 = ["am"]
AT_CLOSE = ["id", "lh", "rvol_day"]


def eligible(window: str) -> list[str]:
    s = START[window]
    out = list(COMMON)
    if s >= 1:
        out += AFTER_1030
    if s >= 3:
        out += AFTER_1230
    if s == 9:
        out += AT_CLOSE
    return out


def _shift(a, k=1):
    out = np.full_like(a, np.nan)
    out[:, k:] = a[:, :-k]
    return out


def _rankz(a: np.ndarray) -> np.ndarray:
    """Per-session (column) rank -> roughly standard-normal scale; NaN stays NaN."""
    pct = pd.DataFrame(a.T).rank(axis=1, pct=True).to_numpy().T
    n = np.sum(~np.isnan(a), axis=0, keepdims=True)
    with np.errstate(invalid="ignore"):
        return (pct - 0.5 / np.maximum(n, 1) - 0.5) * np.sqrt(12)


def signals(X: XPanel) -> dict[str, np.ndarray]:
    O, H, L, C, V, atr, pc = X.O, X.H, X.L, X.C, X.V, X.atr, X.pc
    dc = C[:, :, 6]
    dH, dL = np.nanmax(H, axis=2), np.nanmin(L, axis=2)
    allnan = np.all(np.isnan(V), axis=2)
    dvol = np.where(allnan, np.nan, np.nansum(V, axis=2))
    with np.errstate(invalid="ignore", divide="ignore"):
        raw = {
            "gap": (O[:, :, 0] - pc) / atr,
            "r1": (pc - _shift(pc)) / atr,
            "r5": (_shift(dc) - _shift(dc, 6)) / atr,
            "ibs_prev": _shift((dc - dL) / (dH - dL)),
            "lh_prev": _shift(dc / C[:, :, 4] - 1),
            "d20": (pc - _shift(pd.DataFrame(dc.T).rolling(20, min_periods=16).mean().to_numpy().T)) / atr,
            "rvol_prev": _shift(_rvol(dvol)),
            "atrp": atr / pc,
            "h1": (C[:, :, 0] - O[:, :, 0]) / atr,
            "rvol_h1": _rvol(V[:, :, 0]),
            "am": (C[:, :, 2] - O[:, :, 0]) / atr,
            "id": (dc - O[:, :, 0]) / atr,
            "lh": dc / C[:, :, 4] - 1,
            "rvol_day": _rvol(dvol),
        }
    return {k: _rankz(v) for k, v in raw.items()}


def window_returns(X: XPanel, w: str) -> np.ndarray:
    O, C = X.O, X.C
    nxt = lambda a: np.concatenate([a[:, 1:], np.full((a.shape[0], 1), np.nan)], axis=1)  # noqa: E731
    with np.errstate(invalid="ignore", divide="ignore"):
        return {
            "o-1030": C[:, :, 0] / O[:, :, 0] - 1, "o-1330": C[:, :, 2] / O[:, :, 0] - 1,
            "o-c": C[:, :, 6] / O[:, :, 0] - 1, "1030-1330": C[:, :, 2] / O[:, :, 1] - 1,
            "1030-c": C[:, :, 6] / O[:, :, 1] - 1, "1230-c": C[:, :, 6] / O[:, :, 3] - 1,
            "c-o": nxt(O[:, :, 0]) / C[:, :, 6] - 1, "c-1030": nxt(C[:, :, 0]) / C[:, :, 6] - 1,
        }[w]


@dataclass
class Prepared:
    days: np.ndarray
    Z: dict          # signal -> [ticker x session] rank-z
    excess: dict     # window -> [ticker x session] hedged return (r - equal-weight r)


def prepare(X: XPanel) -> Prepared:
    Z = signals(X)
    exc = {}
    for w in WINDOWS:
        r = window_returns(X, w)
        r = np.where(np.abs(r) > 0.5, np.nan, r)            # drop corrupt bars (>50% in one window)
        exc[w] = r - np.nanmean(r, axis=0, keepdims=True)
    return Prepared(X.days, Z, exc)


@dataclass(frozen=True)
class Model:
    window: str
    feats: tuple
    weights: tuple
    q: float
    side: str


def random_models(n: int, seed: int = 20261007) -> list[Model]:
    rng = np.random.default_rng(seed)
    out = []
    for _ in range(n):
        w = WINDOWS[rng.integers(len(WINDOWS))]
        el = eligible(w)
        k = int(rng.integers(2, 5))
        feats = tuple(sorted(rng.choice(el, size=k, replace=False).tolist()))
        weights = tuple(float(x) for x in rng.choice([-1.0, -0.5, 0.5, 1.0], size=k))
        out.append(Model(w, feats, weights, float(rng.choice([0.05, 0.1, 0.2])),
                         str(rng.choice(["both", "long", "short"]))))
    return out


def score_of(P: Prepared, m: Model) -> np.ndarray:
    s = sum(wt * P.Z[f] for f, wt in zip(m.feats, m.weights))
    return s


def trades(P: Prepared, score: np.ndarray, window: str, q: float, side: str, day_mask=None):
    """Returns (day, bps, sign) arrays for the selected tails."""
    exc = P.excess[window]
    s = np.where(np.isnan(exc), np.nan, score)
    if day_mask is not None:
        s = np.where(day_mask[None, :], s, np.nan)
    pct = pd.DataFrame(s.T).rank(axis=1, pct=True).to_numpy().T
    parts = []
    if side in ("both", "long"):
        ti, di = np.nonzero(pct > 1 - q)
        parts.append((di, exc[ti, di] * 1e4 - 4, np.ones(len(ti))))
    if side in ("both", "short"):
        ti, di = np.nonzero(pct <= q)
        parts.append((di, -exc[ti, di] * 1e4 - 4, -np.ones(len(ti))))
    di = np.concatenate([p[0] for p in parts])
    return P.days[di], np.concatenate([p[1] for p in parts]), np.concatenate([p[2] for p in parts])


def ridge_beta(P: Prepared, window: str, day_mask, alpha: float = 10.0):
    feats = eligible(window)
    Xs = np.stack([P.Z[f][:, day_mask] for f in feats], axis=-1).reshape(-1, len(feats))
    y = P.excess[window][:, day_mask].reshape(-1)
    ok = ~np.isnan(y) & ~np.isnan(Xs).any(axis=1)
    A, b = Xs[ok], y[ok]
    beta = np.linalg.solve(A.T @ A + alpha * np.eye(len(feats)), A.T @ b)
    return feats, beta


def ridge_score(P: Prepared, feats, beta) -> np.ndarray:
    return sum(b * P.Z[f] for f, b in zip(feats, beta))
