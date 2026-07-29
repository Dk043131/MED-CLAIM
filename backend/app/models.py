"""
models.py — Pydantic Schemas (exact contract shapes)
Every shape here matches the API contract verbatim so
Person B's frontend always gets exactly what it expects.
"""
from __future__ import annotations
from typing import List, Literal, Optional
from pydantic import BaseModel, Field


# ── Sub-schemas ─────────────────────────────────────────────────────────────

class LineItem(BaseModel):
    description: str
    raw_text: str


class ExtractedJSON(BaseModel):
    patient_name: str = ""
    age: int = 0
    sex: str = ""
    date: str = ""
    symptoms: List[str] = []
    line_items: List[LineItem] = []
    doctor_name: str = ""
    consultation_fee: float = 0.0
    ocr_confidence_notes: str = ""


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


# ── Primary Claim Record (contract shape) ───────────────────────────────────

class ClaimRecord(BaseModel):
    claim_id: str
    raw_ocr: str
    extracted_json: ExtractedJSON
    coding_result: CodingResult
    eligibility: Eligibility
    route: Literal["auto_approve", "human_review"]
    status: Literal["approved", "pending_review"]


# ── Dashboard Metrics ────────────────────────────────────────────────────────

class DashboardMetrics(BaseModel):
    total_claims: int
    auto_approved: int
    pending_review: int
    auto_adjudication_rate: float   # percentage 0–100


# ── API Response helpers ─────────────────────────────────────────────────────

class ApproveResponse(BaseModel):
    claim_id: str
    status: Literal["approved"]


class ErrorResponse(BaseModel):
    detail: str
