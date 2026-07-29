"""
pipeline/translator.py — Rejection Reason Translator

Translates technical rejection flags into a single, empathetic, plain-language sentence
that patients and clinic submitters without medical/insurance backgrounds can understand.
"""
from __future__ import annotations
from typing import List


def translate_rejection_reasons(reasons: List[str]) -> str:
    """
    Translates technical pipeline flags into a single patient-friendly sentence.
    """
    if not reasons:
        return "Your claim was flagged for standard administrative review by a caseworker."

    combined = " ".join(reasons).lower()

    if "missing" in combined or "incomplete" in combined:
        return "The bill is missing required administrative details (such as doctor signature or date) and needs to be completed before processing."

    if "duplicate" in combined:
        return "This bill appears to match a claim already submitted in our system and is flagged for duplicate review."

    if "family match" in combined:
        return "Individual coverage was not found, but a family member's policy was detected for caseworker verification."

    if "expired" in combined:
        return "The patient's insurance coverage appears to have expired prior to the date of service."

    if "ineligible" in combined:
        return "The patient's policy details could not be automatically verified in the welfare database."

    if "ocr" in combined:
        return "The bill handwriting or image quality was low, so a caseworker is double-checking the extracted details."

    if "icd-10" in combined or "confidence" in combined:
        return "Specific diagnosis codes require manual confirmation by a caseworker to guarantee maximum insurance benefit."

    return "Claim flagged for routine caseworker verification to ensure accurate coverage."
