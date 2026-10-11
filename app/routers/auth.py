"""
Authentication endpoints.

Patient signup is a simple JSON request. Doctor signup is different --
it accepts multipart form data because doctors must upload a degree
certificate image, which then needs manual admin verification before
the doctor account is treated as active (see verification_status).
"""

import uuid
from app.utils.supabase_client import supabase, supabase_auth
from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from pydantic import BaseModel, EmailStr
from app.utils.supabase_client import supabase, supabase_auth, get_fresh_admin_client
from app.utils.otp import send_new_otp
from app.utils.email_service import EmailSendError
from pydantic import BaseModel, EmailStr, Field
from app.utils.otp import verify_otp
from app.utils.otp import send_new_otp
from app.utils.email_service import EmailSendError
from app.utils.pending import save_pending, delete_pending, purge_expired
from app.utils.otp import delete_otp

router = APIRouter(prefix="/auth", tags=["auth"])

ALLOWED_CERT_TYPES = {"image/jpeg", "image/jpg", "image/png", "application/pdf"}
MAX_CERT_SIZE_MB = 10


class PatientSignupRequest(BaseModel):
    email: EmailStr
    password: str
    full_name: str
    mobile_number: str



class LoginRequest(BaseModel):
    email: EmailStr
    password: str

EMAIL_FAIL_MSG = (
    "Something went wrong while sending the verification code. "
    "Please check your email address and try again."
)


def _ensure_email_free(email: str):
    existing = supabase.table("users").select("id").eq("email", email).limit(1).execute()
    if existing.data:
        raise HTTPException(status_code=400, detail="An account with this email already exists.")


def _send_signup_otp_or_fail(email: str):
    """Sends the code. If it fails, the held details are deleted at once."""
    try:
        result = send_new_otp(email, "signup")
    except EmailSendError as e:
        print(f"OTP email failed: {e}")   # real reason shows in Railway logs
        delete_pending(email)
        delete_otp(email, "signup")
        raise HTTPException(status_code=502, detail=EMAIL_FAIL_MSG)
    if result == "cooldown":
        raise HTTPException(
            status_code=429,
            detail="A code was already sent. Please wait a minute before requesting another.",
        )
@router.post("/signup/patient")
def signup_patient(payload: PatientSignupRequest):
    email = payload.email.lower()

    purge_expired()
    _ensure_email_free(email)

    # Nothing is created yet: details are held until the OTP is verified
    save_pending(
        email,
        "patient",
        {"full_name": payload.full_name, "mobile_number": payload.mobile_number},
        payload.password,
    )
    _send_signup_otp_or_fail(email)

    return {
        "message": "We sent a verification code to your email. Enter it to finish creating your account.",
        "email": email,
        "requires_verification": True,
    }

@router.post("/signup/doctor")
async def signup_doctor(
    email: EmailStr = Form(...),
    password: str = Form(...),
    full_name: str = Form(...),
    specialization: str = Form(...),
    hospital: str = Form(...),
    license_number: str = Form(...),
    certificate: UploadFile = File(...),
):
    email = email.lower()

    # --- Validate the certificate file (same as before) ---
    if certificate.content_type not in ALLOWED_CERT_TYPES:
        raise HTTPException(
            status_code=400,
            detail="Certificate must be a JPEG, PNG, or PDF file.",
        )

    cert_bytes = await certificate.read()
    size_mb = len(cert_bytes) / (1024 * 1024)
    if size_mb > MAX_CERT_SIZE_MB:
        raise HTTPException(
            status_code=400,
            detail=f"Certificate file too large ({size_mb:.1f} MB). Max is {MAX_CERT_SIZE_MB} MB.",
        )

    purge_expired()
    _ensure_email_free(email)

    # Upload the certificate to a temporary "pending" folder
    file_ext = certificate.filename.split(".")[-1]
    cert_path = f"pending/{uuid.uuid4().hex}/certificate_{uuid.uuid4().hex}.{file_ext}"
    try:
        supabase.storage.from_("doctor-certificates").upload(
            cert_path,
            cert_bytes,
            {"content-type": certificate.content_type},
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Certificate upload failed: {str(e)}")

    # Nothing is created yet: details are held until the OTP is verified
    try:
        save_pending(
            email,
            "doctor",
            {
                "full_name": full_name,
                "specialization": specialization,
                "hospital": hospital,
                "license_number": license_number,
                "certificate_path": cert_path,
            },
            password,
        )
    except Exception:
        try:
            supabase.storage.from_("doctor-certificates").remove([cert_path])
        except Exception:
            pass
        raise HTTPException(status_code=400, detail="Something went wrong. Please try again.")

    _send_signup_otp_or_fail(email)

    return {
        "message": "We sent a verification code to your email. Enter it to finish creating your account. "
                   "Your certificate will then be reviewed by an admin.",
        "email": email,
        "requires_verification": True,
    }

def _fetch_single(query):
    """Runs a Supabase query and returns the first matching row's data,
    or None if there are no matches. Deliberately avoids .single()/
    .maybe_single() -- some client versions return None even when a
    matching row exists, due to a content-negotiation quirk with
    PostgREST. A plain list query + manual pick is more reliable."""
    response = query.execute()
    if not response.data:
        return None
    return response.data[0]


@router.post("/login")
def login(payload: LoginRequest):
    try:
        
       
        auth_response = supabase_auth.auth.sign_in_with_password(
            {"email": payload.email, "password": payload.password}
        )
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid email or password.")

    profile_data = _fetch_single(
        supabase.table("users").select("*").eq("id", auth_response.user.id)
    )

    if profile_data is None:
        raise HTTPException(
            status_code=404,
            detail="No profile found for this account. Please contact support.",
        )
    if profile_data.get("email_verified") is False:
        raise HTTPException(
            status_code=403,
            detail="EMAIL_NOT_VERIFIED",
        )

    result = {
        "access_token": auth_response.session.access_token,
        "user_id": auth_response.user.id,
        "profile": profile_data,
    }

    if profile_data.get("role") == "doctor":
        result["doctor_profile"] = _fetch_single(
            supabase.table("doctors").select("*").eq("id", auth_response.user.id)
        )

    if profile_data.get("role") == "patient":
        result["patient_profile"] = _fetch_single(
            supabase.table("patients").select("*").eq("id", auth_response.user.id)
        )

    return result
