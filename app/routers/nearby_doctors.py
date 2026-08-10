"""
Nearby doctors/hospitals search, backed by Google Places API.
Requires the patient's current latitude/longitude (obtained on the
device via location permission, then sent as query params here).
"""

from fastapi import APIRouter, Depends, HTTPException

from app.utils.auth import get_current_user_id
from app.utils.google_places import search_nearby_doctors, get_place_details

router = APIRouter(prefix="/patient", tags=["nearby-doctors"])


@router.get("/nearby-doctors")
def nearby_doctors(
    lat: float,
    lng: float,
    radius: int = 5000,
    user_id: str = Depends(get_current_user_id),
):
    try:
        results = search_nearby_doctors(lat, lng, radius)
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Failed to search nearby doctors: {str(e)}")

    return {"count": len(results), "results": results}


@router.get("/nearby-doctors/{place_id}/details")
def nearby_doctor_details(
    place_id: str,
    user_id: str = Depends(get_current_user_id),
):
    try:
        details = get_place_details(place_id)
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Failed to fetch address: {str(e)}")

    return details