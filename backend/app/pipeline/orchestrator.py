"""
pipeline/orchestrator.py — Stage 5: Claim Orchestrator

process_claim() wires together Stages 1–4:
  Stage 1: OCR           → raw_ocr, ocr_confidence
  Stage 2: Structure     → extracted_json
  Stage 3: ICD-10 codes  → coding_result
  Stage 4: Eligibility   → eligibility

Routing logic (deterministic, auditable):
  route = "human_review" if ANY of these conditions is true:
    A. OCR confidence < OCR_CONFIDENCE_THRESHOLD    (illegible bill)
    B. Any ICD-10 confidence < CONFIDENCE_THRESHOLD  (ambiguous coding)
    C. eligibility.eligible == False                  (not covered)

  Otherwise route = "auto_approve"

Status mirrors route:
  auto_approve  → status = "approved"
  human_review  → status = "pending_review"
"""
from __future__ import annotations
import time
import uuid
from app.config import OCR_CONFIDENCE_THRESHOLD
from app.models import ClaimRecord
from app.pipeline.ocr import ocr_bill
from app.pipeline.clean_ocr import structure_ocr
from app.pipeline.harmonizer import harmonize_codes, needs_review
from app.pipeline.eligibility import check_eligibility


def _generate_claim_id() -> str:
    """Generates a CLM-XXXX style claim ID."""
    short = str(uuid.uuid4().int)[:4].lstrip("0") or "1000"
    return f"CLM-{short}"


def process_claim(file_bytes: bytes, filename: str = "") -> ClaimRecord:
    """
    Main pipeline entry point.

    Args:
        file_bytes: Raw bytes of the uploaded bill image/PDF.
        filename:   Original filename (used by OCR stub to select test case).

    Returns:
        A fully populated ClaimRecord ready to be persisted and returned via API.
    """
    t0 = time.perf_counter()

    # ── Stage 1: OCR ─────────────────────────────────────────────────────────
    raw_ocr, ocr_confidence = ocr_bill(file_bytes, filename)
    print(f"[Pipeline] Stage 1 OCR done ({ocr_confidence:.1f}% confidence) — {time.perf_counter()-t0:.2f}s")

    # ── Stage 2: Structure OCR text ───────────────────────────────────────────
    extracted = structure_ocr(raw_ocr)
    print(f"[Pipeline] Stage 2 Structure done — {time.perf_counter()-t0:.2f}s")

    # ── Stage 3: ICD-10 harmonization ─────────────────────────────────────────
    coding_result = harmonize_codes(extracted.symptoms)
    print(f"[Pipeline] Stage 3 Harmonize done — {time.perf_counter()-t0:.2f}s")

    # ── Stage 4: Eligibility check ────────────────────────────────────────────
    eligibility = check_eligibility(extracted.patient_name, extracted.age)
    print(f"[Pipeline] Stage 4 Eligibility done — {time.perf_counter()-t0:.2f}s")

    # ── Routing Logic ─────────────────────────────────────────────────────────
    reason_a = ocr_confidence < OCR_CONFIDENCE_THRESHOLD
    reason_b = needs_review(coding_result)
    reason_c = not eligibility.eligible

    if reason_a or reason_b or reason_c:
        route = "human_review"
        status = "pending_review"
        reasons = []
        if reason_a:
            reasons.append(f"Low OCR confidence ({ocr_confidence:.1f}% < {OCR_CONFIDENCE_THRESHOLD}%)")
        if reason_b:
            reasons.append("One or more ICD-10 codes have low confidence")
        if reason_c:
            reasons.append(f"Ineligible: {eligibility.reason}")
        print(f"[Pipeline] Route → human_review | Reasons: {'; '.join(reasons)}")
    else:
        route = "auto_approve"
        status = "approved"
        print(f"[Pipeline] Route → auto_approve")

    total_time = time.perf_counter() - t0
    print(f"[Pipeline] Total processing time: {total_time:.2f}s")

    return ClaimRecord(
        claim_id=_generate_claim_id(),
        raw_ocr=raw_ocr,
        extracted_json=extracted,
        coding_result=coding_result,
        eligibility=eligibility,
        route=route,
        status=status,
    )
