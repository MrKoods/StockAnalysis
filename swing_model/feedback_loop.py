"""
Logs closed trade outcomes; updates rolling win rate per signal combination;
feeds back into scoring engine calibration (two-speed cycle per Clarification 1).

Two-speed cycle:
  Immediate: log outcome → update signal_win_rates.json (does NOT affect live scoring)
  Monthly (or every 20 trades): mini-calibration pass → out-of-sample check →
    if passing and no version-bump-triggering change: update calibrated_weights.json;
    if failing or needs a version bump first: keep old weights (caller alerts —
    see paper_trading/paper_updater.py's auto-trigger hook).
  Weight changes > 5pp require version increment + mini-backtest — single
  enforcement point: swing_model.model_versioning.check_backtest_required(),
  called from run_calibration() itself.

Data source: run_calibration() takes an explicit `outcomes` list rather than
always reading data/logs/trade_outcomes.csv (this module's own log_trade_outcome()
output, fed only by swing_model/portfolio_manager.py's manual-Discord-confirmation
flow) — that file has stayed empty since no model version has gone live. Real
callers should pass load_calibration_outcomes_from_paper_trades(), which reads
paper_trading/paper_trades.csv — the system that's actually been running.

calibrated_weights.json only reaches live scoring via load_live_weights_if_calibrated(),
which returns None until a real calibration has passed holdout at least once —
see that function's docstring.
"""

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import numpy as np
from scipy.optimize import minimize

from shared.utils.atomic_io import atomic_write_json
from swing_model import model_versioning

_TRADE_OUTCOMES_FILE = Path("data/logs/trade_outcomes.csv")
_SIGNAL_WIN_RATES_FILE = Path("data/processed/signal_win_rates.json")
# Calibrated weight deltas — separate from config/live_weights.json (which has a nested schema)
_LIVE_WEIGHTS_FILE = Path("data/processed/calibrated_weights.json")
# Paper trading's own trade log — see load_calibration_outcomes_from_paper_trades.
_PAPER_TRADES_FILE = Path("paper_trading/paper_trades.csv")

_WEIGHT_KEYS = ("technical", "sentiment", "news")
_DEFAULT_WEIGHTS = {"technical": 0.60, "sentiment": 0.25, "news": 0.15}

# Per-sector calibration (see fit_sector_calibrated_weights) — separate file
# and separate machinery from the global live-paper-trading calibration
# above: different data source (historical backtest replay, not real closed
# paper trades — there isn't enough real per-sector trade history yet) and a
# different trust model (a sample-size gate plus shrinkage, since a sector's
# sample can be far smaller than the pooled global one).
_SECTOR_LIVE_WEIGHTS_FILE = Path("data/processed/calibrated_weights_by_sector.json")

_OUTCOMES_COLUMNS = [
    "timestamp_utc", "ticker", "entry_date", "exit_date",
    "entry_price", "exit_price", "direction", "structure",
    "confidence_score", "technical_total", "sentiment_total", "news_total",
    "holding_days", "pnl_dollars", "pnl_pct", "outcome",  # 'win' | 'loss'
    "signal_key",  # hash of signal combination for win rate lookup
]


def log_trade_outcome(outcome: dict) -> None:
    """
    Log a closed trade outcome to trade_outcomes.csv.
    Also updates signal_win_rates.json immediately.
    """
    path = _TRADE_OUTCOMES_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    write_header = not path.exists()

    row = {col: outcome.get(col, "") for col in _OUTCOMES_COLUMNS}
    if not row.get("timestamp_utc"):
        row["timestamp_utc"] = datetime.now(timezone.utc).isoformat()

    with open(path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=_OUTCOMES_COLUMNS, extrasaction="ignore")
        if write_header:
            writer.writeheader()
        writer.writerow(row)

    update_signal_win_rates(outcome)


def update_signal_win_rates(outcome: dict) -> None:
    """
    Update the rolling win rate for the specific signal combination that fired.
    Stored in data/processed/signal_win_rates.json.
    Does NOT update live_weights.json — that happens only at scheduled recalibration.
    """
    path = _SIGNAL_WIN_RATES_FILE
    path.parent.mkdir(parents=True, exist_ok=True)

    if path.exists():
        try:
            rates = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            rates = {}
    else:
        rates = {}

    key = outcome.get("signal_key", "unknown")
    if key not in rates:
        rates[key] = {"wins": 0, "losses": 0, "total": 0}

    result = outcome.get("outcome", "")
    if result == "win":
        rates[key]["wins"] += 1
    elif result in ("loss", "time_stop"):
        rates[key]["losses"] += 1
    rates[key]["total"] += 1

    # Compute rolling win rate only when >= 10 samples
    if rates[key]["total"] >= 10:
        rates[key]["win_rate"] = round(rates[key]["wins"] / rates[key]["total"], 4)

    atomic_write_json(path, rates)


def load_calibration_outcomes_from_paper_trades(csv_path: Optional[Path] = None) -> list[dict]:
    """
    Adapt paper_trading/paper_trades.csv's closed rows into the shape
    run_calibration() expects. This is the real data source for calibration —
    paper trading is the system that's actually been running (see
    paper_trading/paper_trade_metrics.py::load_paper_trade_gate_inputs for the
    same "which file is real" note); this module's own _TRADE_OUTCOMES_FILE
    (fed by swing_model/portfolio_manager.py's manual-Discord-confirmation
    flow) has stayed empty since no model version has gone live, and would
    give run_calibration() nothing to work with.

    Field mapping: technical_score -> technical_total, sentiment_score ->
    sentiment_total, news_score -> news_total (identical values, renamed to
    match this module's _score_outcomes/_recompute_weights schema); outcome/
    achieved_rr/pnl_pct pass through under their existing names.

    Known gap, not addressed here: signal_key stays "unknown" for every row.
    build_signal_key() needs raw indicator flags (breakout_confirmed,
    sentiment_direction) that paper_trades.csv's schema doesn't capture — it
    stores the aggregate 0-40/0-15/0-15 category scores, not the underlying
    boolean/directional sub-signals those flags come from. update_signal_win_rates()
    still works, it just can't bucket by signal combination yet; that would
    need paper_runner.py's row-writer to additionally persist those raw flags
    — a separate follow-up, not done here.
    """
    path = csv_path or _PAPER_TRADES_FILE
    if not path.exists():
        return []

    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    outcomes = []
    for r in rows:
        # "expired" rows never filled — no entry, no exit, no capital at risk,
        # so they carry no directional-accuracy signal (unlike a win/loss,
        # which is real; see paper_updater.py's fill-confirmation step).
        if not r.get("outcome") or r.get("outcome") == "expired":
            continue
        outcomes.append({
            "timestamp_utc": r.get("exit_date", ""),
            "ticker": r.get("ticker", ""),
            "entry_date": r.get("signal_date", ""),
            "exit_date": r.get("exit_date", ""),
            "entry_price": r.get("entry_price", ""),
            "exit_price": r.get("exit_price", ""),
            "confidence_score": r.get("confidence", ""),
            "technical_total": r.get("technical_score", ""),
            "sentiment_total": r.get("sentiment_score", ""),
            "news_total": r.get("news_score", ""),
            "holding_days": r.get("holding_days", ""),
            "pnl_pct": r.get("pnl_pct", ""),
            "achieved_rr": r.get("achieved_rr", ""),
            "outcome": r.get("outcome", ""),
            "signal_key": "unknown",
        })
    return outcomes


def run_calibration(
    outcomes: Optional[list[dict]] = None,
    holdout_count: Optional[int] = None,
    min_change_for_version: Optional[float] = None,
    cfg: Optional[dict] = None,
) -> dict:
    """
    Monthly (or every-N-trades) calibration pass:
    1. Load outcomes — from `outcomes` if given, else data/logs/trade_outcomes.csv
       (kept as the default for backward compatibility; real callers should
       pass load_calibration_outcomes_from_paper_trades() explicitly — see
       that function's docstring for why trade_outcomes.csv alone is empty)
    2. Withhold most recent holdout_count trades as out-of-sample check
    3. Recompute win rates per signal combination from remaining trades
    4. Test new weights on withheld trades
    5. If new weights equal or better on withheld AND no version bump needed:
       update calibrated_weights.json with last_calibrated/n_trades metadata
    6. If any weight changes > min_change_for_version: require version increment
       (single enforcement point: swing_model.model_versioning.check_backtest_required)
    7. If calibration fails out-of-sample check: keep old weights (caller decides
       whether to alert — see paper_trading/paper_updater.py's auto-trigger hook)

    holdout_count/min_change_for_version fall back to cfg's feedback_loop block
    (recalibrate settings) when not passed explicitly, then to this project's
    documented defaults (5, 0.05) if cfg has neither.

    Returns dict with calibration result details.
    """
    fl_cfg = (cfg or {}).get("feedback_loop", {})
    if holdout_count is None:
        holdout_count = int(fl_cfg.get("out_of_sample_holdout", 5))
    if min_change_for_version is None:
        min_change_for_version = float(fl_cfg.get("weight_change_version_threshold", 0.05))

    if outcomes is None:
        if not _TRADE_OUTCOMES_FILE.exists():
            return {
                "status": "no_data",
                "message": "No trade outcomes file found",
                "weights_updated": False,
            }
        try:
            with open(_TRADE_OUTCOMES_FILE, newline="", encoding="utf-8") as f:
                outcomes = list(csv.DictReader(f))
        except OSError as exc:
            return {"status": "error", "message": str(exc), "weights_updated": False}

    if len(outcomes) < holdout_count + 10:
        return {
            "status": "insufficient_data",
            "message": f"Need at least {holdout_count + 10} trades, have {len(outcomes)}",
            "weights_updated": False,
        }

    train_outcomes = outcomes[:-holdout_count]
    holdout = outcomes[-holdout_count:]

    # Load current weights (metadata-stripped — see _load_live_weights)
    current_weights = _load_live_weights()

    # Recompute weights from training set
    new_weights = _recompute_weights(train_outcomes, current_weights)

    # Test on holdout
    holdout_win_rate_old = _score_outcomes(holdout, current_weights)
    holdout_win_rate_new = _score_outcomes(holdout, new_weights)

    passed_holdout = holdout_win_rate_new >= holdout_win_rate_old

    needs_version = model_versioning.check_backtest_required(
        new_weights, current_weights, change_threshold=min_change_for_version
    )

    result = {
        "status": "pass" if passed_holdout else "fail",
        "holdout_win_rate_old": round(holdout_win_rate_old, 4),
        "holdout_win_rate_new": round(holdout_win_rate_new, 4),
        "weights_updated": False,
        "needs_version_increment": needs_version,
        "train_count": len(train_outcomes),
        "holdout_count": len(holdout),
        "new_weights": new_weights,
        "current_weights": current_weights,
    }

    if passed_holdout and not needs_version:
        _save_live_weights(new_weights, n_trades=len(train_outcomes))
        result["weights_updated"] = True
    elif passed_holdout and needs_version:
        # Changes >5pp — require version bump before applying
        result["message"] = (
            "Calibration passed holdout but weight change > 5pp: "
            "bump model version before applying"
        )
    else:
        result["message"] = (
            f"Calibration failed holdout (new={holdout_win_rate_new:.1%} < "
            f"old={holdout_win_rate_old:.1%}). Keeping current weights."
        )

    return result


def should_recalibrate(closed_trade_count: int, cfg: Optional[dict] = None) -> bool:
    """
    Whether a new calibration pass is due, per config/swing_config.yaml's
    feedback_loop block: every recalibrate_every_n_trades closed trades since
    the last calibration, or recalibrate_monthly if that much wall-clock time
    has passed — whichever fires first.

    Stateless: reads calibrated_weights.json's own last_calibrated/n_trades
    metadata (written by _save_live_weights on a passing calibration) rather
    than tracking a separate "trades since last calibration" counter, so
    there's one source of truth for "when did we last calibrate."

    Never calibrated yet: due once enough trades exist for run_calibration()
    to even attempt it (its own insufficient-data floor is holdout_count + 10,
    default 15) — an imprecise trigger here just means a wasted, cheap
    run_calibration() call that returns "insufficient_data", not a bug.
    """
    fl_cfg = (cfg or {}).get("feedback_loop", {})
    every_n = int(fl_cfg.get("recalibrate_every_n_trades", 20))
    monthly = bool(fl_cfg.get("recalibrate_monthly", True))
    holdout = int(fl_cfg.get("out_of_sample_holdout", 5))

    raw = _load_live_weights_raw()
    last_calibrated = raw.get("last_calibrated")
    last_n_trades = raw.get("n_trades")

    if not last_calibrated:
        return closed_trade_count >= holdout + 10

    if last_n_trades is not None and closed_trade_count - int(last_n_trades) >= every_n:
        return True

    if monthly:
        try:
            last_dt = datetime.fromisoformat(last_calibrated)
            if last_dt.tzinfo is None:
                last_dt = last_dt.replace(tzinfo=timezone.utc)
            if (datetime.now(timezone.utc) - last_dt).days >= 30:
                return True
        except ValueError:
            pass

    return False


def build_signal_key(indicator_state: dict) -> str:
    """
    Create a hashable key for a signal combination (for win rate lookup).
    Key encodes: breakout T/F, trend T/F, RS direction, RSI range, sentiment direction.
    """
    breakout = "B1" if indicator_state.get("breakout_confirmed") else "B0"
    trend = "T1" if indicator_state.get("trend_aligned") else "T0"
    rs = indicator_state.get("relative_strength_direction", "neutral")[:3].upper()

    rsi = float(indicator_state.get("rsi", 50))
    if rsi < 40:
        rsi_band = "RSI_LOW"
    elif rsi < 60:
        rsi_band = "RSI_MID"
    else:
        rsi_band = "RSI_HIGH"

    sentiment = indicator_state.get("sentiment_direction", "neutral")[:3].upper()

    return f"{breakout}_{trend}_{rs}_{rsi_band}_{sentiment}"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _load_live_weights() -> dict:
    """Weight fractions only (technical/sentiment/news) — strips last_calibrated/
    n_trades metadata if present, since callers here only do weight arithmetic."""
    raw = _load_live_weights_raw()
    return {k: raw[k] for k in _WEIGHT_KEYS if k in raw} or dict(_DEFAULT_WEIGHTS)


def _load_live_weights_raw() -> dict:
    if _LIVE_WEIGHTS_FILE.exists():
        try:
            return json.loads(_LIVE_WEIGHTS_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return dict(_DEFAULT_WEIGHTS)


def _save_live_weights(weights: dict, n_trades: Optional[int] = None) -> None:
    """
    Persist calibrated weights plus last_calibrated/n_trades metadata — this
    metadata is what load_live_weights_if_calibrated() checks before letting
    these weights actually reach compute_confidence_score(), so a placeholder/
    default weights file (never genuinely calibrated) can't silently start
    affecting live scoring.
    """
    payload = {k: weights[k] for k in _WEIGHT_KEYS if k in weights}
    payload["last_calibrated"] = datetime.now(timezone.utc).isoformat()
    payload["n_trades"] = n_trades
    atomic_write_json(_LIVE_WEIGHTS_FILE, payload)


def load_live_weights_if_calibrated(sector: Optional[str] = None, direction: str = "bullish") -> Optional[dict]:
    """
    Returns the calibrated weight fractions {"technical", "sentiment", "news"}
    only if a real calibration has actually run and passed — otherwise
    returns None. Callers (run_swing_model.py, paper_runner.py) pass this
    straight into compute_confidence_score(live_weights=...); with zero real
    global calibrations run yet, this returns None and live scoring is
    unaffected — it only starts having any effect once a real calibration
    passes holdout, at which point it's exactly the kind of weight change
    this project's own rule requires a version bump for (see
    run_calibration's needs_version_increment).

    sector: when given and that sector has its own entry in
    calibrated_weights_by_sector.json (see fit_sector_calibrated_weights),
    returns that sector's weights instead of the global ones — semiconductors
    and consumer_discretionary currently have enough historical data to
    support an independent fit; regional_banks/healthcare don't yet and have
    no entry, so they fall through to the same global-weights behavior as
    every caller that doesn't pass a sector at all. None (the default)
    preserves the original sector-agnostic behavior unchanged.

    direction: looks up that sector's direction-specific entry (new nested
    schema: {sector: {"bullish": {...}, "bearish": {...}}}), written by
    backtesting/sector_weight_calibration.py once bearish outcomes exist to
    calibrate against. Falls back to reading an old-format flat entry
    (sector -> weights directly, no direction nesting — every entry written
    before bearish parity existed) as that sector's bullish weights, so
    already-calibrated files keep working unchanged for "bullish". A bearish
    lookup against an old-format-only entry returns None (falls through to
    the global weights) rather than misapplying bullish-fitted weights to a
    bearish candidate.
    """
    if sector is not None:
        sector_entry = _load_sector_weights_raw().get(sector) or {}
        if direction in sector_entry and isinstance(sector_entry.get(direction), dict):
            sector_weights = sector_entry[direction]
        elif direction == "bullish" and sector_entry.get("last_calibrated"):
            sector_weights = sector_entry  # old flat (pre-direction) schema
        else:
            sector_weights = None
        if sector_weights and sector_weights.get("last_calibrated"):
            return {k: sector_weights[k] for k in _WEIGHT_KEYS if k in sector_weights}

    raw = _load_live_weights_raw()
    if not raw.get("last_calibrated"):
        return None
    return {k: raw[k] for k in _WEIGHT_KEYS if k in raw}


def _load_sector_weights_raw() -> dict:
    if _SECTOR_LIVE_WEIGHTS_FILE.exists():
        try:
            return json.loads(_SECTOR_LIVE_WEIGHTS_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def save_sector_weights(sector_weights: dict[str, dict]) -> None:
    """Persist per-sector calibrated weights (see fit_sector_calibrated_weights)
    to their own file — deliberately not merged into calibrated_weights.json,
    which belongs to the separate global/live-paper-trading calibration cycle
    above and has its own format (flat weights + one last_calibrated/n_trades
    pair, not a per-sector nesting)."""
    atomic_write_json(_SECTOR_LIVE_WEIGHTS_FILE, sector_weights)


_MIN_SAMPLES_FOR_REGRESSION = 20
_LOGISTIC_L2_PENALTY = 1.0  # regularization strength — keeps a small holdout-gated
# calibration sample from fitting noise, same spirit as the ±2pp/10pp caps below.


def _sigmoid(z: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-np.clip(z, -30, 30)))


def _fit_logistic_weights(outcomes: list[dict]) -> Optional[dict]:
    """
    Regularized logistic regression: predict win (1) vs. loss (0) from
    [technical_total, sentiment_total, news_total], L2-penalized. Returns
    normalized weight fractions (summing to 1.0) from the fitted
    coefficients' relative magnitudes, or None when there isn't enough
    data or the fit is degenerate (e.g. every sample has identical feature
    values, so there's no real signal to separate wins from losses) —
    callers should fall back to the coarser heuristic in that case.

    Replaces the previous sign-only heuristic (_recompute_weights' old
    body), which only asked "is this sub-signal's average higher in wins
    than losses" and applied the same fixed ±2pp nudge regardless of how
    large or reliable that gap was — a sub-signal with a huge, consistent
    edge and one with a coin-flip-sized edge got an identical adjustment.
    A regression naturally weighs each sub-signal by how much it actually
    separates outcomes, and standardizing features first (see X_std below)
    keeps a large-scale sub-signal (technical: 0-40) from mechanically
    dominating a small-scale one (news: 0-15) purely from units, not
    predictive power.

    A zero-variance feature is dropped from the fit rather than aborting the
    whole thing — found via backtesting/sector_weight_calibration.py:
    historical backtest replay predates Alpha Vantage's article cache (Q4
    2025 onward) for nearly its entire 13.5-year range, so news_total sits on
    its neutral fallback for almost every historical row and has nothing to
    fit against; requiring all 3 features to vary made every historical
    calibration attempt degenerate instead of usefully fitting the 2 that
    do. The returned dict only contains keys for features that could
    actually be fit — callers must treat an omitted key as "no information,
    keep whatever value this weight already had," not as a fitted 0.
    """
    rows = []
    for o in outcomes:
        outcome = o.get("outcome")
        if outcome not in ("win", "loss", "time_stop"):
            continue
        try:
            tech = float(o.get("technical_total", ""))
            sent = float(o.get("sentiment_total", ""))
            news = float(o.get("news_total", ""))
        except (TypeError, ValueError):
            continue
        rows.append((tech, sent, news, 1.0 if outcome == "win" else 0.0))

    if len(rows) < _MIN_SAMPLES_FOR_REGRESSION:
        return None

    feature_names = ["technical", "sentiment", "news"]
    X_full = np.array([[r[0], r[1], r[2]] for r in rows])
    y = np.array([r[3] for r in rows])
    if len(set(y.tolist())) < 2:
        return None  # all wins or all losses — nothing to separate

    keep = [i for i in range(3) if X_full[:, i].std() > 0]
    if not keep:
        return None  # no feature has any variance at all — fully degenerate

    X = X_full[:, keep]
    X_mean = X.mean(axis=0)
    X_std = X.std(axis=0)
    X_norm = (X - X_mean) / X_std

    def neg_log_likelihood(beta: np.ndarray) -> float:
        p = _sigmoid(X_norm @ beta)
        eps = 1e-9
        ll = np.sum(y * np.log(p + eps) + (1 - y) * np.log(1 - p + eps))
        return float(-ll + _LOGISTIC_L2_PENALTY * np.sum(beta ** 2))

    result = minimize(neg_log_likelihood, x0=np.zeros(len(keep)), method="L-BFGS-B")
    if not result.success:
        return None

    coefs = np.abs(result.x)
    total = float(coefs.sum())
    if total <= 1e-9:
        return None  # no sub-signal showed any separating power

    fractions = coefs / total
    return {feature_names[i]: float(fractions[j]) for j, i in enumerate(keep)}


# Below this many qualifying outcomes, a sector doesn't get its own
# independent fit at all — not just a heavily-shrunk one. Chosen from the
# actual per-sector sample sizes in the current historical set (see
# CHANGELOG v2.2.57): semiconductors (127) and consumer_discretionary (506)
# clear it; regional_banks (90) and healthcare (68) don't. Both of the
# excluded sectors are individually above _MIN_SAMPLES_FOR_REGRESSION (20) —
# a fit would technically run — but trusting a 3-parameter regression that
# thin risks replacing "wrong shared weights" with "confidently wrong
# sector-specific weights," which is worse, not better. Excluded sectors
# simply get no entry in the output; load_live_weights_if_calibrated()
# already treats a missing sector as "use the shared default."
_MIN_SAMPLES_FOR_SECTOR_CALIBRATION = 100

# Sectors at or above this many qualifying outcomes get (close to) full trust
# in their fitted weights; below it, the fit is linearly blended toward the
# shared default in proportion to how far short of this it is — a fit on 127
# trades is still less reliable than one on 506, even though both clear the
# floor above to be attempted at all.
_SECTOR_SHRINKAGE_FULL_TRUST_N = 300


def fit_sector_calibrated_weights(outcomes_by_sector: dict[str, list[dict]]) -> dict[str, dict]:
    """
    Fit independent technical/sentiment/news weights per sector, instead of
    one global set applied everywhere regardless of what kind of stock it is
    scoring (see CHANGELOG v2.2.56's architecture_diagnostic.py finding: the
    same weighting that gives semiconductors a 4.16 Sharpe gives regional
    banks 0.64, healthcare 0.69, and consumer discretionary 0.22 — all
    failing the go-live bar on their own data).

    outcomes_by_sector: {sector: outcomes}, already restricted to the
    training split (see backtesting/sector_weight_calibration.py, which
    holds out the most recent ~20% of each sector's outcomes chronologically
    for validation before this function ever sees the rest — the same
    train/holdout discipline run_calibration() already uses for the global
    live-paper-trading calibration).

    Two safeguards against overfitting a thin sector sample, applied in
    order:
    1. A hard floor (_MIN_SAMPLES_FOR_SECTOR_CALIBRATION) — sectors below it
       aren't fit at all, not even with a heavy shrink; they're simply
       absent from the result.
    2. Shrinkage toward the shared default (_DEFAULT_WEIGHTS), proportional
       to sample size up to _SECTOR_SHRINKAGE_FULL_TRUST_N — a fit just
       above the floor is mostly the default with a small nudge from the
       fit; a fit with hundreds of trades is trusted almost fully.

    The same 30-80%/5-40%/5-30% per-weight bounds _recompute_weights applies
    are enforced here too, after shrinkage.

    Returns {sector: {technical, sentiment, news, n_trades, shrinkage_factor,
    last_calibrated}} — only for sectors that cleared the floor AND produced
    a non-degenerate fit (see _fit_logistic_weights). Sectors not present in
    the result should be treated as "not enough data to calibrate
    independently yet," not as a fit that ran and found nothing.
    """
    results: dict[str, dict] = {}
    for sector, outcomes in outcomes_by_sector.items():
        n = len(outcomes)
        if n < _MIN_SAMPLES_FOR_SECTOR_CALIBRATION:
            continue

        fitted = _fit_logistic_weights(outcomes)
        if fitted is None:
            continue

        shrinkage = min(1.0, n / _SECTOR_SHRINKAGE_FULL_TRUST_N)
        # .get(k, _DEFAULT_WEIGHTS[k]) rather than fitted[k]: a key can be
        # missing when _fit_logistic_weights had to drop a zero-variance
        # feature (see that function's docstring) — treated as "no
        # information to calibrate this weight from," which this formula
        # already resolves to the default regardless of shrinkage, since
        # both terms become _DEFAULT_WEIGHTS[k].
        blended = {
            k: shrinkage * fitted.get(k, _DEFAULT_WEIGHTS[k]) + (1 - shrinkage) * _DEFAULT_WEIGHTS[k]
            for k in _WEIGHT_KEYS
        }

        results[sector] = {
            **_clamp_and_normalize_weights(blended),
            "n_trades": n,
            "shrinkage_factor": round(shrinkage, 3),
            "last_calibrated": datetime.now(timezone.utc).isoformat(),
        }
    return results


_WEIGHT_BOUNDS = {"technical": (0.30, 0.80), "sentiment": (0.05, 0.40), "news": (0.05, 0.30)}


def _clamp_and_normalize_weights(raw: dict) -> dict:
    """
    Clamp each weight to _WEIGHT_BOUNDS AND normalize to sum to 1.0 — a
    single clamp-then-rescale pass can violate the very bound it just
    enforced (e.g. sentiment and news both floor-clamped to their minimums
    forces technical above its own ceiling once the three are rescaled back
    to sum to 1.0). Found via a test with a strongly technical-dominant
    synthetic signal (fit_sector_calibrated_weights, CHANGELOG v2.2.57), but
    the same bug was already latent in _recompute_weights' original
    single-pass version — just never triggered by real data yet, since
    real fits so far haven't landed a raw value far enough past a bound to
    expose it.

    Water-filling: clamp everything, then redistribute the (1 - sum) gap
    only across weights not already sitting on a bound, proportional to
    their current share of that free group; repeat, permanently freezing any
    weight the redistribution itself pushes onto a bound, until nothing more
    needs freezing. This is the standard correct algorithm for projecting
    onto a box-constrained simplex — unlike naive rescaling, it's guaranteed
    to land in-bounds whenever a feasible point exists, which it does here
    (_WEIGHT_BOUNDS' minimums sum to 0.40, maximums sum to 1.50, straddling
    the required 1.0).
    """
    values = {k: max(_WEIGHT_BOUNDS[k][0], min(_WEIGHT_BOUNDS[k][1], v)) for k, v in raw.items()}
    frozen: set = set()

    for _ in range(len(values)):
        total = sum(values.values())
        if abs(total - 1.0) < 1e-9:
            break

        free_keys = [k for k in values if k not in frozen]
        if not free_keys:
            break
        free_total = sum(values[k] for k in free_keys)
        frozen_total = total - free_total
        if free_total <= 0:
            break

        # Rescale only the free weights so the whole set sums to 1.0.
        scale = (1.0 - frozen_total) / free_total
        for k in free_keys:
            values[k] *= scale

        newly_frozen = [
            k for k in free_keys
            if values[k] < _WEIGHT_BOUNDS[k][0] - 1e-9 or values[k] > _WEIGHT_BOUNDS[k][1] + 1e-9
        ]
        if not newly_frozen:
            break
        for k in newly_frozen:
            values[k] = max(_WEIGHT_BOUNDS[k][0], min(_WEIGHT_BOUNDS[k][1], values[k]))
            frozen.add(k)

    return {k: round(v, 4) for k, v in values.items()}


def _recompute_weights(outcomes: list[dict], current_weights: dict) -> dict:
    """
    Recompute weights based on which signal components correlate with wins.

    Tries a regularized logistic regression first (_fit_logistic_weights) —
    weighs each sub-signal by how much it actually separates wins from
    losses, not just its sign. Falls back to a coarser win/loss-average
    heuristic (±2pp nudge per sub-signal, direction only) when there isn't
    enough data to fit a regression reliably (see
    _MIN_SAMPLES_FOR_REGRESSION) or the fit is degenerate — the same
    30-80%/5-40%/5-30% bounds and normalization apply either way.
    """
    if not outcomes:
        return current_weights.copy()

    wins = [o for o in outcomes if o.get("outcome") == "win"]
    losses = [o for o in outcomes if o.get("outcome") in ("loss", "time_stop")]

    if not wins or not losses:
        return current_weights.copy()

    fitted = _fit_logistic_weights(outcomes)
    if fitted is not None:
        # .get(k, current_weights[k]) rather than fitted[k]: a key can be
        # missing when a zero-variance feature got dropped from the fit
        # (see _fit_logistic_weights' docstring) — keep that weight
        # unchanged rather than treating the omission as a fitted 0.
        raw_weights = {
            "technical": fitted.get("technical", current_weights.get("technical", 0.60)),
            "sentiment": fitted.get("sentiment", current_weights.get("sentiment", 0.25)),
            "news": fitted.get("news", current_weights.get("news", 0.15)),
        }
    else:
        def avg(outcomes, field):
            vals = [float(o.get(field, 0)) for o in outcomes if o.get(field)]
            return sum(vals) / len(vals) if vals else 0.0

        # If technical signal higher on wins → increase technical weight
        tech_win = avg(wins, "technical_total")
        tech_loss = avg(losses, "technical_total")
        sent_win = avg(wins, "sentiment_total")
        sent_loss = avg(losses, "sentiment_total")
        news_win = avg(wins, "news_total")
        news_loss = avg(losses, "news_total")

        adj_tech = 0.02 if tech_win > tech_loss else -0.02
        adj_sent = 0.02 if sent_win > sent_loss else -0.02
        adj_news = 0.02 if news_win > news_loss else -0.02

        raw_weights = {
            "technical": current_weights.get("technical", 0.60) + adj_tech,
            "sentiment": current_weights.get("sentiment", 0.25) + adj_sent,
            "news": current_weights.get("news", 0.15) + adj_news,
        }

    return _clamp_and_normalize_weights(raw_weights)


def _score_outcomes(outcomes: list[dict], weights: dict) -> float:
    """
    How well `weights` combine the technical/sentiment/news sub-totals to separate
    winning holdout trades from losing ones — mean weighted composite score of wins
    minus mean of losses. Higher is better (mirrors _recompute_weights: a sub-signal
    that scores higher in wins than losses should be upweighted).

    This previously ignored `weights` entirely and returned the raw win rate, which
    made old-vs-new holdout comparisons in run_calibration always identical — the
    safety gate meant to reject a bad recalibration could never actually fail.
    Falls back to raw win rate when sub-signal fields aren't present (e.g. legacy
    CSV rows) or one of the win/loss groups is empty, so the comparison degrades
    gracefully instead of raising or dividing by zero.
    """
    if not outcomes:
        return 0.0

    wins = [o for o in outcomes if o.get("outcome") == "win"]
    losses = [o for o in outcomes if o.get("outcome") in ("loss", "time_stop")]

    has_subsignals = any(f"{k}_total" in o for o in outcomes for k in weights)
    if not has_subsignals or not wins or not losses:
        return sum(1 for o in outcomes if o.get("outcome") == "win") / len(outcomes)

    def composite(o: dict) -> float:
        total = 0.0
        for key, weight in weights.items():
            val = o.get(f"{key}_total")
            if val in (None, ""):
                continue
            try:
                total += float(weight) * float(val)
            except (TypeError, ValueError):
                continue
        return total

    win_avg = sum(composite(o) for o in wins) / len(wins)
    loss_avg = sum(composite(o) for o in losses) / len(losses)
    return win_avg - loss_avg
