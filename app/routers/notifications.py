"""
Lets a logged-in user (patient or doctor) register their device's FCM
token, so the backend knows where to send push notifications for them.

Call this once after login, and again whenever FCM issues a new token
(the SDK does this periodically) -- upsert means re-registering the
same token is harmless.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.utils.supabase_client import supabase
from app.utils.auth import get_current_user_id

router = APIRouter(prefix="/notifications", tags=["notifications"])


class RegisterTokenRequest(BaseModel):
    token: str
    platform: str = "android"


@router.post("/register-token")
def register_device_token(
    payload: RegisterTokenRequest,
    user_id: str = Depends(get_current_user_id),
):
    try:
        supabase.table("device_tokens").upsert(
            {
                "user_id": user_id,
                "token": payload.token,
                "platform": payload.platform,
            },
            on_conflict="token",
        ).execute()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to register device: {str(e)}")

    return {"message": "Device registered for notifications."}


@router.delete("/unregister-token")
def unregister_device_token(
    payload: RegisterTokenRequest,
    user_id: str = Depends(get_current_user_id),
):
    """Call this on logout, so a signed-out device stops receiving
    notifications meant for that user."""
    supabase.table("device_tokens").delete().eq("token", payload.token).eq("user_id", user_id).execute()
    return {"message": "Device unregistered."}
@router.get("/unread-count")
def get_unread_count(user_id: str = Depends(get_current_user_id)):
    response = (
        supabase.table("notifications")
        .select("id", count="exact")
        .eq("user_id", user_id)
        .eq("is_read", False)
        .execute()
    )
    return {"count": response.count or 0}


@router.get("")
def list_notifications(user_id: str = Depends(get_current_user_id)):
    response = (
        supabase.table("notifications")
        .select("*")
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .execute()
    )
    return response.data


@router.patch("/{notification_id}/read")
def mark_notification_read(notification_id: str, user_id: str = Depends(get_current_user_id)):
    response = (
        supabase.table("notifications")
        .select("id")
        .eq("id", notification_id)
        .eq("user_id", user_id)
        .execute()
    )
    if not response.data:
        raise HTTPException(status_code=404, detail="Notification not found.")

    supabase.table("notifications").update({"is_read": True}).eq("id", notification_id).execute()
    return {"message": "Marked as read."}


@router.patch("/read-all")
def mark_all_read(user_id: str = Depends(get_current_user_id)):
    supabase.table("notifications").update({"is_read": True}).eq("user_id", user_id).eq("is_read", False).execute()
    return {"message": "All notifications marked as read."}