"""
OTP endpoints: verify signup, resend code, forgot password, reset password.
"""

import logging
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, EmailStr, Field

from app.utils.supabase_client import supabase, get_fresh_admin_client
from app.utils.otp import verify_otp, send_new_otp
from app.utils.email_service import EmailSendError
from app.utils.push_notifications import notify_all_admins

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["otp"])

GENERIC_SENT = "If this email is registered, a code has been sent."


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
        supabase.table("users")
        .select("id, email_verified, role, full_name")
        .eq("email", email)
        .limit(1)
        .execute()
    )
    return result.data[0] if result.data else None


@router.post("/verify-otp")
def verify_signup_otp(payload: VerifyOtpRequest):
    email = payload.email.lower()
    if not verify_otp(email, "signup", payload.code):
        raise HTTPException(status_code=400, detail="Invalid or expired code.")

    supabase.table("users").update({"email_verified": True}).eq("email", email).execute()

    # Doctors still need admin approval, so alert admins only once the
    # doctor's email is confirmed (not for every unverified signup).
    user = _get_user(email)
    if user and user.get("role") == "doctor":
        try:
            notify_all_admins(
                title="New Doctor Signup",
                body=f"Dr. {user.get('full_name', '')} has registered and is awaiting certificate verification.",
                data={"type": "doctor_pending", "doctor_id": user["id"]},
            )
        except Exception:
            logger.exception("Failed to notify admins about new doctor")

    return {"message": "Email verified. You can now log in."}


@router.post("/resend-otp")
def resend_signup_otp(payload: EmailRequest):
    email = payload.email.lower()
    user = _get_user(email)

    # Only unverified accounts get a signup code; the response is the same
    # either way so this can't be used to discover registered emails.
    if user and user.get("email_verified") is False:
        try:
            send_new_otp(email, "signup")
        except EmailSendError:
            logger.exception("Brevo failed while resending signup OTP")
            raise HTTPException(
                status_code=502,
                detail="Couldn't send the code right now. Please try again.",
            )
    return {"message": GENERIC_SENT}


@router.post("/forgot-password")
def forgot_password(payload: EmailRequest):
    email = payload.email.lower()
    user = _get_user(email)

    if user:
        try:
            send_new_otp(email, "reset")
        except EmailSendError:
            # Logged for you, but the response stays generic.
            logger.exception("Brevo failed while sending reset OTP")
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

    # They just proved they own this email
    supabase.table("users").update({"email_verified": True}).eq("id", user["id"]).execute()
    return {"message": "Password updated. You can now log in."}