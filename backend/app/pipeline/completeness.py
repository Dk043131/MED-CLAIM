"""
pipeline/completeness.py — Pre-Submission Completeness Checklist

Catches administrative gaps (missing signature, missing date, missing line items)
immediately after OCR, bouncing incomplete bills before wasting coding/eligibility bandwidth.
"""
from __future__ import annotations
from typing import Dict, Any, List
from app.models import ExtractedJSON, CompletenessResult


def check_completeness(extracted: ExtractedJSON, raw_ocr: str = "", ocr_confidence: float = 100.0) -> CompletenessResult:
    """
    Validates essential bill components.
    Only triggers if OCR confidence >= 60.0% (illegible bills route to HITL instead).
    """
    # If OCR confidence is low, don't bounce as incomplete — route to HITL review instead
    if ocr_confidence < 60.0:
        return CompletenessResult(complete=True, missing_fields=[])

    missing: List[str] = []

    # Check 1: Doctor name / signature
    if not extracted.doctor_name and "dr" not in raw_ocr.lower() and "doctor" not in raw_ocr.lower():
        missing.append("Doctor's signature/name")

    # Check 2: Patient name
    if not extracted.patient_name:
        missing.append("Patient name")

    # Check 3: Date of bill
    if not extracted.date:
        missing.append("Bill date")

    # Check 4: Itemized charges / line items
    if not extracted.line_items and extracted.consultation_fee <= 0:
        missing.append("Itemized line items")

    return CompletenessResult(
        complete=len(missing) == 0,
        missing_fields=missing
    )
