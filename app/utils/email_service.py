"""
Sends OTP emails through Brevo's HTTPS API (port 443).

Do NOT switch this to SMTP: Railway blocks outbound SMTP on
Free/Trial/Hobby plans, but normal HTTPS requests work fine.
"""

import os
import httpx

BREVO_URL = "https://api.brevo.com/v3/smtp/email"


class EmailSendError(Exception):
    pass


def send_otp_email(to_email: str, code: str, purpose: str) -> None:
    api_key = os.getenv("BREVO_API_KEY")
    sender_email = os.getenv("BREVO_SENDER_EMAIL")
    sender_name = os.getenv("BREVO_SENDER_NAME", "PneumoScan")
    expire_minutes = os.getenv("OTP_EXPIRE_MINUTES", "5")

    if not api_key or not sender_email:
        raise EmailSendError("Email service is not configured.")

    if purpose == "reset":
        subject = f"{sender_name} password reset code"
        intro = "Use this code to reset your password:"
    else:
        subject = f"{sender_name} email verification code"
        intro = "Use this code to verify your email address:"

    html = f"""
    <div style="font-family:Arial,sans-serif;max-width:480px;margin:auto;padding:24px">
      <h2 style="margin:0 0 12px">{sender_name}</h2>
      <p>{intro}</p>
      <p style="font-size:32px;font-weight:bold;letter-spacing:6px;margin:16px 0">{code}</p>
      <p>This code expires in {expire_minutes} minutes. If you didn't request it,
      you can safely ignore this email.</p>
    </div>
    """

    payload = {
        "sender": {"name": sender_name, "email": sender_email},
        "to": [{"email": to_email}],
        "subject": subject,
        "htmlContent": html,
    }

    try:
        response = httpx.post(
            BREVO_URL,
            headers={
                "api-key": api_key,
                "accept": "application/json",
                "content-type": "application/json",
            },
            json=payload,
            timeout=10.0,
        )
    except httpx.HTTPError as e:
        raise EmailSendError("Could not reach the email service.") from e

    if response.status_code not in (200, 201, 202):
        raise EmailSendError(
            f"Brevo returned {response.status_code}: {response.text[:200]}"
        )