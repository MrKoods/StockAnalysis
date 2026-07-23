"""
Fundamental analysis scoring layer for the semiconductor swing trading model.

Computes a fundamental_score (-15 to +15) per ticker using two sub-scores:
  earnings_momentum_score — EPS growth trend, estimate revisions, surprise streak,
                            analyst consensus (max +9, min -9)
  valuation_score         — P/E vs. sector, forward vs. trailing PE, EV/EBITDA vs.
                            sector peers (max +6, min -6)

Combined: fundamental_score = earnings_momentum_score + valuation_score, clamped -15..+15.

Data flows from FundamentalClient.get_all_fundamentals() which is called once per week
(Monday 17:00 ET) and cached in data/processed/fundamental_state.json.

When fundamental data is unavailable, fundamental_score = 0 (neutral — not penalized).
"""

import statistics
from pathlib import Path
from typing import Optional

import yaml

from shared.utils.logger import get_logger

logger = get_logger(__name__)

_OUTLIER_MODIFIED_Z_THRESHOLD = 3.5
_OUTLIER_MIN_SAMPLE_SIZE = 4


def _exclude_outliers(values: list[float]) -> list[float]:
    """
    Drop statistical outliers before averaging a peer group (e.g. sector P/E).

    With a small watchlist (as few as 5-6 tickers), a single distorted metric —
    e.g. a P/E computed off a just-collapsed earnings base — inflates the
    "sector average" enough to make every OTHER ticker look artificially cheap
    by comparison, silently biasing their valuation scores too.

    Uses the modified Z-score (median + MAD), not mean/stdev: with this few
    data points, a single outlier corrupts the mean/stdev nearly as much as it
    corrupts the raw average we're trying to fix, whereas the median and MAD
    are far more resistant to being dragged by the one point under test.
    Falls back to the unfiltered list when there are too few points for
    outlier detection to be meaningful, or when MAD is 0 (no spread to
    measure against — nothing to flag as an outlier).
    """
    if len(values) < _OUTLIER_MIN_SAMPLE_SIZE:
        return values

    median = statistics.median(values)
    mad = statistics.median(abs(v - median) for v in values)
    if mad == 0:
        return values

    filtered = [v for v in values if 0.6745 * abs(v - median) / mad <= _OUTLIER_MODIFIED_Z_THRESHOLD]
    return filtered if filtered else values

_CONFIG_PATH = Path("config/swing_config.yaml")


class FundamentalScorer:
    """
    Scores fundamental data for all watchlist tickers.

    Usage (called from indicator_pipeline.py):
      scorer = FundamentalScorer()
      all_scores = scorer.score_all_tickers(watchlist, fundamental_state)
    """

    def __init__(self, cfg: Optional[dict] = None):
        if cfg is None:
            cfg = self._load_config()
        self._cfg = cfg
        self._watchlist = cfg.get("watchlist", {}).get("tickers", [
            "NVDA", "AMD", "AVGO", "TSM", "MU", "ASML"
        ])

    # ------------------------------------------------------------------
    # Public scoring methods
    # ------------------------------------------------------------------

    def score_earnings_momentum(self, fundamental_data: dict) -> dict:
        """
        Score earnings momentum for one ticker.

        Input: output of FundamentalClient.get_all_fundamentals() for one ticker.

        Returns dict with:
          eps_growth_score       (int, -3 to +3)
          estimate_revisions_score (int, -2 to +2)
          earnings_surprise_score  (int, -2 to +2)
          analyst_consensus_score  (int, -2 to +2)
          earnings_momentum_score  (int, clamped -9 to +9)
          component_breakdown      (dict with inputs used for each sub-score)
        """
        earnings = fundamental_data.get("earnings") or {}
        valuation = fundamental_data.get("valuation") or {}
        revisions = fundamental_data.get("revisions") or {}

        breakdown = {}

        # -- EPS growth score (-3 to +3 pts) -----------------------------
        eps_growth_trend = earnings.get("eps_growth_trend") or []
        valid_growth = [g for g in eps_growth_trend if g is not None]

        if valid_growth:
            avg_growth = sum(valid_growth) / len(valid_growth)
            # Accelerating: average > 10% AND most-recent > second-most-recent
            if len(valid_growth) >= 2:
                accelerating = avg_growth > 0.10 and valid_growth[0] > valid_growth[1]
            else:
                accelerating = avg_growth > 0.10

            # Symmetric -3..+3, graduated on the downside instead of a hard cliff:
            # avg_growth=-0.049 used to score +1 while -0.050 scored -2, and any
            # decline worse than -5% (whether -6% or a -60% earnings collapse)
            # scored identically at -2 — destroying signal for severely
            # deteriorating earnings and biasing the composite toward bullish
            # outcomes (max +3, floor -2).
            if accelerating and avg_growth > 0.10:
                eps_growth_score = 3
            elif avg_growth > 0.0:
                eps_growth_score = 2
            elif avg_growth >= -0.05:
                eps_growth_score = 1
            elif avg_growth >= -0.15:
                eps_growth_score = -1
            elif avg_growth >= -0.30:
                eps_growth_score = -2
            else:
                eps_growth_score = -3

            breakdown["eps_growth"] = {
                "avg_growth": round(avg_growth, 4),
                "quarters_used": len(valid_growth),
                "accelerating": accelerating if len(valid_growth) >= 2 else None,
            }
        else:
            eps_growth_score = 0
            breakdown["eps_growth"] = {"unavailable": True}

        # -- Estimate revisions score (max 2 pts) -------------------------
        # Free-tier limitation: we cannot determine direction vs. 30 days ago.
        # Score as neutral (0) when historical revision data is unavailable.
        # When the revisions endpoint returns data, implied_upside_pct proxies direction:
        #   large positive upside (>20%) → analyst targets are likely rising → 2 pts
        #   moderate (5-20%) → neutral → 0 pts
        #   negative (target below current price) → likely being downgraded → -2 pts
        implied_upside = revisions.get("implied_upside_pct")
        data_limitations = revisions.get("data_limitations")

        if implied_upside is not None:
            if implied_upside > 0.20:
                estimate_revisions_score = 2
            elif implied_upside >= -0.05:
                estimate_revisions_score = 0
            else:
                estimate_revisions_score = -2
            breakdown["estimate_revisions"] = {
                "implied_upside_pct": implied_upside,
                "note": "proxy via implied upside (free-tier limitation)",
            }
        else:
            estimate_revisions_score = 0
            breakdown["estimate_revisions"] = {
                "unavailable": True,
                "data_limitations": data_limitations,
            }

        # -- Earnings surprise score (max 2 pts) --------------------------
        consecutive_beats = earnings.get("consecutive_beats")
        earnings_surprises = earnings.get("earnings_surprises") or []

        if consecutive_beats is not None:
            # Count consecutive misses from most recent
            consecutive_misses = 0
            for surprise in earnings_surprises:
                if surprise is None:
                    break
                if surprise <= 0:
                    consecutive_misses += 1
                else:
                    break

            if consecutive_beats >= 3:
                earnings_surprise_score = 2
            elif consecutive_beats >= 1:
                earnings_surprise_score = 1
            elif consecutive_misses >= 2:
                earnings_surprise_score = -2
            else:
                earnings_surprise_score = 0

            breakdown["earnings_surprise"] = {
                "consecutive_beats": consecutive_beats,
                "consecutive_misses": consecutive_misses,
                "surprises": earnings_surprises[:4],
            }
        else:
            earnings_surprise_score = 0
            breakdown["earnings_surprise"] = {"unavailable": True}

        # -- Analyst consensus score (max 2 pts) --------------------------
        # recommendationMean: 1.0=Strong Buy → 5.0=Strong Sell
        rec_mean = valuation.get("recommendationMean")
        suspect_fields = valuation.get("suspect_fields") or []

        if rec_mean is not None and "recommendationMean" not in suspect_fields:
            if rec_mean <= 2.0:
                analyst_consensus_score = 2
            elif rec_mean <= 2.5:
                analyst_consensus_score = 1
            elif rec_mean <= 3.0:
                analyst_consensus_score = 0
            else:
                analyst_consensus_score = -2
            breakdown["analyst_consensus"] = {"recommendationMean": rec_mean}
        else:
            analyst_consensus_score = 0
            breakdown["analyst_consensus"] = {"unavailable": True}

        earnings_momentum_score = (
            eps_growth_score
            + estimate_revisions_score
            + earnings_surprise_score
            + analyst_consensus_score
        )
        earnings_momentum_score = max(-9, min(9, earnings_momentum_score))

        return {
            "eps_growth_score": eps_growth_score,
            "estimate_revisions_score": estimate_revisions_score,
            "earnings_surprise_score": earnings_surprise_score,
            "analyst_consensus_score": analyst_consensus_score,
            "earnings_momentum_score": earnings_momentum_score,
            "component_breakdown": breakdown,
        }

    def score_valuation_vs_peers(self, all_fundamentals: dict) -> dict:
        """
        Score valuation vs. sector peers for all tickers simultaneously.

        Input: dict of {ticker: fundamental_data} for ALL watchlist tickers.

        Computes sector averages for P/E, forward P/E, EV/EBITDA across all tickers
        (excluding None and suspect values from the averages).

        Returns dict:
          sector_averages: {pe, forward_pe, ev_ebitda}
          ticker_scores: {ticker: {pe_vs_sector_score, forward_vs_trailing_pe_score,
                                   ev_ebitda_vs_peers_score, valuation_score}}
        """
        # --- Compute sector averages (exclude None/suspect) ---
        pe_values = []
        fpe_values = []
        ev_values = []

        for ticker, fd in all_fundamentals.items():
            if fd is None:
                continue
            val = fd.get("valuation") or {}
            suspect = val.get("suspect_fields") or []

            pe = val.get("trailingPE")
            if pe is not None and "trailingPE" not in suspect:
                pe_values.append(pe)

            fpe = val.get("forwardPE")
            if fpe is not None and "forwardPE" not in suspect:
                fpe_values.append(fpe)

            ev = val.get("enterpriseToEbitda")
            if ev is not None and "enterpriseToEbitda" not in suspect:
                ev_values.append(ev)

        pe_values_filtered = _exclude_outliers(pe_values)
        fpe_values_filtered = _exclude_outliers(fpe_values)
        ev_values_filtered = _exclude_outliers(ev_values)

        sector_pe = sum(pe_values_filtered) / len(pe_values_filtered) if pe_values_filtered else None
        sector_fpe = sum(fpe_values_filtered) / len(fpe_values_filtered) if fpe_values_filtered else None
        sector_ev = sum(ev_values_filtered) / len(ev_values_filtered) if ev_values_filtered else None

        sector_averages = {
            "pe": round(sector_pe, 2) if sector_pe else None,
            "forward_pe": round(sector_fpe, 2) if sector_fpe else None,
            "ev_ebitda": round(sector_ev, 2) if sector_ev else None,
        }

        # --- Score each ticker vs. sector averages ---
        ticker_scores = {}

        for ticker, fd in all_fundamentals.items():
            if fd is None:
                ticker_scores[ticker] = {
                    "pe_vs_sector_score": 0,
                    "forward_vs_trailing_pe_score": 0,
                    "ev_ebitda_vs_peers_score": 0,
                    "valuation_score": 0,
                    "data_quality": "unavailable",
                }
                continue

            val = fd.get("valuation") or {}
            suspect = val.get("suspect_fields") or []
            breakdown = {}

            # -- P/E vs. sector average (max 2 pts) ----------------------
            pe = val.get("trailingPE")
            if pe is not None and "trailingPE" not in suspect and sector_pe is not None:
                premium = (pe - sector_pe) / sector_pe if sector_pe != 0 else None
                if premium is not None:
                    if pe < sector_pe:
                        pe_vs_sector_score = 2
                    elif premium <= 0.10:
                        pe_vs_sector_score = 1
                    elif premium >= 1.00:
                        pe_vs_sector_score = -2
                    elif premium >= 0.50:
                        pe_vs_sector_score = -1
                    else:
                        pe_vs_sector_score = 1
                    breakdown["pe_vs_sector"] = {
                        "ticker_pe": pe, "sector_pe": sector_pe,
                        "premium": round(premium, 4),
                    }
                else:
                    pe_vs_sector_score = 0
                    breakdown["pe_vs_sector"] = {"unavailable": True}
            else:
                pe_vs_sector_score = 0
                breakdown["pe_vs_sector"] = {
                    "unavailable": True,
                    "reason": "suspect" if "trailingPE" in suspect else "no_data",
                }

            # -- Forward vs. trailing P/E (max 2 pts) --------------------
            fpe = val.get("forwardPE")
            tpe = val.get("trailingPE")
            if (fpe is not None and tpe is not None
                    and "forwardPE" not in suspect and "trailingPE" not in suspect
                    and tpe != 0):
                ratio = fpe / tpe
                if ratio < 0.95:
                    forward_vs_trailing_pe_score = 2
                elif ratio <= 1.05:
                    forward_vs_trailing_pe_score = 1
                else:
                    forward_vs_trailing_pe_score = -1
                breakdown["forward_vs_trailing"] = {
                    "forwardPE": fpe, "trailingPE": tpe, "ratio": round(ratio, 4),
                }
            else:
                forward_vs_trailing_pe_score = 0
                breakdown["forward_vs_trailing"] = {"unavailable": True}

            # -- EV/EBITDA vs. sector average (max 2 pts) ----------------
            ev = val.get("enterpriseToEbitda")
            if ev is not None and "enterpriseToEbitda" not in suspect and sector_ev is not None:
                ev_premium = (ev - sector_ev) / sector_ev if sector_ev != 0 else None
                if ev_premium is not None:
                    if ev < sector_ev:
                        ev_ebitda_vs_peers_score = 2
                    elif ev_premium <= 0.10:
                        ev_ebitda_vs_peers_score = 1
                    elif ev_premium >= 0.50:
                        ev_ebitda_vs_peers_score = -1
                    else:
                        ev_ebitda_vs_peers_score = 1
                    breakdown["ev_ebitda_vs_peers"] = {
                        "ticker_ev": ev, "sector_ev": sector_ev,
                        "premium": round(ev_premium, 4),
                    }
                else:
                    ev_ebitda_vs_peers_score = 0
                    breakdown["ev_ebitda_vs_peers"] = {"unavailable": True}
            else:
                ev_ebitda_vs_peers_score = 0
                breakdown["ev_ebitda_vs_peers"] = {
                    "unavailable": True,
                    "reason": "suspect" if "enterpriseToEbitda" in suspect else "no_data",
                }

            valuation_score = (
                pe_vs_sector_score + forward_vs_trailing_pe_score + ev_ebitda_vs_peers_score
            )
            valuation_score = max(-6, min(6, valuation_score))

            # Data quality flag
            n_unavailable = sum(1 for b in breakdown.values() if b.get("unavailable"))
            if n_unavailable == 0:
                dq = "complete"
            elif n_unavailable < len(breakdown):
                dq = "partial"
            else:
                dq = "unavailable"

            ticker_scores[ticker] = {
                "pe_vs_sector_score": pe_vs_sector_score,
                "forward_vs_trailing_pe_score": forward_vs_trailing_pe_score,
                "ev_ebitda_vs_peers_score": ev_ebitda_vs_peers_score,
                "valuation_score": valuation_score,
                "data_quality": dq,
                "component_breakdown": breakdown,
            }

        return {
            "sector_averages": sector_averages,
            "ticker_scores": ticker_scores,
        }

    def compute_fundamental_score(self, ticker: str, all_fundamentals: dict) -> dict:
        """
        Compute the full fundamental score for a single ticker.

        Combines earnings_momentum_score + valuation_score.
        Clamps to -15..+15. Sets fundamental_score = 0 when data_quality = 'unavailable'.

        Returns dict:
          fundamental_score       (int, -15 to +15)
          earnings_momentum_score (int)
          valuation_score         (int)
          earnings_breakdown      (dict)
          valuation_breakdown     (dict)
          sector_averages         (dict)
          data_quality            ('complete' | 'partial' | 'unavailable')
        """
        fd = all_fundamentals.get(ticker)

        if fd is None:
            return self._unavailable_score(ticker)

        # Earnings momentum
        em_result = self.score_earnings_momentum(fd)
        em_score = em_result["earnings_momentum_score"]

        # Valuation vs. peers (requires full sector dict)
        val_result = self.score_valuation_vs_peers(all_fundamentals)
        ticker_val = val_result["ticker_scores"].get(ticker, {})
        val_score = ticker_val.get("valuation_score", 0)
        sector_avgs = val_result.get("sector_averages", {})

        # Data quality
        em_dq = "complete"
        for sub in em_result["component_breakdown"].values():
            if sub.get("unavailable"):
                em_dq = "partial"
                break

        val_dq = ticker_val.get("data_quality", "unavailable")

        if em_dq == "unavailable" and val_dq == "unavailable":
            data_quality = "unavailable"
        elif em_dq == "partial" or val_dq == "partial":
            data_quality = "partial"
        elif em_dq == "complete" and val_dq == "complete":
            data_quality = "complete"
        else:
            data_quality = "partial"

        combined = em_score + val_score
        combined = max(-15, min(15, combined))

        if data_quality == "unavailable":
            combined = 0

        return {
            "fundamental_score": combined,
            "earnings_momentum_score": em_score,
            "valuation_score": val_score,
            "earnings_breakdown": em_result["component_breakdown"],
            "eps_growth_score": em_result["eps_growth_score"],
            "estimate_revisions_score": em_result["estimate_revisions_score"],
            "earnings_surprise_score": em_result["earnings_surprise_score"],
            "analyst_consensus_score": em_result["analyst_consensus_score"],
            "valuation_breakdown": ticker_val.get("component_breakdown", {}),
            "pe_vs_sector_score": ticker_val.get("pe_vs_sector_score", 0),
            "forward_vs_trailing_pe_score": ticker_val.get("forward_vs_trailing_pe_score", 0),
            "ev_ebitda_vs_peers_score": ticker_val.get("ev_ebitda_vs_peers_score", 0),
            "sector_averages": sector_avgs,
            "data_quality": data_quality,
        }

    def score_all_tickers(self, watchlist: list, fundamental_state: dict) -> dict:
        """
        Score all tickers in the watchlist.

        fundamental_state: dict loaded from fundamental_state.json, shape:
          {"tickers": {"NVDA": <fundamental_data or None>, ...}}

        fundamental_state.json accumulates every ticker ever fetched across
        every call (forward-building-history, same pattern as Positioning) —
        it is NOT scoped to this call's `watchlist`. The peer pool handed to
        compute_fundamental_score()/score_valuation_vs_peers() below is scoped
        to `watchlist` here, not the full accumulated state: with multi-sector
        support (v2.2.8), indicator_pipeline.run_pipeline() is called once per
        active sector with that sector's own ticker list as `watchlist` — an
        unscoped peer pool would blend semiconductor and bank valuation
        multiples into one meaningless "sector average" the moment both
        sectors' data exists in the same cache file, silently corrupting every
        ticker's valuation score exactly the way the multi-sector design work
        was supposed to prevent.

        Returns dict: {ticker: compute_fundamental_score_output}
        Called by indicator_pipeline.py after fetching or loading cached data.
        """
        all_fundamentals_cached = fundamental_state.get("tickers", {})
        all_fundamentals = {t: v for t, v in all_fundamentals_cached.items() if t in watchlist}
        fetched_dates = fundamental_state.get("fetched_dates", {})

        results = {}
        for ticker in watchlist:
            try:
                results[ticker] = self.compute_fundamental_score(ticker, all_fundamentals)
            except Exception as exc:
                logger.error(f"{ticker}: fundamental scoring failed — {exc}")
                results[ticker] = self._unavailable_score(ticker)
            # Surfaces how stale this ticker's fundamental data is, since refreshes
            # are now staggered per ticker (indicator_pipeline.fetch_fundamental_data)
            # rather than all refreshed together — two tickers scored the same day
            # can have fundamentals from different dates.
            results[ticker]["data_as_of"] = fetched_dates.get(ticker)

        return results

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _unavailable_score(self, ticker: str) -> dict:
        return {
            "fundamental_score": 0,
            "earnings_momentum_score": 0,
            "valuation_score": 0,
            "earnings_breakdown": {},
            "eps_growth_score": 0,
            "estimate_revisions_score": 0,
            "earnings_surprise_score": 0,
            "analyst_consensus_score": 0,
            "valuation_breakdown": {},
            "pe_vs_sector_score": 0,
            "forward_vs_trailing_pe_score": 0,
            "ev_ebitda_vs_peers_score": 0,
            "sector_averages": {},
            "data_quality": "unavailable",
            "data_as_of": None,
        }

    @staticmethod
    def _load_config() -> dict:
        if _CONFIG_PATH.exists():
            with open(_CONFIG_PATH, "r") as f:
                return yaml.safe_load(f) or {}
        return {}
