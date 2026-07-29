"""
pipeline/orchestrator.py — Stage 5: Claim Orchestrator & Differentiator Engine

Wires together Stages 1–4 + Differentiator Features:
  Stage 1: OCR                    → raw_ocr, ocr_confidence
  Stage 2: Structure & Fingerprint → extracted_json, fingerprint_matched
  Stage 2.5: Completeness Check   → completeness (bounces missing signature/date)
  Stage 3: ICD-10 Harmonization   → coding_result
  Stage 4: Eligibility Check      → eligibility (with family cross-match)
  Stage 4.5: Claim Twins Check    → is_duplicate
  Stage 5: Plain Translation      → plain_reason
  Stage 6: Time Saved Receipt     → time_saved_receipt
"""
from __future__ import annotations
import time
import uuid
from typing import List
from app.config import OCR_CONFIDENCE_THRESHOLD
from app.models import ClaimRecord, FingerprintMatch
from app.pipeline.ocr import ocr_bill
from app.pipeline.clean_ocr import structure_ocr
from app.pipeline.fingerprint import check_clinic_fingerprint
from app.pipeline.completeness import check_completeness
from app.pipeline.harmonizer import harmonize_codes, needs_review
from app.pipeline.eligibility import check_eligibility
from app.pipeline.duplicates import check_duplicate_claims
from app.pipeline.translator import translate_rejection_reasons


def _generate_claim_id() -> str:
    """Generates a CLM-XXXX style claim ID."""
    short = str(uuid.uuid4().int)[:4].lstrip("0") or "1000"
    return f"CLM-{short}"


def _detect_clinic_id(raw_ocr: str, filename: str) -> str:
    """Detects clinic ID from bill text or filename for fingerprint lookup."""
    lower_text = (raw_ocr + " " + filename).lower()
    if "menon" in lower_text:
        return "CLINIC-MENON"
    if "city general" in lower_text or "city" in lower_text:
        return "CLINIC-CITY-GENERAL"
    if "apollo" in lower_text:
        return "CLINIC-APOLLO"
    return "CLINIC-DEFAULT"


def process_claim(file_bytes: bytes, filename: str = "") -> ClaimRecord:
    """
    Main pipeline entry point with all 6 differentiator features integrated.
    """
    t0 = time.perf_counter()

    # ── Stage 1: OCR ─────────────────────────────────────────────────────────
    raw_ocr, ocr_confidence = ocr_bill(file_bytes, filename)
    clinic_id = _detect_clinic_id(raw_ocr, filename)
    print(f"[Pipeline] Stage 1 OCR done ({ocr_confidence:.1f}% confidence) | Clinic: {clinic_id}")

    # ── Stage 2: Structure OCR & Clinic Fingerprint Check ──────────────────────
    extracted = structure_ocr(raw_ocr)
    extracted.clinic_id = clinic_id

    # Check clinic fingerprint memory cache for doctor_name
    fingerprint_hit: FingerprintMatch | None = None
    if extracted.doctor_name:
        fp_match = check_clinic_fingerprint(clinic_id, extracted.doctor_name, "doctor_name")
        if fp_match:
            fingerprint_hit = FingerprintMatch(
                matched=True,
                field="doctor_name",
                original=extracted.doctor_name,
                corrected=fp_match["corrected_value"],
                hit_count=fp_match["hit_count"]
            )
            extracted.doctor_name = fp_match["corrected_value"]
            ocr_confidence = max(ocr_confidence, 92.0)  # Boost confidence on fingerprint match

    print(f"[Pipeline] Stage 2 Structure done | Fingerprint matched: {fingerprint_hit.matched if fingerprint_hit else False}")

    # ── Stage 2.5: Completeness Checklist ────────────────────────────────────
    completeness = check_completeness(extracted, raw_ocr, ocr_confidence)
    print(f"[Pipeline] Stage 2.5 Completeness check | Complete: {completeness.complete}")

    # ── Stage 3: ICD-10 Harmonization ─────────────────────────────────────────
    coding_result = harmonize_codes(extracted.symptoms)
    print(f"[Pipeline] Stage 3 Harmonize done")

    # ── Stage 4: Eligibility Check (with Family Fallback) ─────────────────────
    eligibility = check_eligibility(extracted.patient_name, extracted.age)
    print(f"[Pipeline] Stage 4 Eligibility done | Reason: {eligibility.reason}")

    # ── Stage 4.5: Claim Twins (Duplicate Check) ──────────────────────────────
    twin_check = check_duplicate_claims(extracted.patient_name, extracted.symptoms)
    is_duplicate = twin_check["is_duplicate"]
    twin_claim_ids = twin_check["twin_claim_ids"]
    print(f"[Pipeline] Stage 4.5 Duplicate check | Duplicate: {is_duplicate}")

    # ── Stage 5: Routing & Verdict Logic ──────────────────────────────────────
    reasons: List[str] = []

    # Check incomplete documentation bounce
    if not completeness.complete:
        route = "incomplete_documentation"
        status = "incomplete"
        reasons.append(f"Missing required fields: {', '.join(completeness.missing_fields)}")
    else:
        reason_ocr = ocr_confidence < OCR_CONFIDENCE_THRESHOLD
        reason_icd = needs_review(coding_result)
        reason_elig = not eligibility.eligible
        reason_dup = is_duplicate

        if reason_ocr or reason_icd or reason_elig or reason_dup:
            route = "human_review"
            status = "pending_review"
            if reason_ocr:
                reasons.append(f"Low OCR confidence ({ocr_confidence:.1f}% < {OCR_CONFIDENCE_THRESHOLD}%)")
            if reason_icd:
                reasons.append("One or more ICD-10 codes have low confidence")
            if reason_elig:
                reasons.append(eligibility.reason)
            if reason_dup:
                reasons.append(twin_check["reason"])
        else:
            route = "auto_approve"
            status = "approved"

    # Stage 6: Plain language translation & Time Saved Receipt
    plain_reason = translate_rejection_reasons(reasons) if route != "auto_approve" else "Claim auto-adjudicated successfully with high confidence."
    total_time = time.perf_counter() - t0
    time_saved_receipt = f"Processed in {total_time:.2f}s. Manually, this typically takes 12–15 days."

    print(f"[Pipeline] Route → {route} | Total time: {total_time:.2f}s")

    return ClaimRecord(
        claim_id=_generate_claim_id(),
        raw_ocr=raw_ocr,
        extracted_json=extracted,
        coding_result=coding_result,
        eligibility=eligibility,
        route=route,
        status=status,
        completeness=completeness,
        fingerprint_matched=fingerprint_hit,
        is_duplicate=is_duplicate,
        twin_claim_ids=twin_claim_ids,
        plain_reason=plain_reason,
        processing_seconds=round(total_time, 2),
        time_saved_receipt=time_saved_receipt,
    )
