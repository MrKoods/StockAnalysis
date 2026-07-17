"""
Tests for the Event Severity Gate — shared/utils/event_gate.py,
data_validator.validate_event_gate_state, news_layer.classify_severity /
compute_news_score's critical_events, scoring.compute_confidence_score's
event_gate_blocked flag, and run_swing_model's open-position critical alert path.

Advisory, not a veto: a signal with an active critical event still surfaces on
its own score merits — the gate only attaches event_gate_blocked/event_gate_trigger
so the caller can flag it, never suppresses or alters the score itself.
"""

import logging
from datetime import datetime, timezone, timedelta


import shared.utils.event_gate as event_gate
from shared.utils.event_gate import (
    classify_severity,
    is_thesis_opposed,
    is_ticker_blocked,
    add_block,
    has_active_block_for_trigger,
    expire_blocks,
    load_gate_state,
    SEVERITY_NORMAL,
    SEVERITY_CRITICAL,
    SCOPE_TICKER,
    SCOPE_SECTOR,
)
from shared.utils.data_validator import validate_event_gate_state
from swing_model.news_layer import compute_news_score, classify_severity as news_classify_severity
from swing_model.scoring import compute_confidence_score
from swing_model.run_swing_model import _handle_open_position_critical_event
from shared.utils.notification_router import PRIORITY_CRITICAL

WATCHLIST = ["NVDA", "AMD", "AVGO", "TSM", "MU", "ASML"]


def _gate_cfg(enabled: bool = True, min_cred: float = 0.5) -> dict:
    return {
        "event_severity_gate": {
            "enabled": enabled,
            "cooling_off": "next_post_close_scan",
            "sector_wide_triggers": [
                "export restriction", "export ban", "chip ban", "tariff",
                "trade war", "Taiwan Strait", "semiconductor embargo",
                "entity list", "national security review",
            ],
            "ticker_triggers": [
                "CEO resigns", "CEO departure", "fraud", "SEC investigation",
                "DOJ investigation", "guidance withdrawn",
                "accounting irregularities", "restatement", "halted",
            ],
            "principal_sources": [
                "President", "White House", "Federal Reserve",
                "Commerce Department", "USTR",
            ],
            "min_source_credibility": min_cred,
            "require_headline_match": True,
        }
    }


# ---------------------------------------------------------------------------
# classify_severity
# ---------------------------------------------------------------------------

class TestClassifySeverity:
    def test_sector_wide_trigger_from_principal_source_is_critical(self):
        result = classify_severity(
            "White House announces new chip export restriction targeting China",
            source="White House", cfg=_gate_cfg(),
        )
        assert result["severity"] == SEVERITY_CRITICAL
        assert result["scope"] == SCOPE_SECTOR
        assert result["trigger_match"] == "export restriction"
        assert result["principal_source"] is True

    def test_ticker_trigger_with_ner_attribution_is_critical(self):
        result = classify_severity(
            "AMD CEO resigns amid controversy", source="Reuters", cfg=_gate_cfg(),
        )
        assert result["severity"] == SEVERITY_CRITICAL
        assert result["scope"] == SCOPE_TICKER
        assert result["trigger_match"] == "CEO resigns"

    def test_no_trigger_match_is_normal(self):
        result = classify_severity(
            "NVDA gains market share amid strong demand", source="Reuters", cfg=_gate_cfg(),
        )
        assert result["severity"] == SEVERITY_NORMAL
        assert result["scope"] is None
        assert result["trigger_match"] is None

    def test_low_credibility_source_logs_warning_does_not_gate(self, caplog):
        # Unknown outlet defaults to 0.50 credibility; raise the bar to 0.6 so it registers as low.
        cfg = _gate_cfg(min_cred=0.6)
        with caplog.at_level(logging.WARNING):
            result = classify_severity(
                "Random blog claims new tariff imminent",
                source="totally-unknown-blog.example", cfg=cfg,
            )
        assert result["severity"] == SEVERITY_NORMAL
        assert any("low-credibility" in r.message for r in caplog.records)

    def test_principal_source_bypasses_credibility_check(self):
        cfg = _gate_cfg(min_cred=0.99)  # near-impossible bar
        result = classify_severity(
            "Federal Reserve official warns of semiconductor embargo risk",
            source="Federal Reserve", cfg=cfg,
        )
        assert result["severity"] == SEVERITY_CRITICAL

    def test_disabled_gate_is_full_pass_through_but_warns(self, caplog):
        cfg = _gate_cfg(enabled=False)
        with caplog.at_level(logging.WARNING):
            result = classify_severity(
                "White House announces new chip export restriction",
                source="White House", cfg=cfg,
            )
        assert result["severity"] == SEVERITY_NORMAL
        assert result["scope"] is None
        assert any("disabled" in r.message for r in caplog.records)

    def test_credible_ticker_trigger_source_not_downgraded(self):
        result = classify_severity(
            "SEC investigation opened into AMD accounting practices",
            source="Reuters", cfg=_gate_cfg(),
        )
        assert result["severity"] == SEVERITY_CRITICAL
        assert result["scope"] == SCOPE_TICKER


# ---------------------------------------------------------------------------
# is_thesis_opposed
# ---------------------------------------------------------------------------

class TestThesisOpposed:
    def test_bearish_news_opposes_bullish_thesis(self):
        assert is_thesis_opposed("bearish", "bullish") is True

    def test_bullish_news_opposes_bearish_thesis(self):
        assert is_thesis_opposed("bullish", "bearish") is True

    def test_bearish_news_aligned_with_bearish_thesis_not_opposed(self):
        assert is_thesis_opposed("bearish", "bearish") is False

    def test_bullish_news_aligned_with_bullish_thesis_not_opposed(self):
        assert is_thesis_opposed("bullish", "bullish") is False

    def test_neutral_or_unknown_defaults_to_opposed(self):
        assert is_thesis_opposed("neutral", "bullish") is True
        assert is_thesis_opposed(None, "bullish") is True


# ---------------------------------------------------------------------------
# Block state — add_block / is_ticker_blocked / has_active_block_for_trigger
# ---------------------------------------------------------------------------

class TestBlockState:
    def test_sector_block_covers_entire_watchlist(self):
        state = {"blocks": []}
        state = add_block(
            state, tickers=list(WATCHLIST), scope=SCOPE_SECTOR,
            trigger_headline="White House announces chip export restriction",
            trigger_match="export restriction", source="White House",
            event_timestamp_utc=datetime.now(timezone.utc).isoformat(),
        )
        for ticker in WATCHLIST:
            assert is_ticker_blocked(ticker, state) is not None

    def test_ticker_block_covers_only_that_ticker(self):
        state = {"blocks": []}
        state = add_block(
            state, tickers=["AMD"], scope=SCOPE_TICKER,
            trigger_headline="AMD CEO resigns amid controversy",
            trigger_match="CEO resigns", source="Reuters",
            event_timestamp_utc=datetime.now(timezone.utc).isoformat(),
        )
        assert is_ticker_blocked("AMD", state) is not None
        assert is_ticker_blocked("NVDA", state) is None

    def test_no_blocks_returns_none(self):
        assert is_ticker_blocked("NVDA", {"blocks": []}) is None

    def test_has_active_block_for_trigger_dedup(self):
        state = {"blocks": []}
        state = add_block(
            state, tickers=list(WATCHLIST), scope=SCOPE_SECTOR,
            trigger_headline="Tariff announcement", trigger_match="tariff",
            source="White House", event_timestamp_utc=datetime.now(timezone.utc).isoformat(),
        )
        assert has_active_block_for_trigger(state, "tariff", SCOPE_SECTOR) is True
        assert has_active_block_for_trigger(state, "chip ban", SCOPE_SECTOR) is False

    def test_expired_block_does_not_block(self):
        state = {"blocks": []}
        state = add_block(
            state, tickers=["NVDA"], scope=SCOPE_TICKER,
            trigger_headline="x", trigger_match="fraud", source="Reuters",
            event_timestamp_utc=datetime.now(timezone.utc).isoformat(),
        )
        state["blocks"][0]["expired"] = True
        assert is_ticker_blocked("NVDA", state) is None


# ---------------------------------------------------------------------------
# expire_blocks — cooling-off window
# ---------------------------------------------------------------------------

class TestExpireBlocks:
    def _blocked_state(self, event_hours_ago: float = 2.0):
        event_ts = datetime.now(timezone.utc) - timedelta(hours=event_hours_ago)
        return add_block(
            {"blocks": []}, tickers=["NVDA"], scope=SCOPE_TICKER,
            trigger_headline="x", trigger_match="fraud", source="Reuters",
            event_timestamp_utc=event_ts.isoformat(),
        )

    def test_post_close_scan_after_event_expires_block(self):
        state = self._blocked_state(event_hours_ago=2.0)
        completed_at = datetime.now(timezone.utc)
        expired = expire_blocks(state, "post_close", completed_at)
        assert len(expired) == 1
        assert is_ticker_blocked("NVDA", state) is None

    def test_non_post_close_scan_never_expires(self):
        state = self._blocked_state(event_hours_ago=2.0)
        expired = expire_blocks(state, "pre_market", datetime.now(timezone.utc))
        assert expired == []
        assert is_ticker_blocked("NVDA", state) is not None

    def test_block_created_this_scan_is_excluded_from_expiry(self):
        """
        Cooling-off requires a scan that STARTS after the block already existed —
        not the same scan run that just created it moments ago (see
        event_gate.expire_blocks docstring).
        """
        state = self._blocked_state(event_hours_ago=0.001)
        block_id = state["blocks"][0]["id"]
        expired = expire_blocks(
            state, "post_close", datetime.now(timezone.utc), exclude_ids={block_id},
        )
        assert expired == []
        assert is_ticker_blocked("NVDA", state) is not None

    def test_ticker_surfaces_normally_after_expiry(self):
        """Once expired, is_ticker_blocked returns None — normal scoring resumes."""
        state = self._blocked_state(event_hours_ago=2.0)
        expire_blocks(state, "post_close", datetime.now(timezone.utc))
        # Simulates a fresh scoring call after the gate has cleared
        assert is_ticker_blocked("NVDA", state) is None


# ---------------------------------------------------------------------------
# data_validator.validate_event_gate_state — malformed/stale auto-repair
# ---------------------------------------------------------------------------

class TestValidateEventGateState:
    def test_non_dict_repairs_to_empty(self):
        assert validate_event_gate_state(None) == {"blocks": []}
        assert validate_event_gate_state("garbage") == {"blocks": []}

    def test_missing_blocks_key_repairs_to_empty(self):
        assert validate_event_gate_state({"foo": "bar"}) == {"blocks": []}

    def test_non_list_blocks_repairs_to_empty(self):
        assert validate_event_gate_state({"blocks": "not-a-list"}) == {"blocks": []}

    def test_malformed_block_entry_dropped(self):
        result = validate_event_gate_state({"blocks": [{"unexpected": "shape"}]})
        assert result == {"blocks": []}

    def test_malformed_timestamp_dropped(self):
        block = {
            "tickers": ["NVDA"], "scope": "ticker", "trigger_match": "fraud",
            "event_timestamp_utc": "not-a-timestamp", "expired": False,
        }
        result = validate_event_gate_state({"blocks": [block]})
        assert result == {"blocks": []}

    def test_valid_recent_block_survives(self):
        block = {
            "tickers": ["NVDA"], "scope": "ticker", "trigger_match": "fraud",
            "event_timestamp_utc": datetime.now(timezone.utc).isoformat(), "expired": False,
        }
        result = validate_event_gate_state({"blocks": [block]})
        assert len(result["blocks"]) == 1
        assert result["blocks"][0]["expired"] is False

    def test_stale_block_auto_expired(self):
        old_ts = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        block = {
            "tickers": ["NVDA"], "scope": "ticker", "trigger_match": "fraud",
            "event_timestamp_utc": old_ts, "expired": False,
        }
        result = validate_event_gate_state({"blocks": [block]})
        assert len(result["blocks"]) == 1
        assert result["blocks"][0]["expired"] is True

    def test_load_gate_state_never_crashes_on_bad_json(self, tmp_path, monkeypatch):
        bad_file = tmp_path / "event_gate_state.json"
        bad_file.write_text("{not valid json,,,")
        monkeypatch.setattr(event_gate, "_STATE_FILE", bad_file)
        state = load_gate_state()
        assert state == {"blocks": []}

    def test_load_gate_state_missing_file_returns_empty(self, tmp_path, monkeypatch):
        monkeypatch.setattr(event_gate, "_STATE_FILE", tmp_path / "does_not_exist.json")
        assert load_gate_state() == {"blocks": []}


# ---------------------------------------------------------------------------
# news_layer.classify_severity + compute_news_score critical_events
# ---------------------------------------------------------------------------

class TestNewsLayerIntegration:
    def test_classify_severity_attaches_severity_and_scope(self):
        item = {"title": "Tariff fears grip semiconductor sector", "source_domain": "Reuters"}
        result = news_classify_severity(item, _gate_cfg())
        assert result["severity"] == SEVERITY_CRITICAL
        assert result["scope"] == SCOPE_SECTOR
        assert result["trigger_match"] == "tariff"
        assert result["title"] == item["title"]  # original fields preserved

    def test_sector_wide_event_detected_without_ticker_mention(self):
        cfg = _gate_cfg()
        now = datetime.now(timezone.utc)
        articles = [{
            "title": "White House announces new chip export restriction targeting China",
            "source_domain": "White House",
            "timestamp_utc": now.isoformat(),
        }]
        result = compute_news_score(articles, [], "NVDA", cfg, reference_date=now)
        critical = result["critical_events"]
        assert len(critical) == 1
        assert critical[0]["scope"] == SCOPE_SECTOR
        assert critical[0]["trigger_match"] == "export restriction"

    def test_stale_sector_wide_article_does_not_retrigger(self):
        """
        A news API can keep resurfacing the same old article indefinitely.
        Once a sector-wide article is beyond the same 5-day recency bar used
        for ticker-relevant news, it must stop producing new critical_events —
        otherwise one stale headline re-triggers a fresh block every day,
        forever, after the prior block's cooling-off expires.
        """
        cfg = _gate_cfg()
        now = datetime.now(timezone.utc)
        stale_ts = now - timedelta(days=6)
        articles = [{
            "title": "White House announces new chip export restriction targeting China",
            "source_domain": "White House",
            "timestamp_utc": stale_ts.isoformat(),
        }]
        result = compute_news_score(articles, [], "NVDA", cfg, reference_date=now)
        assert result["critical_events"] == []

    def test_recent_sector_wide_article_within_bar_still_triggers(self):
        cfg = _gate_cfg()
        now = datetime.now(timezone.utc)
        recent_ts = now - timedelta(days=2)
        articles = [{
            "title": "White House announces new chip export restriction targeting China",
            "source_domain": "White House",
            "timestamp_utc": recent_ts.isoformat(),
        }]
        result = compute_news_score(articles, [], "NVDA", cfg, reference_date=now)
        assert len(result["critical_events"]) == 1

    def test_ticker_specific_event_ner_attributed(self):
        cfg = _gate_cfg()
        now = datetime.now(timezone.utc)
        articles = [{
            "title": "AMD CEO resigns amid controversy",
            "source_domain": "Reuters",
            "timestamp_utc": now.isoformat(),
        }]
        result = compute_news_score(articles, [], "AMD", cfg, reference_date=now)
        critical = result["critical_events"]
        assert len(critical) == 1
        assert critical[0]["scope"] == SCOPE_TICKER
        assert critical[0]["trigger_match"] == "CEO resigns"

    def test_normal_news_produces_no_critical_events(self):
        cfg = _gate_cfg()
        now = datetime.now(timezone.utc)
        articles = [{
            "title": "NVDA gains market share amid strong AI demand",
            "source_domain": "Reuters",
            "timestamp_utc": now.isoformat(),
        }]
        result = compute_news_score(articles, [], "NVDA", cfg, reference_date=now)
        assert result["critical_events"] == []

    def test_disabled_gate_produces_no_critical_events(self):
        cfg = _gate_cfg(enabled=False)
        now = datetime.now(timezone.utc)
        articles = [{
            "title": "White House announces new chip export restriction",
            "source_domain": "White House",
            "timestamp_utc": now.isoformat(),
        }]
        result = compute_news_score(articles, [], "NVDA", cfg, reference_date=now)
        assert result["critical_events"] == []
        # Normal 15-point scoring is completely unaffected by the gate being disabled
        assert "news_score_total" in result


# ---------------------------------------------------------------------------
# scoring.compute_confidence_score — advisory flag, not a score input
# ---------------------------------------------------------------------------

def _max_technical():
    return {
        "breakout_volume_zscore": 3.0, "rs_zscore": 3.0, "rsi_14": 60.0,
        "breakout_confirmed": True, "trend_intact": True,
        "sma_20_above_sma_50": True, "price_above_sma_50": True, "macd_bullish": True,
    }


def _max_positioning():
    return {"positioning_score_total": 20.0, "options_score": 6, "institutional_score": 5,
            "short_interest_score": 4, "insider_score": 3, "analyst_score": 2}


def _max_sent():
    return {"sentiment_score_total": 15.0, "dominant_sentiment": "bullish",
            "ratio_score": 7, "velocity_score": 5, "engagement_score": 3}


def _max_news():
    return {"news_score_total": 15.0,
            "credibility_weighted_score": 6, "theme_alignment_score": 4,
            "clustering_score": 3, "decay_score": 2}


class TestScoringEventGateAdvisory:
    def test_high_confidence_candidate_still_surfaces_when_flagged(self):
        result = compute_confidence_score(
            technical=_max_technical(), positioning=_max_positioning(),
            sentiment=_max_sent(), news=_max_news(),
            regime_modifier=5, sector_rotation_modifier=0, earnings_modifier=0,
            cross_ticker_modifier=5, seasonality_modifier=0, macro_modifier=0,
            volume_profile_score=8.0,
            event_gate_blocked=True, event_gate_trigger="export restriction",
        )
        assert result["final_score"] >= 90
        assert result["meets_threshold"] is True  # advisory only — still surfaces
        assert result["event_gate_blocked"] is True  # caller uses this to flag, not suppress
        assert result["event_gate_trigger"] == "export restriction"

    def test_not_flagged_by_default(self):
        result = compute_confidence_score(
            technical=_max_technical(), positioning=_max_positioning(),
            sentiment=_max_sent(), news=_max_news(),
            regime_modifier=5, sector_rotation_modifier=0, earnings_modifier=0,
            cross_ticker_modifier=5, seasonality_modifier=0, macro_modifier=0,
            volume_profile_score=8.0,
        )
        assert result["event_gate_blocked"] is False
        assert result["event_gate_trigger"] is None
        assert result["meets_threshold"] is True

    def test_flagged_score_is_identical_to_unflagged_score(self):
        """The gate never changes the score itself — advisory flag only, never a boost or penalty."""
        kwargs = dict(
            technical=_max_technical(), positioning=_max_positioning(),
            sentiment=_max_sent(), news=_max_news(),
            regime_modifier=5, sector_rotation_modifier=0, earnings_modifier=0,
            cross_ticker_modifier=5, seasonality_modifier=0, macro_modifier=0,
            volume_profile_score=8.0,
        )
        unflagged = compute_confidence_score(**kwargs)
        flagged = compute_confidence_score(**kwargs, event_gate_blocked=True, event_gate_trigger="fraud")
        assert unflagged["final_score"] == flagged["final_score"]
        assert unflagged["base_score"] == flagged["base_score"]
        assert unflagged["meets_threshold"] == flagged["meets_threshold"]


# ---------------------------------------------------------------------------
# Open-position critical alert — immediate, critical-priority routing
# ---------------------------------------------------------------------------

class TestOpenPositionCriticalAlert:
    def test_routes_critical_priority_and_does_not_wait_for_rescore(self, monkeypatch):
        calls = {}

        def fake_route_alert(message, alert_type, priority, discord_webhook_url=None):
            calls["message"] = message
            calls["alert_type"] = alert_type
            calls["priority"] = priority
            return {"discord_sent": True, "email_sent": True, "sms_sent": False, "errors": []}

        monkeypatch.setattr("shared.utils.notification_router.route_alert", fake_route_alert)
        monkeypatch.setattr("swing_model.run_swing_model.write_audit_entry", lambda entry: None)

        position = {"ticker": "AMD", "direction": "bullish", "entry_price": 150.0}
        event = {"trigger_match": "CEO resigns", "headline": "AMD CEO resigns amid controversy"}
        result = _handle_open_position_critical_event(position, event, "v2.1.0")

        assert calls["alert_type"] == "event_gate_critical"
        assert calls["priority"] == PRIORITY_CRITICAL
        assert "AMD" in calls["message"]
        assert "CEO resigns" in calls["message"]
        assert result["discord_sent"] is True
        assert result["email_sent"] is True  # critical priority escalates to email
