"""
FastAPI backend for the Pneumonia Detection FYP.

Endpoints:
    GET  /               -> health check
    POST /predict         -> upload an X-ray image, get prediction + explanation

Run locally with:
    uvicorn app.main:app --reload --port 8000

Then open http://127.0.0.1:8000/docs for the interactive Swagger UI
to test uploads directly from the browser.
"""

from datetime import datetime, timezone

from dotenv import load_dotenv
load_dotenv()

import uuid

from fastapi import FastAPI, File, UploadFile, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from app.routers.patient_xrays import router as patient_xrays_router
from app.utils.model_utils import predict_pneumonia
from app.utils.gemini_gatekeeper import is_chest_xray_gemini
from app.utils.explanation import get_explanation_and_recommendation, DISCLAIMER
from app.utils.auth import get_current_user_id
from app.utils.supabase_client import supabase
from app.routers.auth import router as auth_router
from app.routers.admin import router as admin_router
from app.routers.patient import router as patient_router
from app.routers.health_qa import router as health_qa_router
from app.routers.nearby_doctors import router as nearby_doctors_router
from app.routers.doctor import router as doctor_router
from app.routers.patient_doctors import router as patient_doctors_router
from app.routers.consultations import router as consultations_router

app = FastAPI(
    title="Pneumonia Detection API",
    description="AI-powered pneumonia detection from chest X-ray images.",
    version="1.0.0",
)
app.include_router(health_qa_router)
app.include_router(patient_xrays_router)
app.include_router(auth_router)
app.include_router(admin_router)
app.include_router(patient_router)
app.include_router(nearby_doctors_router)
app.include_router(doctor_router)
app.include_router(patient_doctors_router)
app.include_router(consultations_router)

# Allow the React Native app (and Expo dev server) to call this API.
# Tighten allow_origins to your actual domain/app scheme before production deployment.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/jpg", "image/png"}
MAX_FILE_SIZE_MB = 10


@app.get("/")
def health_check():
    return {"status": "ok", "message": "Pneumonia Detection API is running."}


@app.post("/predict")
async def predict(
    file: UploadFile = File(...),
    user_id: str = Depends(get_current_user_id),
):
    # --- Validate file type ---
    if file.content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{file.content_type}'. Please upload a JPEG or PNG image.",
        )

    # --- Read and validate file size ---
    image_bytes = await file.read()
    size_mb = len(image_bytes) / (1024 * 1024)
    if size_mb > MAX_FILE_SIZE_MB:
        raise HTTPException(
            status_code=400,
            detail=f"File too large ({size_mb:.1f} MB). Maximum allowed is {MAX_FILE_SIZE_MB} MB.",
        )

    # --- Validate this actually looks like a chest X-ray (Gemini vision check) ---
    gemini_result = is_chest_xray_gemini(image_bytes, file.content_type)

    if gemini_result is None:
        raise HTTPException(
            status_code=503,
            detail="Image validation service is temporarily unavailable. Please try again shortly.",
        )

    if not gemini_result:
        raise HTTPException(
            status_code=400,
            detail=(
                "The uploaded image doesn't appear to be a chest X-ray. "
                "Please upload a valid chest X-ray image."
            ),
        )

    # --- Run prediction ---
    try:
        result = predict_pneumonia(image_bytes)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Prediction failed: {str(e)}")

    # --- Generate explanation + recommendation ---
    explanation, recommendation, risk_level = get_explanation_and_recommendation(
        result["label"], result["confidence"]
    )
# --- Upload the X-ray image to Storage, under a folder named by user_id ---
    file_ext = (file.filename or "xray.jpg").split(".")[-1]
    storage_path = f"{user_id}/xray_{uuid.uuid4().hex}.{file_ext}"

    try:
        supabase.storage.from_("xray-images").upload(
            storage_path,
            image_bytes,
            {"content-type": file.content_type},
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save X-ray image: {str(e)}")

    # --- Save the prediction record to the database ---
    try:
        insert_response = (
            supabase.table("predictions")
            .insert(
                {
                    "patient_id": user_id,
                    "image_url": storage_path,
                    "prediction": result["label"],
                    "confidence": result["confidence"],
                    "risk_level": risk_level,
                    "explanation": explanation,
                    "recommendation": recommendation,
                }
            )
            .execute()
        )
        prediction_id = insert_response.data[0]["id"] if insert_response.data else None
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save prediction record: {str(e)}")

    return {
        "prediction_id": prediction_id,
        "prediction": result["label"],
        "confidence": result["confidence"],
        "raw_probability": result["raw_probability"],
        "risk_level": risk_level,
        "explanation": explanation,
        "recommendation": recommendation,
        "disclaimer": DISCLAIMER,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }