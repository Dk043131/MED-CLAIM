"""
pipeline/orchestrator.py — Stage 5: Claim Orchestrator & Differentiator Engine

Wires together Stages 1–4 + Differentiator Features:
  Stage 1: OCR                    → raw_ocr, ocr_confidence
  Stage 2: Structure & Fingerprint → extracted_json, fingerprint_matched
             (Gemini combined OCR+extract in one API call if key available)
  Stage 2.5: Completeness Check   → completeness (bounces missing signature/date)
  Stage 3: ICD-10 Harmonization   → coding_result (PANDA codes + Claude)
  Stage 4: Eligibility Check      → eligibility (with family cross-match)
  Stage 4.5: Claim Twins Check    → is_duplicate
  Stage 5: Plain Translation      → plain_reason
  Stage 6: Time Saved Receipt     → time_saved_receipt
"""
from __future__ import annotations
import time
import uuid
import datetime
from typing import List, Callable, Optional
from app.config import OCR_CONFIDENCE_THRESHOLD, USE_GEMINI
from app.models import ClaimRecord, FingerprintMatch, LifecycleEvent
from app.pipeline.ocr import ocr_bill
from app.pipeline.clean_ocr import structure_ocr
from app.pipeline.fingerprint import check_clinic_fingerprint
from app.pipeline.completeness import check_completeness
from app.pipeline.harmonizer import harmonize_codes, needs_review
from app.pipeline.eligibility import check_eligibility
from app.pipeline.duplicates import check_duplicate_claims
from app.pipeline.translator import translate_rejection_reasons
from app.pipeline.snomed_mapper import lookup_snomed_ct
from app.pipeline.fraud_scorer import evaluate_fraud_risk
from app.pipeline.portal import submit_to_government_portal
from app.pipeline.pmjay_procedure_check import check_procedure_scope, needs_procedure_review


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
    if "adichunchanagiri" in lower_text or "aims" in lower_text:
        return "CLINIC-AIMS-BGRNAGARA"
    if "aiims" in lower_text:
        return "CLINIC-AIIMS"
    if "fortis" in lower_text:
        return "CLINIC-FORTIS"
    if "max" in lower_text and "hospital" in lower_text:
        return "CLINIC-MAX"
    return "CLINIC-DEFAULT"


def process_claim(
    file_bytes: bytes,
    filename: str = "",
    progress_callback: Optional[Callable[[int, str, str], None]] = None
) -> ClaimRecord:
    """
    Main pipeline entry point with all 6 differentiator features integrated.
    
    Args:
        file_bytes: Raw bytes of the medical bill image/PDF
        filename: Original filename (used for MIME type detection and clinic ID)
        progress_callback: Optional callback(stage_num, stage_name, status)
                          Called at each stage start/end for SSE streaming
    
    Returns:
        ClaimRecord with all pipeline results populated.
    """
    t0 = time.perf_counter()
    stage_times = {}
    lifecycle_events: List[LifecycleEvent] = []

    def record_event(stage_name: str, status: str, elapsed_ms: int, reason: str = ""):
        lifecycle_events.append(
            LifecycleEvent(
                stage=stage_name,
                status=status,
                timestamp_iso=datetime.datetime.utcnow().isoformat() + "Z",
                elapsed_ms=elapsed_ms,
                reason=reason,
            )
        )

    record_event("SUBMITTED", "success", 0, "Claim uploaded and received by pipeline")

    def emit(stage: int, name: str, status: str = "running"):
        """Emit progress event via callback."""
        if progress_callback:
            try:
                progress_callback(stage, name, status)
            except Exception:
                pass

    # ── Stage 1: OCR ─────────────────────────────────────────────────────────
    emit(1, "OCR & Document Reading", "running")
    t_stage = time.perf_counter()

    # If Gemini available, use combined OCR+extraction in one call (faster + better)
    gemini_extracted = None
    if USE_GEMINI:
        try:
            from app.pipeline.gemini_ocr import extract_with_gemini, gemini_dict_to_extracted
            raw_ocr, gemini_data, ocr_confidence = extract_with_gemini(file_bytes, filename)
            gemini_extracted = gemini_dict_to_extracted(gemini_data)
            print(f"[Pipeline] Stage 1+2 Gemini combined ({ocr_confidence:.1f}% confidence)")
        except Exception as exc:
            print(f"[Pipeline] Gemini combined failed ({exc}); falling back to separate OCR+structure")
            gemini_extracted = None
            raw_ocr, ocr_confidence = ocr_bill(file_bytes, filename)
    else:
        raw_ocr, ocr_confidence = ocr_bill(file_bytes, filename)

    clinic_id = _detect_clinic_id(raw_ocr, filename)
    stage_times["ocr"] = time.perf_counter() - t_stage
    record_event("OCR", "success", int(stage_times.get("ocr", 0) * 1000), f"OCR confidence {ocr_confidence:.1f}%")
    print(f"[Pipeline] Stage 1 OCR done ({ocr_confidence:.1f}% confidence) | Clinic: {clinic_id}")
    emit(1, "OCR & Document Reading", "done")

    # ── Stage 2: Structure OCR & Clinic Fingerprint Check ──────────────────────
    emit(2, "Structuring & Fingerprinting", "running")
    t_stage = time.perf_counter()

    if gemini_extracted is not None:
        # Already extracted by Gemini — just set clinic_id
        extracted = gemini_extracted
        extracted.clinic_id = clinic_id
    else:
        # Fall back to separate structure call
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

    stage_times["structure"] = time.perf_counter() - t_stage
    record_event("STRUCTURED", "success", int(stage_times.get("structure", 0) * 1000), f"Clinic ID: {clinic_id}")
    print(f"[Pipeline] Stage 2 Structure done | Fingerprint matched: {fingerprint_hit.matched if fingerprint_hit else False}")
    emit(2, "Structuring & Fingerprinting", "done")

    # ── Stage 2.5: Completeness Checklist ────────────────────────────────────
    emit(3, "Completeness & Validation", "running")
    t_stage = time.perf_counter()
    completeness = check_completeness(extracted, raw_ocr, ocr_confidence)
    stage_times["completeness"] = time.perf_counter() - t_stage
    print(f"[Pipeline] Stage 2.5 Completeness check | Complete: {completeness.complete}")
    emit(3, "Completeness & Validation", "done")

    # ── Stage 3: ICD-10 Harmonization (PANDA codes) + SNOMED-CT ──────────────
    emit(4, "ICD-10 Clinical Code Harmonization", "running")
    t_stage = time.perf_counter()
    coding_result = harmonize_codes(extracted.symptoms)
    for d in coding_result.coded_diagnoses:
        sc_code, sc_desc = lookup_snomed_ct(d.icd10_code, d.symptom)
        d.snomed_ct_code = sc_code
        d.snomed_ct_description = sc_desc
    stage_times["harmonize"] = time.perf_counter() - t_stage
    record_event("CODED", "success", int(stage_times.get("harmonize", 0) * 1000), f"Mapped {len(coding_result.coded_diagnoses)} ICD-10 & SNOMED-CT codes")
    print(f"[Pipeline] Stage 3 Harmonize done | Codes: {len(coding_result.coded_diagnoses)}")
    emit(4, "ICD-10 Clinical Code Harmonization", "done")

    # ── Stage 3.5: PM-JAY Procedure Scope Check (new) ──────────────────────
    emit(5, "PM-JAY Procedure Scope Validation", "running")
    t_proc = time.perf_counter()
    icd10_codes = [d.icd10_code for d in coding_result.coded_diagnoses]
    line_items_text = [li.description for li in extracted.line_items]
    procedure_scope = check_procedure_scope(icd10_codes, line_items_text, extracted.symptoms)
    stage_times["procedure_scope"] = time.perf_counter() - t_proc
    record_event(
        "PROCEDURE_SCOPE",
        "warning" if not procedure_scope.covered else "success",
        int(stage_times["procedure_scope"] * 1000),
        f"Covered={procedure_scope.covered} | {procedure_scope.rejection_reason or procedure_scope.package_name or 'in scope'}",
    )
    print(f"[Pipeline] Stage 3.5 Procedure scope | Covered: {procedure_scope.covered} | Pkg: {procedure_scope.package_code}")
    emit(5, "PM-JAY Procedure Scope Validation", "done")

    # ── Stage 4: Eligibility Check with PM-JAY 3-Gate Engine ──────────────────
    emit(6, "PM-JAY Eligibility & Duplicate Check", "running")
    t_stage = time.perf_counter()
    eligibility = check_eligibility(
        extracted.patient_name,
        extracted.age,
        hospital_name=extracted.hospital_name,  # Gate 3: empanelment check
    )
    print(f"[Pipeline] Stage 4 PM-JAY Eligibility | Scheme: {getattr(eligibility, 'scheme', 'N/A')} | Gate: {getattr(eligibility, 'gate_results', {})}")
    print(f"[Pipeline] Stage 4 Eligibility done | Reason: {eligibility.reason}")

    # ── Stage 4.5: Claim Twins (Duplicate Check) ──────────────────────────────
    twin_check = check_duplicate_claims(extracted.patient_name, extracted.symptoms, filename=filename)
    is_duplicate = twin_check["is_duplicate"]
    twin_claim_ids = twin_check["twin_claim_ids"]
    stage_times["eligibility"] = time.perf_counter() - t_stage
    record_event(
        "ELIGIBILITY",
        "success" if eligibility.eligible else "warning",
        int(stage_times.get("eligibility", 0) * 1000),
        (
            f"PM-JAY | Scheme={getattr(eligibility, 'scheme', 'N/A')} | "
            f"SECC={getattr(eligibility, 'secc_category', 'N/A')} | "
            f"Cap=₹{getattr(eligibility, 'annual_cap_remaining_inr', 0):,.0f} | "
            f"{eligibility.reason or 'Patient eligible'}"
        ),
    )
    print(f"[Pipeline] Stage 4.5 Duplicate check | Duplicate: {is_duplicate}")
    emit(6, "PM-JAY Eligibility & Duplicate Check", "done")

    # ── Stage 4.8: Fraud Probability & Safety Guardrails ──────────────────────
    t_fraud = time.perf_counter()
    fraud_result = evaluate_fraud_risk(extracted, is_duplicate=is_duplicate)
    stage_times["fraud_check"] = time.perf_counter() - t_fraud
    record_event(
        "FRAUD_CHECK",
        "warning" if fraud_result.escalated_to_hitl else "success",
        int(stage_times.get("fraud_check", 0) * 1000),
        f"Risk={fraud_result.risk_level.upper()} (Score={fraud_result.fraud_score})",
    )
    print(f"[Pipeline] Stage 4.8 Fraud check | Score: {fraud_result.fraud_score} | Escalate: {fraud_result.escalated_to_hitl}")


    # ── Stage 5: Routing & Verdict Logic ──────────────────────────────────────
    emit(6, "Routing & Verdict", "running")
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
        reason_fraud = fraud_result.escalated_to_hitl
        reason_proc_scope = needs_procedure_review(procedure_scope)

        if reason_ocr or reason_icd or reason_elig or reason_dup or reason_fraud or reason_proc_scope:
            route = "human_review"
            status = "pending_review"
            if reason_ocr:
                reasons.append(f"Low OCR confidence ({ocr_confidence:.1f}% < {OCR_CONFIDENCE_THRESHOLD}%)")
            if reason_icd:
                reasons.append("One or more ICD-10 codes have low confidence — clinical review required")
            if reason_elig:
                # PM-JAY rejection type taxonomy
                rej_type = getattr(eligibility, "rejection_type", "")
                if rej_type == "cap_exhausted":
                    reasons.append(f"PM-JAY cap exhausted: {eligibility.reason}")
                elif rej_type == "hard_eligibility":
                    reasons.append(f"PM-JAY eligibility rejected: {eligibility.reason}")
                else:
                    reasons.append(eligibility.reason)
            if reason_proc_scope:
                # PM-JAY procedure scope rejection
                scope_rej = procedure_scope.rejection_reason
                if scope_rej == "outpatient_only":
                    reasons.append("PM-JAY covers hospitalisation only — outpatient-only visits are not reimbursed.")
                elif scope_rej == "dental_cosmetic":
                    reasons.append("PM-JAY does not cover dental, cosmetic, or elective aesthetic procedures.")
                elif scope_rej == "not_in_list":
                    reasons.append("Procedure is not in PM-JAY's covered 1,929-package list.")
                else:
                    reasons.append(f"Procedure scope check failed: {scope_rej}")
            if reason_dup:
                reasons.append(twin_check["reason"])
            if reason_fraud:
                reasons.append(f"High fraud risk score ({fraud_result.fraud_score}): {'; '.join(fraud_result.flags)}")
        else:
            route = "auto_approve"
            status = "approved"

    # Stage 6: Plain language translation & Time Saved Receipt
    plain_reason = (
        translate_rejection_reasons(reasons)
        if route != "auto_approve"
        else "Claim auto-adjudicated successfully — all checks passed with high confidence."
    )

    total_time = time.perf_counter() - t0
    stage_breakdown = " | ".join(f"{k}: {v:.2f}s" for k, v in stage_times.items())
    time_saved_receipt = (
        f"AI-processed in {total_time:.2f}s ({stage_breakdown}). "
        f"Manual adjudication typically takes 12–15 days. "
        f"Time saved: ~14 days."
    )

    print(f"[Pipeline] Route → {route} | Total: {total_time:.2f}s")
    emit(6, "Routing & Verdict", "done")

    claim_id = _generate_claim_id()
    temp_record = ClaimRecord(
        claim_id=claim_id,
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
        lifecycle_events=lifecycle_events,
        fraud_result=fraud_result,
    )

    portal_sub = submit_to_government_portal(temp_record)
    record_event(
        "PORTAL",
        "success" if portal_sub.submitted else "warning",
        0,
        f"Portal status={portal_sub.portal_status}",
    )
    record_event(
        "COMPLETE",
        "success" if status == "approved" else "warning",
        int(total_time * 1000),
        f"Final verdict={status.upper()}",
    )

    temp_record.portal_submission = portal_sub
    temp_record.lifecycle_events = lifecycle_events
    return temp_record

