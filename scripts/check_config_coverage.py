"""
CI gate: fail if config/swing_config.yaml declares a leaf key that no real
(non-test) code reads.

Two full-model audits (2026-08-19) found the same recurring shape repeatedly:
a config key computed or documented but never wired to a real consumer — the
project's own `app_ui/config_validation.py` only sum-checks a handful of
sections, it doesn't verify any key is actually *read* by the scoring/trading
code. This script is the general enforcement that was missing: it fails CI
the moment a *new* decorative key is added, rather than waiting for the next
manual sweep to notice.

Method: flatten every leaf in the YAML tree (a "leaf" is a scalar, a list —
including a list of dicts, e.g. `position_sizing.tiers`, which is not
descended into — or a dict whose keys aren't all valid identifiers, e.g.
`modifiers.seasonality.monthly_modifiers` keyed 1-12). For each leaf's final
key name, search all non-test `*.py` files for that name appearing as a
quoted dict-key string literal (`"name"` / `'name'`) — this codebase reads
config exclusively via plain nested dicts (`cfg.get("section", {})...`), so a
quoted-literal match is a real reference; a bare identifier match (e.g. the
word "min" inside `series.min()`) is not, and quoted-literal matching avoids
that false-positive class deliberately.

`app_ui/config_validation.py` is excluded from the search — its sum-checks
(weights sum to 100, sub-signals sum to parent max, threshold in range) read
key names without the code ever *acting* on the values, which is exactly the
kind of non-real "consumer" the original audit flagged. Counting it would
silently hide the entire `scoring_weights` / `*_sub_signals` / stale
`confidence.min_threshold` cluster this check exists to catch.

Known-decorative keys (today's backlog, scoped separately — see CHANGELOG.md
and the "recurring pattern audit" — not fixed by this change) are allowlisted
in `_KNOWN_DECORATIVE` below, each with a one-line reason. A newly-added
decorative key is NOT allowlisted, so it fails the build until someone wires
it in for real or makes a deliberate, documented call to allowlist it.

Usage:
    python scripts/check_config_coverage.py
"""

import re
import sys
from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).resolve().parent.parent
_CONFIG_PATH = _REPO_ROOT / "config" / "swing_config.yaml"

_EXCLUDED_DIR_NAMES = {"tests", ".git", "__pycache__", ".venv", "venv", "node_modules"}
_EXCLUDED_FILES = {
    # Sum-checks key *names* without ever consuming the values — not a real
    # consumer, see module docstring above.
    _REPO_ROOT / "app_ui" / "config_validation.py",
    # This file's own docstring/allowlist mentions every decorative key name.
    Path(__file__).resolve(),
}

# Confirmed-decorative as of the 2026-08-19 recurring-pattern audit follow-up.
# Tier B/C/D backlog — intentionally not fixed here, see CHANGELOG.md and
# memory entry project_recurring_pattern_audit_2026-08-19. Each entry is a
# real leaf key with zero real code reference; remove an entry only once the
# key is actually wired in (and this script will then confirm it for free).
_KNOWN_DECORATIVE: dict[str, str] = {
    "scoring_weights.technical_max": "Tier B — scoring.py hardcodes TECHNICAL_MAX=40 etc. instead of reading this",
    "scoring_weights.positioning_max": "Tier B — see technical_max",
    "scoring_weights.sentiment_max": "Tier B — see technical_max",
    "scoring_weights.news_max": "Tier B — see technical_max",
    "scoring_weights.fundamental_max": "Tier B — see technical_max",
    "technical_sub_signals.breakout": "Tier B — scoring.py hardcodes 8pts/sub-signal instead of reading this block",
    "technical_sub_signals.trend": "Tier B — see breakout",
    "technical_sub_signals.relative_strength": "Tier B — see breakout",
    "technical_sub_signals.rsi": "Tier B — see breakout",
    "technical_sub_signals.volume_profile": "Tier B — see breakout",
    "positioning_sub_signals.options_positioning": "Tier B — positioning_layer.py's cfg param is unused for this",
    "positioning_sub_signals.institutional_ownership": "Tier B — see options_positioning",
    "positioning_sub_signals.short_interest": "Tier B — see options_positioning",
    "positioning_sub_signals.insider_transactions": "Tier B — see options_positioning",
    "positioning_sub_signals.analyst_rating_trend": "Tier B — see options_positioning",
    "sentiment_sub_signals.stocktwits_ratio": "Tier B — sentiment_layer.py's cfg param is unused for this",
    "sentiment_sub_signals.stocktwits_velocity": "Tier B — see stocktwits_ratio",
    "sentiment_sub_signals.seeking_alpha_engagement": "Tier B — see stocktwits_ratio",
    "news_sub_signals.credibility_weighted": "Tier B — news_layer.py hardcodes its sub-signal maximums",
    "news_sub_signals.theme_alignment": "Tier B — see credibility_weighted",
    "news_sub_signals.clustering": "Tier B — see credibility_weighted",
    "news_sub_signals.decay_factor": "Tier B — see credibility_weighted",
    "confidence.min_threshold": "Tier B — stale (=90); real gate is CONFIDENCE_THRESHOLD=70 hardcoded in scoring.py",
    "event_severity_gate.cooling_off": "Tier D — event_gate.py hardcodes 'next post_close scan' instead of reading this",
    "event_severity_gate.require_headline_match": "Tier D — event_gate.py always headline-matches unconditionally",
    "circuit_breakers.orange.no_new_positions": "Tier D — position_sizer.py hardcodes mult=0.0 for CB_ORANGE/CB_RED",
    "circuit_breakers.orange.pause_days": "Tier D — only consecutive_loss.at_3.pause_days is actually read",
    "circuit_breakers.red.full_stop": "Tier D — see orange.no_new_positions",
    "pdt.max_day_trades_per_5_days": "Tier D — no PDT-tracking code exists at all",
    "profit_targets.vertical_debit_spreads": "Tier C — no structure-specific profit-taking logic exists yet",
    "profit_targets.calendar_diagonal": "Tier C — see vertical_debit_spreads",
    "profit_targets.long_call_put_leaps": "Tier C — see vertical_debit_spreads",
    "profit_targets.vertical_credit_spreads": "Tier C — see vertical_debit_spreads",
    "profit_targets.cash_secured_put": "Tier C — see vertical_debit_spreads",
    "profit_targets.covered_call": "Tier C — see vertical_debit_spreads",
    "profit_targets.iron_condor_butterfly": "Tier C — see vertical_debit_spreads",
    "profit_targets.long_butterfly": "Tier C — see vertical_debit_spreads",
    "profit_targets.long_straddle_strangle_one_side": "Tier C — see vertical_debit_spreads",
    "profit_targets.structure_stop_debit_spread_pct": "Tier C — see vertical_debit_spreads",
    "modifier_bounds.regime.min": "Tier D — no code clamps any modifier to these documented bounds",
    "modifier_bounds.regime.max": "Tier D — see regime.min",
    "modifier_bounds.sector_rotation.min": "Tier D — see regime.min",
    "modifier_bounds.sector_rotation.max": "Tier D — see regime.min",
    "modifier_bounds.earnings_proximity.min": "Tier D — see regime.min",
    "modifier_bounds.earnings_proximity.max": "Tier D — see regime.min",
    "modifier_bounds.cross_ticker.min": "Tier D — see regime.min",
    "modifier_bounds.cross_ticker.max": "Tier D — see regime.min",
    "modifier_bounds.seasonality.min": "Tier D — see regime.min",
    "modifier_bounds.seasonality.max": "Tier D — see regime.min",
    "modifier_bounds.macro_overlay.min": "Tier D — see regime.min",
    "modifier_bounds.macro_overlay.max": "Tier D — see regime.min",
    "position_sizing.tiers": "Tier D — position_sizer.py hardcodes an equivalent SIZING_TIERS constant instead",
    # --- Discovered by this script's first run (2026-08-19), same shape as the
    # Tier B/C/D backlog above but never individually verified by either prior
    # manual audit (both explicitly sample-checked, not exhaustive, for the
    # fundamental/positioning/sentiment/news config sections). Confirmed real
    # gaps, not script false-negatives — spot-checked several: fundamental_layer.py
    # hardcodes its own module-level threshold constants (_PREMIUM_NEAR_PARITY_MAX
    # etc.) instead of reading cfg; positioning_layer.py hardcodes
    # OPTIONS_MAX/INSTITUTIONAL_MAX/etc.; backtesting call sites hardcode
    # train_split=0.70 as a Python default rather than reading config;
    # holding_period is hardcoded as a (1, 15) default tuple in simulation.py.
    # Deliberately not fixed here — out of scope for this CI-check batch (see
    # session decision 2026-08-19) — but should not be silently rediscovered by
    # a future audit as if new; scale noted in memory for a future session.
    "alpha_vantage_budget.daily_total": "estimate-only per the config's own comment; daily_limit is the real consumer",
    "alpha_vantage_budget.news_cadence": "documentary only — news_client.py's confirmation-only behavior is hardcoded",
    "backtesting.min_qualifying_trades": "backtest_engine.py hardcodes min_qualifying_trades=100 as a Python default",
    "backtesting.performance_review_rolling_window": "no real code reference found",
    "backtesting.slippage_options_bid_ask_pct": "no real code reference found",
    "backtesting.slippage_stock_per_share": "no real code reference found",
    "backtesting.test_split": "no real code reference found (train_split's complement is computed inline instead)",
    "backtesting.train_split": "backtest_engine.py/diagnostics hardcode train_split=0.70 as a Python default everywhere",
    "backtesting.walk_forward_windows.initial_train_months": "no real code reference found",
    "backtesting.walk_forward_windows.initial_validate_months": "no real code reference found",
    "confidence.sensitivity_thresholds": "only named in a diagnostic script's docstring prose, never read as cfg[...]",
    "data_validation.sentiment_ratio_max": "no real code reference found",
    "data_validation.sentiment_ratio_min": "no real code reference found",
    "fundamental.alpha_vantage_calls_per_week": "no real code reference found",
    "fundamental.analyst_consensus_max": "fundamental_layer.py hardcodes its own module-level threshold constants",
    "fundamental.cache_file": "no real code reference found",
    "fundamental.earnings_momentum_max": "fundamental_layer.py hardcodes its own module-level threshold constants",
    "fundamental.earnings_surprise_max": "fundamental_layer.py hardcodes its own module-level threshold constants",
    "fundamental.eps_accelerating_threshold": "fundamental_layer.py hardcodes its own module-level threshold constants",
    "fundamental.eps_flat_threshold": "fundamental_layer.py hardcodes its own module-level threshold constants",
    "fundamental.eps_growth_max": "fundamental_layer.py hardcodes its own module-level threshold constants",
    "fundamental.eps_negative_threshold": "fundamental_layer.py hardcodes its own module-level threshold constants",
    "fundamental.eps_positive_threshold": "fundamental_layer.py hardcodes its own module-level threshold constants",
    "fundamental.estimate_revisions_max": "fundamental_layer.py hardcodes its own module-level threshold constants",
    "fundamental.ev_ebitda_premium_threshold": "fundamental_layer.py hardcodes its own module-level threshold constants",
    "fundamental.ev_ebitda_vs_peers_max": "fundamental_layer.py hardcodes its own module-level threshold constants",
    "fundamental.forward_trailing_tolerance": "fundamental_layer.py hardcodes its own module-level threshold constants",
    "fundamental.forward_vs_trailing_pe_max": "fundamental_layer.py hardcodes its own module-level threshold constants",
    "fundamental.pe_extreme_premium_threshold": "fundamental_layer.py hardcodes its own module-level threshold constants",
    "fundamental.pe_premium_penalty_threshold": "fundamental_layer.py hardcodes its own module-level threshold constants",
    "fundamental.pe_vs_sector_max": "fundamental_layer.py hardcodes its own module-level threshold constants",
    "fundamental.suspect_field_score": "no real code reference found",
    "fundamental.unavailable_score": "no real code reference found",
    "fundamental.update_time_et": "no real code reference found (update_cadence/update_day ARE read; this isn't)",
    "fundamental.valuation_peers_max": "fundamental_layer.py hardcodes its own module-level threshold constants",
    "holding_period.max_days": "backtesting/simulation.py hardcodes holding_period as a (1, 15) default tuple",
    "holding_period.min_days": "backtesting/simulation.py hardcodes holding_period as a (1, 15) default tuple",
    "modifiers.macro_overlay.adverse_max_confidence": "no real code reference found",
    "modifiers.seasonality.strong_period_boost": "no real code reference found",
    "modifiers.seasonality.weak_period_penalty": "no real code reference found",
    "news.alpha_vantage_news_function": "no real code reference found",
    "news.cluster_window_days": "no real code reference found",
    "news.decay_halflife_hours": "no real code reference found",
    "news.decay_zero_at_days": "no real code reference found",
    "positioning.analyst_max": "positioning_layer.py hardcodes its own module-level MAX constants instead of cfg",
    "positioning.analyst_trend_lookback_days": "no real code reference found",
    "positioning.cache_file": "no real code reference found",
    "positioning.insider_max": "positioning_layer.py hardcodes its own module-level MAX constants instead of cfg",
    "positioning.institutional_accumulation_threshold": "no real code reference found",
    "positioning.institutional_distribution_threshold": "no real code reference found",
    "positioning.institutional_max": "positioning_layer.py hardcodes its own module-level MAX constants instead of cfg",
    "positioning.options_max": "positioning_layer.py hardcodes its own module-level MAX constants instead of cfg",
    "positioning.short_interest_declining_threshold": "no real code reference found",
    "positioning.short_interest_increasing_threshold": "no real code reference found",
    "positioning.short_interest_max": "positioning_layer.py hardcodes its own module-level MAX constants instead of cfg",
    "positioning.unavailable_score": "no real code reference found",
    "risk_reward.breakout_lookback": "no real code reference found",
    "sentiment.timezone_windows.asian_pre_market_end_et": "no real code reference found",
    "sentiment.timezone_windows.asian_pre_market_start_et": "no real code reference found",
    "sentiment.timezone_windows.european_end_et": "no real code reference found",
    "sentiment.timezone_windows.european_start_et": "no real code reference found",
    "sentiment.timezone_windows.us_after_hours_end_et": "no real code reference found",
    "sentiment.timezone_windows.us_after_hours_start_et": "no real code reference found",
    "sentiment.timezone_windows.us_session_end_et": "no real code reference found",
    "sentiment.timezone_windows.us_session_start_et": "no real code reference found",
    "sentiment.trajectory_lookback_days": "no real code reference found",
    "sentiment.velocity_window_days": "no real code reference found",
}


def _flatten_leaves(node, prefix: str = ""):
    """Yield (dotted_path, leaf_key_name) for every leaf in the config tree."""
    if isinstance(node, dict) and node and all(
        isinstance(k, str) and k.isidentifier() for k in node
    ):
        for key, value in node.items():
            path = f"{prefix}.{key}" if prefix else key
            yield from _flatten_leaves(value, path)
    else:
        leaf_name = prefix.rsplit(".", 1)[-1]
        yield prefix, leaf_name


def _collect_py_files() -> list[Path]:
    files = []
    for path in _REPO_ROOT.rglob("*.py"):
        if path in _EXCLUDED_FILES:
            continue
        if any(part in _EXCLUDED_DIR_NAMES for part in path.parts):
            continue
        files.append(path)
    return files


def _is_referenced(leaf_name: str, py_files: list[Path]) -> bool:
    pattern = re.compile(r"['\"]" + re.escape(leaf_name) + r"['\"]")
    for path in py_files:
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if pattern.search(text):
            return True
    return False


def main() -> int:
    if not _CONFIG_PATH.exists():
        print(f"::error::check_config_coverage: config file not found at {_CONFIG_PATH}")
        return 1

    config = yaml.safe_load(_CONFIG_PATH.read_text(encoding="utf-8"))
    leaves = list(_flatten_leaves(config))
    py_files = _collect_py_files()

    reference_cache: dict[str, bool] = {}
    unreferenced = []
    allowlisted = []
    for dotted_path, leaf_name in leaves:
        if leaf_name not in reference_cache:
            reference_cache[leaf_name] = _is_referenced(leaf_name, py_files)
        if reference_cache[leaf_name]:
            continue
        if dotted_path in _KNOWN_DECORATIVE:
            allowlisted.append(dotted_path)
        else:
            unreferenced.append(dotted_path)

    if allowlisted:
        print(
            f"check_config_coverage: {len(allowlisted)} known-decorative key(s) "
            f"allowlisted (existing backlog, not touched by this check):"
        )
        for path in sorted(allowlisted):
            print(f"  - {path}: {_KNOWN_DECORATIVE[path]}")

    if unreferenced:
        print(
            f"::error::check_config_coverage: {len(unreferenced)} leaf key(s) in "
            f"config/swing_config.yaml have no real (non-test) code reference and "
            f"are not in the allowlist:"
        )
        for path in sorted(unreferenced):
            print(f"  - {path}")
        print(
            "::error::check_config_coverage: either wire this key into real code, "
            "or add it to _KNOWN_DECORATIVE in scripts/check_config_coverage.py "
            "with a one-line reason — a deliberate call, not a silent gap."
        )
        return 1

    print(f"check_config_coverage: all {len(leaves)} leaf keys referenced or allowlisted — OK.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
