"""
Tests for swing_model/positioning_layer.py — the Market Positioning scoring
category (options, institutional ownership, short interest, insider, analyst
trend). All tests use synthetic data — no API calls.
"""

from datetime import datetime, timedelta, timezone

from swing_model.positioning_layer import compute_positioning_score, POSITIONING_MAX


class TestOptionsScore:
    def test_call_heavy_low_ratio_is_bullish(self):
        data = {"options": {"put_call_ratio": 0.4, "iv_skew": None}}
        result = compute_positioning_score("NVDA", data)
        assert result["options_score"] > 3.0

    def test_put_heavy_high_ratio_is_bearish(self):
        data = {"options": {"put_call_ratio": 1.8, "iv_skew": None}}
        result = compute_positioning_score("NVDA", data)
        assert result["options_score"] < 3.0

    def test_missing_options_forfeits_to_zero(self):
        result = compute_positioning_score("NVDA", {"options": None})
        assert result["options_score"] == 0.0
        assert result["sub_signal_data_quality"]["options"] == "unavailable"

    def test_raw_options_passthrough_for_trade_selector_greeks_filter(self):
        raw_options = {"chain": [{"strike": 100.0}], "dte": 10, "iv_percentile": 62.0}
        data = {"options": {**raw_options, "put_call_ratio": 0.9, "iv_skew": None}}
        result = compute_positioning_score("NVDA", data)
        assert result["_options_raw"] == data["options"]

    def test_raw_options_passthrough_is_none_when_no_positioning_data(self):
        result = compute_positioning_score("NVDA", {"options": None})
        assert result["_options_raw"] is None


class TestInstitutionalScore:
    def test_accumulation_scores_above_midpoint(self):
        current = {"institutional": {"held_percent_institutions": 0.62}}
        previous = {"institutional": {"held_percent_institutions": 0.58}}
        result = compute_positioning_score("NVDA", current, previous_snapshot=previous)
        assert result["institutional_score"] > 2.5

    def test_distribution_scores_below_midpoint(self):
        current = {"institutional": {"held_percent_institutions": 0.54}}
        previous = {"institutional": {"held_percent_institutions": 0.60}}
        result = compute_positioning_score("NVDA", current, previous_snapshot=previous)
        assert result["institutional_score"] < 2.5

    def test_no_previous_snapshot_gives_neutral_midpoint(self):
        current = {"institutional": {"held_percent_institutions": 0.55}}
        result = compute_positioning_score("NVDA", current, previous_snapshot=None)
        assert result["institutional_score"] == 2.5

    def test_missing_data_forfeits_to_zero(self):
        result = compute_positioning_score("NVDA", {"institutional": None})
        assert result["institutional_score"] == 0.0


class TestShortInterestScore:
    def test_declining_short_interest_is_bullish(self):
        data = {"short_interest": {"trend": "declining"}}
        result = compute_positioning_score("NVDA", data)
        assert result["short_interest_score"] == 4.0

    def test_increasing_short_interest_is_bearish(self):
        data = {"short_interest": {"trend": "increasing"}}
        result = compute_positioning_score("NVDA", data)
        assert result["short_interest_score"] == 0.0

    def test_missing_trend_forfeits_to_zero(self):
        result = compute_positioning_score("NVDA", {"short_interest": {"trend": None}})
        assert result["short_interest_score"] == 0.0


class TestInsiderScore:
    def _make_tx(self, insider, transaction, days_ago=2):
        return {
            "insider": insider, "name": insider, "transaction": transaction,
            "_parsed_date": datetime.now(timezone.utc) - timedelta(days=days_ago),
        }

    def test_multiple_buyers_scores_max(self):
        txs = [self._make_tx("A", "Purchase"), self._make_tx("B", "Purchase")]
        result = compute_positioning_score("NVDA", {"insider_transactions": txs})
        assert result["insider_score"] == 3.0

    def test_selling_cluster_scores_zero(self):
        txs = [self._make_tx("A", "Sale"), self._make_tx("B", "Sale")]
        result = compute_positioning_score("NVDA", {"insider_transactions": txs})
        assert result["insider_score"] == 0.0

    def test_no_transactions_gives_partial_midpoint(self):
        result = compute_positioning_score("NVDA", {"insider_transactions": []})
        assert result["insider_score"] == 1.5

    def test_none_forfeits_to_zero(self):
        result = compute_positioning_score("NVDA", {"insider_transactions": None})
        assert result["insider_score"] == 0.0


class TestAnalystTrendScore:
    def test_upgrade_scores_max(self):
        data = {"analyst_trend": {"net_action": "upgrade"}}
        result = compute_positioning_score("NVDA", data)
        assert result["analyst_score"] == 2.0

    def test_downgrade_scores_zero(self):
        data = {"analyst_trend": {"net_action": "downgrade"}}
        result = compute_positioning_score("NVDA", data)
        assert result["analyst_score"] == 0.0

    def test_missing_forfeits_to_zero(self):
        result = compute_positioning_score("NVDA", {"analyst_trend": None})
        assert result["analyst_score"] == 0.0


class TestPositioningAggregate:
    def test_total_capped_at_max(self):
        data = {
            "options": {"put_call_ratio": 0.2, "iv_skew": -0.08},
            "institutional": {"held_percent_institutions": 0.90},
            "short_interest": {"trend": "declining"},
            "insider_transactions": [
                {"insider": "A", "name": "A", "transaction": "Purchase"},
                {"insider": "B", "name": "B", "transaction": "Purchase"},
            ],
            "analyst_trend": {"net_action": "upgrade"},
        }
        previous = {"institutional": {"held_percent_institutions": 0.50}}
        result = compute_positioning_score("NVDA", data, previous_snapshot=previous)
        assert result["positioning_score_total"] <= POSITIONING_MAX

    def test_all_unavailable_flags_offline(self):
        result = compute_positioning_score("NVDA", {})
        assert result["positioning_offline"] is True
        assert result["positioning_score_total"] == 0.0
        assert result["data_quality"] == "unavailable"

    def test_partial_data_quality_when_mixed(self):
        data = {"short_interest": {"trend": "declining"}}
        result = compute_positioning_score("NVDA", data)
        assert result["data_quality"] == "partial"

    def test_all_required_keys_present(self):
        result = compute_positioning_score("NVDA", {})
        required = [
            "options_score", "institutional_score", "short_interest_score",
            "insider_score", "analyst_score", "positioning_score_total",
            "positioning_offline", "positioning_offline_cap", "data_quality",
            "sub_signal_data_quality",
        ]
        for key in required:
            assert key in result, f"Missing key: {key}"
