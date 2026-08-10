"""
Doctor module endpoints -- lets a logged-in, verified doctor manage
their own profile (basic info, professional info, consultation
settings) and their weekly availability (a working time range per day,
toggled on/off).

Every endpoint checks role == 'doctor' via the token -- a doctor can
only ever view/edit their own data, never another doctor's.
"""

from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from pydantic import BaseModel

from app.utils.supabase_client import supabase
from app.utils.auth import get_current_user_id

router = APIRouter(prefix="/doctor", tags=["doctor"])

ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/jpg", "image/png"}
MAX_IMAGE_SIZE_MB = 5

VALID_DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


def _require_doctor(user_id: str) -> dict:
    user_response = supabase.table("users").select("*").eq("id", user_id).execute()
    if not user_response.data:
        raise HTTPException(status_code=404, detail="Profile not found.")
    if user_response.data[0].get("role") != "doctor":
        raise HTTPException(status_code=403, detail="This account is not a doctor account.")
    return user_response.data[0]


class UpdateDoctorProfileRequest(BaseModel):
    # Basic info
    full_name: Optional[str] = None
    specialization: Optional[str] = None
    hospital: Optional[str] = None
    mobile_number: Optional[str] = None
    # Professional info
    qualifications: Optional[str] = None
    experience_years: Optional[int] = None
    languages: Optional[str] = None
    about_text: Optional[str] = None
    # Consultation settings
    video_enabled: Optional[bool] = None
    video_fee: Optional[float] = None
    video_duration_minutes: Optional[int] = None
    voice_enabled: Optional[bool] = None
    voice_fee: Optional[float] = None
    voice_duration_minutes: Optional[int] = None


class DaySchedule(BaseModel):
    day_of_week: str
    is_active: bool
    start_time: Optional[str] = None  # "09:00"
    end_time: Optional[str] = None    # "17:00"


class SaveAvailabilityRequest(BaseModel):
    days: List[DaySchedule]


# --- Profile ---

@router.get("/profile")
def get_doctor_profile(user_id: str = Depends(get_current_user_id)):
    user_data = _require_doctor(user_id)

    doctor_response = supabase.table("doctors").select("*").eq("id", user_id).execute()
    doctor_data = doctor_response.data[0] if doctor_response.data else {}

    return {
        "id": user_data["id"],
        "email": user_data["email"],
        "full_name": user_data["full_name"],
        "profile_picture_url": user_data.get("profile_picture_url"),
        "specialization": doctor_data.get("specialization"),
        "hospital": doctor_data.get("hospital"),
        "mobile_number": doctor_data.get("mobile_number"),
        "license_number": doctor_data.get("license_number"),
        "verification_status": doctor_data.get("verification_status"),
        "qualifications": doctor_data.get("qualifications"),
        "experience_years": doctor_data.get("experience_years"),
        "languages": doctor_data.get("languages"),
        "about_text": doctor_data.get("about_text"),
        "video_enabled": doctor_data.get("video_enabled"),
        "video_fee": doctor_data.get("video_fee"),
        "video_duration_minutes": doctor_data.get("video_duration_minutes"),
        "voice_enabled": doctor_data.get("voice_enabled"),
        "voice_fee": doctor_data.get("voice_fee"),
        "voice_duration_minutes": doctor_data.get("voice_duration_minutes"),
    }


@router.patch("/profile")
def update_doctor_profile(
    payload: UpdateDoctorProfileRequest,
    user_id: str = Depends(get_current_user_id),
):
    _require_doctor(user_id)

    data = payload.dict(exclude_unset=True)

    # full_name lives on the users table, everything else on doctors
    if "full_name" in data:
        try:
            supabase.table("users").update({"full_name": data.pop("full_name")}).eq("id", user_id).execute()
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Failed to update name: {str(e)}")

    if data:
        try:
            supabase.table("doctors").update(data).eq("id", user_id).execute()
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Failed to update profile: {str(e)}")

    return get_doctor_profile(user_id)


@router.post("/profile/picture")
async def upload_doctor_picture(
    file: UploadFile = File(...),
    user_id: str = Depends(get_current_user_id),
):
    _require_doctor(user_id)

    if file.content_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(status_code=400, detail="Profile picture must be a JPEG or PNG image.")

    image_bytes = await file.read()
    size_mb = len(image_bytes) / (1024 * 1024)
    if size_mb > MAX_IMAGE_SIZE_MB:
        raise HTTPException(
            status_code=400,
            detail=f"Image too large ({size_mb:.1f} MB). Maximum allowed is {MAX_IMAGE_SIZE_MB} MB.",
        )

    file_ext = (file.filename or "profile.jpg").split(".")[-1]
    storage_path = f"{user_id}/profile.{file_ext}"

    try:
        supabase.storage.from_("profile-pictures").upload(
            storage_path, image_bytes, {"content-type": file.content_type, "upsert": "true"}
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to upload profile picture: {str(e)}")

    public_url = supabase.storage.from_("profile-pictures").get_public_url(storage_path)

    try:
        supabase.table("users").update({"profile_picture_url": public_url}).eq("id", user_id).execute()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save picture URL: {str(e)}")

    return {"message": "Profile picture updated.", "profile_picture_url": public_url}


# --- Availability (weekly working-hours range per day) ---

@router.get("/availability")
def get_availability(user_id: str = Depends(get_current_user_id)):
    _require_doctor(user_id)

    response = (
        supabase.table("doctor_availability")
        .select("*")
        .eq("doctor_id", user_id)
        .execute()
    )

    # Always return all 7 days, even ones the doctor hasn't configured yet,
    # so the frontend can render a full week of toggles without special-casing.
    existing = {row["day_of_week"]: row for row in response.data}
    result = []
    for day in VALID_DAYS:
        row = existing.get(day)
        result.append({
            "day_of_week": day,
            "is_active": row["is_active"] if row else False,
            "start_time": row["start_time"] if row else None,
            "end_time": row["end_time"] if row else None,
        })
    return result


@router.put("/availability")
def save_availability(
    payload: SaveAvailabilityRequest,
    user_id: str = Depends(get_current_user_id),
):
    doctor_response = supabase.table("doctors").select("verification_status").eq("id", user_id).execute()
    if not doctor_response.data or doctor_response.data[0].get("verification_status") != "verified":
        raise HTTPException(
            status_code=403,
            detail="Your account must be verified by an admin before setting availability.",
        )

    for day in payload.days:
        if day.day_of_week.lower() not in VALID_DAYS:
            raise HTTPException(status_code=400, detail=f"Invalid day_of_week: {day.day_of_week}")

        if day.is_active and (not day.start_time or not day.end_time):
            raise HTTPException(
                status_code=400,
                detail=f"start_time and end_time are required when {day.day_of_week} is active.",
            )

        try:
            supabase.table("doctor_availability").upsert(
                {
                    "doctor_id": user_id,
                    "day_of_week": day.day_of_week.lower(),
                    "is_active": day.is_active,
                    "start_time": day.start_time,
                    "end_time": day.end_time,
                },
                on_conflict="doctor_id,day_of_week",
            ).execute()
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Failed to save availability: {str(e)}")

    return get_availability(user_id)