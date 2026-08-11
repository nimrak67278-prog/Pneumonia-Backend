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