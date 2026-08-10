"""
Patient-facing consultation booking flow:
1. View a specific doctor's available days
2. View discrete bookable time slots for one of those days
3. Create a booking (pending payment)
4. Start Stripe payment (test mode)
5. Confirm payment succeeded -> booking becomes confirmed

Plus the appointments list (patient and doctor side), cancel/decline/
complete actions, and the Agora call-token endpoint used to join a
video or voice consultation.

Duration/pricing come from the doctor's own settings (video_fee,
video_duration_minutes, voice_fee, voice_duration_minutes) set via
PATCH /doctor/profile.
"""

import os
from datetime import datetime, timedelta, date, time as time_cls
from typing import Optional

import stripe
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.utils.supabase_client import supabase
from app.utils.auth import get_current_user_id

router = APIRouter(tags=["consultations"])

stripe.api_key = os.environ.get("STRIPE_SECRET_KEY")

DAY_INDEX = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
    "friday": 4, "saturday": 5, "sunday": 6,
}

JOIN_WINDOW_BEFORE_MINUTES = 5
JOIN_WINDOW_AFTER_GRACE_MINUTES = 30


def _next_date_for_day(day_of_week: str) -> date:
    today = date.today()
    target_idx = DAY_INDEX[day_of_week.lower()]
    days_ahead = (target_idx - today.weekday()) % 7
    return today + timedelta(days=days_ahead)


def _generate_slots(start_time: str, end_time: str, duration_minutes: int) -> list[str]:
    slots = []
    start = datetime.combine(date.today(), time_cls.fromisoformat(start_time))
    end = datetime.combine(date.today(), time_cls.fromisoformat(end_time))
    current = start
    while current + timedelta(minutes=duration_minutes) <= end:
        slots.append(current.strftime("%H:%M"))
        current += timedelta(minutes=duration_minutes)
    return slots


def _compute_display_status(booking: dict) -> str:
    if booking["status"] in ("cancelled", "declined"):
        return "cancelled"
    if booking["status"] == "completed":
        return "completed"
    if booking["status"] == "confirmed":
        start = datetime.fromisoformat(f"{booking['scheduled_date']}T{booking['scheduled_time']}")
        end = start + timedelta(minutes=booking["duration_minutes"])
        now = datetime.now()
        if start <= now <= end:
            return "in_progress"
        return "scheduled"
    return "scheduled"


def _format_appointment(row: dict, other_party_key: str) -> dict:
    other = row.pop(other_party_key, {}) or {}
    user_info = other.pop("users", {}) or {}
    return {
        "id": row["id"],
        "consultation_type": row["consultation_type"],
        "scheduled_date": row["scheduled_date"],
        "scheduled_time": row["scheduled_time"],
        "duration_minutes": row["duration_minutes"],
        "fee": row["fee"],
        "status": _compute_display_status(row),
        "other_party_name": user_info.get("full_name"),
        "other_party_picture_url": user_info.get("profile_picture_url"),
        "specialization": other.get("specialization"),
        "reschedule_reason": row.get("reschedule_reason"),
    }


@router.get("/patient/doctors/{doctor_id}/availability")
def get_doctor_availability(doctor_id: str, user_id: str = Depends(get_current_user_id)):
    response = (
        supabase.table("doctor_availability")
        .select("day_of_week, start_time, end_time")
        .eq("doctor_id", doctor_id)
        .eq("is_active", True)
        .execute()
    )
    return response.data


@router.get("/patient/doctors/{doctor_id}/slots")
def get_available_slots(
    doctor_id: str,
    day_of_week: str,
    consultation_type: str = Query(..., pattern="^(video|voice)$"),
    user_id: str = Depends(get_current_user_id),
):
    day_of_week = day_of_week.lower()
    if day_of_week not in DAY_INDEX:
        raise HTTPException(status_code=400, detail="Invalid day_of_week.")

    availability_response = (
        supabase.table("doctor_availability")
        .select("start_time, end_time")
        .eq("doctor_id", doctor_id)
        .eq("day_of_week", day_of_week)
        .eq("is_active", True)
        .execute()
    )
    if not availability_response.data:
        raise HTTPException(status_code=404, detail="Doctor is not available on this day.")

    day_range = availability_response.data[0]

    doctor_response = (
        supabase.table("doctors")
        .select("video_duration_minutes, voice_duration_minutes, video_enabled, voice_enabled")
        .eq("id", doctor_id)
        .execute()
    )
    if not doctor_response.data:
        raise HTTPException(status_code=404, detail="Doctor not found.")
    doctor = doctor_response.data[0]

    if consultation_type == "video":
        if not doctor.get("video_enabled"):
            raise HTTPException(status_code=400, detail="This doctor does not offer video consultations.")
    else:
        if not doctor.get("voice_enabled"):
            raise HTTPException(status_code=400, detail="This doctor does not offer voice consultations.")

    SLOT_INTERVAL_MINUTES = 30

    all_slots = _generate_slots(day_range["start_time"], day_range["end_time"], SLOT_INTERVAL_MINUTES)
    scheduled_date = _next_date_for_day(day_of_week)

    booked_response = (
        supabase.table("consultation_bookings")
        .select("scheduled_time")
        .eq("doctor_id", doctor_id)
        .eq("scheduled_date", scheduled_date.isoformat())
        .in_("status", ["pending_payment", "confirmed"])
        .execute()
    )
    booked_times = {row["scheduled_time"][:5] for row in booked_response.data}

    available_slots = [s for s in all_slots if s not in booked_times]

    return {
        "day_of_week": day_of_week,
        "scheduled_date": scheduled_date.isoformat(),
        "available_slots": available_slots,
    }


class CreateBookingRequest(BaseModel):
    doctor_id: str
    consultation_type: str
    day_of_week: str
    slot_time: str


@router.post("/patient/bookings")
def create_booking(payload: CreateBookingRequest, user_id: str = Depends(get_current_user_id)):
    if payload.consultation_type not in ("video", "voice"):
        raise HTTPException(status_code=400, detail="consultation_type must be 'video' or 'voice'.")

    day_of_week = payload.day_of_week.lower()
    if day_of_week not in DAY_INDEX:
        raise HTTPException(status_code=400, detail="Invalid day_of_week.")

    doctor_response = (
        supabase.table("doctors")
        .select("video_fee, video_duration_minutes, voice_fee, voice_duration_minutes, video_enabled, voice_enabled, verification_status")
        .eq("id", payload.doctor_id)
        .execute()
    )
    if not doctor_response.data:
        raise HTTPException(status_code=404, detail="Doctor not found.")
    doctor = doctor_response.data[0]

    if doctor.get("verification_status") != "verified":
        raise HTTPException(status_code=400, detail="This doctor is not currently available for booking.")

    if payload.consultation_type == "video":
        if not doctor.get("video_enabled"):
            raise HTTPException(status_code=400, detail="This doctor does not offer video consultations.")
        fee = doctor.get("video_fee")
        duration = doctor.get("video_duration_minutes") or 30
    else:
        if not doctor.get("voice_enabled"):
            raise HTTPException(status_code=400, detail="This doctor does not offer voice consultations.")
        fee = doctor.get("voice_fee")
        duration = doctor.get("voice_duration_minutes") or 15

    if fee is None:
        raise HTTPException(status_code=400, detail="This doctor has not set a fee for this consultation type yet.")

    scheduled_date = _next_date_for_day(day_of_week)

    existing = (
        supabase.table("consultation_bookings")
        .select("id")
        .eq("doctor_id", payload.doctor_id)
        .eq("scheduled_date", scheduled_date.isoformat())
        .eq("scheduled_time", payload.slot_time)
        .in_("status", ["pending_payment", "confirmed"])
        .execute()
    )
    if existing.data:
        raise HTTPException(status_code=409, detail="This slot was just booked by someone else. Please pick another.")

    insert_response = (
        supabase.table("consultation_bookings")
        .insert(
            {
                "patient_id": user_id,
                "doctor_id": payload.doctor_id,
                "consultation_type": payload.consultation_type,
                "fee": fee,
                "duration_minutes": duration,
                "day_of_week": day_of_week,
                "scheduled_date": scheduled_date.isoformat(),
                "scheduled_time": payload.slot_time,
            }
        )
        .execute()
    )

    return insert_response.data[0]


@router.get("/patient/bookings/{booking_id}")
def get_booking_summary(booking_id: str, user_id: str = Depends(get_current_user_id)):
    response = (
        supabase.table("consultation_bookings")
        .select("*, doctors!inner(specialization, users!inner(full_name, profile_picture_url))")
        .eq("id", booking_id)
        .eq("patient_id", user_id)
        .execute()
    )
    if not response.data:
        raise HTTPException(status_code=404, detail="Booking not found.")

    row = response.data[0]
    doctor_info = row.pop("doctors", {}) or {}
    user_info = doctor_info.pop("users", {}) or {}

    return {
        **row,
        "doctor_name": user_info.get("full_name"),
        "doctor_specialization": doctor_info.get("specialization"),
        "doctor_picture_url": user_info.get("profile_picture_url"),
        "platform_fee": 0,
        "total_amount": row["fee"],
    }


@router.get("/patient/appointments")
def list_patient_appointments(
    tab: Optional[str] = Query(None, description="'upcoming', 'completed', or 'cancelled'"),
    user_id: str = Depends(get_current_user_id),
):
    response = (
        supabase.table("consultation_bookings")
        .select("*, doctors!inner(specialization, users!inner(full_name, profile_picture_url))")
        .eq("patient_id", user_id)
        .in_("status", ["confirmed", "completed", "cancelled", "declined"])
        .order("scheduled_date", desc=False)
        .order("scheduled_time", desc=False)
        .execute()
    )

    appointments = [_format_appointment(row, "doctors") for row in response.data]

    if tab == "upcoming":
        appointments = [a for a in appointments if a["status"] in ("scheduled", "in_progress")]
    elif tab == "completed":
        appointments = [a for a in appointments if a["status"] == "completed"]
    elif tab == "cancelled":
        appointments = [a for a in appointments if a["status"] == "cancelled"]

    return {"count": len(appointments), "appointments": appointments}


@router.patch("/patient/bookings/{booking_id}/cancel")
def cancel_booking(booking_id: str, user_id: str = Depends(get_current_user_id)):
    response = (
        supabase.table("consultation_bookings")
        .select("status")
        .eq("id", booking_id)
        .eq("patient_id", user_id)
        .execute()
    )
    if not response.data:
        raise HTTPException(status_code=404, detail="Booking not found.")
    if response.data[0]["status"] not in ("pending_payment", "confirmed"):
        raise HTTPException(status_code=400, detail="This booking can no longer be cancelled.")

    supabase.table("consultation_bookings").update({"status": "cancelled"}).eq("id", booking_id).execute()
    return {"message": "Booking cancelled.", "booking_id": booking_id}


@router.get("/doctor/appointments")
def list_doctor_appointments(
    tab: Optional[str] = Query(None),
    user_id: str = Depends(get_current_user_id),
):
    response = (
        supabase.table("consultation_bookings")
        .select("*, patients!inner(users!inner(full_name, profile_picture_url))")
        .eq("doctor_id", user_id)
        .in_("status", ["confirmed", "completed", "cancelled", "declined"])
        .order("scheduled_date", desc=False)
        .order("scheduled_time", desc=False)
        .execute()
    )

    appointments = [_format_appointment(row, "patients") for row in response.data]

    if tab == "upcoming":
        appointments = [a for a in appointments if a["status"] in ("scheduled", "in_progress")]
    elif tab == "completed":
        appointments = [a for a in appointments if a["status"] == "completed"]
    elif tab == "cancelled":
        appointments = [a for a in appointments if a["status"] == "cancelled"]

    return {"count": len(appointments), "appointments": appointments}


class RescheduleRequest(BaseModel):
    day_of_week: str
    slot_time: str  # "10:00"
    reason: Optional[str] = None


@router.patch("/doctor/appointments/{booking_id}/reschedule")
def reschedule_booking(
    booking_id: str,
    payload: RescheduleRequest,
    user_id: str = Depends(get_current_user_id),
):
    booking_response = (
        supabase.table("consultation_bookings")
        .select("*")
        .eq("id", booking_id)
        .eq("doctor_id", user_id)
        .execute()
    )
    if not booking_response.data:
        raise HTTPException(status_code=404, detail="Booking not found.")

    booking = booking_response.data[0]
    if booking["status"] != "confirmed":
        raise HTTPException(status_code=400, detail="Only confirmed bookings can be rescheduled.")

    day_of_week = payload.day_of_week.lower()
    if day_of_week not in DAY_INDEX:
        raise HTTPException(status_code=400, detail="Invalid day_of_week.")

    # Confirm the doctor is actually available on this new day
    availability_response = (
        supabase.table("doctor_availability")
        .select("start_time, end_time")
        .eq("doctor_id", user_id)
        .eq("day_of_week", day_of_week)
        .eq("is_active", True)
        .execute()
    )
    if not availability_response.data:
        raise HTTPException(status_code=400, detail="You are not available on this day.")

    new_scheduled_date = _next_date_for_day(day_of_week)

    # Make sure the new slot isn't already taken by a DIFFERENT booking
    conflict_response = (
        supabase.table("consultation_bookings")
        .select("id")
        .eq("doctor_id", user_id)
        .eq("scheduled_date", new_scheduled_date.isoformat())
        .eq("scheduled_time", payload.slot_time)
        .neq("id", booking_id)
        .in_("status", ["pending_payment", "confirmed"])
        .execute()
    )
    if conflict_response.data:
        raise HTTPException(status_code=409, detail="You already have another booking at that time.")

    update_data = {
        "day_of_week": day_of_week,
        "scheduled_date": new_scheduled_date.isoformat(),
        "scheduled_time": payload.slot_time,
    }
    if payload.reason:
        update_data["reschedule_reason"] = payload.reason

    supabase.table("consultation_bookings").update(update_data).eq("id", booking_id).execute()

    return {
        "message": "Appointment rescheduled.",
        "booking_id": booking_id,
        "new_scheduled_date": new_scheduled_date.isoformat(),
        "new_scheduled_time": payload.slot_time,
        "reason": payload.reason,
    }

@router.patch("/doctor/appointments/{booking_id}/complete")
def complete_booking(booking_id: str, user_id: str = Depends(get_current_user_id)):
    response = (
        supabase.table("consultation_bookings")
        .select("status")
        .eq("id", booking_id)
        .eq("doctor_id", user_id)
        .execute()
    )
    if not response.data:
        raise HTTPException(status_code=404, detail="Booking not found.")
    if response.data[0]["status"] != "confirmed":
        raise HTTPException(status_code=400, detail="Only confirmed bookings can be marked completed.")

    supabase.table("consultation_bookings").update({"status": "completed"}).eq("id", booking_id).execute()
    return {"message": "Consultation marked as completed.", "booking_id": booking_id}


@router.post("/consultations/{booking_id}/call-token")
def get_call_token(booking_id: str, user_id: str = Depends(get_current_user_id)):
    response = supabase.table("consultation_bookings").select("*").eq("id", booking_id).execute()
    if not response.data:
        raise HTTPException(status_code=404, detail="Booking not found.")

    booking = response.data[0]

    if user_id not in (booking["patient_id"], booking["doctor_id"]):
        raise HTTPException(status_code=403, detail="You are not part of this consultation.")

    if booking["status"] != "confirmed":
        raise HTTPException(status_code=400, detail="This consultation is not currently active.")

    start = datetime.fromisoformat(f"{booking['scheduled_date']}T{booking['scheduled_time']}")
    join_window_start = start - timedelta(minutes=JOIN_WINDOW_BEFORE_MINUTES)
    join_window_end = start + timedelta(minutes=booking["duration_minutes"] + JOIN_WINDOW_AFTER_GRACE_MINUTES)
    now = datetime.now()

    if now < join_window_start:
        raise HTTPException(
            status_code=400,
            detail=f"This consultation hasn't started yet. You can join starting {JOIN_WINDOW_BEFORE_MINUTES} minutes before the scheduled time.",
        )
    if now > join_window_end:
        raise HTTPException(status_code=400, detail="This consultation's time window has passed.")

    if user_id == booking["patient_id"]:
        other_response = supabase.table("users").select("full_name").eq("id", booking["doctor_id"]).execute()
    else:
        other_response = supabase.table("users").select("full_name").eq("id", booking["patient_id"]).execute()
    other_name = other_response.data[0]["full_name"] if other_response.data else "Unknown"

    app_id = os.environ.get("AGORA_APP_ID")
    app_certificate = os.environ.get("AGORA_APP_CERTIFICATE")
    if not app_id or not app_certificate:
        raise HTTPException(status_code=500, detail="Call service is not configured.")

    from agora_token_builder import RtcTokenBuilder

    channel_name = f"consultation_{booking_id}"
    uid = 0
    expire_seconds = 3600
    privilege_expire_ts = int(datetime.now().timestamp()) + expire_seconds

    token = RtcTokenBuilder.buildTokenWithUid(
        app_id, app_certificate, channel_name, uid, 1, privilege_expire_ts
    )

    return {
        "app_id": app_id,
        "channel_name": channel_name,
        "token": token,
        "uid": uid,
        "consultation_type": booking["consultation_type"],
        "remote_name": other_name,
    }


@router.post("/patient/bookings/{booking_id}/create-payment-intent")
def create_payment_intent(booking_id: str, user_id: str = Depends(get_current_user_id)):
    booking_response = (
        supabase.table("consultation_bookings")
        .select("*")
        .eq("id", booking_id)
        .eq("patient_id", user_id)
        .execute()
    )
    if not booking_response.data:
        raise HTTPException(status_code=404, detail="Booking not found.")

    booking = booking_response.data[0]
    if booking["status"] != "pending_payment":
        raise HTTPException(status_code=400, detail=f"This booking is already {booking['status']}.")

    try:
        intent = stripe.PaymentIntent.create(
            amount=int(booking["fee"] * 100),
            currency="pkr",
            metadata={"booking_id": booking_id, "patient_id": user_id},
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to start payment: {str(e)}")

    supabase.table("consultation_bookings").update(
        {"stripe_payment_intent_id": intent.id}
    ).eq("id", booking_id).execute()

    return {"client_secret": intent.client_secret}


@router.post("/patient/bookings/{booking_id}/confirm")
def confirm_booking_payment(booking_id: str, user_id: str = Depends(get_current_user_id)):
    booking_response = (
        supabase.table("consultation_bookings")
        .select("*")
        .eq("id", booking_id)
        .eq("patient_id", user_id)
        .execute()
    )
    if not booking_response.data:
        raise HTTPException(status_code=404, detail="Booking not found.")

    booking = booking_response.data[0]
    if not booking.get("stripe_payment_intent_id"):
        raise HTTPException(status_code=400, detail="No payment was started for this booking.")

    try:
        intent = stripe.PaymentIntent.retrieve(booking["stripe_payment_intent_id"])
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to verify payment: {str(e)}")

    if intent.status != "succeeded":
        raise HTTPException(status_code=400, detail=f"Payment not completed yet (status: {intent.status}).")

    supabase.table("consultation_bookings").update({"status": "confirmed"}).eq("id", booking_id).execute()

    return {"message": "Booking confirmed.", "booking_id": booking_id, "status": "confirmed"}
@router.get("/doctor/appointments/{booking_id}")
def get_appointment_detail(booking_id: str, user_id: str = Depends(get_current_user_id)):
    booking_response = (
        supabase.table("consultation_bookings")
        .select("*, patient:patient_id(users(full_name, profile_picture_url))")
        .eq("id", booking_id)
        .eq("doctor_id", user_id)
        .execute()
    )
    if not booking_response.data:
        raise HTTPException(status_code=404, detail="Booking not found.")

    booking = booking_response.data[0]

    # Pull the patient's most recent x-ray + AI results, if any exist
    predictions_response = (
        supabase.table("predictions")
        .select("id, image_url, confidence, risk_level, explanation, recommendation, created_at")
        .eq("patient_id", booking["patient_id"])
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )

    latest_predictions = predictions_response.data[0] if predictions_response.data else None

    appointment = _format_appointment(booking, "patient")
    appointment["latest_xray_report"] = latest_predictions  # null if patient never uploaded one

    return appointment