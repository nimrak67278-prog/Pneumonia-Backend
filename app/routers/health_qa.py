"""
"Ask PneumoScan AI" -- suggests thoughtful questions a patient could ask
their doctor, tailored to their occupation and their most recent X-ray
screening result. Nothing here is stored -- each request generates a
fresh set of questions.
"""

from fastapi import APIRouter, Depends, HTTPException

from app.utils.auth import get_current_user_id
from app.utils.gemini_qa import get_suggested_questions
from app.utils.supabase_client import supabase

router = APIRouter(prefix="/patient/ask-ai", tags=["health-qa"])


def _get_latest_diagnosis(user_id: str) -> str | None:
    """Returns 'PNEUMONIA', 'NORMAL', or None if the patient has no X-ray on record."""
    response = (
        supabase.table("predictions")
        .select("prediction")
        .eq("patient_id", user_id)
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    if response.data:
        return response.data[0]["prediction"]
    return None


@router.get("/suggested-questions")
def suggested_questions(
    occupation: str,
    user_id: str = Depends(get_current_user_id),
):
    diagnosis = _get_latest_diagnosis(user_id)
    questions = get_suggested_questions(occupation, diagnosis)

    if not questions:
        raise HTTPException(
            status_code=503,
            detail="Unable to generate suggested questions right now. Please try again shortly.",
        )

    return {"occupation": occupation, "diagnosis": diagnosis, "questions": questions}