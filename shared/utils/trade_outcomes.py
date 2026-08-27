"""
SHARED: terminal outcome values for paper-trading rows, and which of them
represent a trade that never had capital at risk.

Why this module exists (2026-08-26, v2.2.101): "did this row ever put money
at risk?" was expressed as a scattered `outcome != "expired"` literal in at
least eight places across paper_updater.py, paper_trade_metrics.py and
feedback_loop.py — every win-rate denominator, every P&L total, and the
calibration training set. Each was independently correct, but adding a
SECOND never-funded outcome meant finding and updating all eight, and any
one missed would silently count an unfilled signal as a real scored trade:
dragging win rate down, feeding a phantom loss into weight calibration, and
doing it invisibly, since the row looks structurally identical to a real
closed trade.

That is the same shape as the hardcoded-threshold bug this project already
hit three times (see CHANGELOG v2.2.75/v2.2.83 and
scripts/check_confidence_threshold_duplication.py). One definition, imported
everywhere, is the structural fix.
"""

# A breakout/breakdown entry order that never triggered inside
# FILL_WINDOW_DAYS. No entry, no exit, no capital at risk.
OUTCOME_EXPIRED = "expired"

# A still-pending (never filled) signal cancelled because a NEWER qualifying
# signal arrived on the same ticker and took its place. Same "no capital was
# ever at risk" status as expired, different cause: expired means the market
# never came to the order, superseded means the model changed its mind about
# the setup before the market got there.
OUTCOME_SUPERSEDED = "superseded"

# Terminal outcomes where no capital was ever at risk. These rows are real
# history worth keeping — they record that the model fired — but they must
# stay out of win-rate denominators, R:R averages, realised P&L, and the
# calibration training set, all of which are statements about capital that
# was actually committed.
UNFUNDED_OUTCOMES = frozenset({OUTCOME_EXPIRED, OUTCOME_SUPERSEDED})


def is_unfunded(outcome) -> bool:
    """True for a terminal outcome that never had capital at risk."""
    return (outcome or "") in UNFUNDED_OUTCOMES


def is_scored(outcome) -> bool:
    """
    True for a CLOSED row whose outcome represents a real directional result.

    Note an open row (blank outcome) is not "scored" either: it has no result
    yet. Callers that want "closed at all" should test `outcome` truthiness.

    This tests the OUTCOME only. A row can be scored and still never have
    deployed a cent — see is_funded() and is_performance_row() below.
    """
    return bool(outcome) and not is_unfunded(outcome)


def is_funded(row: dict) -> bool:
    """
    True if this row actually deployed capital (position_size > 0).

    A signal can qualify, resolve a real directional call, and still size to
    zero units — its best structure cost more than the confidence tier's risk
    budget allowed at this account size (see trade_selector.py's selection
    chain and paper_runner.py's sizing_note).
    """
    try:
        return float(row.get("position_size", 0) or 0) > 0
    except (TypeError, ValueError):
        return False


def is_performance_row(row: dict) -> bool:
    """
    True if this row belongs in a WIN RATE, R:R or P&L statistic — i.e. it
    closed with a real directional result AND real capital behind it.

    The distinction is not pedantic. LLY 2026-08-12 closed 2026-08-26 as a
    time_stop at -0.264R with position_size=0, pnl_dollars=0.00 — it could
    never have made or lost a cent. Counted by outcome alone it lands in the
    win-rate DENOMINATOR (and, being unprofitable, not the numerator), taking
    the paper track from 0-of-2 to 0-of-3 on the strength of a trade that
    never existed in dollar terms.

    Deliberately NOT the right filter for signal-accuracy or weight
    calibration: an unaffordable call still resolved a genuine directional
    prediction, and that is real evidence about whether the MODEL is right,
    just not about whether the STRATEGY is fit to trade money. Those callers
    (paper_trade_metrics.compute_signal_accuracy, which reports funded and
    unfunded side by side, and feedback_loop's calibration set) intentionally
    keep unfunded rows.
    """
    return is_scored(row.get("outcome")) and is_funded(row)
