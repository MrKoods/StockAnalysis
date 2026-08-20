"""Tests for app_ui/config_validation.py — the Config tab's pre-save checks."""

from pathlib import Path

from app_ui.config_validation import validate_config_text

_VALID_YAML = """
scoring_weights:
  technical_max: 40
  positioning_max: 20
  sentiment_max: 15
  news_max: 15
  fundamental_max: 10

confidence:
  min_threshold: 90
"""


class TestValidConfig:
    def test_valid_yaml_passes(self):
        is_valid, errors = validate_config_text(_VALID_YAML)
        assert is_valid is True
        assert errors == []

    def test_real_config_file_passes(self):
        """The actual swing_config.yaml shipped in the repo must always validate clean."""
        real_path = Path("config/swing_config.yaml")
        is_valid, errors = validate_config_text(real_path.read_text(encoding="utf-8"))
        assert is_valid is True, errors


class TestInvalidYaml:
    def test_malformed_yaml_reported(self):
        is_valid, errors = validate_config_text("scoring_weights: [1, 2\n  bad indent: x")
        assert is_valid is False
        assert any("Invalid YAML" in e for e in errors)

    def test_non_mapping_top_level(self):
        is_valid, errors = validate_config_text("- just\n- a\n- list\n")
        assert is_valid is False
        assert "mapping" in errors[0]


class TestWeightSums:
    def test_scoring_weights_not_summing_to_100(self):
        bad = _VALID_YAML.replace("technical_max: 40", "technical_max: 41")
        is_valid, errors = validate_config_text(bad)
        assert is_valid is False
        assert any("scoring_weights" in e and "must sum to 100" in e for e in errors)

    def test_missing_weight_key(self):
        bad = _VALID_YAML.replace("  fundamental_max: 10\n", "")
        is_valid, errors = validate_config_text(bad)
        assert is_valid is False
        assert any("missing/non-numeric" in e for e in errors)


class TestThresholdRange:
    def test_threshold_out_of_range(self):
        bad = _VALID_YAML.replace("min_threshold: 90", "min_threshold: 150")
        is_valid, errors = validate_config_text(bad)
        assert is_valid is False
        assert any("min_threshold" in e for e in errors)

    def test_threshold_in_range_ok(self):
        ok = _VALID_YAML.replace("min_threshold: 90", "min_threshold: 85")
        is_valid, errors = validate_config_text(ok)
        assert is_valid is True
