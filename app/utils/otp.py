"""
OTP generation, hashed storage, and verification.

- Codes are 6 digits, stored only as an HMAC-SHA256 hash (keyed with OTP_SECRET).
- Each code expires after OTP_EXPIRE_MINUTES and allows MAX_ATTEMPTS guesses.
- A new code can only be issued every RESEND_COOLDOWN_SECONDS per email/purpose.
"""

import hashlib
import hmac
import os
import secrets
import time

from app.utils.supabase_client import supabase
from app.utils.email_service import send_otp_email

OTP_LENGTH = 6
OTP_EXPIRE_SECONDS = int(os.getenv("OTP_EXPIRE_MINUTES", "5")) * 60
MAX_ATTEMPTS = 5
RESEND_COOLDOWN_SECONDS = 60


def _hash(email: str, purpose: str, code: str) -> str:
    secret = os.getenv("OTP_SECRET")
    if not secret:
        raise RuntimeError("OTP_SECRET is not set.")
    message = f"{email}:{purpose}:{code}".encode()
    return hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()


def create_otp(email: str, purpose: str) -> str | None:
    """Creates and stores a new OTP. Returns the plain code, or None if the
    resend cooldown hasn't passed yet."""
    email = email.lower().strip()
    now = int(time.time())

    latest = (
        supabase.table("otp_codes")
        .select("created_at")
        .eq("email", email)
        .eq("purpose", purpose)
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    if latest.data and now - latest.data[0]["created_at"] < RESEND_COOLDOWN_SECONDS:
        return None

    # Only one active code per email/purpose
    supabase.table("otp_codes").delete().eq("email", email).eq("purpose", purpose).execute()

    code = "".join(secrets.choice("0123456789") for _ in range(OTP_LENGTH))
    supabase.table("otp_codes").insert(
        {
            "email": email,
            "purpose": purpose,
            "code_hash": _hash(email, purpose, code),
            "attempts": 0,
            "created_at": now,
            "expires_at": now + OTP_EXPIRE_SECONDS,
        }
    ).execute()
    return code


def verify_otp(email: str, purpose: str, code: str) -> bool:
    """True only if the code is correct, unexpired, and within the attempt limit.
    A successful check deletes the code so it can't be reused."""
    email = email.lower().strip()
    result = (
        supabase.table("otp_codes")
        .select("*")
        .eq("email", email)
        .eq("purpose", purpose)
        .limit(1)
        .execute()
    )
    if not result.data:
        return False

    row = result.data[0]
    now = int(time.time())

    # Expired or out of attempts: keep the row (so the resend cooldown still
    # applies) but reject.
    if row["expires_at"] < now or row["attempts"] >= MAX_ATTEMPTS:
        return False

    supabase.table("otp_codes").update({"attempts": row["attempts"] + 1}).eq(
        "id", row["id"]
    ).execute()

    if not hmac.compare_digest(row["code_hash"], _hash(email, purpose, code)):
        return False

    supabase.table("otp_codes").delete().eq("id", row["id"]).execute()
    return True


def send_new_otp(email: str, purpose: str) -> str:
    """Creates an OTP and emails it. Returns 'sent' or 'cooldown'.
    Raises EmailSendError if Brevo fails."""
    code = create_otp(email, purpose)
    if code is None:
        return "cooldown"
    send_otp_email(email.lower().strip(), code, purpose)
    return "sent"


def otp_is_dead(email: str, purpose: str) -> bool:
    """True if there is no usable code left: missing, expired, or out of attempts."""
    email = email.lower().strip()
    result = (
        supabase.table("otp_codes")
        .select("attempts, expires_at")
        .eq("email", email)
        .eq("purpose", purpose)
        .limit(1)
        .execute()
    )
    if not result.data:
        return True
    row = result.data[0]
    return row["expires_at"] < int(time.time()) or row["attempts"] >= MAX_ATTEMPTS


def delete_otp(email: str, purpose: str) -> None:
    supabase.table("otp_codes").delete().eq("email", email.lower().strip()).eq(
        "purpose", purpose
    ).execute()