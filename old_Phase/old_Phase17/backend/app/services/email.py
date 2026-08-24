"""
Sends real email via Resend when RESEND_API_KEY is configured; falls
back to logging the would-be email to the server console when it isn't
(every test, CI run, and local dev session without a key). This
fallback is deliberate, not a leftover - the whole point is that the
app, the test suite, and CI all keep working identically whether or not
a real provider is wired up.

Sends from Resend's shared onboarding@resend.dev address - no custom
domain verification required to get this working. The tradeoff: without
domain verification, Resend only delivers to the email address you used
to create your Resend account (see Resend's own docs on this). Fine for
now; verifying a real domain later is a dashboard change on Resend's
side, nothing here needs to change.
"""
import logging

import httpx

from app.core.config import settings

logger = logging.getLogger("erp.email")

RESEND_API_URL = "https://api.resend.com/emails"
FROM_ADDRESS = "Base ERP <onboarding@resend.dev>"


def send_email(to: str, subject: str, body: str) -> None:
    if not settings.RESEND_API_KEY:
        logger.warning(
            "\n"
            "==================== EMAIL NOT ACTUALLY SENT (no RESEND_API_KEY configured) ====================\n"
            f"To: {to}\n"
            f"Subject: {subject}\n"
            f"{body}\n"
            "==================================================================================================="
        )
        return

    html_body = body.replace("\n", "<br>")
    try:
        response = httpx.post(
            RESEND_API_URL,
            headers={"Authorization": f"Bearer {settings.RESEND_API_KEY}"},
            json={"from": FROM_ADDRESS, "to": [to], "subject": subject, "html": html_body},
            timeout=10.0,
        )
        if response.status_code >= 400:
            # Never let a provider-side failure (bad key, rate limit,
            # unverified recipient) break the actual business action -
            # same soft-fail philosophy as notify_user()/notify_role()
            # in app/services/notifications.py. The caller already
            # returns a generic "if that email exists..." response
            # regardless of whether the send worked, so this failing
            # doesn't change what the user sees - it just means the
            # link never arrives, which is diagnosable here in the logs.
            logger.error(f"Resend API returned {response.status_code} sending to {to}: {response.text}")
        else:
            logger.info(f"Email sent via Resend to {to}: {subject!r} (id={response.json().get('id')})")
    except Exception as e:
        logger.error(f"Failed to send email via Resend to {to}: {e}")


def send_password_reset_email(to: str, raw_token: str) -> None:
    reset_link = f"{settings.FRONTEND_URL}/reset-password?token={raw_token}"
    send_email(
        to=to,
        subject="Reset your password",
        body=f"Click here to reset your password (expires in 1 hour):\n{reset_link}",
    )


def send_verification_email(to: str, raw_token: str) -> None:
    verify_link = f"{settings.FRONTEND_URL}/verify-email?token={raw_token}"
    send_email(
        to=to,
        subject="Verify your email",
        body=f"Click here to verify your email (expires in 24 hours):\n{verify_link}",
    )


def send_invite_email(to: str, org_name: str, raw_token: str) -> None:
    accept_link = f"{settings.FRONTEND_URL}/accept-invite?token={raw_token}"
    send_email(
        to=to,
        subject=f"You've been invited to join {org_name}",
        body=f"You've been invited to join {org_name}. Click here to set up your account "
             f"(expires in 7 days):\n{accept_link}",
    )
