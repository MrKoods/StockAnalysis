"""
Tests for the insider-selling blind spot fix.

Before this fix: classify_transactions() had an explicit branch for a single
BUYER ("buying"), but no equivalent branch for a single SELLER — it fell
through every condition to "neutral". _signal_to_modifier() had no "selling"
case either. The module's own docstring promised "single large sell -> -3
(asymmetric — insiders sell for many reasons)" — that path didn't exist.
Downstream, positioning_layer._score_insider() gave a lone sale the exact
same score as zero insider data at all, while a lone buy always got bullish
credit — a systematic bullish bias in the insider sub-signal.
"""

from datetime import datetime, timezone, timedelta

from shared.utils.insider_tracker import (
    classify_transactions,
    _signal_to_modifier,
    _build_rationale,
)
from swing_model.positioning_layer import _score_insider, INSIDER_MAX


def _tx(shares, days_ago=0, transaction="Sale", insider="Jane CFO"):
    return {
        "insider": insider,
        "shares": shares,
        "transaction": transaction,
        "_parsed_date": datetime.now(timezone.utc) - timedelta(days=days_ago),
    }


class TestClassifyTransactionsSingleSeller:
    def test_single_seller_classified_as_selling_not_neutral(self):
        tx = [_tx(-50000)]
        assert classify_transactions(tx) == "selling"

    def test_two_sellers_still_classified_as_cluster(self):
        tx = [_tx(-50000, insider="A"), _tx(-20000, insider="B")]
        assert classify_transactions(tx) == "selling_cluster"

    def test_single_seller_via_text_field_only(self):
        tx = [{"insider": "X", "shares": 0, "transaction": "Sale",
               "_parsed_date": datetime.now(timezone.utc)}]
        assert classify_transactions(tx) == "selling"

    def test_no_transactions_still_neutral(self):
        assert classify_transactions([]) == "neutral"


class TestSignalToModifierSingleSeller:
    def test_single_seller_scores_negative_three(self):
        tx = [_tx(-50000)]
        assert _signal_to_modifier("selling", tx) == -3.0

    def test_selling_cluster_still_scores_negative_eight(self):
        tx = [_tx(-50000, insider="A"), _tx(-20000, insider="B")]
        assert _signal_to_modifier("selling_cluster", tx) == -8.0

    def test_rationale_mentions_single_seller(self):
        tx = [_tx(-50000)]
        rationale = _build_rationale("selling", tx)
        assert "seller" in rationale.lower() or "sale" in rationale.lower()


class TestScoreInsiderSingleSellerNoLongerNeutral:
    def test_single_sale_scores_below_neutral_midpoint(self):
        tx = [_tx(-50000)]
        score, dq = _score_insider(tx)
        assert dq == "complete"
        assert score < INSIDER_MAX / 2.0  # must NOT equal the "no data" midpoint

    def test_single_sale_is_not_identical_to_zero_data(self):
        """The exact bug: a real, large single sale must score DIFFERENTLY
        from having zero insider transactions at all."""
        sale_score, _ = _score_insider([_tx(-50000)])
        no_data_score, _ = _score_insider([])
        assert sale_score != no_data_score

    def test_single_buy_still_scores_above_neutral(self):
        tx = [_tx(50000, transaction="Purchase")]
        score, dq = _score_insider(tx)
        assert score > INSIDER_MAX / 2.0

    def test_selling_cluster_still_scores_zero(self):
        tx = [_tx(-50000, insider="A"), _tx(-20000, insider="B")]
        score, dq = _score_insider(tx)
        assert score == 0.0

    def test_single_sale_score_is_symmetric_with_single_buy(self):
        """Single buy = neutral + 0.75; single sell should be neutral - 0.75,
        the same distance in the opposite direction."""
        buy_score, _ = _score_insider([_tx(50000, transaction="Purchase")])
        sell_score, _ = _score_insider([_tx(-50000)])
        midpoint = INSIDER_MAX / 2.0
        assert (buy_score - midpoint) == (midpoint - sell_score)


class TestSignalToModifierDirectionMirror:
    """insider_tracker.get_insider_signal/_signal_to_modifier were bullish-only
    and unused (dead code) — fixed while building the direction-parity
    registry/CI check (2026-08-19) so it can't become a silent bullish-only
    landmine if ever wired in as a standalone modifier."""

    def test_buying_modifier_flips_negative_for_bearish(self):
        tx = [_tx(50000, transaction="Purchase", insider="A"),
              _tx(40000, transaction="Purchase", insider="B")]
        assert _signal_to_modifier("buying", tx, direction="bullish") == 8.0
        assert _signal_to_modifier("buying", tx, direction="bearish") == -8.0

    def test_selling_cluster_modifier_flips_positive_for_bearish(self):
        tx = [_tx(-50000, insider="A"), _tx(-20000, insider="B")]
        assert _signal_to_modifier("selling_cluster", tx, direction="bullish") == -8.0
        assert _signal_to_modifier("selling_cluster", tx, direction="bearish") == 8.0

    def test_default_direction_is_bullish_unchanged(self):
        tx = [_tx(-50000)]
        assert _signal_to_modifier("selling", tx) == -3.0
