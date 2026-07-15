"""
SHARED: Routes alerts to Discord (primary) + email/SMTP (secondary, critical only)
+ SMS/Twilio (tertiary, Black Swan + Red circuit breaker only).
All alerts → Discord; critical → also email; highest-priority → also SMS.
If Discord delivery fails (HTTP error), auto-escalates to email for that alert.
Priority classification defined in global_config.yaml['notifications'].
"""

import os
import smtplib
from email.mime.text import MIMEText
from typing import Optional

from shared.utils.logger import get_logger

logger = get_logger(__name__)

# Alert priority levels
PRIORITY_NORMAL = "normal"
PRIORITY_CRITICAL = "critical"     # circuit breakers, Black Swan, time stops, missed scan
PRIORITY_HIGHEST = "highest"       # Black Swan, Red circuit breaker only


def route_alert(
    message: str,
    alert_type: str,
    priority: str = PRIORITY_NORMAL,
    discord_webhook_url: Optional[str] = None,
) -> dict:
    """
    Route an alert through the priority-based notification hierarchy.

    All alerts → Discord.
    critical/highest → also email.
    highest → also SMS.
    If Discord fails → auto-escalate to email.

    Returns dict:
    {
        discord_sent: bool,
        email_sent: bool,
        sms_sent: bool,
        errors: list[str],
    }
    """
    errors = []
    email_sent = False
    sms_sent = False

    # Always try Discord first
    from shared.utils.discord_alerts import _post_to_webhook
    discord_payload = {
        "content": message[:2000],
    }
    discord_sent = _post_to_webhook(discord_payload, webhook_url=discord_webhook_url)

    if not discord_sent:
        errors.append("discord_delivery_failed")
        # Auto-escalate to email when Discord fails
        if priority in (PRIORITY_NORMAL,):
            email_sent = send_email(
                subject=f"[StockAnalysis] {alert_type.replace('_', ' ').title()}",
                body=message,
            )

    if priority in (PRIORITY_CRITICAL, PRIORITY_HIGHEST):
        email_sent = send_email(
            subject=f"[StockAnalysis] {alert_type.replace('_', ' ').title()}",
            body=message,
        )

    if priority == PRIORITY_HIGHEST:
        sms_sent = send_sms(body=message[:160])

    return {
        "discord_sent": discord_sent,
        "email_sent": email_sent,
        "sms_sent": sms_sent,
        "errors": errors,
    }


def classify_alert_priority(alert_type: str) -> str:
    """
    Return the priority level for a given alert type.
    Mapping defined by the alert types table in the scope.
    """
    _CRITICAL_TYPES = {
        "circuit_breaker_yellow", "circuit_breaker_orange", "circuit_breaker_red",
        "black_swan", "time_stop", "structure_stop", "missed_scan",
        "event_gate_critical",
    }
    _HIGHEST_TYPES = {"black_swan", "circuit_breaker_red"}

    if alert_type in _HIGHEST_TYPES:
        return PRIORITY_HIGHEST
    if alert_type in _CRITICAL_TYPES:
        return PRIORITY_CRITICAL
    return PRIORITY_NORMAL


def send_discord(webhook_url: str, message: str, embed: Optional[dict] = None) -> bool:
    """POST alert to Discord webhook. Returns True on success."""
    from shared.utils.discord_alerts import _post_to_webhook
    payload = {"content": message[:2000]}
    if embed:
        payload["embeds"] = [embed]
    return _post_to_webhook(payload, webhook_url=webhook_url)


def send_email(subject: str, body: str) -> bool:
    """Send email via SMTP (credentials from .env). Returns True on success."""
    smtp_host = os.getenv("SMTP_HOST", "")
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_user = os.getenv("SMTP_USER", "")
    smtp_pass = os.getenv("SMTP_PASS", "")
    email_to = os.getenv("ALERT_EMAIL_TO", "")

    if not all([smtp_host, smtp_user, smtp_pass, email_to]):
        logger.warning("Email not configured — SMTP_HOST/USER/PASS/ALERT_EMAIL_TO not all set")
        return False

    try:
        msg = MIMEText(body)
        msg["Subject"] = subject
        msg["From"] = smtp_user
        msg["To"] = email_to

        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.starttls()
            server.login(smtp_user, smtp_pass)
            server.send_message(msg)
        return True
    except Exception as exc:
        logger.error(f"Email send failed: {exc}")
        return False


def send_sms(body: str) -> bool:
    """Send SMS via Twilio (credentials from .env). Returns True on success."""
    account_sid = os.getenv("TWILIO_ACCOUNT_SID", "")
    auth_token = os.getenv("TWILIO_AUTH_TOKEN", "")
    from_number = os.getenv("TWILIO_FROM", "")
    to_number = os.getenv("ALERT_SMS_TO", "")

    if not all([account_sid, auth_token, from_number, to_number]):
        logger.warning("SMS not configured — Twilio credentials not set")
        return False

    try:
        from twilio.rest import Client
        client = Client(account_sid, auth_token)
        client.messages.create(body=body[:160], from_=from_number, to=to_number)
        return True
    except ImportError:
        logger.warning("twilio package not installed — SMS unavailable")
        return False
    except Exception as exc:
        logger.error(f"SMS send failed: {exc}")
        return False
