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


def _leave_one_out_average(values_by_ticker: dict, exclude_ticker: str) -> Optional[float]:
    """
    Peer average for one ticker, excluding that ticker's own value.

    With a 6-name watchlist, each ticker's own number is worth ~17% of a
    naive full-pool average — comparing a stock's valuation/growth against a
    "peer average" that includes itself biases the comparison toward parity
    (an outlier ticker drags its own benchmark toward itself). Excluding self
    is standard peer-comparison practice; this is the shared helper both
    score_valuation_vs_peers and compute_fundamental_score's growth-vs-peers
    check use.
    """
    others = [v for t, v in values_by_ticker.items() if t != exclude_ticker]
    filtered = _exclude_outliers(others)
    return sum(filtered) / len(filtered) if filtered else None


# Monotonic premium-vs-peers scale, shared by P/E-vs-sector and EV/EBITDA-vs-
# sector scoring. premium = (ticker_metric - peer_avg) / peer_avg.
#
# Previously each metric had its own bucket ladder, and both had the same
# bug: the "else" fallback for a 10%-50%(ish) premium evaluated to the same
# score as the near-parity (0-10%) bucket, so a stock trading 45% above its
# peers scored identically to one trading 5% above — collapsing exactly the
# range most large-cap semiconductor names actually sit in. Replaced with one
# explicit monotonic ladder used by both metrics.
_PREMIUM_NEAR_PARITY_MAX = 0.15
_PREMIUM_MODERATE_MAX = 0.40
_PREMIUM_HIGH_MAX = 0.75


def _score_premium(premium: float) -> int:
    """-2..+2 score for how far a ticker's valuation multiple sits above (or
    below) its peer average. Negative premium (trading below peers) always
    scores the max +2 regardless of magnitude — a bigger discount isn't a
    stronger signal here, just a cheaper one."""
    if premium < 0:
        return 2
    if premium <= _PREMIUM_NEAR_PARITY_MAX:
        return 1
    if premium <= _PREMIUM_MODERATE_MAX:
        return 0
    if premium <= _PREMIUM_HIGH_MAX:
        return -1
    return -2


def _avg_eps_growth(fundamental_data: Optional[dict]) -> Optional[float]:
    """Average of the available quarterly YoY EPS growth rates for one
    ticker — the same figure score_earnings_momentum computes for its own
    eps_growth_score, factored out here so it can also be used to build the
    peer pool for growth-vs-peers comparison."""
    if not fundamental_data:
        return None
    earnings = fundamental_data.get("earnings") or {}
    valid_growth = [g for g in (earnings.get("eps_growth_trend") or []) if g is not None]
    return sum(valid_growth) / len(valid_growth) if valid_growth else None


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

    # Revenue declining while EPS growth screens positive/strong is the
    # classic "low quality" earnings-growth pattern — margin expansion or
    # buybacks rather than actual demand growth. Caps eps_growth_score back
    # down rather than zeroing it: the EPS growth is still real, just less
    # trustworthy as a standalone bullish signal.
    _REVENUE_QUALITY_DECLINE_THRESHOLD = -0.02
    _REVENUE_QUALITY_CAPPED_SCORE = 1

    # Peer-relative nudge applied on top of the absolute eps_growth_score —
    # absolute growth thresholds don't know whether the whole sector is in an
    # upcycle (where 10% growth is actually weak relative to peers) or a
    # downcycle (where -5% is relatively strong). +-1, capped within -3..+3,
    # so this refines rather than overrides the absolute read.
    _RELATIVE_GROWTH_OUTPERFORM_THRESHOLD = 0.10
    _RELATIVE_GROWTH_UNDERPERFORM_THRESHOLD = -0.10

    # Target-price revision threshold: a change smaller than this between two
    # snapshots is noise, not a real analyst re-rating.
    _TARGET_PRICE_REVISION_THRESHOLD = 0.02

    def score_earnings_momentum(
        self,
        fundamental_data: dict,
        peer_avg_growth: Optional[float] = None,
        live_price: Optional[float] = None,
    ) -> dict:
        """
        Score earnings momentum for one ticker.

        Input: output of FundamentalClient.get_all_fundamentals() for one ticker.

        peer_avg_growth: leave-one-out average avg_growth across the rest of
          the watchlist (see compute_fundamental_score), used to nudge
          eps_growth_score relative to peers rather than fixed absolute
          thresholds alone. None skips the nudge (e.g. single-ticker calls).
        live_price: today's actual close, used to recompute implied upside
          when the cached revisions snapshot's current_price may be stale
          (fundamentals refresh weekly-ish; price shouldn't be). Falls back
          to the cached current_price when not supplied.

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
            # Accelerating requires 2 CONSECUTIVE quarters of improving YoY
            # growth when available, not just the latest vs. the one before —
            # a single easy year-ago comp (common for cyclicals like MU,
            # living through memory-pricing boom/bust cycles) could flip a
            # 2-point comparison to "accelerating" without any real momentum.
            # Degrades gracefully to fewer points when less history exists.
            if len(valid_growth) >= 3:
                accelerating = avg_growth > 0.10 and valid_growth[0] > valid_growth[1] > valid_growth[2]
            elif len(valid_growth) == 2:
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

            # -- Peer-relative nudge ----------------------------------------
            if peer_avg_growth is not None:
                relative_growth = avg_growth - peer_avg_growth
                if relative_growth >= self._RELATIVE_GROWTH_OUTPERFORM_THRESHOLD:
                    eps_growth_score = min(3, eps_growth_score + 1)
                elif relative_growth <= self._RELATIVE_GROWTH_UNDERPERFORM_THRESHOLD:
                    eps_growth_score = max(-3, eps_growth_score - 1)
                breakdown["eps_growth"]["peer_avg_growth"] = round(peer_avg_growth, 4)
                breakdown["eps_growth"]["relative_to_peers"] = round(relative_growth, 4)

            # -- Revenue-quality check ------------------------------------
            # Runs AFTER the peer-relative nudge, not before: this is meant to
            # be the final word on whether a "screens positive" EPS growth
            # score can be trusted, not a check the peer nudge can partially
            # undo. Checking pre-nudge let a borderline score (e.g. 1, below
            # the >=2 trigger) get peer-boosted to 2 with bad revenue quality
            # behind it, and the check would never fire on it at all — and let
            # a score correctly capped to 1 for bad revenue quality get
            # nudged back up to 2 by the very next block, quietly eroding
            # 2 of the cap's intended 3-point-worth of "don't trust this"
            # penalty. Checking last catches both.
            revenue_yoy = earnings.get("revenue_yoy_growth")
            if revenue_yoy is not None:
                breakdown["eps_growth"]["revenue_yoy_growth"] = revenue_yoy
                if eps_growth_score >= 2 and revenue_yoy < self._REVENUE_QUALITY_DECLINE_THRESHOLD:
                    eps_growth_score = self._REVENUE_QUALITY_CAPPED_SCORE
                    breakdown["eps_growth"]["revenue_quality_flag"] = (
                        f"EPS growth screens positive but revenue is down "
                        f"{revenue_yoy:.1%} YoY — likely margin/buyback-driven, capped"
                    )
            gross_margin_latest = earnings.get("gross_margin_latest")
            if gross_margin_latest is not None:
                breakdown["eps_growth"]["gross_margin_latest"] = gross_margin_latest
                breakdown["eps_growth"]["gross_margin_prior"] = earnings.get("gross_margin_prior")
        else:
            eps_growth_score = 0
            breakdown["eps_growth"] = {"unavailable": True}

        # -- Estimate revisions score (max 2 pts) -------------------------
        # Prefer a real revision signal: compare today's analyst target price
        # against the PRIOR snapshot's target price (indicator_pipeline.py
        # carries the prior value forward before each refresh overwrites it).
        # This isolates "analysts changed their number" from "the stock price
        # moved" — the old implied-upside-only proxy conflated the two, since
        # upside shrinks just because a stock rallied toward its target, with
        # no analyst having revised anything.
        target = revisions.get("analyst_target_price")
        prior_target = revisions.get("prior_analyst_target_price")
        data_limitations = revisions.get("data_limitations")

        if target is not None and prior_target:
            target_change_pct = (target - prior_target) / abs(prior_target)
            if target_change_pct > self._TARGET_PRICE_REVISION_THRESHOLD:
                estimate_revisions_score = 2
            elif target_change_pct >= -self._TARGET_PRICE_REVISION_THRESHOLD:
                estimate_revisions_score = 0
            else:
                estimate_revisions_score = -2
            breakdown["estimate_revisions"] = {
                "target_change_pct": round(target_change_pct, 4),
                "prior_target": prior_target,
                "current_target": target,
                "note": "revision direction via target-price delta vs. prior snapshot",
            }
        else:
            # Cold start (no prior snapshot yet) — fall back to the
            # implied-upside proxy, recomputed against today's live price
            # when supplied rather than trusting the cached snapshot's
            # current_price, which can be up to a rotation-cycle (~7-9 days)
            # stale for a metric that's purely a price-vs-target gap.
            price = live_price if live_price is not None else revisions.get("current_price")
            implied_upside = (target - price) / price if (target is not None and price) else None

            if implied_upside is not None:
                if implied_upside > 0.20:
                    estimate_revisions_score = 2
                elif implied_upside >= -0.05:
                    estimate_revisions_score = 0
                else:
                    estimate_revisions_score = -2
                breakdown["estimate_revisions"] = {
                    "implied_upside_pct": round(implied_upside, 4),
                    "note": "proxy via implied upside — no prior snapshot yet for a true revision delta",
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
        # Two purposes: the *_by_ticker dicts feed each ticker's own
        # leave-one-out peer average below (excluding that ticker from its
        # own benchmark — see _leave_one_out_average); sector_averages (the
        # full-pool version, self included) is reported as top-level display
        # data only and is never used to score any individual ticker.
        pe_by_ticker: dict = {}
        fpe_by_ticker: dict = {}
        ev_by_ticker: dict = {}

        for ticker, fd in all_fundamentals.items():
            if fd is None:
                continue
            val = fd.get("valuation") or {}
            suspect = val.get("suspect_fields") or []

            pe = val.get("trailingPE")
            if pe is not None and "trailingPE" not in suspect:
                pe_by_ticker[ticker] = pe

            fpe = val.get("forwardPE")
            if fpe is not None and "forwardPE" not in suspect:
                fpe_by_ticker[ticker] = fpe

            ev = val.get("enterpriseToEbitda")
            if ev is not None and "enterpriseToEbitda" not in suspect:
                ev_by_ticker[ticker] = ev

        pe_values_filtered = _exclude_outliers(list(pe_by_ticker.values()))
        fpe_values_filtered = _exclude_outliers(list(fpe_by_ticker.values()))
        ev_values_filtered = _exclude_outliers(list(ev_by_ticker.values()))

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

            # -- P/E vs. peers, excluding self (max 2 pts) ----------------
            peer_pe = _leave_one_out_average(pe_by_ticker, ticker)
            pe = val.get("trailingPE")
            if pe is not None and "trailingPE" not in suspect and peer_pe:
                premium = (pe - peer_pe) / peer_pe
                pe_vs_sector_score = _score_premium(premium)
                breakdown["pe_vs_sector"] = {
                    "ticker_pe": pe, "sector_pe": round(peer_pe, 2),
                    "premium": round(premium, 4),
                }
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

            # -- EV/EBITDA vs. peers, excluding self (max 2 pts) ----------
            peer_ev = _leave_one_out_average(ev_by_ticker, ticker)
            ev = val.get("enterpriseToEbitda")
            if ev is not None and "enterpriseToEbitda" not in suspect and peer_ev:
                ev_premium = (ev - peer_ev) / peer_ev
                ev_ebitda_vs_peers_score = _score_premium(ev_premium)
                breakdown["ev_ebitda_vs_peers"] = {
                    "ticker_ev": ev, "sector_ev": round(peer_ev, 2),
                    "premium": round(ev_premium, 4),
                }
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

    def compute_fundamental_score(
        self, ticker: str, all_fundamentals: dict, live_price: Optional[float] = None
    ) -> dict:
        """
        Compute the full fundamental score for a single ticker.

        Combines earnings_momentum_score + valuation_score.
        Clamps to -15..+15. Sets fundamental_score = 0 when data_quality = 'unavailable'.

        live_price: today's actual close for this ticker (see score_all_tickers/
        score_earnings_momentum) — used to keep the implied-upside fallback
        current even when the cached fundamentals snapshot is a few days old.

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

        # Earnings momentum — peer_avg_growth is a leave-one-out average
        # across the rest of the watchlist's avg_growth, so eps_growth_score
        # can be nudged relative to peers, not just fixed absolute thresholds.
        growth_by_ticker = {
            t: g for t, fd_t in all_fundamentals.items()
            if (g := _avg_eps_growth(fd_t)) is not None
        }
        peer_avg_growth = _leave_one_out_average(growth_by_ticker, ticker)

        em_result = self.score_earnings_momentum(fd, peer_avg_growth=peer_avg_growth, live_price=live_price)
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

    def score_all_tickers(
        self, watchlist: list, fundamental_state: dict, current_prices: Optional[dict] = None
    ) -> dict:
        """
        Score all tickers in the watchlist.

        fundamental_state: dict loaded from fundamental_state.json, shape:
          {"tickers": {"NVDA": <fundamental_data or None>, ...}}

        current_prices: optional {ticker: today's close} from the same scan's
        OHLCV fetch (indicator_pipeline.run_pipeline already has this before
        it calls in). Passed through to compute_fundamental_score/
        score_earnings_momentum so the implied-upside fallback isn't computed
        against a stale cached price. None (the default) falls back to
        whatever current_price was cached in the fundamentals snapshot.

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

        current_prices = current_prices or {}
        results = {}
        for ticker in watchlist:
            try:
                results[ticker] = self.compute_fundamental_score(
                    ticker, all_fundamentals, live_price=current_prices.get(ticker)
                )
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
            with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        return {}
