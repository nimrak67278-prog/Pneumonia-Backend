"""
Temporary storage for signups that are waiting for their OTP.

No Supabase Auth user or profile row exists until the OTP is verified.
The password is stored encrypted (Fernet).

A pending signup is deleted:
  - as soon as the account is created
  - when its OTP expires (OTP_EXPIRE_MINUTES, default 5)
  - after too many wrong code attempts
  - if the verification email could not be sent
Expired rows are also purged on every signup / verify / resend request.
"""

import base64
import hashlib
import os
import time

from cryptography.fernet import Fernet

from app.utils.supabase_client import supabase

OTP_EXPIRE_SECONDS = int(os.getenv("OTP_EXPIRE_MINUTES", "5")) * 60
MAX_PENDING_LIFETIME_SECONDS = 15 * 60   # absolute cap, even with resends
CERT_BUCKET = "doctor-certificates"


def _fernet() -> Fernet:
    secret = os.getenv("OTP_SECRET")
    if not secret:
        raise RuntimeError("OTP_SECRET is not set.")
    key = base64.urlsafe_b64encode(hashlib.sha256(f"pending:{secret}".encode()).digest())
    return Fernet(key)


def encrypt_password(password: str) -> str:
    return _fernet().encrypt(password.encode()).decode()


def decrypt_password(token: str) -> str:
    return _fernet().decrypt(token.encode()).decode()


def _remove_certificate(payload: dict | None):
    path = (payload or {}).get("certificate_path")
    if path:
        try:
            supabase.storage.from_(CERT_BUCKET).remove([path])
        except Exception:
            pass


def _fetch(email: str):
    result = (
        supabase.table("pending_signups")
        .select("*")
        .eq("email", email)
        .limit(1)
        .execute()
    )
    return result.data[0] if result.data else None


def delete_pending(email: str, remove_certificate: bool = True):
    """remove_certificate=False once a doctor account has been created,
    because the certificate file is then in use."""
    row = _fetch(email)
    if not row:
        return
    if remove_certificate:
        _remove_certificate(row.get("payload"))
    supabase.table("pending_signups").delete().eq("id", row["id"]).execute()


def get_pending(email: str):
    """Returns the pending signup, or None. An expired one is deleted."""
    row = _fetch(email)
    if not row:
        return None
    if row["expires_at"] < int(time.time()):
        delete_pending(email)
        return None
    return row


def save_pending(email: str, role: str, payload: dict, password: str):
    delete_pending(email)  # a new attempt replaces any older one
    now = int(time.time())
    supabase.table("pending_signups").insert(
        {
            "email": email,
            "role": role,
            "payload": payload,
            "enc_password": encrypt_password(password),
            "created_at": now,
            "expires_at": now + OTP_EXPIRE_SECONDS,
        }
    ).execute()


def extend_pending(row: dict):
    """Called when a new code is sent. Extends the deadline, but never past
    MAX_PENDING_LIFETIME_SECONDS from the original request."""
    now = int(time.time())
    new_expiry = min(now + OTP_EXPIRE_SECONDS, row["created_at"] + MAX_PENDING_LIFETIME_SECONDS)
    supabase.table("pending_signups").update({"expires_at": new_expiry}).eq(
        "id", row["id"]
    ).execute()


def purge_expired():
    now = int(time.time())
    old = (
        supabase.table("pending_signups")
        .select("id, payload")
        .lt("expires_at", now)
        .execute()
    )
    for row in old.data or []:
        _remove_certificate(row.get("payload"))
        supabase.table("pending_signups").delete().eq("id", row["id"]).execute()