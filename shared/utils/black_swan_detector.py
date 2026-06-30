"""
SHARED: Intraday monitor for SMH > 7% drop or VIX > 40% spike.
When triggered: fires Red Alert to Discord, suspends new signals,
remains in Black Swan mode until regime normalizes for 3 consecutive trading days.
"""

from datetime import datetime, timezone
from typing import Optional


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
        smh_drop_threshold = float(bs_cfg.get("smh_drop_threshold", smh_drop_threshold))
        vix_spike_threshold = float(bs_cfg.get("vix_spike_threshold", vix_spike_threshold))

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
            f"SUSPEND all new signals immediately. "
            f"Trigger: {trigger_type} (SMH {smh_current_pct_change:+.1%} / "
            f"VIX {vix_current_pct_change:+.1%}). "
            f"Review all open positions — close directional exposure."
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
        f"**Action: SUSPEND all new signals. All new trades BLOCKED.**\n"
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
        "\n**Resume Condition:** 3 consecutive trading days of normal regime "
        "(VIX < 25, SMH above 20-day SMA).\n"
        "Reply RESUME when conditions are met to re-enable signal generation."
    )

    return header + body + footer


def should_resume_after_black_swan(
    regime_normal_days: int,
    required_normal_days: int = 3,
) -> bool:
    """
    Returns True if the system can resume normal operation.
    Requires regime_normal_days consecutive trading days of normal regime.
    """
    return regime_normal_days >= required_normal_days
