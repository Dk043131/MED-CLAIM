"""
models.py — Pydantic Schemas (exact contract shapes + differentiator extensions)
Every shape here matches the API contract verbatim so
Person B's frontend always gets exactly what it expects.
"""
from __future__ import annotations
from typing import List, Literal, Optional, Dict, Any
from pydantic import BaseModel, Field


# ── Sub-schemas ─────────────────────────────────────────────────────────────

class LineItem(BaseModel):
    description: str
    raw_text: str


class ExtractedJSON(BaseModel):
    clinic_id: str = "CLINIC-GENERAL"
    patient_name: str = ""
    age: int = 0
    sex: str = ""
    date: str = ""
    symptoms: List[str] = []
    line_items: List[LineItem] = []
    doctor_name: str = ""
    consultation_fee: float = 0.0
    ocr_confidence_notes: str = ""


class CompletenessResult(BaseModel):
    complete: bool = True
    missing_fields: List[str] = []


class FingerprintMatch(BaseModel):
    matched: bool = False
    field: str = ""
    original: str = ""
    corrected: str = ""
    hit_count: int = 0


class CodedDiagnosis(BaseModel):
    symptom: str
    icd10_code: str
    icd10_description: str
    confidence: float = Field(ge=0.0, le=1.0)


class CodingResult(BaseModel):
    coded_diagnoses: List[CodedDiagnosis] = []


class Eligibility(BaseModel):
    eligible: bool
    patient_id: str = ""
    income_bracket: str = ""
    existing_coverage: str = ""
    reason: str = ""


# ── Primary Claim Record (contract shape + extensions) ───────────────────────

class ClaimRecord(BaseModel):
    claim_id: str
    raw_ocr: str
    extracted_json: ExtractedJSON
    coding_result: CodingResult
    eligibility: Eligibility
    route: Literal["auto_approve", "human_review", "incomplete_documentation"]
    status: Literal["approved", "pending_review", "incomplete"]
    
    # Differentiator Extension Fields (Optional / Defaulted)
    completeness: CompletenessResult = Field(default_factory=CompletenessResult)
    fingerprint_matched: Optional[FingerprintMatch] = None
    is_duplicate: bool = False
    twin_claim_ids: List[str] = []
    plain_reason: str = ""
    processing_seconds: float = 0.5
    time_saved_receipt: str = "Processed in 0.5s. Manually, this typically takes 12–15 days."


# ── Dashboard Metrics ────────────────────────────────────────────────────────

class DashboardMetrics(BaseModel):
    total_claims: int
    auto_approved: int
    pending_review: int
    auto_adjudication_rate: float   # percentage 0–100


# ── API Response & Request helpers ──────────────────────────────────────────

class ApproveRequest(BaseModel):
    clinic_id: Optional[str] = None
    corrections: Optional[Dict[str, str]] = None  # e.g. {"doctor_name": "Dr. Priya Mehta"}


class ApproveResponse(BaseModel):
    claim_id: str
    status: Literal["approved"]
    fingerprint_updated: bool = False


class ErrorResponse(BaseModel):
    detail: str
