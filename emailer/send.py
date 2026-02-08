"""Email dispatch via SMTP – supports DRY_RUN mode."""

from __future__ import annotations

import logging
import os
import smtplib
from email.message import EmailMessage

log = logging.getLogger(__name__)


def _env(key: str, default: str | None = None) -> str:
    val = os.getenv(key, default)
    if val is None:
        raise RuntimeError(f"Missing required env var: {key}")
    return val


def send_brief(subject: str, body: str, dry_run: bool = False) -> None:
    """Send (or print) the daily brief email.

    Required env vars (unless *dry_run* is True):
      SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD,
      EMAIL_FROM, EMAIL_TO
    """
    email_to = os.getenv("EMAIL_TO", "user@example.com")
    email_from = os.getenv("EMAIL_FROM", "world-brief@example.com")

    if dry_run:
        log.info("DRY_RUN – printing email instead of sending")
        separator = "=" * 72
        print(separator)
        print(f"From: {email_from}")
        print(f"To:   {email_to}")
        print(f"Subject: {subject}")
        print(separator)
        print(body)
        print(separator)
        return

    # Build message
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = email_from
    msg["To"] = email_to
    msg.set_content(body)

    # SMTP settings
    host = _env("SMTP_HOST")
    port = int(_env("SMTP_PORT", "587"))
    user = _env("SMTP_USER")
    password = _env("SMTP_PASSWORD")
    use_tls = os.getenv("SMTP_USE_TLS", "true").lower() in ("true", "1", "yes")

    log.info("Sending email to %s via %s:%d", email_to, host, port)
    try:
        if use_tls:
            with smtplib.SMTP(host, port) as server:
                server.ehlo()
                server.starttls()
                server.ehlo()
                server.login(user, password)
                server.send_message(msg)
        else:
            with smtplib.SMTP(host, port) as server:
                server.login(user, password)
                server.send_message(msg)
        log.info("Email sent successfully")
    except Exception:
        log.exception("Failed to send email")
        raise
