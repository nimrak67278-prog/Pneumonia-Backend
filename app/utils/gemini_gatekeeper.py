"""
Uses Google Gemini's vision capability to confirm an uploaded image is
actually a chest X-ray before running it through the pneumonia detection
model.
"""

import os
import base64
import logging

import google.generativeai as genai

logger = logging.getLogger(__name__)

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

_model = None
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
    _model = genai.GenerativeModel("gemini-3.1-flash-lite")
else:
    logger.warning(
        "GEMINI_API_KEY not set. Gemini gatekeeper check will be skipped "
        "and the grayscale heuristic fallback will be used instead."
    )

GATEKEEPER_PROMPT = (
    "You are checking an uploaded medical image for a pneumonia detection "
    "system. Look at this image carefully, including cases where it may be "
    "a phone photo of a screen/monitor displaying an X-ray (which can have "
    "glare, color artifacts, or visible UI elements around it).\n\n"
    "Answer with exactly one word: YES if this image shows a chest X-ray "
    "(a radiograph of the chest/lungs/ribcage), or NO if it does not "
    "(e.g. it's a photo of a person, an object, a scene, a different type "
    "of medical scan such as an MRI or CT, or anything else)."
)


def is_chest_xray_gemini(image_bytes: bytes, content_type: str = "image/jpeg") -> bool | None:
    """
    Returns:
        True  -> Gemini confirms this is a chest X-ray
        False -> Gemini confirms this is NOT a chest X-ray
        None  -> Gemini check unavailable (no API key, or request failed);
                 caller should fall back to the heuristic check instead.
    """
    if _model is None:
        return None

    try:
        response = _model.generate_content(
            [
                GATEKEEPER_PROMPT,
                {"mime_type": content_type, "data": image_bytes},
            ]
        )
        answer = response.text.strip().upper()
        return answer.startswith("YES")
    except Exception as e:
        logger.warning(f"Gemini gatekeeper check failed, falling back to heuristic: {e}")
        return None
