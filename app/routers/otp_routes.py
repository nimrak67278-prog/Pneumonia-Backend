"""
OTP endpoints:
  POST /auth/send-signup-otp -> emails a code to a NEW email (no account is created)
  POST /auth/forgot-password -> emails a reset code to an existing account
  POST /auth/reset-password  -> checks the code and sets a new password

The signup endpoints themselves (/auth/signup/patient and /auth/signup/doctor,
in auth.py) check the code and create the account in one step.
"""

import logging
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, EmailStr, Field

from app.utils.supabase_client import supabase, get_fresh_admin_client
from app.utils.otp import verify_otp, send_new_otp
from app.utils.email_service import EmailSendError

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["otp"])

GENERIC_SENT = "If this email is registered, a code has been sent."
EMAIL_FAIL_MSG = (
    "Something went wrong while sending the verification code. "
    "Please check your email address and try again."
)


class EmailRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    email: EmailStr
    code: str = Field(min_length=6, max_length=6)
    new_password: str = Field(min_length=8)


def _get_user(email: str):
    result = (
        supabase.table("users").select("id").eq("email", email).limit(1).execute()
    )
    return result.data[0] if result.data else None


@router.post("/send-signup-otp")
def send_signup_otp(payload: EmailRequest):
    """Step 1 of signup. Creates nothing; it only emails a code."""
    email = payload.email.lower()

    if _get_user(email):
        raise HTTPException(
            status_code=400, detail="An account with this email already exists."
        )

    try:
        result = send_new_otp(email, "signup")
    except EmailSendError as e:
        logger.error("Signup OTP email failed: %s", e)
        # Remove the unsent code so the user can retry immediately
        supabase.table("otp_codes").delete().eq("email", email).eq(
            "purpose", "signup"
        ).execute()
        raise HTTPException(status_code=502, detail=EMAIL_FAIL_MSG)

    if result == "cooldown":
        raise HTTPException(
            status_code=429,
            detail="Please wait a minute before requesting another code.",
        )

    return {"message": "We sent a verification code to your email."}


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