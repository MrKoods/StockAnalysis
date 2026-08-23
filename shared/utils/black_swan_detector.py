"""
SHARED: Intraday monitor for SMH > 7% drop or VIX > 40% spike.
When triggered: fires a Red Alert to Discord with open-position guidance.

Advisory only — same treatment as the Event Severity Gate: it flags the
condition and lets the trader decide, it does not veto or suspend new
signals. run_swing_model.py surfaces candidates on their own score merits
regardless of this state; only the alert and an advisory note are affected.
"""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

_STATE_FILE = Path("data/processed/black_swan_state.json")


def check_black_swan(
    smh_current_pct_change: float,
    vix_current_pct_change: float,
    cfg: Optional[dict] = None,
    smh_drop_threshold: float = -0.07,
    vix_spike_threshold: float = 0.40,
) -> dict:
    """
    Check if Black Swan conditions are met.

    Returns dict:
    {
        black_swan_triggered: bool,
        trigger_type: str or None,   # 'smh_drop', 'vix_spike', or None
        smh_pct_change: float,
        vix_pct_change: float,
        action_required: str,        # human-readable action summary
    }
    """
    if cfg is not None:
        bs_cfg = cfg.get("black_swan", {})
        # config/swing_config.yaml's actual keys are *_pct-suffixed
        # (smh_drop_threshold_pct/vix_spike_threshold_pct) — these used to read
        # the un-suffixed names, which don't exist in config, so the configured
        # values were silently never applied (harmless only by coincidence,
        # since the hardcoded defaults above happen to equal the configured
        # ones today).
        smh_drop_threshold = float(bs_cfg.get("smh_drop_threshold_pct", smh_drop_threshold))
        vix_spike_threshold = float(bs_cfg.get("vix_spike_threshold_pct", vix_spike_threshold))

    trigger_type = None
    triggered = False

    if smh_current_pct_change <= smh_drop_threshold:
        triggered = True
        trigger_type = "smh_drop"
    elif vix_current_pct_change >= vix_spike_threshold:
        triggered = True
        trigger_type = "vix_spike"

    if triggered:
        action = (
            f"ADVISORY — extreme market conditions detected. "
            f"Trigger: {trigger_type} (SMH {smh_current_pct_change:+.1%} / "
            f"VIX {vix_current_pct_change:+.1%}). "
            f"Review all open positions and any new candidates before acting — "
            f"signals are not automatically suspended."
        )
    else:
        action = "No action required — market within normal parameters."

    return {
        "black_swan_triggered": triggered,
        "trigger_type": trigger_type,
        "smh_pct_change": round(smh_current_pct_change, 4),
        "vix_pct_change": round(vix_current_pct_change, 4),
        "action_required": action,
    }


def build_black_swan_alert(
    trigger_type: str,
    open_positions: list[dict],
    smh_pct_change: float,
    vix_pct_change: float,
) -> str:
    """
    Build the Discord Red Alert message for a Black Swan event.

    Includes: all open positions listed, theoretical current P&L per position,
    recommended immediate action per position (close immediately / hold / roll).
    """
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    header = (
        f"🚨 **BLACK SWAN ALERT** — {now_str}\n"
        f"**Trigger:** {trigger_type.replace('_', ' ').upper()}\n"
        f"SMH: {smh_pct_change:+.1%}  |  VIX: {vix_pct_change:+.1%}\n\n"
        f"**Advisory — review before acting.** New signals still surface on their "
        f"own score merits; this is not an automatic block.\n"
    )

    if not open_positions:
        body = "No open positions. No immediate action required.\n"
    else:
        pos_lines = ["\n**Open Positions — Immediate Review:**"]
        for pos in open_positions:
            ticker = pos.get("ticker", "?")
            direction = pos.get("direction", "bullish")
            entry = pos.get("entry_price", 0.0)
            stop = pos.get("stop_loss", 0.0)

            # In a black swan, recommend closing directional long exposure
            if direction == "bullish":
                recommendation = "CLOSE IMMEDIATELY — directional long in market crash"
            else:
                recommendation = "EVALUATE — directional short may be profitable, set trailing stop"

            pos_lines.append(
                f"• **{ticker}** {direction} entry={entry:.2f} stop={stop:.2f} → {recommendation}"
            )
        body = "\n".join(pos_lines) + "\n"

    footer = (
        "\n**Normal conditions:** 3 consecutive trading days of normal regime "
        "(VIX < 25, SMH above 20-day SMA) — this alert re-fires only on the next "
        "new trigger, not every scan while conditions remain extreme."
    )

    return header + body + footer


def load_black_swan_state() -> dict:
    """
    Load data/processed/black_swan_state.json — one entry per sector name,
    each holding that sector's own black_swan_mode/black_swan_normal_days
    (see portfolio_manager.update_black_swan_state, which operates on
    whatever flat dict it's given; this file stores one such dict per sector
    so each sector's cooldown tracks its own benchmark independently).

    Shared between run_swing_model.py (live, semiconductors-only historically)
    and paper_trading/paper_runner.py (the pipeline actually running daily,
    wired in 2026-08-23 after a full model audit found it had no crash
    circuit breaker at all) — both watch the same real market, so sharing
    trigger/cooldown state between them is correct, not a layering mistake.
    """
    if not _STATE_FILE.exists():
        return {}
    try:
        raw = json.loads(_STATE_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        return {}
    return raw if isinstance(raw, dict) else {}


def save_black_swan_state(state: dict) -> None:
    """Persist per-sector black swan state to data/processed/black_swan_state.json."""
    _STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    _STATE_FILE.write_text(json.dumps(state, indent=2, default=str), encoding="utf-8")


def should_resume_after_black_swan(
    regime_normal_days: int,
    required_normal_days: int = 3,
) -> bool:
    """
    Returns True if the system can resume normal operation.
    Requires regime_normal_days consecutive trading days of normal regime.
    """
    return regime_normal_days >= required_normal_days
