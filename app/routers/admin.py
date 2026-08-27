"""
Admin-only endpoints. Every route here requires the `require_admin`
dependency, which checks the caller's role is 'admin' in the users table.

The admin logs in through the same /auth/login endpoint as everyone else
(their account just happens to have role='admin') and then includes that
session token on every request to these routes.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.utils.supabase_client import supabase
from app.utils.auth import require_admin

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])


class VerifyDoctorRequest(BaseModel):
    status: str  # "verified" or "rejected"


# --- Doctor verification ---


@router.get("/doctors/pending")
def list_pending_doctors():
    result = (
        supabase.table("doctors")
        .select("*, users!inner(full_name, email, created_at)")
        .eq("verification_status", "pending")
        .execute()
    )
    return result.data


@router.get("/doctors/{doctor_id}/certificate-url")
def get_certificate_url(doctor_id: str):
    doctor = (
        supabase.table("doctors")
        .select("certificate_url")
        .eq("id", doctor_id)
        .single()
        .execute()
    )
    if not doctor.data or not doctor.data.get("certificate_url"):
        raise HTTPException(status_code=404, detail="Certificate not found.")

    # Generates a temporary signed URL since the bucket is private
    signed = supabase.storage.from_("doctor-certificates").create_signed_url(
        doctor.data["certificate_url"], expires_in=300  # 5 minutes
    )
    return {"url": signed.get("signedURL") or signed.get("signedUrl")}


@router.patch("/doctors/{doctor_id}/verify")
def verify_doctor(doctor_id: str, payload: VerifyDoctorRequest):
    if payload.status not in ("verified", "rejected"):
        raise HTTPException(status_code=400, detail="status must be 'verified' or 'rejected'.")

    result = (
        supabase.table("doctors")
        .update({"verification_status": payload.status})
        .eq("id", doctor_id)
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=404, detail="Doctor not found.")

    return {"message": f"Doctor {payload.status}.", "doctor_id": doctor_id}


# --- User oversight ---

@router.get("/users")
def list_all_users():
    result = supabase.table("users").select("*").order("created_at", desc=True).execute()
    return result.data


@router.delete("/users/{user_id}")
def deactivate_user(user_id: str):
    from supabase import create_client
    import os

    # Fresh, throwaway client used ONLY for this one call -- guarantees
    # zero session pollution from any other code path in the app, since
    # this client is never reused or touched anywhere else.
    fresh_admin_client = create_client(
        os.environ.get("SUPABASE_URL"),
        os.environ.get("SUPABASE_SERVICE_ROLE_KEY"),
    )

    try:
        fresh_admin_client.auth.admin.delete_user(user_id)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to deactivate user: {str(e)}")

    return {"message": "User deactivated.", "user_id": user_id}
# --- Predictions oversight ---

@router.get("/predictions")
def list_all_predictions():
    result = (
        supabase.table("predictions")
        .select("*, users!inner(full_name, email)")
        .order("created_at", desc=True)
        .execute()
    )
    return result.data


# --- Requests oversight ---

@router.get("/requests")
def list_all_requests():
    result = (
        supabase.table("requests")
        .select("*")
        .order("requested_at", desc=True)
        .execute()
    )
    return result.data
@router.get("/appointments")
def list_all_appointments():
    response = (
        supabase.table("consultation_bookings")
        .select(
            "*, "
            "doctors!inner(specialization, users!inner(full_name)), "
            "patients!inner(users!inner(full_name))"
        )
        .order("scheduled_date", desc=True)
        .execute()
    )

    results = []
    for row in response.data:
        doctor_info = row.pop("doctors", {}) or {}
        doctor_user = doctor_info.pop("users", {}) or {}
        patient_info = row.pop("patients", {}) or {}
        patient_user = patient_info.pop("users", {}) or {}
        results.append({
            **row,
            "doctor_name": doctor_user.get("full_name"),
            "doctor_specialization": doctor_info.get("specialization"),
            "patient_name": patient_user.get("full_name"),
        })

    return {"count": len(results), "appointments": results}


@router.get("/reports")
def list_all_reports():
    response = (
        supabase.table("consultation_reports")
        .select(
            "*, "
            "reporter:users!consultation_reports_reporter_id_fkey(full_name), "
            "reported:users!consultation_reports_reported_user_id_fkey(full_name)"
        )
        .order("created_at", desc=True)
        .execute()
    )

    results = []
    for row in response.data:
        reporter = row.pop("reporter", {}) or {}
        reported = row.pop("reported", {}) or {}
        results.append({
            **row,
            "reporter_name": reporter.get("full_name"),
            "reported_name": reported.get("full_name"),
        })

    return {"count": len(results), "reports": results}


@router.get("/reviews")
def list_all_reviews():
    response = (
        supabase.table("consultation_reviews")
        .select(
            "*, "
            "reviewer:users!consultation_reviews_reviewer_id_fkey(full_name), "
            "reviewee:users!consultation_reviews_reviewee_id_fkey(full_name)"
        )
        .order("created_at", desc=True)
        .execute()
    )

    results = []
    for row in response.data:
        reviewer = row.pop("reviewer", {}) or {}
        reviewee = row.pop("reviewee", {}) or {}
        results.append({
            **row,
            "reviewer_name": reviewer.get("full_name"),
            "reviewee_name": reviewee.get("full_name"),
        })

    return {"count": len(results), "reviews": results}
