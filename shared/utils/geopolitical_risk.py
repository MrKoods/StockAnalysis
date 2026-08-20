"""
SHARED: Fixed confidence penalty for tickers with outsized geopolitical
exposure (TSM/ASML — foreign-ADR listing risk, export-policy targeting).

Extracted from paper_runner.py/run_swing_model.py's duplicated inline blocks
(both applied the identical penalty formula; only how the resulting note was
surfaced downstream differed) — same "currently equivalent, promote once
stable" pattern already used for shared/utils/position_sizer.py's
per_unit_cost extraction.
"""


def apply_geopolitical_penalty(cfg: dict, ticker: str, final_score: float) -> tuple[float, str]:
    """
    Apply config.geopolitical_penalty to final_score if `ticker` is listed in
    config.geopolitical_risk_tickers, clamped back to [0, 100].

    Returns (adjusted_score, note) — note is "" when the ticker isn't
    flagged, otherwise a human-readable description of the penalty applied.
    The caller decides what to do with the note (append to an audit-log
    notes string, log it, both, or ignore it).
    """
    if ticker not in cfg.get("geopolitical_risk_tickers", []):
        return final_score, ""
    geo_penalty = float(cfg.get("geopolitical_penalty", -5))
    adjusted_score = max(0.0, min(100.0, final_score + geo_penalty))
    note = f"Geopolitical risk ticker ({geo_penalty:+.0f} confidence penalty applied)"
    return adjusted_score, note
