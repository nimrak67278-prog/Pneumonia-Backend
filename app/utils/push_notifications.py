"""
Sends push notifications via Firebase Cloud Messaging (FCM).

This uses ONLY Firebase's messaging service -- nothing else in this app
uses Firebase. Auth, database, and storage all remain on Supabase. FCM
is free with no meaningful usage limits, and works independently of
whatever backend/database you're using.

Setup:
1. Create a Firebase project (console.firebase.google.com)
2. Project Settings -> Service Accounts -> Generate new private key
3. Paste the ENTIRE downloaded JSON as one line into .env as
   FIREBASE_SERVICE_ACCOUNT_JSON
"""

import os
import json
import logging

import firebase_admin
from firebase_admin import credentials, messaging

logger = logging.getLogger(__name__)

_firebase_app = None

FIREBASE_SERVICE_ACCOUNT_JSON = os.environ.get("FIREBASE_SERVICE_ACCOUNT_JSON")

if FIREBASE_SERVICE_ACCOUNT_JSON:
    try:
        cred_dict = json.loads(FIREBASE_SERVICE_ACCOUNT_JSON)
        cred = credentials.Certificate(cred_dict)
        _firebase_app = firebase_admin.initialize_app(cred)
    except Exception as e:
        logger.warning(f"Failed to initialize Firebase Admin SDK: {e}")
else:
    logger.warning(
        "FIREBASE_SERVICE_ACCOUNT_JSON not set. Push notifications will be skipped."
    )


def send_push_notification(
    device_token: str,
    title: str,
    body: str,
    data: dict | None = None,
) -> bool:
    """
    Sends a single push notification. Returns True on success, False if
    it failed or Firebase isn't configured -- callers should NOT let a
    failed notification block the actual action (e.g. a booking should
    still get confirmed even if the notification fails to send).
    """
    if _firebase_app is None:
        return False

    try:
        message = messaging.Message(
            notification=messaging.Notification(title=title, body=body),
            data={k: str(v) for k, v in (data or {}).items()},
            token=device_token,
        )
        messaging.send(message)
        return True
    except Exception as e:
        logger.warning(f"Failed to send push notification: {e}")
        return False


def notify_user(user_id: str, title: str, body: str, data: dict | None = None):
    """
    Saves a persistent notification record (so unread counts/badges work
    even if the push is missed), then sends the actual push to every
    device this user has registered.
    """
    from app.utils.supabase_client import supabase

    try:
        supabase.table("notifications").insert(
            {
                "user_id": user_id,
                "title": title,
                "body": body,
                "type": (data or {}).get("type"),
                "booking_id": (data or {}).get("booking_id"),
            }
        ).execute()
    except Exception as e:
        logger.warning(f"Failed to save notification record: {e}")

    response = supabase.table("device_tokens").select("token").eq("user_id", user_id).execute()
    for row in response.data:
        send_push_notification(row["token"], title, body, data)