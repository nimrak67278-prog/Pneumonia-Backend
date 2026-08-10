"""
Generates a patient-friendly explanation, recommendation, and risk level
based on the model's prediction label and confidence score.

This is template-based (not LLM-generated) intentionally:
- Fast, free, no external API dependency
- Deterministic and safe for a medical-adjacent FYP demo
- No risk of API downtime during your defense/presentation
"""

from typing import Tuple


def get_explanation_and_recommendation(label: str, confidence: float) -> Tuple[str, str, str]:
    """
    Args:
        label: "PNEUMONIA" or "NORMAL"
        confidence: value between 0 and 100 (percentage)

    Returns:
        (explanation, recommendation, risk_level)
    """
    if label == "PNEUMONIA":
        if confidence >= 90:
            risk_level = "high"
            explanation = (
                "The model detected strong indicators of lung opacity and "
                "consolidation patterns that are typically associated with "
                "pneumonia."
            )
            recommendation = (
                "This is a high-confidence result. Please consult a doctor "
                "or pulmonologist as soon as possible for confirmation and "
                "treatment."
            )
        elif confidence >= 70:
            risk_level = "moderate-high"
            explanation = (
                "The model detected patterns commonly associated with "
                "pneumonia, with moderate-to-high confidence."
            )
            recommendation = (
                "We recommend visiting a doctor soon to confirm this "
                "result through clinical examination."
            )
        else:
            risk_level = "moderate"
            explanation = (
                "The model detected some signs that may indicate pneumonia, "
                "but the confidence level is relatively low."
            )
            recommendation = (
                "This result is uncertain. Please consult a doctor for a "
                "proper diagnosis rather than relying on this result alone."
            )
    else:  # NORMAL
        if confidence >= 90:
            risk_level = "low"
            explanation = (
                "The X-ray does not show significant signs of lung opacity "
                "or consolidation typically associated with pneumonia."
            )
            recommendation = (
                "No signs of pneumonia were detected. Continue regular "
                "health checkups as needed."
            )
        else:
            risk_level = "low-moderate"
            explanation = (
                "The X-ray appears mostly normal, though the model's "
                "confidence is moderate rather than high."
            )
            recommendation = (
                "Results appear normal, but if you are experiencing "
                "symptoms such as persistent cough, fever, or difficulty "
                "breathing, please consult a doctor for further evaluation."
            )

    return explanation, recommendation, risk_level


DISCLAIMER = (
    "This is an AI-assisted screening tool and not a substitute for "
    "professional medical diagnosis. Always consult a qualified doctor "
    "for confirmation and treatment decisions."
)
