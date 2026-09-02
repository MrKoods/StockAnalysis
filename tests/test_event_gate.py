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
    was_critical_alert_sent,
    record_critical_alert,
    SEVERITY_NORMAL,
    SEVERITY_CRITICAL,
    SCOPE_TICKER,
    SCOPE_SECTOR,
)
from shared.utils.data_validator import validate_event_gate_state
from swing_model.news_layer import (
    compute_news_score,
    classify_severity as news_classify_severity,
    free_sources_flag_critical_event,
)
from swing_model.scoring import compute_confidence_score
from swing_model.run_swing_model import _handle_open_position_critical_event

WATCHLIST = ["NVDA", "AMD", "AVGO", "TSM", "MU", "ASML"]


def _gate_cfg(enabled: bool = True, min_cred: float = 0.5) -> dict:
    return {
        "event_severity_gate": {
            "enabled": enabled,
            "cooling_off": "next_post_close_scan",
            "sector_triggers": {
                "semiconductors": [
                    "export restriction", "export ban", "chip ban", "tariff",
                    "trade war", "Taiwan Strait", "semiconductor embargo",
                    "entity list", "national security review",
                ],
            },
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

    def test_add_block_stores_ner_sentiment(self):
        state = add_block(
            {"blocks": []}, tickers=["NVDA"], scope=SCOPE_TICKER,
            trigger_headline="x", trigger_match="fraud", source="Reuters",
            event_timestamp_utc=datetime.now(timezone.utc).isoformat(),
            ner_sentiment="bearish",
        )
        assert state["blocks"][0]["ner_sentiment"] == "bearish"

    def test_sector_block_with_direction_only_flags_opposed_tickers(self):
        """
        2026-09 fix: a sector-wide block used to cover every ticker regardless
        of that ticker's own direction. A bearish-flavored headline should
        flag a bullish-thesis ticker (opposed) but NOT a bearish-thesis one
        (the news confirms it, not opposes it).
        """
        state = {"blocks": []}
        state = add_block(
            state, tickers=list(WATCHLIST), scope=SCOPE_SECTOR,
            trigger_headline="Sector-wide bad news", trigger_match="bad news",
            source="Reuters", event_timestamp_utc=datetime.now(timezone.utc).isoformat(),
            ner_sentiment="bearish",
        )
        assert is_ticker_blocked("NVDA", state, direction="bullish") is not None
        assert is_ticker_blocked("NVDA", state, direction="bearish") is None

    def test_sector_block_without_direction_arg_blocks_everyone(self):
        """Backward compatible: omitting direction preserves the old unconditional check."""
        state = {"blocks": []}
        state = add_block(
            state, tickers=list(WATCHLIST), scope=SCOPE_SECTOR,
            trigger_headline="Sector-wide bad news", trigger_match="bad news",
            source="Reuters", event_timestamp_utc=datetime.now(timezone.utc).isoformat(),
            ner_sentiment="bearish",
        )
        assert is_ticker_blocked("NVDA", state) is not None

    def test_sector_block_without_stored_ner_sentiment_blocks_everyone(self):
        """A block with no ner_sentiment (older state, or never supplied) can't be
        direction-checked — fails safe to the old unconditional-membership behavior."""
        state = {"blocks": []}
        state = add_block(
            state, tickers=list(WATCHLIST), scope=SCOPE_SECTOR,
            trigger_headline="Sector-wide bad news", trigger_match="bad news",
            source="Reuters", event_timestamp_utc=datetime.now(timezone.utc).isoformat(),
        )
        assert is_ticker_blocked("NVDA", state, direction="bullish") is not None
        assert is_ticker_blocked("NVDA", state, direction="bearish") is not None


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
        # Asserts on ["blocks"], not whole-dict equality: the subject here is
        # which BLOCKS survive, and the state dict also carries the
        # critical_alerts_sent dedup ledger (see TestCriticalAlertDedup).
        result = validate_event_gate_state({"blocks": [{"unexpected": "shape"}]})
        assert result["blocks"] == []

    def test_malformed_timestamp_dropped(self):
        block = {
            "tickers": ["NVDA"], "scope": "ticker", "trigger_match": "fraud",
            "event_timestamp_utc": "not-a-timestamp", "expired": False,
        }
        result = validate_event_gate_state({"blocks": [block]})
        assert result["blocks"] == []

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

    def test_seeking_alpha_only_sector_event_still_detected(self):
        """
        AV news (alpha_vantage_articles) is post-close-only; pre-market/mid-session
        pass an empty list there. Seeking Alpha runs every scan, so a sector-wide
        critical event present ONLY in seeking_alpha_articles must still surface —
        this is what closes the detection-lag gap for non-post-close scans.
        """
        cfg = _gate_cfg()
        now = datetime.now(timezone.utc)
        sa_articles = [{
            "title": "White House announces new chip export restriction targeting China",
            "source": "seekingalpha.com",
            "timestamp_utc": now.isoformat(),
        }]
        result = compute_news_score(
            [], [], "NVDA", cfg, reference_date=now, seeking_alpha_articles=sa_articles
        )
        critical = result["critical_events"]
        assert len(critical) == 1
        assert critical[0]["scope"] == SCOPE_SECTOR

    def test_seeking_alpha_only_ticker_event_still_detected(self):
        cfg = _gate_cfg()
        now = datetime.now(timezone.utc)
        sa_articles = [{
            "title": "AMD CEO resigns amid controversy",
            "source": "seekingalpha.com",
            "timestamp_utc": now.isoformat(),
        }]
        result = compute_news_score(
            [], [], "AMD", cfg, reference_date=now, seeking_alpha_articles=sa_articles
        )
        critical = result["critical_events"]
        assert len(critical) == 1
        assert critical[0]["scope"] == SCOPE_TICKER

    def test_seeking_alpha_articles_feed_the_scored_news_total(self):
        """
        seeking_alpha_articles are folded into the scored 0-15 News total
        (credibility/theme/clustering/decay), not just severity detection —
        a ticker-relevant Seeking Alpha item should grow total_article_count
        and contribute to news_score_total exactly like an AV/Yahoo/Finnhub
        article would. (Reversed from the original behavior, where Seeking
        Alpha fed severity detection only, as part of the AV-budget-relief
        change — see news_layer.py's compute_news_score docstring.)
        """
        cfg = _gate_cfg()
        now = datetime.now(timezone.utc)
        av_articles = [{
            "title": "NVDA gains market share amid strong AI demand",
            "source_domain": "Reuters",
            "timestamp_utc": now.isoformat(),
        }]
        sa_articles = [{
            "title": "NVDA earnings beat expectations on strong data center demand",
            "source": "seekingalpha.com",
            "timestamp_utc": now.isoformat(),
        }]
        without_sa = compute_news_score(av_articles, [], "NVDA", cfg, reference_date=now)
        with_sa = compute_news_score(
            av_articles, [], "NVDA", cfg, reference_date=now, seeking_alpha_articles=sa_articles
        )
        assert with_sa["total_article_count"] == without_sa["total_article_count"] + 1
        assert with_sa["relevant_article_count"] == without_sa["relevant_article_count"] + 1
        assert with_sa["news_score_total"] >= without_sa["news_score_total"]

    def test_seeking_alpha_sector_event_does_not_inflate_score_when_not_ticker_relevant(self):
        """
        A sector-wide (not ticker-named) Seeking Alpha headline still counts
        toward total_article_count (it's now in all_articles) but shouldn't
        pass the NER ticker-relevance filter into `relevant` — so it can still
        trigger Event Severity Gate detection without silently inflating the
        ticker's own News sub-scores.
        """
        cfg = _gate_cfg()
        now = datetime.now(timezone.utc)
        sa_articles = [{
            "title": "White House announces new chip export restriction targeting China",
            "source": "seekingalpha.com",
            "timestamp_utc": now.isoformat(),
        }]
        result = compute_news_score(
            [], [], "NVDA", cfg, reference_date=now, seeking_alpha_articles=sa_articles
        )
        assert result["total_article_count"] == 1
        assert result["relevant_article_count"] == 0
        assert len(result["critical_events"]) == 1


class TestFreeSourcesFlagCriticalEvent:
    """
    free_sources_flag_critical_event() — the cheap, local, no-API-cost check
    run_swing_model.py/paper_runner.py use to decide whether a scan should
    spend one Alpha Vantage call to cross-reference an event already surfaced
    by Yahoo, Finnhub, or Seeking Alpha (AV is a confirmation tool, called on
    every scan type when triggered — not a routine per-ticker post-close fetch).
    """

    def test_ticker_scope_critical_event_triggers(self):
        cfg = _gate_cfg()
        sa_articles = [{
            "title": "AMD CEO resigns amid controversy",
            "source": "seekingalpha.com",
        }]
        assert free_sources_flag_critical_event(sa_articles, "AMD", cfg) is True

    def test_sector_scope_critical_event_triggers(self):
        cfg = _gate_cfg()
        sa_articles = [{
            "title": "White House announces new chip export restriction targeting China",
            "source": "seekingalpha.com",
        }]
        assert free_sources_flag_critical_event(sa_articles, "NVDA", cfg, sector="semiconductors") is True

    def test_yahoo_or_finnhub_sourced_critical_event_triggers(self):
        cfg = _gate_cfg()
        # Yahoo/Finnhub articles use "source_domain" rather than SA's "source" key.
        free_articles = [{
            "title": "AMD CEO resigns amid controversy",
            "source_domain": "finance.yahoo.com",
        }]
        assert free_sources_flag_critical_event(free_articles, "AMD", cfg) is True

    def test_ticker_scope_event_for_a_different_ticker_does_not_trigger(self):
        cfg = _gate_cfg()
        sa_articles = [{
            "title": "AMD CEO resigns amid controversy",
            "source": "seekingalpha.com",
        }]
        assert free_sources_flag_critical_event(sa_articles, "NVDA", cfg) is False

    def test_normal_headline_does_not_trigger(self):
        cfg = _gate_cfg()
        sa_articles = [{
            "title": "NVDA gains market share amid strong AI demand",
            "source": "seekingalpha.com",
        }]
        assert free_sources_flag_critical_event(sa_articles, "NVDA", cfg) is False

    def test_empty_articles_does_not_trigger(self):
        cfg = _gate_cfg()
        assert free_sources_flag_critical_event([], "NVDA", cfg) is False
        assert free_sources_flag_critical_event(None, "NVDA", cfg) is False

    def test_gate_disabled_does_not_trigger(self):
        cfg = _gate_cfg(enabled=False)
        sa_articles = [{
            "title": "AMD CEO resigns amid controversy",
            "source": "seekingalpha.com",
        }]
        assert free_sources_flag_critical_event(sa_articles, "AMD", cfg) is False


class TestClassifyFreeSourceCritical:
    """classify_free_source_critical() returns (scope, trigger) so the caller
    can de-dupe a SECTOR-scope critical to one AV cross-reference per scan."""

    def test_returns_sector_scope_and_trigger(self):
        from swing_model.news_layer import classify_free_source_critical
        arts = [{"title": "White House imposes new tariff on chip imports", "source": "seekingalpha.com"}]
        assert classify_free_source_critical(arts, "NVDA", _gate_cfg(), sector="semiconductors") == (
            SCOPE_SECTOR, "tariff",
        )

    def test_returns_ticker_scope_and_trigger(self):
        from swing_model.news_layer import classify_free_source_critical
        arts = [{"title": "AMD CEO resigns amid controversy", "source": "seekingalpha.com"}]
        assert classify_free_source_critical(arts, "AMD", _gate_cfg()) == (SCOPE_TICKER, "CEO resigns")

    def test_returns_none_on_normal_headline(self):
        from swing_model.news_layer import classify_free_source_critical
        arts = [{"title": "NVDA gains share on AI demand", "source": "seekingalpha.com"}]
        assert classify_free_source_critical(arts, "NVDA", _gate_cfg()) is None


class TestShouldFetchAvConfirmation:
    """_should_fetch_av_confirmation() — a market-wide tariff/boycott headline
    lands in every sector member's free-source feed on every scan, so the AV
    cross-reference must fire once per (sector, trigger) per scan, not once per
    ticker (which exhausted the 24/day AV budget — v2.2.117)."""

    def _sector_tariff_article(self):
        return [{"title": "White House imposes sweeping new tariff on semiconductors", "source": "seekingalpha.com"}]

    def test_first_sector_ticker_fetches_rest_do_not(self):
        from swing_model.run_swing_model import _should_fetch_av_confirmation
        cfg, gate_state, seen = _gate_cfg(), {"blocks": []}, set()
        arts = self._sector_tariff_article()
        assert _should_fetch_av_confirmation(arts, "NVDA", cfg, "semiconductors", gate_state, seen) is True
        assert _should_fetch_av_confirmation(arts, "AMD", cfg, "semiconductors", gate_state, seen) is False
        assert _should_fetch_av_confirmation(arts, "AVGO", cfg, "semiconductors", gate_state, seen) is False
        assert seen == {("semiconductors", "tariff")}

    def test_skips_entirely_when_an_active_block_already_exists(self):
        from swing_model.run_swing_model import _should_fetch_av_confirmation
        gate_state = {"blocks": [{"trigger_match": "tariff", "scope": SCOPE_SECTOR, "expired": False}]}
        assert _should_fetch_av_confirmation(
            self._sector_tariff_article(), "NVDA", _gate_cfg(), "semiconductors", gate_state, set()
        ) is False

    def test_ticker_scope_critical_still_fetches_per_ticker(self):
        from swing_model.run_swing_model import _should_fetch_av_confirmation
        cfg, gate_state, seen = _gate_cfg(), {"blocks": []}, set()
        amd = [{"title": "AMD CEO resigns amid controversy", "source": "seekingalpha.com"}]
        nvda = [{"title": "NVDA CEO resigns amid controversy", "source": "seekingalpha.com"}]
        assert _should_fetch_av_confirmation(amd, "AMD", cfg, "semiconductors", gate_state, seen) is True
        assert _should_fetch_av_confirmation(nvda, "NVDA", cfg, "semiconductors", gate_state, seen) is True

    def test_no_critical_no_fetch(self):
        from swing_model.run_swing_model import _should_fetch_av_confirmation
        arts = [{"title": "NVDA gains share on AI demand", "source": "seekingalpha.com"}]
        assert _should_fetch_av_confirmation(arts, "NVDA", _gate_cfg(), "semiconductors", {"blocks": []}, set()) is False


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
# Open-position critical alert — fires immediately, does not wait for rescore
# ---------------------------------------------------------------------------

class TestOpenPositionCriticalAlert:
    def test_routes_immediately_and_does_not_wait_for_rescore(self, monkeypatch):
        calls = {}

        def fake_route_alert(message, alert_type, discord_webhook_url=None):
            calls["message"] = message
            calls["alert_type"] = alert_type
            return {"discord_sent": True, "errors": []}

        monkeypatch.setattr("shared.utils.notification_router.route_alert", fake_route_alert)
        monkeypatch.setattr("swing_model.run_swing_model.write_audit_entry", lambda entry: None)

        position = {"ticker": "AMD", "direction": "bullish", "entry_price": 150.0}
        event = {"trigger_match": "CEO resigns", "headline": "AMD CEO resigns amid controversy"}
        result = _handle_open_position_critical_event(position, event, "v2.1.0")

        assert calls["alert_type"] == "event_gate_critical"
        assert "AMD" in calls["message"]
        assert "CEO resigns" in calls["message"]
        assert result["discord_sent"] is True


class TestCriticalAlertDedup:
    """
    Open-position critical alerts fire once per (ticker, trigger, event
    timestamp), not once per matching event per scan.

    A critical news item stays in the feed for days and the alert used to be
    unguarded, so it re-fired on every one of the day's three scans — MU
    generated ~9 identical 'tariff' alerts a day across 2026-08-24/25, for a
    position that was sized to 0 units so there was nothing to act on
    either. Alert fatigue on a safety channel is a real failure mode.
    """

    @staticmethod
    def _event(trigger="tariff", ts="2026-08-24T07:17:51+00:00", headline="Tariffs incoming"):
        return {"trigger_match": trigger, "event_timestamp_utc": ts, "headline": headline}

    def test_first_alert_is_not_suppressed(self):
        state = {"blocks": []}
        assert was_critical_alert_sent(state, "MU", self._event()) is False

    def test_same_event_is_suppressed_after_recording(self):
        state = record_critical_alert({"blocks": []}, "MU", self._event())
        assert was_critical_alert_sent(state, "MU", self._event()) is True

    def test_different_headline_for_the_same_event_is_still_suppressed(self):
        """Same event via another vendor's phrasing must not re-alert."""
        state = record_critical_alert({"blocks": []}, "MU", self._event(headline="Trump tariff review"))
        assert was_critical_alert_sent(state, "MU", self._event(headline="Tariffs incoming")) is True

    def test_a_different_ticker_still_alerts(self):
        state = record_critical_alert({"blocks": []}, "MU", self._event())
        assert was_critical_alert_sent(state, "NVDA", self._event()) is False

    def test_a_different_trigger_still_alerts(self):
        state = record_critical_alert({"blocks": []}, "MU", self._event())
        assert was_critical_alert_sent(state, "MU", self._event(trigger="fraud")) is False

    def test_a_genuinely_new_event_for_the_same_trigger_still_alerts(self):
        """A fresh tariff story days later is news again, not a duplicate."""
        state = record_critical_alert({"blocks": []}, "MU", self._event())
        later = self._event(ts="2026-08-28T09:00:00+00:00")
        assert was_critical_alert_sent(state, "MU", later) is False

    def test_ledger_survives_a_validate_round_trip(self):
        """
        validate_event_gate_state() rebuilds the state dict from scratch, so a
        key it doesn't explicitly preserve is discarded on every load — which
        would reset this ledger each scan and restore the duplicate alerts.
        """
        state = record_critical_alert({"blocks": []}, "MU", self._event())
        reloaded = validate_event_gate_state(state)
        assert was_critical_alert_sent(reloaded, "MU", self._event()) is True

    def test_stale_ledger_entries_are_pruned_on_validate(self):
        from datetime import datetime, timezone, timedelta
        old = (datetime.now(timezone.utc) - timedelta(days=60)).isoformat()
        state = {"blocks": [], "critical_alerts_sent": {"MU|tariff|whenever": old}}
        assert validate_event_gate_state(state)["critical_alerts_sent"] == {}

    def test_malformed_ledger_does_not_crash_validate(self):
        for bad in ("not-a-dict", 42, None, {"key": "not-a-timestamp"}):
            result = validate_event_gate_state({"blocks": [], "critical_alerts_sent": bad})
            assert result["critical_alerts_sent"] == {}
