"""
Uses Gemini to generate suggested questions for the "Ask PneumoScan AI"
feature -- specifically, the kind of thoughtful questions patients often
DON'T think to ask in the moment, but wish they had once they've left
the doctor's clinic.

This does NOT generate answers, and nothing here is persisted to the
database -- each call generates a fresh set of questions, returned
directly to the app.

Reuses the same GEMINI_API_KEY already configured for the X-ray
gatekeeper check (see gemini_gatekeeper.py) -- no new API key needed.
"""

import os
import json
import logging

import google.generativeai as genai

logger = logging.getLogger(__name__)

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

_model = None
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
    _model = genai.GenerativeModel("gemini-3.1-flash-lite")


DIAGNOSED_QUESTIONS_PROMPT = """A patient has just been diagnosed with
pneumonia via chest X-ray screening. Their occupation is: {occupation}

Generate exactly 6 SPECIFIC, THOUGHTFUL questions this patient should
ask their doctor -- specifically the kind of questions patients rarely
think to ask in the moment during a stressful appointment, but often
wish afterward that they had. Go beyond the obvious ("how do I treat
this?") and include things like: how their specific occupation affects
recovery or risk of relapse, what warning signs mean they should return
immediately, how this affects their daily work duties, and any
non-obvious lifestyle or timeline questions.

CRITICAL LANGUAGE REQUIREMENT: This patient has NO medical background.
Write every question in plain, everyday language a non-medical person
would actually say out loud to their doctor. NEVER use clinical or
technical terms (e.g. do not say "mucociliary clearance," "volatile
organic compounds," "airway inflammation," "bacterial load" -- say
"my lungs clearing mucus," "cleaning product fumes," "swelling in my
airways," "germs in the air" instead). Each question should be short
(one sentence, easy to read out loud) and sound like something a real
person would naturally ask, not a textbook.

Respond with ONLY a JSON array of 6 strings, nothing else. Example format:
["Question one?", "Question two?", "Question three?", "Question four?", "Question five?", "Question six?"]
"""

NOT_DIAGNOSED_QUESTIONS_PROMPT = """A patient's recent chest X-ray
screening came back NORMAL (no pneumonia detected). Their occupation
is: {occupation}

Generate exactly 6 SPECIFIC, THOUGHTFUL questions this patient could ask
a doctor about respiratory health and pneumonia prevention -- the kind
of non-obvious questions people rarely think to ask during a routine
visit, but would find valuable. Consider risks specific to their
occupation (e.g. dust/chemical exposure, close patient contact, extended
outdoor exposure), early warning signs they might overlook, and
preventive steps that aren't common knowledge.

CRITICAL LANGUAGE REQUIREMENT: This patient has NO medical background.
Write every question in plain, everyday language a non-medical person
would actually say out loud to their doctor. NEVER use clinical or
technical terms (e.g. do not say "mucociliary clearance," "volatile
organic compounds," "airway inflammation," "bacterial load" -- say
"my lungs clearing mucus," "cleaning product fumes," "swelling in my
airways," "germs in the air" instead). Each question should be short
(one sentence, easy to read out loud) and sound like something a real
person would naturally ask, not a textbook.

Respond with ONLY a JSON array of 6 strings, nothing else. Example format:
["Question one?", "Question two?", "Question three?", "Question four?", "Question five?", "Question six?"]
"""


def get_suggested_questions(occupation: str, diagnosis: str | None) -> list[str]:
    if _model is None:
        return []

    prompt_template = (
        DIAGNOSED_QUESTIONS_PROMPT
        if diagnosis == "PNEUMONIA"
        else NOT_DIAGNOSED_QUESTIONS_PROMPT
    )

    try:
        response = _model.generate_content(prompt_template.format(occupation=occupation))
        text = response.text.strip()
        if text.startswith("```"):
            text = text.strip("`")
            if text.startswith("json"):
                text = text[4:].strip()
        questions = json.loads(text)
        if isinstance(questions, list):
            return questions[:6]
        return []
    except Exception as e:
        logger.warning(f"Failed to generate suggested questions: {e}")
        return []