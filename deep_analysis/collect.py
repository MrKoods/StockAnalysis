"""
Stage 1 — run every analysis layer for a single ticker and collect the full
result (every sub-signal plus the raw inputs behind it) into one bundle.

This is a single-ticker sibling of swing_model/run_swing_model.py's per-ticker
loop, with the trade-selection machinery removed — no position sizing, no
trade-structure ranking, no circuit breaker, no Discord alerts, no event-gate
blocking. It reuses V2's layer functions unchanged; V3's job for now is to
surface what they see, not to re-derive them. The layers themselves get
deepened in a later phase (see RESEARCH_LOG / CHANGELOG v3.0.0).

Every external fetch degrades to a neutral empty result on failure and records
the failure under findings["data_quality"] so the synthesis stage — and the
reader — can see which layers were running on real data.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from shared.utils.logger import get_logger
from swing_model.indicator_pipeline import load_config, run_pipeline
from swing_model.scoring import compute_confidence_score, determine_direction
from swing_model.sentiment_layer import classify_dominant_sentiment, compute_sentiment_score
from swing_model.news_layer import compute_news_score

from shared.api_clients.market_data_client import (
    fetch_earnings_calendar,
    fetch_ohlcv_batch,
    fetch_vix_and_pct_change,
)
from shared.api_clients.macro_data_client import fetch_treasury_yield_10y, fetch_usd_strength
from shared.api_clients.sentiment_client import fetch_seeking_alpha_engagement, fetch_stocktwits
from shared.api_clients.news_client import (
    fetch_news_alpha_vantage,
    fetch_news_finnhub,
    fetch_news_yahoo,
)
from shared.api_clients.sec_edgar_client import fetch_recent_8k_filings

from shared.utils.regime_detection import classify_regime, get_regime_modifiers
from shared.utils.macro_overlay import compute_macro_state
from shared.utils.sector_rotation import compute_rotation_state
from shared.utils.seasonality import get_seasonality_modifier
from shared.utils.earnings_calendar import get_earnings_modifier
from shared.utils.sector_config import get_ticker_benchmark, get_ticker_sector_map

logger = get_logger(__name__)

FINDINGS_SCHEMA_VERSION = 1

# Same split swing_model/run_swing_model.py's _safe_fetch draws: an expected
# feed outage degrades to empty; a programming fault is re-raised so it can't
# masquerade as "the vendor returned nothing".
_EXPECTED_FETCH_ERRORS = (OSError, ValueError, KeyError, IndexError)


def _safe(label: str, dq: dict, fn, *args, default=None, **kwargs):
    """Run one fetch; on an expected failure, record it in `dq` and return `default`."""
    try:
        result = fn(*args, **kwargs)
        return result if result is not None else default
    except _EXPECTED_FETCH_ERRORS as exc:
        logger.warning(f"{label} failed — {exc}")
        dq.setdefault("degraded", []).append(f"{label}: {exc}")
        return default
    except Exception as exc:  # noqa: BLE001 — see module docstring / _EXPECTED_FETCH_ERRORS
        logger.error(f"{label} raised an unexpected {type(exc).__name__} — this is a bug: {exc}", exc_info=True)
        dq.setdefault("errors", []).append(f"{label}: {type(exc).__name__}: {exc}")
        return default


def _headline_digest(articles: list[dict], limit: int = 40) -> list[dict]:
    """Trim raw article dicts to the fields the synthesis stage actually reads."""
    digest = []
    for art in articles or []:
        digest.append(
            {
                "title": (art.get("title") or art.get("headline") or "").strip(),
                "source": art.get("source") or art.get("provider") or "",
                "timestamp_utc": art.get("timestamp_utc") or art.get("published_utc") or art.get("datetime") or "",
                "summary": (art.get("summary") or art.get("description") or "").strip()[:400],
                "url": art.get("url") or art.get("link") or "",
            }
        )
        if len(digest) >= limit:
            break
    return digest


def _market_context(benchmark: str, dq: dict) -> dict:
    """VIX + the benchmark/SPY/TNX/DXY series the shared modifiers need."""
    ohlcv = _safe("market context OHLCV", dq, fetch_ohlcv_batch, [benchmark, "SPY"],
                  period="3mo", interval="1d", default={}) or {}
    vix = vix_pct = None
    got = _safe("VIX", dq, fetch_vix_and_pct_change, default=None)
    if isinstance(got, (tuple, list)) and len(got) == 2:
        vix, vix_pct = got
    return {
        "benchmark_df": ohlcv.get(benchmark),
        "spy_df": ohlcv.get("SPY"),
        "tnx_series": _safe("10y Treasury yield", dq, fetch_treasury_yield_10y, default=None),
        "dxy_series": _safe("USD strength", dq, fetch_usd_strength, default=None),
        "vix": float(vix) if vix is not None else None,
        "vix_pct_change": float(vix_pct) if vix_pct is not None else None,
    }


def _parse_earnings_date(raw: Optional[dict]) -> Optional[datetime]:
    if not raw:
        return None
    val = raw.get("next_earnings_date") or raw.get("earnings_date")
    if not val:
        return None
    try:
        dt = datetime.fromisoformat(str(val)[:19])
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def collect_findings(
    ticker: str,
    *,
    benchmark: Optional[str] = None,
    sector: Optional[str] = None,
    cfg: Optional[dict] = None,
    scan_type: str = "post_close",
) -> dict:
    """
    Run all five layers plus the macro backdrop for one ticker.

    benchmark: relative-strength benchmark (SMH for semis, KRE for banks, ...).
               Defaults to the ticker's configured sector benchmark, else SMH.
    sector:    sector key for the sector-scoped modifiers (macro/seasonality are
               only validated for `semiconductors` — other sectors resolve
               neutral by design). Defaults to the ticker's configured sector.

    Returns a JSON-serializable-ish bundle (pandas objects are dropped) with one
    top-level key per layer, the combined score, and a data_quality report.
    """
    ticker = ticker.upper().strip()
    cfg = cfg if cfg is not None else load_config()

    sector_map = get_ticker_sector_map(cfg)
    sector = sector or sector_map.get(ticker)
    benchmark = benchmark or get_ticker_benchmark(cfg, ticker) or "SMH"

    dq: dict = {}
    logger.info(f"deep_analysis: collecting findings for {ticker} (benchmark={benchmark}, sector={sector})")

    # --- Technical + Fundamental + Positioning (one pipeline call) --------------
    pipeline = _safe("indicator pipeline", dq, run_pipeline, [ticker],
                     benchmark=benchmark, scan_type=scan_type, cfg=cfg, default={}) or {}
    indicators = pipeline.get(ticker)
    if not indicators:
        dq.setdefault("degraded", []).append("indicator pipeline: no data for ticker (OHLCV gap or excluded)")
        indicators = {}

    fundamental = indicators.get("_fundamental_full") or {}
    positioning_bull = indicators.get("_positioning_full") or {}
    positioning_bear = indicators.get("_positioning_full_bearish") or {}
    # Keep `technical` readable — the two heavy nested bundles have their own keys.
    technical = {k: v for k, v in indicators.items() if not k.startswith("_")}

    # --- Direction (needed before the direction-aware layer formulas) ----------
    stocktwits = _safe("StockTwits", dq, fetch_stocktwits, ticker, default=[]) or []
    dominant = classify_dominant_sentiment(stocktwits).get("dominant_sentiment", "neutral")
    # cfg=None so a genuine bearish setup is described as bearish even when the
    # live prediction model has enable_bearish_signals off.
    direction = determine_direction(indicators, {"dominant_sentiment": dominant}, None)
    positioning = positioning_bear if direction == "bearish" else positioning_bull

    # --- Sentiment layer -----------------------------------------------------------
    sa_engagement = _safe("Seeking Alpha engagement", dq, fetch_seeking_alpha_engagement, ticker, default=[]) or []
    price_data = {
        "price_change_5d_pct": (
            indicators.get("close", 1.0) / max(indicators.get("sma_20", 1.0), 0.01) - 1.0
        )
    }
    sentiment = _safe(
        "sentiment scoring", dq, compute_sentiment_score,
        stocktwits, sa_engagement, ticker, price_data, cfg, direction=direction, default={},
    ) or {}

    # --- News layer --------------------------------------------------------------
    yahoo = _safe("Yahoo news", dq, fetch_news_yahoo, ticker, default=[]) or []
    finnhub = _safe("Finnhub news", dq, fetch_news_finnhub, ticker, default=[]) or []
    sec_filings = _safe("SEC 8-K filings", dq, fetch_recent_8k_filings, ticker, default=[]) or []
    sa_news = [{**item, "source": "seekingalpha.com"} for item in sa_engagement]
    # Deep-analysis mode is not rate-budget-constrained the way a 49-ticker scan
    # is: pull the Alpha Vantage per-ticker sentiment feed directly instead of
    # only as a critical-event confirmation.
    av = _safe("Alpha Vantage news", dq, fetch_news_alpha_vantage, ticker,
               scan_type=scan_type, cfg=cfg, default=[]) or []
    news = _safe(
        "news scoring", dq, compute_news_score,
        av, yahoo, ticker, cfg,
        finnhub_articles=finnhub, sector=sector, seeking_alpha_articles=sa_news,
        sec_edgar_filings=sec_filings, direction=direction, default={},
    ) or {}

    # --- Macro backdrop + shared modifiers -------------------------------------
    mkt = _market_context(benchmark, dq)
    regime = "choppy"
    if mkt["benchmark_df"] is not None and mkt["vix"] is not None:
        regime = _safe("regime classification", dq, classify_regime,
                       mkt["vix"], mkt["benchmark_df"], default="choppy") or "choppy"
    regime_modifier = get_regime_modifiers(regime, cfg, direction=direction).get("regime_modifier", 0.0)

    rotation = {}
    if mkt["benchmark_df"] is not None and mkt["spy_df"] is not None:
        rotation = _safe(
            "sector rotation", dq, compute_rotation_state,
            mkt["benchmark_df"]["Close"], mkt["spy_df"]["Close"], cfg=cfg, default={},
        ) or {}

    macro = {}
    if mkt["tnx_series"] is not None or mkt["dxy_series"] is not None:
        macro = _safe(
            "macro overlay", dq, compute_macro_state,
            mkt["tnx_series"], mkt["dxy_series"], 0, cfg, sector, direction, default={},
        ) or {}

    seasonality = get_seasonality_modifier(cfg=cfg, sector=sector, direction=direction)

    earnings_raw = _safe("earnings calendar", dq, fetch_earnings_calendar, ticker, default=None)
    earnings_date = _parse_earnings_date(earnings_raw)
    earnings = get_earnings_modifier(ticker, earnings_date, cfg=cfg)

    # --- Combined score (kept as a rail under the narrative, not the headline) -
    score = _safe(
        "confidence score", dq, compute_confidence_score,
        technical=indicators, positioning=positioning, sentiment=sentiment, news=news,
        regime_modifier=regime_modifier,
        sector_rotation_modifier=rotation.get("confidence_modifier", 0.0),
        earnings_modifier=earnings.get("confidence_modifier", 0.0),
        cross_ticker_modifier=0.0,
        seasonality_modifier=seasonality.get("confidence_modifier", 0.0),
        macro_modifier=macro.get("confidence_modifier", 0.0),
        cfg=cfg, regime=regime, fundamental=fundamental, direction_override=direction,
        default={},
    ) or {}

    layer_ok = {
        "technical": bool(technical),
        "fundamental": fundamental.get("data_quality") not in (None, "unavailable"),
        "sentiment": bool(stocktwits) or bool(sa_engagement),
        "news": bool(yahoo or finnhub or av or sec_filings),
        "positioning": bool(positioning),
        "macro": bool(mkt["tnx_series"] is not None or mkt["dxy_series"] is not None),
    }

    return {
        "schema_version": FINDINGS_SCHEMA_VERSION,
        "ticker": ticker,
        "as_of_utc": datetime.now(timezone.utc).isoformat(),
        "benchmark": benchmark,
        "sector": sector,
        "scan_type": scan_type,
        "direction": direction,
        "score": score,
        "technical": technical,
        "fundamental": fundamental,
        "positioning": {"scored_direction": direction, "bullish": positioning_bull, "bearish": positioning_bear},
        "sentiment": {
            "score": sentiment,
            "dominant_sentiment": dominant,
            "stocktwits_message_count": len(stocktwits),
            "seeking_alpha_engagement_count": len(sa_engagement),
        },
        "news": {
            "score": news,
            "headlines": _headline_digest(
                sa_news + yahoo + finnhub + av + sec_filings
            ),
            "source_counts": {
                "alpha_vantage": len(av), "yahoo": len(yahoo), "finnhub": len(finnhub),
                "seeking_alpha": len(sa_news), "sec_edgar": len(sec_filings),
            },
        },
        "macro": macro,
        "regime": {"regime": regime, "modifier": regime_modifier},
        "rotation": rotation,
        "seasonality": seasonality,
        "earnings": {
            "next_earnings_date": earnings_date.isoformat() if earnings_date else None,
            **earnings,
        },
        "market_context": {"vix": mkt["vix"], "vix_pct_change": mkt["vix_pct_change"]},
        "data_quality": {
            "layers_on_real_data": layer_ok,
            "degraded": dq.get("degraded", []),
            "errors": dq.get("errors", []),
        },
    }
