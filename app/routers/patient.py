"""
Patient profile endpoints -- lets a logged-in patient view and update
their own profile info (full name, mobile number, profile picture).

Uses get_current_user_id (not require_admin) since this is for any
logged-in patient managing their OWN data, identified by their token --
there's no user_id in the URL, so there's no way to accidentally view
or edit someone else's profile.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from pydantic import BaseModel
from typing import Optional

from app.utils.supabase_client import supabase
from app.utils.auth import get_current_user_id

router = APIRouter(prefix="/patient", tags=["patient"])

ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/jpg", "image/png"}
MAX_IMAGE_SIZE_MB = 5


class UpdateProfileRequest(BaseModel):
    full_name: Optional[str] = None
    mobile_number: Optional[str] = None


@router.get("/profile")
def get_profile(user_id: str = Depends(get_current_user_id)):
    user_response = supabase.table("users").select("*").eq("id", user_id).execute()

    if not user_response.data:
        raise HTTPException(status_code=404, detail="Profile not found.")

    user_data = user_response.data[0]

    if user_data.get("role") != "patient":
        raise HTTPException(status_code=403, detail="This account is not a patient account.")

    patient_response = supabase.table("patients").select("*").eq("id", user_id).execute()
    patient_data = patient_response.data[0] if patient_response.data else None

    return {
        "id": user_data["id"],
        "email": user_data["email"],
        "full_name": user_data["full_name"],
        "role": user_data["role"],
        "created_at": user_data["created_at"],
        "mobile_number": patient_data["mobile_number"] if patient_data else None,
        "profile_picture_url": user_data.get("profile_picture_url"),
    }


@router.patch("/profile")
def update_profile(
    payload: UpdateProfileRequest,
    user_id: str = Depends(get_current_user_id),
):
    user_response = supabase.table("users").select("role").eq("id", user_id).execute()
    if not user_response.data:
        raise HTTPException(status_code=404, detail="Profile not found.")
    if user_response.data[0].get("role") != "patient":
        raise HTTPException(status_code=403, detail="This account is not a patient account.")

    if payload.full_name is not None:
        try:
            supabase.table("users").update(
                {"full_name": payload.full_name}
            ).eq("id", user_id).execute()
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Failed to update name: {str(e)}")

    if payload.mobile_number is not None:
        try:
            supabase.table("patients").update(
                {"mobile_number": payload.mobile_number}
            ).eq("id", user_id).execute()
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Failed to update mobile number: {str(e)}")

    return get_profile(user_id)


@router.post("/profile/picture")
async def upload_profile_picture(
    file: UploadFile = File(...),
    user_id: str = Depends(get_current_user_id),
):
    if file.content_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(
            status_code=400,
            detail="Profile picture must be a JPEG or PNG image.",
        )

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
            storage_path,
            image_bytes,
            {"content-type": file.content_type, "upsert": "true"},
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to upload profile picture: {str(e)}")

    public_url = supabase.storage.from_("profile-pictures").get_public_url(storage_path)

    try:
        supabase.table("users").update(
            {"profile_picture_url": public_url}
        ).eq("id", user_id).execute()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save picture URL: {str(e)}")

    return {"message": "Profile picture updated.", "profile_picture_url": public_url}