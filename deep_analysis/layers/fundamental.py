"""
Deep fundamental view — growth, margins, cash flow, balance sheet, valuation vs
peers, analyst targets, and third-party ratings.

Feeds: SEC XBRL company-concept facts (growth / margins / cash flow / balance
sheet — the clean source), Finnhub `/stock/metric` + `/stock/profile2`
(valuation & quality ratios, peers), Seeking Alpha factor grades + analyst
price target (via RapidAPI).
"""

from __future__ import annotations

from typing import Optional

from shared.utils.logger import get_logger
from shared.api_clients import finnhub_client
from shared.api_clients import seeking_alpha_client as sa
from shared.api_clients.sec_edgar_client import fetch_financial_facts

logger = get_logger(__name__)

# GAAP concepts for a full-picture pull (non-bank issuers). Each key maps to
# candidate tags in preference order — filers tag the same line differently.
_CONCEPTS = {
    "revenue": [
        "RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues",
        "RevenueFromContractWithCustomerIncludingAssessedTax", "SalesRevenueNet",
    ],
    "gross_profit": ["GrossProfit"],
    "operating_income": ["OperatingIncomeLoss"],
    "net_income": ["NetIncomeLoss"],
    "eps_diluted": ["EarningsPerShareDiluted", "EarningsPerShareBasic"],
    "operating_cash_flow": [
        "NetCashProvidedByUsedInOperatingActivities",
        "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
    ],
    "capex": [
        "PaymentsToAcquirePropertyPlantAndEquipment",
        "PaymentsToAcquireProductiveAssets",
    ],
    "cash": [
        "CashAndCashEquivalentsAtCarryingValue",
        "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
    ],
    "total_debt": ["LongTermDebtNoncurrent", "LongTermDebt", "DebtLongtermAndShorttermCombinedAmount"],
    "equity": ["StockholdersEquity", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"],
}


def _pick(facts: dict, candidates: list[str]) -> list[dict]:
    """
    Merge every candidate tag that has data into one series, newest-tag-wins on
    any (start, end) collision, older tags filling the gaps before it.

    Filers migrate a line item between GAAP tags over the years (NVDA's revenue
    moved from `Revenues` to `RevenueFromContractWithCustomerExcludingAssessedTax`);
    taking the first tag with *any* data returned a series that stopped in 2020.
    Ordering by each tag's most-recent point and letting the freshest win keeps
    the series current while still using the retired tag for deep history.
    """
    with_data = [(t, facts[t]) for t in candidates if facts.get(t)]
    if not with_data:
        return []
    with_data.sort(key=lambda kv: kv[1][-1].get("end", ""), reverse=True)
    merged: dict = {}
    for _tag, series in with_data:  # freshest tag first — setdefault keeps its value
        for p in series:
            merged.setdefault((p.get("start"), p.get("end")), p)
    return sorted(merged.values(), key=lambda p: (p.get("end") or "", p.get("start") or ""))


def _latest_end(*series_lists: list[dict]) -> Optional[str]:
    ends = [s[-1]["end"] for s in series_lists if s and s[-1].get("end")]
    return max(ends) if ends else None


def _age_days(iso_date: Optional[str]) -> Optional[int]:
    if not iso_date:
        return None
    try:
        from datetime import date
        return (date.today() - date.fromisoformat(iso_date[:10])).days
    except (ValueError, TypeError):
        return None


def _windowed(points: list[dict], lo: int, hi: int) -> list[dict]:
    return [p for p in points if p.get("duration_days") and lo <= p["duration_days"] <= hi]


def _quarterly(points: list[dict]) -> list[dict]:
    return _windowed(points, 80, 100)


def _annual(points: list[dict]) -> list[dict]:
    return _windowed(points, 340, 380)


def _yoy(series: list[dict], n: int = 4) -> Optional[float]:
    """
    Growth of the latest value vs the same period a year earlier. Matches on the
    `end` date closest to 365 days before the latest point (NVDA and others skip
    a standalone Q4 10-Q, so a fixed n-back offset lands on the wrong quarter);
    falls back to `n` periods earlier when no dated match is close enough.
    """
    if len(series) < 2:
        return None
    from datetime import date

    cur = series[-1]
    cur_val = cur["val"]
    try:
        cur_end = date.fromisoformat(cur["end"][:10])
        target = cur_end.replace(year=cur_end.year - 1)
        prior = min(
            (p for p in series[:-1] if p.get("end")),
            key=lambda p: abs((date.fromisoformat(p["end"][:10]) - target).days),
            default=None,
        )
        if prior and abs((date.fromisoformat(prior["end"][:10]) - target).days) <= 45:
            if prior["val"]:
                return round((cur_val - prior["val"]) / abs(prior["val"]), 4)
    except (ValueError, TypeError):
        pass

    if len(series) < n + 1 or not series[-1 - n]["val"]:
        return None
    return round((cur_val - series[-1 - n]["val"]) / abs(series[-1 - n]["val"]), 4)


def _series_tail(series: list[dict], k: int = 8) -> list[dict]:
    return [{"end": p["end"], "val": round(p["val"], 4), "fp": p.get("fp")} for p in series[-k:]]


def _margin_trend(numer: list[dict], denom: list[dict]) -> list[dict]:
    d_by_end = {p["end"]: p["val"] for p in denom}
    out = []
    for p in numer:
        base = d_by_end.get(p["end"])
        if base and base != 0:
            m = p["val"] / base
            if -1.0 < m < 1.5:
                out.append({"end": p["end"], "margin": round(m, 4)})
    return out[-8:]


def _growth(facts: dict) -> dict:
    rev_q = _quarterly(_pick(facts, _CONCEPTS["revenue"]))
    rev_a = _annual(_pick(facts, _CONCEPTS["revenue"]))
    eps_q = _quarterly(_pick(facts, _CONCEPTS["eps_diluted"]))
    ni_q = _quarterly(_pick(facts, _CONCEPTS["net_income"]))
    as_of = _latest_end(rev_q, eps_q, ni_q)
    age = _age_days(as_of)
    return {
        "xbrl_as_of": as_of,
        "xbrl_age_days": age,
        "xbrl_stale": age is not None and age > 150,
        "revenue_quarterly": _series_tail(rev_q),
        "revenue_yoy_latest": _yoy(rev_q, 4),
        "revenue_yoy_prior": _yoy(rev_q[:-1], 4) if len(rev_q) > 5 else None,
        "revenue_annual": _series_tail(rev_a, 5),
        "revenue_yoy_annual": _yoy(rev_a, 1),
        "eps_yoy_latest": _yoy(eps_q, 4),
        "net_income_yoy_latest": _yoy(ni_q, 4),
    }


def _profitability(facts: dict) -> dict:
    rev_q = _quarterly(_pick(facts, _CONCEPTS["revenue"]))
    return {
        "gross_margin_trend": _margin_trend(_quarterly(_pick(facts, _CONCEPTS["gross_profit"])), rev_q),
        "operating_margin_trend": _margin_trend(_quarterly(_pick(facts, _CONCEPTS["operating_income"])), rev_q),
        "net_margin_trend": _margin_trend(_quarterly(_pick(facts, _CONCEPTS["net_income"])), rev_q),
    }


def _cash_flow(facts: dict) -> dict:
    ocf = _quarterly(_pick(facts, _CONCEPTS["operating_cash_flow"]))
    capex = _quarterly(_pick(facts, _CONCEPTS["capex"]))
    rev_q = {p["end"]: p["val"] for p in _quarterly(_pick(facts, _CONCEPTS["revenue"]))}
    capex_by_end = {p["end"]: p["val"] for p in capex}
    fcf = []
    for p in ocf:
        cx = capex_by_end.get(p["end"])
        if cx is not None:
            f = p["val"] - cx
            entry = {"end": p["end"], "fcf": round(f, 0)}
            if rev_q.get(p["end"]):
                entry["fcf_margin"] = round(f / rev_q[p["end"]], 4)
            fcf.append(entry)
    return {"operating_cash_flow_quarterly": _series_tail(ocf), "free_cash_flow_quarterly": fcf[-8:]}


def _balance_sheet(facts: dict) -> dict:
    def _latest_instant(points):
        inst = [p for p in points if not p.get("start")]
        return inst[-1] if inst else (points[-1] if points else None)

    cash = _latest_instant(_pick(facts, _CONCEPTS["cash"]))
    debt = _latest_instant(_pick(facts, _CONCEPTS["total_debt"]))
    equity = _latest_instant(_pick(facts, _CONCEPTS["equity"]))
    out = {
        "cash": round(cash["val"], 0) if cash else None,
        "long_term_debt": round(debt["val"], 0) if debt else None,
        "equity": round(equity["val"], 0) if equity else None,
        "as_of": (cash or debt or equity or {}).get("end"),
    }
    if out["cash"] is not None and out["long_term_debt"] is not None:
        out["net_debt"] = round(out["long_term_debt"] - out["cash"], 0)
    if out["long_term_debt"] is not None and out["equity"] not in (None, 0):
        out["debt_to_equity"] = round(out["long_term_debt"] / out["equity"], 2)
    return out


def _valuation_and_quality(ticker: str, current_price: Optional[float]) -> dict:
    metric = {}
    try:
        metric = finnhub_client.get_metric(ticker) or {}
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"{ticker}: finnhub metric failed — {exc}")

    def m(*keys):
        for k in keys:
            v = metric.get(k)
            if isinstance(v, (int, float)):
                return round(float(v), 3)
        return None

    valuation = {
        "pe_ttm": m("peTTM", "peBasicExclExtraTTM"),
        "pe_forward": m("peForward", "forwardPE"),
        "ps_ttm": m("psTTM"),
        "pb": m("pbAnnual", "pbQuarterly"),
        "ev_ebitda": m("currentEv/freeCashFlowTTM", "evEbitdaTTM"),
        "peg": m("pegTTM", "pegRatio"),
    }
    quality = {
        "roe_ttm": m("roeTTM"),
        "roa_ttm": m("roaTTM"),
        "gross_margin_ttm": m("grossMarginTTM"),
        "operating_margin_ttm": m("operatingMarginTTM"),
        "net_margin_ttm": m("netProfitMarginTTM"),
        "revenue_growth_ttm_yoy": m("revenueGrowthTTMYoy"),
        "eps_growth_ttm_yoy": m("epsGrowthTTMYoy"),
        "beta": m("beta"),
        "52w_high": m("52WeekHigh"), "52w_low": m("52WeekLow"),
    }

    peers_val = []
    try:
        peers = (finnhub_client.get_peers(ticker) or [])[:8]
        for p in peers:
            if p.upper() == ticker.upper():
                continue
            pm = finnhub_client.get_metric(p) or {}
            row = {"ticker": p}
            for label, key in (("pe_ttm", "peTTM"), ("ps_ttm", "psTTM"), ("ev_ebitda", "evEbitdaTTM")):
                v = pm.get(key)
                if isinstance(v, (int, float)):
                    row[label] = round(float(v), 2)
            if len(row) > 1:
                peers_val.append(row)
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"{ticker}: peer valuation failed — {exc}")

    def _peer_avg(field):
        vals = [r[field] for r in peers_val if isinstance(r.get(field), (int, float)) and r[field] > 0]
        return round(sum(vals) / len(vals), 2) if vals else None

    return {
        "valuation": valuation,
        "quality": quality,
        "peers": peers_val,
        "peer_avg": {f: _peer_avg(f) for f in ("pe_ttm", "ps_ttm", "ev_ebitda")},
    }


def _ratings_and_targets(ticker: str, current_price: Optional[float]) -> dict:
    grades = {}
    try:
        grades = sa.get_factor_grades(ticker) or {}
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"{ticker}: SA factor grades failed — {exc}")
    target = {}
    try:
        target = sa.get_analyst_price_target(ticker) or {}
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"{ticker}: SA price target failed — {exc}")

    tmean = target.get("target_mean")
    implied = None
    if tmean and current_price:
        implied = round(tmean / current_price - 1.0, 4)
    return {
        "sa_quant_rating": grades.get("quant_rating"),
        "sa_sell_side_rating": grades.get("sell_side_rating"),
        "sa_authors_rating": grades.get("authors_rating"),
        "sa_rating_revision_30d": {
            "buy": grades.get("buy_count_30d"), "hold": grades.get("hold_count_30d"),
            "sell": grades.get("sell_count_30d"),
        },
        "analyst_target_mean": tmean,
        "analyst_target_low": target.get("target_low"),
        "analyst_target_high": target.get("target_high"),
        "analyst_target_implied_pct": implied,
        "analyst_revisions_up": target.get("revisions_up"),
        "analyst_revisions_down": target.get("revisions_down"),
    }


def _observations(d: dict) -> list[str]:
    obs: list[str] = []
    g = d.get("growth", {})
    q = d.get("valuation_quality", {}).get("quality", {})
    stale = g.get("xbrl_stale")

    # Current growth: prefer Finnhub TTM; use the SEC XBRL quarter only when it's fresh.
    if q.get("revenue_growth_ttm_yoy") is not None:
        obs.append(f"Revenue growth {q['revenue_growth_ttm_yoy']}% TTM YoY, EPS growth "
                   f"{q.get('eps_growth_ttm_yoy')}% TTM YoY (Finnhub, trailing-twelve-month).")
    if stale:
        obs.append(f"NOTE: the SEC-XBRL quarterly/margin trend series below is stale — it ends "
                   f"{g.get('xbrl_as_of')} ({g.get('xbrl_age_days')} days ago), so its 'latest quarter' "
                   f"figures describe an old period, not the most recent report. Use the TTM figures above "
                   f"for the current picture.")
    elif g.get("revenue_yoy_latest") is not None:
        line = f"SEC XBRL: revenue grew {g['revenue_yoy_latest'] * 100:+.1f}% YoY in the quarter ending {g.get('xbrl_as_of')}"
        if g.get("revenue_yoy_prior") is not None:
            line += f" (vs {g['revenue_yoy_prior'] * 100:+.1f}% the quarter before — " + (
                "accelerating" if g["revenue_yoy_latest"] > g["revenue_yoy_prior"] else "decelerating") + ")"
        obs.append(line + ".")
        if g.get("eps_yoy_latest") is not None:
            obs.append(f"SEC XBRL: diluted EPS {g['eps_yoy_latest'] * 100:+.1f}% YoY that quarter.")

    p = d.get("profitability", {})
    if not stale:
        for name, key in (("Gross", "gross_margin_trend"), ("Operating", "operating_margin_trend"), ("Net", "net_margin_trend")):
            tr = p.get(key) or []
            if len(tr) >= 2:
                obs.append(f"{name} margin {tr[-1]['margin'] * 100:.1f}% (quarter ending {tr[-1]['end']}) vs "
                           f"{tr[-2]['margin'] * 100:.1f}% prior "
                           f"({'expanding' if tr[-1]['margin'] > tr[-2]['margin'] else 'compressing'}).")
    if q.get("gross_margin_ttm") is not None:
        obs.append(f"Margins (TTM): gross {q['gross_margin_ttm']}%, operating {q.get('operating_margin_ttm')}%, "
                   f"net {q.get('net_margin_ttm')}%.")
    cf = d.get("cash_flow", {})
    fcf = cf.get("free_cash_flow_quarterly") or []
    if fcf and "fcf_margin" in fcf[-1] and not stale:
        obs.append(f"Free cash flow margin {fcf[-1]['fcf_margin'] * 100:.1f}% (quarter ending {fcf[-1]['end']}).")
    bs = d.get("balance_sheet", {})
    if bs.get("net_debt") is not None:
        obs.append(f"Net debt {bs['net_debt'] / 1e9:+.2f}B (debt/equity {bs.get('debt_to_equity')}), as of {bs.get('as_of')}.")
    v = d.get("valuation_quality", {}).get("valuation", {})
    pa = d.get("valuation_quality", {}).get("peer_avg", {})
    if v.get("pe_ttm") is not None:
        line = f"P/E (TTM) {v['pe_ttm']}"
        if pa.get("pe_ttm"):
            line += f" vs peer avg {pa['pe_ttm']}"
        if v.get("pe_forward"):
            line += f"; forward P/E {v['pe_forward']}"
        obs.append(line + ".")
    if v.get("ev_ebitda") is not None and pa.get("ev_ebitda"):
        obs.append(f"EV/EBITDA {v['ev_ebitda']} vs peer avg {pa['ev_ebitda']}.")
    q = d.get("valuation_quality", {}).get("quality", {})
    if q.get("roe_ttm") is not None:
        obs.append(f"ROE (TTM) {q['roe_ttm']}%, net margin {q.get('net_margin_ttm')}%.")
    r = d.get("ratings_targets", {})
    if r.get("sa_quant_rating") is not None:
        obs.append(f"Seeking Alpha quant rating {r['sa_quant_rating']}/5 "
                   f"(sell-side {r.get('sa_sell_side_rating')}/5).")
    if r.get("analyst_target_implied_pct") is not None:
        obs.append(f"Mean analyst target implies {r['analyst_target_implied_pct'] * 100:+.1f}% "
                   f"(range {r.get('analyst_target_low')}–{r.get('analyst_target_high')}); "
                   f"revisions {r.get('analyst_revisions_up')} up / {r.get('analyst_revisions_down')} down.")
    return obs


def analyze_fundamental(
    ticker: str, sector: Optional[str] = None, *, current_price: Optional[float] = None,
) -> dict:
    """Deep fundamental view for `ticker`."""
    facts = {}
    try:
        all_tags = [t for cands in _CONCEPTS.values() for t in cands]
        facts = fetch_financial_facts(ticker, all_tags) or {}
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"{ticker}: SEC XBRL fetch failed — {exc}")

    profile = {}
    try:
        profile = finnhub_client.get_profile(ticker) or {}
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"{ticker}: finnhub profile failed — {exc}")

    detail = {
        "profile": profile,
        "growth": _growth(facts) if facts else {},
        "profitability": _profitability(facts) if facts else {},
        "cash_flow": _cash_flow(facts) if facts else {},
        "balance_sheet": _balance_sheet(facts) if facts else {},
        "valuation_quality": _valuation_and_quality(ticker, current_price),
        "ratings_targets": _ratings_and_targets(ticker, current_price),
        "xbrl_concepts_found": sorted(facts.keys()),
    }

    g = detail["growth"]
    qual = detail["valuation_quality"]["quality"]
    summary = {
        "industry": profile.get("industry"),
        "market_cap_m": profile.get("market_cap_m"),
        "revenue_growth_ttm_yoy": qual.get("revenue_growth_ttm_yoy"),
        "eps_growth_ttm_yoy": qual.get("eps_growth_ttm_yoy"),
        "net_margin_ttm": qual.get("net_margin_ttm"),
        "pe_ttm": detail["valuation_quality"]["valuation"].get("pe_ttm"),
        "pe_forward": detail["valuation_quality"]["valuation"].get("pe_forward"),
        "sa_quant_rating": detail["ratings_targets"].get("sa_quant_rating"),
        "analyst_target_implied_pct": detail["ratings_targets"].get("analyst_target_implied_pct"),
        "xbrl_trend_as_of": g.get("xbrl_as_of"),
        "xbrl_trend_stale": g.get("xbrl_stale", False),
        "balance_sheet_as_of": detail["balance_sheet"].get("as_of"),
    }

    has_sec = bool(facts) and not g.get("xbrl_stale", False)
    has_ratios = detail["valuation_quality"]["valuation"].get("pe_ttm") is not None
    dq = "complete" if (has_sec and has_ratios) else "partial" if (bool(facts) or has_ratios) else "unavailable"

    return {
        "summary": summary,
        "detail": detail,
        "observations": _observations(detail),
        "data_quality": dq,
    }
