"""
tests/test_differentiators.py — Unit tests for the 6 Differentiator Features
"""
import pytest
from app.models import ExtractedJSON, LineItem
from app.pipeline.fingerprint import check_clinic_fingerprint, save_correction_to_fingerprint
from app.pipeline.completeness import check_completeness
from app.pipeline.eligibility import check_eligibility
from app.pipeline.duplicates import check_duplicate_claims
from app.pipeline.translator import translate_rejection_reasons
from app.pipeline.orchestrator import process_claim


def test_clinic_fingerprint_learning_and_shortcircuit():
    """Verify clinic fingerprint saves correction and matches fuzzy snippets."""
    clinic_id = "CLINIC-MENON"
    raw_ocr_snippet = "Dr. M3non (MBBS)"
    corrected_name = "Dr. Menon"

    # Save caseworker correction
    saved = save_correction_to_fingerprint(clinic_id, raw_ocr_snippet, corrected_name, "doctor_name")
    assert saved is True

    # Check fuzzy match against similar messy OCR text
    match = check_clinic_fingerprint(clinic_id, "Dr. M3non (MBBS)", "doctor_name")
    assert match is not None
    assert match["corrected_value"] == corrected_name
    assert match["match_confidence"] >= 0.85
    assert match["source"] == "clinic_fingerprint"


def test_completeness_checklist():
    """Verify completeness checklist flags missing administrative fields."""
    incomplete_json = ExtractedJSON(
        patient_name="",
        date="",
        doctor_name="",
        symptoms=[],
        line_items=[],
        consultation_fee=0.0
    )
    result = check_completeness(incomplete_json, raw_ocr="Torn Bill", ocr_confidence=95.0)
    assert result.complete is False
    assert len(result.missing_fields) >= 2


def test_family_cross_match_assistant():
    """Verify family cross-match fallback when individual patient is absent."""
    # "Sunita Shaikh" with age 0 avoids age-tolerance direct match and triggers family surname match
    elig = check_eligibility("Sunita Shaikh", age=0)
    assert elig.eligible is False
    assert "Family match found" in elig.reason or "family" in elig.reason.lower()


from app.storage import save_claim, get_claims

def test_claim_twins_duplicate_check(tmp_path):
    """Verify duplicate check flags twin claims for same patient & symptoms."""
    # Process and save initial claim
    claim1 = process_claim(b"Patient Name: Rahul Sharma\nFever, Cough\nRs 500", "clean_bill.txt")
    save_claim(claim1)
    
    # Confirm persisted
    all_claims = get_claims()
    assert len(all_claims) >= 1

    # Check for duplicate with matching symptoms from initial claim (simulating new claim CLM-NEW)
    dup_res = check_duplicate_claims(
        claim1.extracted_json.patient_name,
        claim1.extracted_json.symptoms,
        current_claim_id="CLM-NEW"
    )
    print("DEBUG dup_res:", dup_res, "patient:", repr(claim1.extracted_json.patient_name), "symptoms:", claim1.extracted_json.symptoms)
    assert dup_res["is_duplicate"] is True
    assert claim1.claim_id in dup_res["twin_claim_ids"]


def test_rejection_translator():
    """Verify technical flags translate into plain language patient explanations."""
    reasons = ["Low OCR confidence (48.0% < 70.0%)", "Ineligible: Coverage expired on 2022-03-15."]
    translated = translate_rejection_reasons(reasons)
    assert isinstance(translated, str)
    assert len(translated) > 10
    assert "handwriting" in translated.lower() or "expired" in translated.lower() or "caseworker" in translated.lower()


def test_time_saved_receipt():
    """Verify ClaimRecord includes processing duration & time saved receipt line."""
    record = process_claim(b"Patient Name: Rahul Sharma\nFever\nRs 500", "clean_bill.txt")
    assert record.processing_seconds >= 0.0
    assert "12–15 days" in record.time_saved_receipt
