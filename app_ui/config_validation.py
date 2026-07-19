"""
Validation for swing_config.yaml edits made in the app UI's Config tab
(App_UI_Scope.md §3.3) — catches a bad edit before it's written back to the
file the pipeline actually reads, since config remains the single source of
truth (the DB never stores config, only results/notifications).

Kept to what the scope doc named explicitly: weights sum correctly, and
thresholds fall in a valid range. Not a full schema validator — the pipeline's
own code is the source of truth for what a field means; this only catches the
mistakes that would silently corrupt scoring (weights that no longer sum
right) or are obviously out of range (a threshold outside 0-100).
"""

import yaml

_WEIGHT_GROUPS = [
    ("scoring_weights", ["technical_max", "positioning_max", "sentiment_max", "news_max", "fundamental_max"], 100),
]

_SUB_SIGNAL_GROUPS = [
    # (sub-signal section, parent section.key holding the target sum)
    ("technical_sub_signals", "scoring_weights", "technical_max"),
    ("positioning_sub_signals", "scoring_weights", "positioning_max"),
    ("sentiment_sub_signals", "scoring_weights", "sentiment_max"),
    ("news_sub_signals", "scoring_weights", "news_max"),
]


def validate_config_text(raw_yaml: str) -> tuple[bool, list[str]]:
    """
    Returns (is_valid, errors). errors is empty when is_valid is True.
    Never raises — a YAML parse failure is itself reported as an error.
    """
    errors: list[str] = []

    try:
        cfg = yaml.safe_load(raw_yaml)
    except yaml.YAMLError as exc:
        return False, [f"Invalid YAML: {exc}"]

    if not isinstance(cfg, dict):
        return False, ["Config must be a YAML mapping at the top level."]

    for section_name, keys, expected_sum in _WEIGHT_GROUPS:
        section = cfg.get(section_name)
        if not isinstance(section, dict):
            errors.append(f"Missing or invalid section: {section_name}")
            continue
        total = 0.0
        missing = []
        for key in keys:
            value = section.get(key)
            if not isinstance(value, (int, float)):
                missing.append(key)
                continue
            total += value
        if missing:
            errors.append(f"{section_name}: missing/non-numeric key(s): {', '.join(missing)}")
        elif abs(total - expected_sum) > 1e-9:
            errors.append(f"{section_name}: {'+'.join(keys)} sum to {total}, must sum to {expected_sum}")

    for sub_section_name, parent_section, parent_key in _SUB_SIGNAL_GROUPS:
        sub_section = cfg.get(sub_section_name)
        parent = cfg.get(parent_section, {})
        expected = parent.get(parent_key) if isinstance(parent, dict) else None
        if not isinstance(sub_section, dict):
            errors.append(f"Missing or invalid section: {sub_section_name}")
            continue
        if not isinstance(expected, (int, float)):
            # Already reported above as part of the parent weight-group check.
            continue
        values = list(sub_section.values())
        if not all(isinstance(v, (int, float)) for v in values):
            errors.append(f"{sub_section_name}: all values must be numeric")
            continue
        total = sum(values)
        if abs(total - expected) > 1e-9:
            errors.append(
                f"{sub_section_name}: sums to {total}, must match {parent_section}.{parent_key} ({expected})"
            )

    threshold = cfg.get("confidence", {}).get("min_threshold") if isinstance(cfg.get("confidence"), dict) else None
    if threshold is not None:
        if not isinstance(threshold, (int, float)) or not (0 <= threshold <= 100):
            errors.append(f"confidence.min_threshold must be a number in [0, 100], got {threshold!r}")

    return (len(errors) == 0), errors
