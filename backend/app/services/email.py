"""
No outbound email provider is configured anywhere in this codebase (no
SMTP, SendGrid, Resend, SES — nothing). Rather than either skip password
reset/email verification entirely, or silently fail as if email was
sent when it wasn't, this logs the would-be email clearly to the server
console — good enough to actually test the reset/verify flows end-to-end
in dev, and an honest placeholder in production logs (visible in Render's
Logs tab) rather than a silent black hole.

To wire in a real provider later: replace the body of send_email() with
an actual API call (Resend and SendGrid both have generous free tiers
and a five-line Python integration) — nothing else in the app needs to
change, every caller already goes through this one function.
"""
import logging

logger = logging.getLogger("erp.email")


def send_email(to: str, subject: str, body: str) -> None:
    logger.warning(
        "\n"
        "==================== EMAIL NOT ACTUALLY SENT (no provider configured) ====================\n"
        f"To: {to}\n"
        f"Subject: {subject}\n"
        f"{body}\n"
        "==========================================================================================="
    )


def send_password_reset_email(to: str, raw_token: str, frontend_url: str = "http://localhost:3000") -> None:
    reset_link = f"{frontend_url}/reset-password?token={raw_token}"
    send_email(
        to=to,
        subject="Reset your password",
        body=f"Click here to reset your password (expires in 1 hour):\n{reset_link}",
    )


def send_verification_email(to: str, raw_token: str, frontend_url: str = "http://localhost:3000") -> None:
    verify_link = f"{frontend_url}/verify-email?token={raw_token}"
    send_email(
        to=to,
        subject="Verify your email",
        body=f"Click here to verify your email (expires in 24 hours):\n{verify_link}",
    )
