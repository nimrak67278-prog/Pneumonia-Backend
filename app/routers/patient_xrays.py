"""
Patient X-ray history endpoints -- list, view, and delete a patient's
own past X-ray predictions. Uploading itself already happens via
/predict (which saves both the image and the prediction record).

All three endpoints here operate ONLY on records belonging to the
logged-in patient (matched by patient_id == their own user_id from the
token) -- there's no way to list, view, or delete someone else's X-ray.
"""

from fastapi import APIRouter, Depends, HTTPException

from app.utils.supabase_client import supabase
from app.utils.auth import get_current_user_id
from fastapi.responses import StreamingResponse
from io import BytesIO
from app.utils.pdf_report import generate_xray_report_pdf

router = APIRouter(prefix="/patient/xrays", tags=["patient-xrays"])


@router.get("")
def list_xrays(user_id: str = Depends(get_current_user_id)):
    response = (
        supabase.table("predictions")
        .select("id, prediction, confidence, risk_level, created_at")
        .eq("patient_id", user_id)
        .order("created_at", desc=True)
        .execute()
    )
    return response.data


@router.get("/{prediction_id}")
def get_xray_detail(prediction_id: str, user_id: str = Depends(get_current_user_id)):
    response = (
        supabase.table("predictions")
        .select("*")
        .eq("id", prediction_id)
        .eq("patient_id", user_id)  # ensures patients can't view another patient's record
        .execute()
    )

    if not response.data:
        raise HTTPException(status_code=404, detail="X-ray not found.")

    return response.data[0]


@router.get("/{prediction_id}/image-url")
def get_xray_image_url(prediction_id: str, user_id: str = Depends(get_current_user_id)):
    record_response = (
        supabase.table("predictions")
        .select("image_url")
        .eq("id", prediction_id)
        .eq("patient_id", user_id)
        .execute()
    )

    if not record_response.data:
        raise HTTPException(status_code=404, detail="X-ray not found.")

    storage_path = record_response.data[0]["image_url"]

    try:
        signed = supabase.storage.from_("xray-images").create_signed_url(
            storage_path, expires_in=300  # 5 minutes -- generate fresh each time it's needed
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate image URL: {str(e)}")

    return {"url": signed.get("signedURL") or signed.get("signedUrl")}


@router.delete("/{prediction_id}")
def delete_xray(prediction_id: str, user_id: str = Depends(get_current_user_id)):
    record_response = (
        supabase.table("predictions")
        .select("image_url")
        .eq("id", prediction_id)
        .eq("patient_id", user_id)
        .execute()
    )

    if not record_response.data:
        raise HTTPException(status_code=404, detail="X-ray not found.")

    storage_path = record_response.data[0]["image_url"]

    # Delete the stored image file first
    try:
        supabase.storage.from_("xray-images").remove([storage_path])
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete image file: {str(e)}")

    # Then delete the database record
    try:
        supabase.table("predictions").delete().eq("id", prediction_id).eq(
            "patient_id", user_id
        ).execute()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete X-ray record: {str(e)}")

    return {"message": "X-ray deleted.", "prediction_id": prediction_id}
@router.get("/{prediction_id}/report")
def download_report(prediction_id: str, user_id: str = Depends(get_current_user_id)):
    record_response = (
        supabase.table("predictions")
        .select("*")
        .eq("id", prediction_id)
        .eq("patient_id", user_id)
        .execute()
    )

    if not record_response.data:
        raise HTTPException(status_code=404, detail="X-ray not found.")

    record = record_response.data[0]

    # Fetch the patient's name to display on the report
    user_response = supabase.table("users").select("full_name").eq("id", user_id).execute()
    record["patient_name"] = user_response.data[0]["full_name"] if user_response.data else "N/A"

    image_bytes = None
    try:
        image_bytes = supabase.storage.from_("xray-images").download(record["image_url"])
    except Exception:
        pass

    pdf_bytes = generate_xray_report_pdf(record, image_bytes)

    filename = f"pneumoscan_report_{prediction_id[:8]}.pdf"

    return StreamingResponse(
        BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )