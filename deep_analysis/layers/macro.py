"""
Deep macro backdrop — rates and the yield environment, the dollar, inflation,
volatility regime, the sector's own trend and its rotation vs the broad market,
and calendar seasonality — plus how much of it actually applies to this name.

Feeds: macro_data_client (Alpha Vantage economic series), the benchmark/SPY
price frames already loaded for the technical layer, and V2's macro_overlay /
seasonality helpers for the model's own read.
"""

from __future__ import annotations

from typing import Optional

import pandas as pd

from shared.utils.logger import get_logger
from shared.api_clients.macro_data_client import (
    fetch_cpi,
    fetch_federal_funds_rate,
    fetch_treasury_yield_10y,
    fetch_usd_strength,
)
from shared.api_clients.market_data_client import fetch_vix_and_pct_change
from shared.utils.macro_overlay import compute_macro_state
from shared.utils.seasonality import get_seasonality_modifier
from deep_analysis.layers._prices import last, slope_sign

logger = get_logger(__name__)

_VALIDATED_SECTORS = {"semiconductors"}  # macro_overlay / seasonality rationale scope


def _series_move(s: Optional[pd.Series], n: int) -> Optional[float]:
    if s is None or len(s.dropna()) < n + 1:
        return None
    s = s.dropna()
    prev = float(s.iloc[-n - 1])
    if prev == 0:
        return None
    return round(float(s.iloc[-1]) / prev - 1.0, 4)


def _rates() -> dict:
    tnx = _safe(fetch_treasury_yield_10y)
    ff = _safe(fetch_federal_funds_rate)
    cpi = _safe(fetch_cpi)
    cpi_yoy = None
    if cpi is not None and len(cpi.dropna()) >= 13:
        c = cpi.dropna()
        cpi_yoy = round(float(c.iloc[-1]) / float(c.iloc[-13]) - 1.0, 4)
    return {
        "treasury_10y": last(tnx),
        "treasury_10y_20d_change_pct": _series_move(tnx, 20),
        "treasury_10y_trend": slope_sign(tnx, 20) if tnx is not None else None,
        "fed_funds_rate": last(ff),
        "fed_funds_trend": slope_sign(ff, 6) if ff is not None else None,
        "cpi_yoy": cpi_yoy,
    }


def _dollar() -> dict:
    # Alpha Vantage FX series (USD/EUR-ish rate near 1.0), NOT the DXY index —
    # only its trend/direction is meaningful here, not the level.
    dxy = _safe(fetch_usd_strength)
    return {
        "usd_fx_proxy_level": last(dxy),
        "usd_20d_change_pct": _series_move(dxy, 20),
        "usd_trend": slope_sign(dxy, 20) if dxy is not None else None,
    }


def _volatility_regime() -> dict:
    vix = vix_pct = None
    got = _safe(fetch_vix_and_pct_change)
    if isinstance(got, (tuple, list)) and len(got) == 2:
        vix, vix_pct = got
    band = None
    if vix is not None:
        band = "elevated" if vix >= 25 else "low" if vix < 15 else "normal"
    return {"vix": round(vix, 2) if vix is not None else None,
            "vix_1d_change_pct": round(vix_pct, 4) if vix_pct is not None else None,
            "vix_band": band}


def _sector(
    bench_df: Optional[pd.DataFrame], spy_df: Optional[pd.DataFrame], benchmark: str,
    rotation: Optional[dict] = None,
) -> dict:
    if bench_df is None or len(bench_df) < 60:
        return {"data_quality": "unavailable"}
    bc = bench_df["Close"]
    out = {
        "benchmark": benchmark,
        "benchmark_trend_50d": slope_sign(bc, 50),
        "benchmark_vs_200d_sma_pct": (
            round(float(bc.iloc[-1]) / float(bc.rolling(200).mean().iloc[-1]) - 1.0, 4)
            if len(bc) >= 200 else None
        ),
        "benchmark_pct_from_52w_high": round(float(bc.iloc[-1]) / float(bench_df["High"].tail(252).max()) - 1.0, 4),
    }
    if spy_df is not None and len(spy_df) >= 60:
        sc = spy_df["Close"]
        idx = bc.index.intersection(sc.index)
        b, s = bc.loc[idx], sc.loc[idx]
        for n, label in ((21, "1m"), (63, "3m"), (126, "6m")):
            if len(b) > n + 1:
                out[f"benchmark_vs_spy_{label}_pp"] = round(
                    (float(b.iloc[-1] / b.iloc[-n - 1] - 1) - float(s.iloc[-1] / s.iloc[-n - 1] - 1)) * 100, 1)
    # rotation_state comes from V2's compute_rotation_state (the one the composite
    # score uses), not a second local rule that could disagree with it. The
    # per-window spreads above are supplementary colour.
    if rotation:
        out["rotation_state"] = rotation.get("rotation_state")
        out["rotation_modifier"] = rotation.get("confidence_modifier")
        out["rotation_windows"] = {
            k: rotation.get(k) for k in ("smh_vs_spy_5d", "smh_vs_spy_20d", "smh_vs_spy_60d")
            if rotation.get(k) is not None
        }
    return out


def _safe(fn):
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"macro feed {fn.__name__} failed — {exc}")
        return None


def _observations(d: dict, applies: bool, sector: Optional[str]) -> list[str]:
    obs: list[str] = []
    r = d["rates"]
    if r.get("treasury_10y") is not None:
        obs.append(f"10-year Treasury {r['treasury_10y']:.2f}% ({r.get('treasury_10y_trend')}, "
                   f"{(r.get('treasury_10y_20d_change_pct') or 0) * 100:+.1f}% over 20 sessions); "
                   f"fed funds {r.get('fed_funds_rate')}% ({r.get('fed_funds_trend')}).")
    if r.get("cpi_yoy") is not None:
        obs.append(f"CPI running {r['cpi_yoy'] * 100:.1f}% YoY.")
    dl = d["dollar"]
    if dl.get("usd_trend") is not None:
        obs.append(f"US dollar (AV FX proxy, direction only): {dl.get('usd_trend')}, "
                   f"{(dl.get('usd_20d_change_pct') or 0) * 100:+.1f}% over 20 sessions.")
    v = d["volatility_regime"]
    if v.get("vix") is not None:
        obs.append(f"VIX {v['vix']} ({v['vix_band']}).")
    s = d["sector"]
    if s.get("benchmark_trend_50d"):
        obs.append(f"{s['benchmark']} 50-day trend {s['benchmark_trend_50d']}, "
                   f"{(s.get('benchmark_pct_from_52w_high') or 0) * 100:.0f}% from its 52-week high. "
                   f"{s['benchmark']} vs SPY: {s.get('benchmark_vs_spy_1m_pp')}pp (1m) / "
                   f"{s.get('benchmark_vs_spy_3m_pp')}pp (3m) / {s.get('benchmark_vs_spy_6m_pp')}pp (6m). "
                   f"Rotation state (from the model's own rule): {s.get('rotation_state')} "
                   f"(modifier {s.get('rotation_modifier')}).")
    seas = d["seasonality"]
    if seas.get("rationale"):
        obs.append(f"Seasonality: {seas.get('seasonality_state')} — {seas['rationale']}")
    model = d["model_macro_state"]
    if model.get("macro_state"):
        obs.append(f"Model macro overlay: {model['macro_state']} "
                   f"(confidence modifier {model.get('confidence_modifier')}).")
    if not applies:
        obs.append(f"NOTE: the rates/USD/China macro rationale and the seasonality calendar are "
                   f"validated only for semiconductors — for {sector or 'this sector'} they are shown "
                   f"for context but carry no scoring weight by design.")
    return obs


def analyze_macro(
    ticker: str, sector: Optional[str] = None, *,
    benchmark: str = "SMH", frames: Optional[dict] = None, cfg: Optional[dict] = None,
    rotation: Optional[dict] = None,
) -> dict:
    """
    Deep macro backdrop for `ticker`'s sector.

    rotation: the V2 compute_rotation_state() result the composite score uses —
    passed in so this layer reports the same rotation_state rather than a second
    local rule that could disagree with it.
    """
    frames = frames or {}
    rates = _rates()
    dollar = _dollar()
    vol_regime = _volatility_regime()
    sector_view = _sector(frames.get("benchmark_daily"), frames.get("spy_daily"), benchmark, rotation)

    seasonality = get_seasonality_modifier(cfg=cfg, sector=sector, direction="bullish")

    model_macro = {}
    try:
        tnx = fetch_treasury_yield_10y()
        dxy = fetch_usd_strength()
        if tnx is not None or dxy is not None:
            model_macro = compute_macro_state(tnx, dxy, 0, cfg, sector, "bullish")
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"{ticker}: compute_macro_state failed — {exc}")

    applies = sector in _VALIDATED_SECTORS
    detail = {
        "rates": rates,
        "dollar": dollar,
        "volatility_regime": vol_regime,
        "sector": sector_view,
        "seasonality": seasonality,
        "model_macro_state": model_macro,
        "sector_rationale_applies": applies,
    }

    have = sum(1 for x in (rates.get("treasury_10y"), dollar.get("usd_fx_proxy_level"),
                           vol_regime.get("vix"), sector_view.get("benchmark_trend_50d")) if x is not None)
    dq = "complete" if have >= 3 else "partial" if have >= 1 else "unavailable"

    return {
        "summary": {
            "treasury_10y": rates.get("treasury_10y"),
            "treasury_10y_trend": rates.get("treasury_10y_trend"),
            "usd_trend": dollar.get("usd_trend"),
            "vix_band": vol_regime.get("vix_band"),
            "sector_trend": sector_view.get("benchmark_trend_50d"),
            "rotation_state": sector_view.get("rotation_state"),
            "sector_rationale_applies": applies,
        },
        "detail": detail,
        "observations": _observations(detail, applies, sector),
        "data_quality": dq,
    }
