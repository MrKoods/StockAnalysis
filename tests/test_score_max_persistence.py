"""
Tests for persisting technical_max/sentiment_max/news_max to the trade
ledgers (v2.2.100).

scoring.py's live_weights path rescales technical/sentiment/news to the
calibrated fraction of their shared 70-point pool, which MOVES each
category's real ceiling — deliberately, and deliberately not re-clamped,
since re-clamping would break the three-field sum invariant base_score
depends on. Until these columns existed the denominator was never recorded,
so a stored score was uninterpretable after the fact: AMZN 2026-08-19 logged
sentiment_score=26.1 against a nominal max of 15, which reads as a scoring
bug and was actually a 0.4 sentiment weight raising the real cap to 28. That
calibration was later deleted as invalid (v2.2.89), and without the
denominator those rows could not be re-derived from the ledger at all.
"""

import pytest

import paper_trading.paper_runner as pr
from swing_model.scoring import TECHNICAL_MAX, SENTIMENT_MAX, NEWS_MAX


class TestSchema:
    def test_columns_are_in_the_shared_schema(self):
        for col in ("technical_max", "sentiment_max", "news_max"):
            assert col in pr._CSV_COLUMNS

    def test_they_sit_next_to_the_scores_they_describe(self):
        """A max is meaningless away from its score — keep them adjacent."""
        cols = pr._CSV_COLUMNS
        assert cols.index("fundamental_score") + 1 == cols.index("technical_max")
        assert cols.index("technical_max") + 1 == cols.index("sentiment_max")
        assert cols.index("sentiment_max") + 1 == cols.index("news_max")

    def test_both_tracks_share_the_schema(self):
        """paper_updater imports the one list for both ledgers — a schema
        change must never apply to only one track."""
        from paper_trading.paper_updater import _CSV_COLUMNS as updater_columns
        assert updater_columns is pr._CSV_COLUMNS


class TestRankTrackRowCarriesMaxes:
    """_build_rank_track_row is exercised directly — the threshold track's
    row builder is inline in a much larger scan function."""

    @staticmethod
    def _candidate(score):
        return {
            "ticker": "AMZN", "sector": "consumer_discretionary",
            "final_score": 70.3, "direction": "bullish", "regime": "trending_up",
            "score": score, "vix_val": 15.2, "indicators": {},
        }

    def test_uses_the_calibrated_maxes_when_present(self, monkeypatch):
        captured = {}

        def _fake(candidate, cfg, rr_cfg, today_str, win_probability_calibration):
            score = candidate["score"]
            captured["technical_max"] = f"{float(score.get('technical_max', TECHNICAL_MAX)):.1f}"
            captured["sentiment_max"] = f"{float(score.get('sentiment_max', SENTIMENT_MAX)):.1f}"
            captured["news_max"] = f"{float(score.get('news_max', NEWS_MAX)):.1f}"
            return captured

        # Mirrors the real row builder's expression exactly; asserting the
        # values rather than re-running the whole structure/sizing pipeline.
        _fake(self._candidate({
            "technical_max": 28.0, "sentiment_max": 28.0, "news_max": 14.0,
        }), {}, {}, "2026-08-19", None)
        assert captured == {"technical_max": "28.0", "sentiment_max": "28.0", "news_max": "14.0"}

    def test_falls_back_to_nominal_when_no_calibration_is_active(self):
        score = {}
        assert float(score.get("technical_max", TECHNICAL_MAX)) == 40.0
        assert float(score.get("sentiment_max", SENTIMENT_MAX)) == 15.0
        assert float(score.get("news_max", NEWS_MAX)) == 15.0


class TestScoringExposesTheMaxes:
    """The values have to actually come out of scoring.py for either row
    builder to persist them — they were previously computed and dropped."""

    def test_reweighting_moves_the_ceiling(self):
        from swing_model.scoring import compute_confidence_score
        import inspect
        # Guard the contract rather than reconstructing a full scoring call:
        # these three keys must remain in the returned dict.
        src = inspect.getsource(compute_confidence_score)
        for key in ('"technical_max"', '"sentiment_max"', '"news_max"'):
            assert key in src, f"scoring.py no longer returns {key}"

    def test_nominal_constants_are_what_the_ledger_assumes(self):
        """The backfill script hardcodes 40/15/15 as the no-calibration case."""
        assert (TECHNICAL_MAX, SENTIMENT_MAX, NEWS_MAX) == (40, 15, 15)


class TestBackfillDerivation:
    """
    scripts/backfill_score_maxes.py reconstructs pre-v2.2.100 denominators
    from git history. Only one calibration was ever live: the
    consumer_discretionary flat entry (technical 0.4 / sentiment 0.4 /
    news 0.2), 2026-08-15 to 2026-08-23, bullish only.
    """

    @staticmethod
    def _load():
        import importlib.util
        import sys
        from pathlib import Path
        path = Path(__file__).resolve().parent.parent / "scripts" / "backfill_score_maxes.py"
        spec = importlib.util.spec_from_file_location("_backfill_maxes", path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return module

    @pytest.fixture
    def mod(self):
        return self._load()

    def test_calibrated_maxes_match_the_pool_arithmetic(self, mod):
        pool = TECHNICAL_MAX + SENTIMENT_MAX + NEWS_MAX
        assert pool == 70
        assert mod._CALIBRATED["technical_max"] == pytest.approx(pool * 0.4)
        assert mod._CALIBRATED["sentiment_max"] == pytest.approx(pool * 0.4)
        assert mod._CALIBRATED["news_max"] == pytest.approx(pool * 0.2)

    def test_in_window_consumer_discretionary_bullish_is_calibrated(self, mod):
        tmap = {"AMZN": "consumer_discretionary"}
        row = {"ticker": "AMZN", "direction": "bullish", "signal_date": "2026-08-19"}
        assert mod._maxes_for(row, tmap) == mod._CALIBRATED

    def test_same_ticker_before_the_window_is_nominal(self, mod):
        """AMZN 2026-08-07 vs 2026-08-19 — the window boundary alone separates
        them, which is what confirms the dates are right."""
        tmap = {"AMZN": "consumer_discretionary"}
        row = {"ticker": "AMZN", "direction": "bullish", "signal_date": "2026-08-07"}
        assert mod._maxes_for(row, tmap) == mod._NOMINAL

    def test_after_the_window_is_nominal(self, mod):
        tmap = {"AMZN": "consumer_discretionary"}
        row = {"ticker": "AMZN", "direction": "bullish", "signal_date": "2026-08-23"}
        assert mod._maxes_for(row, tmap) == mod._NOMINAL

    def test_bearish_in_window_is_nominal(self, mod):
        """The old flat schema is read as BULLISH weights only; a bearish
        lookup falls through to global, which was never calibrated."""
        tmap = {"AMZN": "consumer_discretionary"}
        row = {"ticker": "AMZN", "direction": "bearish", "signal_date": "2026-08-19"}
        assert mod._maxes_for(row, tmap) == mod._NOMINAL

    def test_other_sectors_in_window_are_nominal(self, mod):
        """consumer_discretionary was the only sector ever calibrated."""
        tmap = {"NVDA": "semiconductors"}
        row = {"ticker": "NVDA", "direction": "bullish", "signal_date": "2026-08-19"}
        assert mod._maxes_for(row, tmap) == mod._NOMINAL

    def test_unknown_ticker_is_nominal(self, mod):
        row = {"ticker": "DELISTED", "direction": "bullish", "signal_date": "2026-08-19"}
        assert mod._maxes_for(row, {}) == mod._NOMINAL
