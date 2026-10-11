"""
OTP endpoints:
  POST /auth/verify-otp      -> checks the code, THEN creates the account
  POST /auth/resend-otp      -> new signup code for a pending signup
  POST /auth/forgot-password -> emails a reset code
  POST /auth/reset-password  -> checks the code and sets a new password
"""

import logging
import time
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, EmailStr, Field

from app.utils.supabase_client import supabase, get_fresh_admin_client
from app.utils.otp import verify_otp, send_new_otp, otp_is_dead, delete_otp
from app.utils.email_service import EmailSendError
from app.utils.pending import (
    get_pending,
    delete_pending,
    decrypt_password,
    extend_pending,
    purge_expired,
    MAX_PENDING_LIFETIME_SECONDS,
)
from app.utils.push_notifications import notify_all_admins

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["otp"])

GENERIC_SENT = "If this email is registered, a code has been sent."
EMAIL_FAIL_MSG = (
    "Something went wrong while sending the verification code. "
    "Please check your email address and try again."
)
SIGNUP_EXPIRED_MSG = "Your signup has expired. Please sign up again."


class EmailRequest(BaseModel):
    email: EmailStr


class VerifyOtpRequest(BaseModel):
    email: EmailStr
    code: str = Field(min_length=6, max_length=6)


class ResetPasswordRequest(BaseModel):
    email: EmailStr
    code: str = Field(min_length=6, max_length=6)
    new_password: str = Field(min_length=8)


def _get_user(email: str):
    result = (
        supabase.table("users").select("id").eq("email", email).limit(1).execute()
    )
    return result.data[0] if result.data else None


def _create_account(pending: dict) -> str:
    """Creates the Supabase Auth user and profile rows from a pending signup."""
    email = pending["email"]
    role = pending["role"]
    data = pending["payload"]
    password = decrypt_password(pending["enc_password"])

    try:
        auth_response = get_fresh_admin_client().auth.admin.create_user(
            {"email": email, "password": password, "email_confirm": True}
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Signup failed: {str(e)}")

    user_id = auth_response.user.id

    try:
        supabase.table("users").insert(
            {
                "id": user_id,
                "email": email,
                "full_name": data["full_name"],
                "role": role,
            }
        ).execute()

        if role == "patient":
            supabase.table("patients").insert(
                {"id": user_id, "mobile_number": data["mobile_number"]}
            ).execute()
        else:
            supabase.table("doctors").insert(
                {
                    "id": user_id,
                    "specialization": data["specialization"],
                    "hospital": data["hospital"],
                    "license_number": data["license_number"],
                    "certificate_url": data["certificate_path"],
                    "verification_status": "pending",
                }
            ).execute()
    except Exception as e:
        # Undo everything so no half-created account is left behind
        supabase.table("patients").delete().eq("id", user_id).execute()
        supabase.table("doctors").delete().eq("id", user_id).execute()
        supabase.table("users").delete().eq("id", user_id).execute()
        get_fresh_admin_client().auth.admin.delete_user(user_id)
        raise HTTPException(status_code=400, detail=f"Profile creation failed: {str(e)}")

    return user_id


@router.post("/verify-otp")
def verify_signup_otp(payload: VerifyOtpRequest):
    email = payload.email.lower()
    purge_expired()

    pending = get_pending(email)
    if not pending:
        raise HTTPException(status_code=400, detail=SIGNUP_EXPIRED_MSG)

    if not verify_otp(email, "signup", payload.code):
        # Code expired or too many wrong tries: throw the held data away now
        if otp_is_dead(email, "signup"):
            delete_pending(email)
            delete_otp(email, "signup")
            raise HTTPException(
                status_code=400,
                detail="The code expired or had too many wrong attempts. Please sign up again.",
            )
        raise HTTPException(status_code=400, detail="Incorrect code. Please try again.")

    # The code is correct: only NOW is the real account created.
    user_id = _create_account(pending)
    delete_pending(email, remove_certificate=False)

    if pending["role"] == "doctor":
        try:
            notify_all_admins(
                title="New Doctor Signup",
                body=f"Dr. {pending['payload'].get('full_name', '')} has registered and is awaiting certificate verification.",
                data={"type": "doctor_pending", "doctor_id": user_id},
            )
        except Exception:
            logger.exception("Failed to notify admins about new doctor")

    if pending["role"] == "doctor":
        message = (
            "Email verified. Your account has been created and is pending "
            "approval. An admin will review your certificate before you can "
            "accept patient requests."
        )
    else:
        message = "Email verified. Your account has been created. You can now log in."

    return {"message": message, "user_id": user_id, "role": pending["role"]}


@router.post("/resend-otp")
def resend_signup_otp(payload: EmailRequest):
    email = payload.email.lower()
    purge_expired()

    pending = get_pending(email)
    if not pending or int(time.time()) - pending["created_at"] > MAX_PENDING_LIFETIME_SECONDS:
        delete_pending(email)
        delete_otp(email, "signup")
        raise HTTPException(status_code=400, detail=SIGNUP_EXPIRED_MSG)

    try:
        result = send_new_otp(email, "signup")
    except EmailSendError as e:
        logger.error("Resend OTP failed: %s", e)
        delete_pending(email)
        delete_otp(email, "signup")
        raise HTTPException(status_code=502, detail=EMAIL_FAIL_MSG)

    if result == "cooldown":
        raise HTTPException(
            status_code=429,
            detail="Please wait a minute before requesting another code.",
        )

    extend_pending(pending)
    return {"message": "We sent a new verification code to your email."}


@router.post("/forgot-password")
def forgot_password(payload: EmailRequest):
    email = payload.email.lower()

    if _get_user(email):
        try:
            send_new_otp(email, "reset")
        except EmailSendError as e:
            # Logged for you; the response stays generic.
            logger.error("Reset OTP failed: %s", e)
    return {"message": GENERIC_SENT}


@router.post("/reset-password")
def reset_password(payload: ResetPasswordRequest):
    email = payload.email.lower()

    if not verify_otp(email, "reset", payload.code):
        raise HTTPException(status_code=400, detail="Invalid or expired code.")

    user = _get_user(email)
    if not user:
        raise HTTPException(status_code=400, detail="Invalid or expired code.")

    try:
        get_fresh_admin_client().auth.admin.update_user_by_id(
            user["id"], {"password": payload.new_password}
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Could not update password: {str(e)}")

    return {"message": "Password updated. You can now log in."}