"""
Searches Google Places for nearby hospitals/clinics/doctors, and fetches
the full precise address for one specific place on demand.

The GOOGLE_PLACES_API_KEY must only ever be used here, server-side --
never sent to the React Native app, which only calls our own
/patient/nearby-doctors endpoints and never talks to Google directly.
"""

import os
import requests

GOOGLE_PLACES_API_KEY = os.environ.get("GOOGLE_PLACES_API_KEY")

NEARBY_SEARCH_URL = "https://maps.googleapis.com/maps/api/place/nearbysearch/json"
PLACE_DETAILS_URL = "https://maps.googleapis.com/maps/api/place/details/json"


def search_nearby_doctors(lat: float, lng: float, radius_meters: int = 5000) -> list[dict]:
    if not GOOGLE_PLACES_API_KEY:
        raise RuntimeError("GOOGLE_PLACES_API_KEY is not configured.")

    params = {
        "location": f"{lat},{lng}",
        "radius": radius_meters,
        "type": "hospital",
        "keyword": "doctor clinic pulmonologist",
        "key": GOOGLE_PLACES_API_KEY,
    }

    response = requests.get(NEARBY_SEARCH_URL, params=params, timeout=10)
    response.raise_for_status()
    data = response.json()

    if data.get("status") not in ("OK", "ZERO_RESULTS"):
        raise RuntimeError(f"Google Places API error: {data.get('status')} - {data.get('error_message', '')}")

    results = []
    for place in data.get("results", []):
        location = place.get("geometry", {}).get("location", {})
        results.append(
            {
                "place_id": place.get("place_id"),
                "name": place.get("name"),
                "address": place.get("vicinity"),
                "rating": place.get("rating"),
                "total_ratings": place.get("user_ratings_total"),
                "latitude": location.get("lat"),
                "longitude": location.get("lng"),
                "open_now": place.get("opening_hours", {}).get("open_now"),
            }
        )

    return results


def get_place_details(place_id: str) -> dict:
    """
    Fetches the full, precise address (and a couple of useful extras)
    for one specific place -- called only when the patient taps "Get
    Address" on a specific doctor, not for every result in the list.
    """
    if not GOOGLE_PLACES_API_KEY:
        raise RuntimeError("GOOGLE_PLACES_API_KEY is not configured.")

    params = {
        "place_id": place_id,
        "fields": "name,formatted_address,formatted_phone_number,website,opening_hours",
        "key": GOOGLE_PLACES_API_KEY,
    }

    response = requests.get(PLACE_DETAILS_URL, params=params, timeout=10)
    response.raise_for_status()
    data = response.json()

    if data.get("status") != "OK":
        raise RuntimeError(f"Google Places API error: {data.get('status')} - {data.get('error_message', '')}")

    result = data.get("result", {})
    return {
        "name": result.get("name"),
        "formatted_address": result.get("formatted_address"),
        "phone_number": result.get("formatted_phone_number"),
        "website": result.get("website"),
        "open_now": result.get("opening_hours", {}).get("open_now"),
    }