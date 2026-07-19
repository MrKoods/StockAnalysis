"""
SHARED: Sends alerts to Discord. Discord and the desktop app UI (see App_UI_Scope.md)
are the only two places alerts surface — there is no email or SMS delivery channel.
"""

from typing import Optional

from shared.utils.logger import get_logger

logger = get_logger(__name__)


def route_alert(
    message: str,
    alert_type: str,
    discord_webhook_url: Optional[str] = None,
) -> dict:
    """
    Send an alert to Discord.

    Returns dict:
    {
        discord_sent: bool,
        errors: list[str],
    }
    """
    from shared.utils.discord_alerts import _post_to_webhook
    discord_payload = {
        "content": message[:2000],
    }
    discord_sent = _post_to_webhook(discord_payload, webhook_url=discord_webhook_url)

    return {
        "discord_sent": discord_sent,
        "errors": [] if discord_sent else ["discord_delivery_failed"],
    }


def send_discord(webhook_url: str, message: str, embed: Optional[dict] = None) -> bool:
    """POST alert to Discord webhook. Returns True on success."""
    from shared.utils.discord_alerts import _post_to_webhook
    payload = {"content": message[:2000]}
    if embed:
        payload["embeds"] = [embed]
    return _post_to_webhook(payload, webhook_url=webhook_url)
