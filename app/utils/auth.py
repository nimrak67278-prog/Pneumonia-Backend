"""
Verifies the logged-in user's Supabase session token, sent by the React
Native app in the Authorization header (e.g. "Bearer <access_token>").

Uses FastAPI's HTTPBearer security scheme (instead of a raw Header param)
so Swagger UI shows a proper padlock "Authorize" button -- you paste your
token once and it's automatically attached to every protected endpoint
you test afterward, rather than retyping it per-endpoint in a plain text
field (which proved unreliable in Swagger UI).
"""

from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from app.utils.supabase_client import supabase, supabase_auth

bearer_scheme = HTTPBearer()


def get_current_user_id(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
) -> str:
    """
    FastAPI dependency. Extracts and verifies the bearer token, returning
    the authenticated user's UUID. Raises 401 if missing/invalid.
    """
    token = credentials.credentials

    try:
       user_response = supabase_auth.auth.get_user(token)
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired session token.")

    if not user_response or not user_response.user:
        raise HTTPException(status_code=401, detail="Invalid or expired session token.")

    return user_response.user.id


def require_admin(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
) -> str:
    """
    FastAPI dependency for admin-only endpoints. Verifies the token
    (same as get_current_user_id), then additionally checks that this
    user's role in the users table is 'admin'. Raises 403 otherwise.
    """
    user_id = get_current_user_id(credentials)

    response = (
        supabase.table("users")
        .select("role")
        .eq("id", user_id)
        .execute()
    )

    if not response.data or response.data[0].get("role") != "admin":
        raise HTTPException(
            status_code=403,
            detail="Admin access required.",
        )

    return user_id