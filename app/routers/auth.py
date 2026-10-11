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
from app.utils.push_notifications import notify_all_admins
from app.utils.otp import send_new_otp
from app.utils.email_service import EmailSendError

router = APIRouter(prefix="/auth", tags=["auth"])

ALLOWED_CERT_TYPES = {"image/jpeg", "image/jpg", "image/png", "application/pdf"}
MAX_CERT_SIZE_MB = 10


class PatientSignupRequest(BaseModel):
    email: EmailStr
    password: str
    full_name: str
    mobile_number: str          # <- added



class LoginRequest(BaseModel):
    email: EmailStr
    password: str


@router.post("/signup/patient")
def signup_patient(payload: PatientSignupRequest):
    email = payload.email.lower()

    # 1. Create the Supabase Auth user
    try:
        auth_response = get_fresh_admin_client().auth.admin.create_user(
            {
                "email": email,
                "password": payload.password,
                "email_confirm": True,
            }
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Signup failed: {str(e)}")

    user_id = auth_response.user.id

    # 2. Insert the profile rows (email_verified starts False)
    try:
        supabase.table("users").insert(
            {
                "id": user_id,
                "email": email,
                "full_name": payload.full_name,
                "role": "patient",
                "email_verified": False,
            }
        ).execute()

        supabase.table("patients").insert(
            {
                "id": user_id,
                "mobile_number": payload.mobile_number,
            }
        ).execute()
    except Exception as e:
        get_fresh_admin_client().auth.admin.delete_user(user_id)
        raise HTTPException(status_code=400, detail=f"Profile creation failed: {str(e)}")

    # 3. Email the verification code
    try:
        send_new_otp(email, "signup")
    except EmailSendError:
        raise HTTPException(
            status_code=502,
            detail="Account created, but we couldn't send the code. Tap 'Resend code'.",
        )

    return {
        "message": "Account created. Enter the code we emailed you.",
        "user_id": user_id,
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
    # --- Validate the certificate file ---
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
    email = email.lower()

    # 1. Create the Supabase Auth user
    try:
        auth_response = get_fresh_admin_client().auth.admin.create_user(
            {
                "email": email,
                "password": password,
                "email_confirm": True,
            }
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Signup failed: {str(e)}")

    user_id = auth_response.user.id

    # 2. Upload the certificate to Storage, under a folder named by user_id
    file_ext = certificate.filename.split(".")[-1]
    storage_path = f"{user_id}/certificate_{uuid.uuid4().hex}.{file_ext}"

    try:
        supabase.storage.from_("doctor-certificates").upload(
            storage_path,
            cert_bytes,
            {"content-type": certificate.content_type},
        )
    except Exception as e:
        get_fresh_admin_client().auth.admin.delete_user(user_id)
        raise HTTPException(status_code=400, detail=f"Certificate upload failed: {str(e)}")

    # 3. Insert profile + doctor rows
    try:
        supabase.table("users").insert(
            {
                "id": user_id,
                "email": email,
                "full_name": full_name,
                "role": "doctor",
                "email_verified": False,

            }
        ).execute()

        supabase.table("doctors").insert(
            {
                "id": user_id,
                "specialization": specialization,
                "hospital": hospital,
                "license_number": license_number,
                "certificate_url": storage_path,
                "verification_status": "pending",
            }
        ).execute()
    except Exception as e:
        get_fresh_admin_client().auth.admin.delete_user(user_id)
        raise HTTPException(status_code=400, detail=f"Profile creation failed: {str(e)}")
        # Email the verification code. Admins are notified after the doctor
    # verifies their email (done in /auth/verify-otp).
    try:
        send_new_otp(email, "signup")
    except EmailSendError:
        raise HTTPException(
            status_code=502,
            detail="Account created, but we couldn't send the code. Tap 'Resend code'.",
        )

    return {
        "message": "Account created. Enter the code we emailed you. "
                   "Your certificate will then be reviewed by an admin.",
        "user_id": user_id,
        "verification_status": "pending",
        "requires_verification": True,
    }

    return {
        "message": (
            "Doctor account created successfully. Your certificate is "
            "pending verification before you can accept patient requests."
        ),
        "user_id": user_id,
        "verification_status": "pending",
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