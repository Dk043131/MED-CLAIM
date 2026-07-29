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
    raw_text: str = ""
    amount: float = 0.0


class ExtractedJSON(BaseModel):
    clinic_id: str = "CLINIC-GENERAL"
    document_type: str = ""       # Discharge Summary, Lab Report, Prescription, Bill
    patient_name: str = ""
    patient_id: str = ""          # UHID / IP number
    hospital_name: str = ""       # Hospital/clinic name from bill
    age: int = 0
    sex: str = ""
    date: str = ""
    symptoms: List[str] = []
    diagnosis: List[str] = []
    procedure_performed: str = "" # e.g. CABG x 3, Appendectomy
    line_items: List[LineItem] = []
    prescribed_medications: List[Dict[str, Any]] = []
    lab_results: List[Dict[str, Any]] = []
    doctor_name: str = ""
    doctor_id: str = ""           # Doctor's registration/signature ID
    consultation_fee: float = 0.0
    total: float = 0.0
    ocr_confidence_notes: str = ""
    vitals: Dict[str, Any] = {}   # BP, pulse, RBS, SpO2, temp, weight
    advice: List[str] = []        # Non-medication instructions



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
    snomed_ct_code: str = ""
    snomed_ct_description: str = ""


class CodingResult(BaseModel):
    coded_diagnoses: List[CodedDiagnosis] = []


class Eligibility(BaseModel):
    eligible: bool
    patient_id: str = ""
    income_bracket: str = ""
    existing_coverage: str = ""
    reason: str = ""


class PMJAYEligibility(Eligibility):
    """Extended eligibility result for PM-JAY (Ayushman Bharat) claims."""
    secc_category: str = ""                          # rural_deprivation|urban_occupation|senior_citizen_70plus|asha_worker|state_supplementary|none
    family_id: str = ""                              # Shared floater pool key
    annual_cap_remaining_inr: float = 500000.0       # ₹5L family cap remaining
    senior_cap_remaining_inr: float = 500000.0       # Separate ₹5L for 70+ (2024 expansion)
    hospital_empanelled: bool = True                 # Hospital on PM-JAY list
    scheme: str = "PMJAY"                            # PMJAY|CMCHIS|MJPJAY|RGHS|WBHS|NONE
    fallback_scheme: str = ""                        # State scheme if not in PMJAY
    rejection_type: str = ""                         # hard_eligibility|procedure_scope|cap_exhausted|""
    gate_results: Dict[str, Any] = {}               # Per-gate pass/fail details for audit


class ProcedureScopeResult(BaseModel):
    """Result of PM-JAY Stage 3.5 — procedure scope gate."""
    covered: bool = True
    package_code: str = ""
    package_name: str = ""
    max_rate_inr: float = 0.0
    rejection_reason: str = ""                       # outpatient_only|dental_cosmetic|not_in_list|""


class HospitalEmpanelmentResult(BaseModel):
    """Result of hospital empanelment fuzzy lookup."""
    empanelled: bool = True
    hospital_id: str = ""
    matched_name: str = ""
    match_score: float = 0.0
    empanelment_expiry: str = ""
    state: str = ""


class EnrollmentRecord(BaseModel):
    """PM-JAY beneficiary enrollment record issued on card creation."""
    aadhaar_number: str                              # Masked: XXXX-XXXX-XXXX
    mobile_number: str
    family_id: str
    secc_category: str
    scheme: str
    card_number: str = ""                            # e.g. ABHA-XXXX-XXXX-XXXX
    card_issued: bool = False
    card_issued_at: str = ""
    members: List[str] = []                          # Aadhaar numbers of family members


class OTPSession(BaseModel):
    """Transient OTP session for Aadhaar verification."""
    otp_token: str
    aadhaar_number: str
    mobile_number: str
    expires_at: str
    verified: bool = False


class LifecycleEvent(BaseModel):
    stage: str          # e.g. "SUBMITTED", "OCR", "STRUCTURED", "CODED", "ELIGIBILITY", "FRAUD_CHECK", "PORTAL", "COMPLETE"
    status: str         # "success", "warning", "error", "pending"
    timestamp_iso: str  # ISO string
    elapsed_ms: int = 0
    reason: str = ""


class FraudResult(BaseModel):
    fraud_score: float = Field(default=0.0, ge=0.0, le=1.0)
    risk_level: Literal["low", "medium", "high"] = "low"
    flags: List[str] = []
    escalated_to_hitl: bool = False


class PortalSubmission(BaseModel):
    submitted: bool = False
    portal_ref: str = ""           # e.g. "PMJAY-2024-849201"
    submitted_at: str = ""         # ISO timestamp
    portal_status: str = "NOT_SUBMITTED"  # NOT_SUBMITTED, PENDING_PORTAL, PORTAL_ACCEPTED, PORTAL_REJECTED
    expected_settlement_days: int = 0
    rejection_reason: str = ""


# ── Primary Claim Record (contract shape + extensions) ───────────────────────

class ClaimRecord(BaseModel):
    claim_id: str
    raw_ocr: str
    extracted_json: ExtractedJSON
    coding_result: CodingResult
    eligibility: Eligibility
    route: Literal["auto_approve", "human_review", "incomplete_documentation"]
    status: Literal["approved", "pending_review", "incomplete", "rejected"]
    
    # Differentiator Extension Fields (Optional / Defaulted)
    completeness: CompletenessResult = Field(default_factory=CompletenessResult)
    fingerprint_matched: Optional[FingerprintMatch] = None
    is_duplicate: bool = False
    twin_claim_ids: List[str] = []
    plain_reason: str = ""
    processing_seconds: float = 0.5
    time_saved_receipt: str = "Processed in 0.5s. Manually, this typically takes 12–15 days."
    
    # New Production Upgrade Fields
    lifecycle_events: List[LifecycleEvent] = []
    fraud_result: FraudResult = Field(default_factory=FraudResult)
    portal_submission: PortalSubmission = Field(default_factory=PortalSubmission)


# ── Dashboard Metrics ────────────────────────────────────────────────────────

class TimeSeriesPoint(BaseModel):
    label: str
    value: int


class DashboardMetrics(BaseModel):
    total_claims: int
    auto_approved: int
    pending_review: int
    auto_adjudication_rate: float   # percentage 0–100
    total_savings_inr: float = 0.0  # Estimated INR saved
    total_hours_saved: float = 0.0  # Estimated manual hours saved
    volume_series: List[TimeSeriesPoint] = []
    stage_timing_avg_ms: Dict[str, float] = {}


# ── Pre-Authorization Models ─────────────────────────────────────────────────

class PreAuthRequest(BaseModel):
    patient_id: str
    patient_name: str
    hospital_name: str
    procedure_name: str
    estimated_cost: float
    clinical_justification: str = ""
    urgency: Literal["routine", "urgent", "emergency"] = "routine"


class PreAuthRecord(BaseModel):
    preauth_id: str
    patient_id: str
    patient_name: str
    hospital_name: str
    procedure_name: str
    estimated_cost: float
    clinical_justification: str = ""
    urgency: str = "routine"
    status: Literal["approved", "pending", "rejected"] = "pending"
    created_at: str
    decided_at: str = ""
    decision_reason: str = ""


# ── API Response & Request helpers ──────────────────────────────────────────

class ApproveRequest(BaseModel):
    clinic_id: Optional[str] = None
    corrections: Optional[Dict[str, str]] = None  # e.g. {"doctor_name": "Dr. Priya Mehta"}


class ApproveResponse(BaseModel):
    claim_id: str
    status: Literal["approved", "rejected"]
    fingerprint_updated: bool = False


class ErrorResponse(BaseModel):
    detail: str


# ── Auth Pydantic Models ───────────────────────────────────────────────────

class RegisterRequest(BaseModel):
    email: str
    full_name: str
    password: str
    role: Optional[str] = "Caseworker"
    clinic_id: Optional[str] = None


class LoginRequest(BaseModel):
    email: str
    password: str


class UserOut(BaseModel):
    id: str
    email: str
    full_name: str
    role: str
    clinic_id: Optional[str] = None


class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut
