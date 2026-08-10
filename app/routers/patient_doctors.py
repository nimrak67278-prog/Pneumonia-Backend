"""
Lets a logged-in patient browse doctors available for online consultation.

Only shows doctors with verification_status = 'verified' -- pending or
rejected doctor accounts are never visible to patients.

Ratings/reviews are not included yet -- that's a separate future feature
requiring an actual review system, not a placeholder field here.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Optional

from app.utils.supabase_client import supabase
from app.utils.auth import get_current_user_id

router = APIRouter(prefix="/patient/doctors", tags=["patient-doctors"])


def _format_doctor(row: dict) -> dict:
    user_info = row.pop("users", {}) or {}
    return {
        "id": row["id"],
        "full_name": user_info.get("full_name"),
        "profile_picture_url": user_info.get("profile_picture_url"),
        "specialization": row.get("specialization"),
        "hospital": row.get("hospital"),
        "qualifications": row.get("qualifications"),
        "experience_years": row.get("experience_years"),
        "languages": row.get("languages"),
        "about_text": row.get("about_text"),
        "video_enabled": row.get("video_enabled"),
        "video_fee": row.get("video_fee"),
        "video_duration_minutes": row.get("video_duration_minutes"),
        "voice_enabled": row.get("voice_enabled"),
        "voice_fee": row.get("voice_fee"),
        "voice_duration_minutes": row.get("voice_duration_minutes"),
    }


@router.get("")
def list_doctors(
    search: Optional[str] = Query(None, description="Search by doctor name"),
    sort: Optional[str] = Query(
        None,
        description="'video_fee_asc', 'video_fee_desc', 'voice_fee_asc', or 'voice_fee_desc'",
    ),
    user_id: str = Depends(get_current_user_id),
):
    query = (
        supabase.table("doctors")
        .select("*, users!inner(full_name, profile_picture_url)")
        .eq("verification_status", "verified")
    )

    sort_map = {
        "video_fee_asc": ("video_fee", False),
        "video_fee_desc": ("video_fee", True),
        "voice_fee_asc": ("voice_fee", False),
        "voice_fee_desc": ("voice_fee", True),
    }
    if sort in sort_map:
        column, desc = sort_map[sort]
        query = query.order(column, desc=desc, nullsfirst=False)

    response = query.execute()
    doctors = [_format_doctor(row) for row in response.data]

    # Name search done in Python since it's filtering on a joined column,
    # which is awkward to express directly in a single Supabase query.
    if search:
        search_lower = search.lower()
        doctors = [d for d in doctors if search_lower in (d.get("full_name") or "").lower()]

    return {"count": len(doctors), "doctors": doctors}


@router.get("/{doctor_id}")
def get_doctor_profile(doctor_id: str, user_id: str = Depends(get_current_user_id)):
    response = (
        supabase.table("doctors")
        .select("*, users!inner(full_name, profile_picture_url, email)")
        .eq("id", doctor_id)
        .eq("verification_status", "verified")
        .execute()
    )

    if not response.data:
        raise HTTPException(status_code=404, detail="Doctor not found.")

    row = response.data[0]
    user_info = row.pop("users", {}) or {}

    return {
        "id": row["id"],
        "full_name": user_info.get("full_name"),
        "email": user_info.get("email"),
        "profile_picture_url": user_info.get("profile_picture_url"),
        "specialization": row.get("specialization"),
        "hospital": row.get("hospital"),
        "qualifications": row.get("qualifications"),
        "experience_years": row.get("experience_years"),
        "languages": row.get("languages"),
        "about_text": row.get("about_text"),
        "video_enabled": row.get("video_enabled"),
        "video_fee": row.get("video_fee"),
        "video_duration_minutes": row.get("video_duration_minutes"),
        "voice_enabled": row.get("voice_enabled"),
        "voice_fee": row.get("voice_fee"),
        "voice_duration_minutes": row.get("voice_duration_minutes"),
    }