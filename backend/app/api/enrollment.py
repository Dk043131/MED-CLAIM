"""
api/enrollment.py — PM-JAY Beneficiary Enrollment API Router

Implements the Ayushman Bharat enrollment flow, mirroring the real-world
online process at beneficiary.nha.gov.in:

  Step 1: POST /enrollment/check          — Check eligibility by name/Aadhaar/ration card
  Step 2: POST /enrollment/send-otp       — Dispatch mock Aadhaar OTP
  Step 3: POST /enrollment/verify-otp     — Verify OTP, issue e-card
  Step 4: GET  /enrollment/{aadhaar}/card — Fetch issued e-card data

Additional endpoints:
  POST /enrollment/family/add-member      — Add family member to existing enrollment
  GET  /enrollment/schemes/states         — State → scheme routing map
  GET  /hospitals/search                  — Search empanelled hospitals
  GET  /hospitals/{hospital_id}/status    — Single hospital empanelment status
  GET  /family/{family_id}/cap            — Family ₹5L cap utilization

Q&A ready:
  Real:   Aadhaar format validation (Verhoeff), OTP session expiry logic,
          beneficiary lookup by Aadhaar/ration card, e-card generation
  Mocked: OTP (deterministic SHA-256 hash, not UIDAI), beneficiary DB = CSV
  Roadmap: UIDAI Auth API, NHA beneficiary API, actual card issuance database
"""
from __future__ import annotations

import datetime
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.models import EnrollmentRecord, OTPSession, PMJAYEligibility
from app.config import STATE_SCHEME_MAP, PMJAY_FAMILY_CAP_INR

router = APIRouter(prefix="/enrollment", tags=["PM-JAY Enrollment"])
hospitals_router = APIRouter(tags=["PM-JAY Hospitals"])
family_router = APIRouter(tags=["PM-JAY Family"])


# ── In-memory OTP session store (demo; replace with Redis in production) ─────
_otp_sessions: dict[str, OTPSession] = {}

# ── In-memory enrollment registry (demo; replace with DB in production) ──────
_enrollment_registry: dict[str, EnrollmentRecord] = {}


# ── Request/Response Schemas ──────────────────────────────────────────────────

class EligibilityCheckRequest(BaseModel):
    patient_name: str
    state: str
    aadhaar_number: Optional[str] = ""
    ration_card_number: Optional[str] = ""
    age: Optional[int] = 0
    hospital_name: Optional[str] = ""


class OTPRequest(BaseModel):
    aadhaar_number: str
    mobile_number: str


class OTPVerifyRequest(BaseModel):
    otp_token: str
    entered_otp: str
    aadhaar_number: str
    mobile_number: str
    consent_given: bool = False


class AddMemberRequest(BaseModel):
    family_id: str
    member_aadhaar: str
    member_name: str
    member_age: int
    relationship: str


class EligibilityCheckResponse(BaseModel):
    eligible: bool
    scheme: str
    fallback_scheme: str
    secc_category: str
    family_id: str
    annual_cap_remaining_inr: float
    reason: str
    rejection_type: str
    apply_online_url: str = "https://beneficiary.nha.gov.in"
    helpline: str = "14555 / 1800-111-565"
    gate_results: dict = {}


class OTPResponse(BaseModel):
    otp_token: str
    expires_at: str
    message: str
    # In demo mode, expose the OTP so the frontend can auto-fill
    demo_otp: str = ""


class CardIssueResponse(BaseModel):
    card_issued: bool
    enrollment: EnrollmentRecord
    ecard_data: dict
    message: str


# ── Endpoint: Check PM-JAY Eligibility ───────────────────────────────────────

@router.post("/check", response_model=EligibilityCheckResponse, summary="Check PM-JAY eligibility")
def check_pmjay_eligibility(req: EligibilityCheckRequest):
    """
    Gate 1: Check if a beneficiary is in the PM-JAY / SECC database.
    Returns eligibility status, scheme routing, and cap information.

    Mirrors the first step at beneficiary.nha.gov.in — search by name + Aadhaar/ration card.
    """
    from app.pipeline.eligibility import check_eligibility

    result: PMJAYEligibility = check_eligibility(
        patient_name=req.patient_name,
        age=req.age or 0,
        hospital_name=req.hospital_name or "",
        aadhaar_number=req.aadhaar_number or "",
        ration_card_number=req.ration_card_number or "",
    )

    return EligibilityCheckResponse(
        eligible=result.eligible,
        scheme=result.scheme,
        fallback_scheme=result.fallback_scheme,
        secc_category=result.secc_category,
        family_id=result.family_id,
        annual_cap_remaining_inr=result.annual_cap_remaining_inr,
        reason=result.reason,
        rejection_type=result.rejection_type,
        gate_results=result.gate_results,
    )


# ── Endpoint: Send Mock Aadhaar OTP ──────────────────────────────────────────

@router.post("/send-otp", response_model=OTPResponse, summary="Send mock Aadhaar OTP")
def send_aadhaar_otp(req: OTPRequest):
    """
    Step 2 of enrollment: validates Aadhaar format and dispatches a mock OTP.

    Real PM-JAY flow: UIDAI dispatches OTP to registered mobile via Aadhaar Auth API.
    Demo: OTP is a deterministic 4-digit code derived from Aadhaar + mobile + today's date.
    """
    from app.pipeline.aadhaar_verifier import validate_aadhaar_format, generate_otp_token

    if not validate_aadhaar_format(req.aadhaar_number):
        raise HTTPException(
            status_code=422,
            detail=(
                "Invalid Aadhaar number format. Aadhaar must be 12 digits. "
                "Please check and re-enter."
            ),
        )

    session_data = generate_otp_token(req.aadhaar_number, req.mobile_number)

    otp_session = OTPSession(
        otp_token=session_data["otp_token"],
        aadhaar_number=req.aadhaar_number,
        mobile_number=req.mobile_number,
        expires_at=session_data["expires_at"],
        verified=False,
    )
    _otp_sessions[session_data["otp_token"]] = otp_session

    return OTPResponse(
        otp_token=session_data["otp_token"],
        expires_at=session_data["expires_at"],
        message=f"OTP sent to mobile number ending in ...{req.mobile_number[-4:]}. Valid for 10 minutes.",
        demo_otp=session_data["otp"],   # Demo only — remove in production
    )


# ── Endpoint: Verify OTP + Issue E-Card ──────────────────────────────────────

@router.post("/verify-otp", response_model=CardIssueResponse, summary="Verify OTP and issue Ayushman Card")
def verify_otp_and_issue_card(req: OTPVerifyRequest):
    """
    Step 3 of enrollment: verifies OTP, performs Aadhaar KYC, and issues the e-card.

    On success:
    - Beneficiary record is created / updated in the enrollment registry
    - Mock Ayushman Card (ABHA number) is generated
    - E-card JSON is returned (can be rendered as PDF/PVC in production)
    """
    if not req.consent_given:
        raise HTTPException(status_code=422, detail="Consent must be given to proceed with Aadhaar KYC.")

    from app.pipeline.aadhaar_verifier import verify_otp, lookup_by_aadhaar, generate_ecard_data

    # Check session exists and hasn't expired
    session = _otp_sessions.get(req.otp_token)
    if not session:
        raise HTTPException(status_code=404, detail="OTP session not found. Please request a new OTP.")

    expires_dt = datetime.datetime.fromisoformat(session.expires_at.replace("Z", "+00:00"))
    if datetime.datetime.now(datetime.timezone.utc) > expires_dt:
        _otp_sessions.pop(req.otp_token, None)
        raise HTTPException(status_code=410, detail="OTP has expired. Please request a new OTP.")

    # Verify OTP
    otp_valid = verify_otp(req.otp_token, req.entered_otp, req.aadhaar_number, req.mobile_number)
    if not otp_valid:
        raise HTTPException(status_code=401, detail="Invalid OTP. Please check and try again.")

    # Mark session verified
    session.verified = True

    # Lookup beneficiary in SECC database
    patient_row = lookup_by_aadhaar(req.aadhaar_number)
    if not patient_row:
        raise HTTPException(
            status_code=404,
            detail=(
                "Aadhaar not found in PM-JAY beneficiary database. "
                "If you believe you are eligible, visit a Common Service Centre (CSC) "
                "with your Aadhaar and ration card for manual verification. Helpline: 14555."
            ),
        )

    # Generate family member list (same family_id)
    family_id = patient_row.get("family_id", "FAM-0000")
    members = [req.aadhaar_number]  # Demo: just the requester; production would list all

    # Issue e-card
    ecard_data = generate_ecard_data(patient_row, [patient_row])

    # Create enrollment record
    enrollment = EnrollmentRecord(
        aadhaar_number=req.aadhaar_number,
        mobile_number=req.mobile_number,
        family_id=family_id,
        secc_category=patient_row.get("secc_category", ""),
        scheme=patient_row.get("scheme", "PMJAY"),
        card_number=ecard_data.get("card_number", ""),
        card_issued=True,
        card_issued_at=datetime.datetime.utcnow().isoformat() + "Z",
        members=members,
    )
    _enrollment_registry[req.aadhaar_number] = enrollment

    return CardIssueResponse(
        card_issued=True,
        enrollment=enrollment,
        ecard_data=ecard_data,
        message=(
            "Ayushman Card issued successfully. Your card is ready to use at any "
            "PM-JAY empanelled hospital for cashless treatment up to ₹5,00,000 per year."
        ),
    )


# ── Endpoint: Fetch Issued E-Card ─────────────────────────────────────────────

@router.get("/{aadhaar}/card", summary="Fetch issued Ayushman Card data")
def get_ecard(aadhaar: str):
    """Returns the issued e-card data for a given Aadhaar number."""
    from app.pipeline.aadhaar_verifier import lookup_by_aadhaar, generate_ecard_data

    record = _enrollment_registry.get(aadhaar)
    if record:
        patient_row = lookup_by_aadhaar(aadhaar) or {}
        return {"card_issued": True, "enrollment": record, "ecard_data": generate_ecard_data(patient_row, [patient_row])}

    # Card not yet issued — check if Aadhaar exists in SECC
    patient_row = lookup_by_aadhaar(aadhaar)
    if not patient_row:
        raise HTTPException(status_code=404, detail="No Ayushman Card found for this Aadhaar number.")

    return {
        "card_issued": False,
        "message": "Aadhaar found in PM-JAY database but card not yet issued. Complete enrollment first.",
        "patient_name": patient_row.get("patient_name", ""),
        "scheme": patient_row.get("scheme", "PMJAY"),
        "apply_url": "https://beneficiary.nha.gov.in",
    }


# ── Endpoint: Add Family Member ───────────────────────────────────────────────

@router.post("/family/add-member", summary="Add family member to existing enrollment")
def add_family_member(req: AddMemberRequest):
    """
    Adds a new family member to an existing PM-JAY family enrollment.
    In the real system, each member is individually Aadhaar-verified with biometrics.
    Demo: adds member to the in-memory registry.
    """
    from app.pipeline.aadhaar_verifier import validate_aadhaar_format

    if not validate_aadhaar_format(req.member_aadhaar):
        raise HTTPException(status_code=422, detail="Invalid Aadhaar number for the new member.")

    # Find existing family enrollment
    family_enrollment = next(
        (rec for rec in _enrollment_registry.values() if rec.family_id == req.family_id),
        None,
    )
    if not family_enrollment:
        raise HTTPException(
            status_code=404,
            detail=f"No enrollment found for Family ID '{req.family_id}'. Please complete primary enrollment first.",
        )

    if req.member_aadhaar not in family_enrollment.members:
        family_enrollment.members.append(req.member_aadhaar)

    return {
        "success": True,
        "family_id": req.family_id,
        "member_added": req.member_aadhaar,
        "total_members": len(family_enrollment.members),
        "message": f"Family member '{req.member_name}' added to Family ID {req.family_id}.",
    }


# ── Endpoint: State Schemes Map ───────────────────────────────────────────────

@router.get("/schemes/states", summary="Get state-to-scheme routing map")
def get_state_schemes():
    """Returns the mapping of Indian states to health scheme names."""
    return {
        "pmjay_states": "All states except West Bengal",
        "opted_out": ["West Bengal → WBHS (West Bengal Health Scheme)"],
        "state_supplementary_schemes": {
            "Tamil Nadu": "CMCHIS (Chief Minister's Comprehensive Health Insurance Scheme)",
            "Maharashtra": "MJPJAY (Mahatma Jyotiba Phule Jan Arogya Yojana)",
            "Rajasthan": "RGHS (Rajasthan Government Health Scheme)",
            "West Bengal": "WBHS (West Bengal Health Scheme)",
        },
        "helpline": "14555 / 1800-111-565",
        "enrollment_portal": "https://beneficiary.nha.gov.in",
    }


# ── Hospital Router Endpoints ─────────────────────────────────────────────────

@hospitals_router.get("/hospitals/search", summary="Search PM-JAY empanelled hospitals")
def search_hospitals(
    name: str = Query("", description="Hospital name (partial match OK)"),
    state: str = Query("", description="Filter by state"),
    district: str = Query("", description="Filter by district"),
):
    """
    Search PM-JAY empanelled hospitals. Fuzzy matches on name.
    Find hospitals at: hospitals.pmjay.gov.in
    """
    import pandas as pd
    from app.config import EMPANELLED_HOSPITALS_CSV
    import os

    if not os.path.exists(EMPANELLED_HOSPITALS_CSV):
        return {"hospitals": [], "note": "Empanelled hospitals database not yet loaded."}

    df = pd.read_csv(EMPANELLED_HOSPITALS_CSV)
    df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]

    mask = pd.Series([True] * len(df))
    if name.strip():
        mask = mask & df["hospital_name"].str.lower().str.contains(name.lower(), na=False)
    if state.strip():
        mask = mask & df["state"].str.lower().str.contains(state.lower(), na=False)
    if district.strip():
        mask = mask & df["district"].str.lower().str.contains(district.lower(), na=False)

    results = df[mask].head(20).to_dict(orient="records")
    return {
        "total": int(mask.sum()),
        "showing": len(results),
        "hospitals": results,
        "find_more": "https://hospitals.pmjay.gov.in",
    }


@hospitals_router.get("/hospitals/{hospital_id}/status", summary="Check hospital empanelment status")
def get_hospital_status(hospital_id: str):
    """Check if a specific hospital (by ID) is currently empanelled under PM-JAY."""
    import pandas as pd
    from app.config import EMPANELLED_HOSPITALS_CSV
    import os

    if not os.path.exists(EMPANELLED_HOSPITALS_CSV):
        raise HTTPException(status_code=503, detail="Empanelled hospitals database not available.")

    df = pd.read_csv(EMPANELLED_HOSPITALS_CSV)
    df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]
    row_mask = df["hospital_id"].astype(str).str.strip() == hospital_id.strip()
    rows = df[row_mask]

    if rows.empty:
        raise HTTPException(status_code=404, detail=f"Hospital ID '{hospital_id}' not found.")

    row = rows.iloc[0].to_dict()
    return {
        "hospital_id": hospital_id,
        "hospital_name": row.get("hospital_name", ""),
        "state": row.get("state", ""),
        "district": row.get("district", ""),
        "empanelled": bool(row.get("empanelled", False)),
        "empanelment_expiry": str(row.get("empanelment_expiry", "")),
        "hospital_type": row.get("hospital_type", ""),
        "contact": row.get("contact", ""),
    }


# ── Family Cap Router ─────────────────────────────────────────────────────────

@family_router.get("/family/{family_id}/cap", summary="Get family ₹5L cap utilization")
def get_family_cap(family_id: str):
    """
    Returns the PM-JAY ₹5 lakh annual coverage cap utilization for a family floater pool.
    Senior citizen members with 70+ age have an additional separate ₹5L cap.
    """
    import pandas as pd
    from app.config import ELIGIBILITY_CSV
    import os

    if not os.path.exists(ELIGIBILITY_CSV):
        raise HTTPException(status_code=503, detail="Eligibility database not available.")

    df = pd.read_csv(ELIGIBILITY_CSV)
    df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]

    if "family_id" not in df.columns:
        raise HTTPException(status_code=503, detail="Eligibility database does not have PM-JAY family_id column.")

    family_mask = df["family_id"].astype(str).str.strip() == family_id.strip()
    family_rows = df[family_mask]

    if family_rows.empty:
        raise HTTPException(status_code=404, detail=f"Family ID '{family_id}' not found.")

    for col in ("annual_utilization_inr", "senior_citizen_utilization_inr"):
        if col not in family_rows.columns:
            family_rows = family_rows.copy()
            family_rows[col] = 0.0
        else:
            family_rows = family_rows.copy()
            family_rows[col] = pd.to_numeric(family_rows[col], errors="coerce").fillna(0.0)

    total_utilized = float(family_rows["annual_utilization_inr"].sum())
    cap_remaining = max(0.0, PMJAY_FAMILY_CAP_INR - total_utilized)
    members = family_rows[["patient_id", "patient_name", "annual_utilization_inr"]].to_dict(orient="records")

    # Senior cap
    secc_col = "secc_category" if "secc_category" in family_rows.columns else None
    age_col = "age" if "age" in family_rows.columns else None
    senior_rows = family_rows[
        (family_rows[secc_col].str.strip() == "senior_citizen_70plus" if secc_col else pd.Series([False] * len(family_rows)))
        | (family_rows[age_col] >= 70 if age_col else pd.Series([False] * len(family_rows)))
    ] if secc_col or age_col else pd.DataFrame()

    senior_utilized = float(senior_rows["senior_citizen_utilization_inr"].sum()) if not senior_rows.empty else 0.0
    senior_cap_remaining = max(0.0, PMJAY_FAMILY_CAP_INR - senior_utilized)

    return {
        "family_id": family_id,
        "annual_cap_inr": PMJAY_FAMILY_CAP_INR,
        "total_utilized_inr": total_utilized,
        "cap_remaining_inr": cap_remaining,
        "utilization_percentage": round((total_utilized / PMJAY_FAMILY_CAP_INR) * 100, 1),
        "senior_citizen_cap_inr": PMJAY_FAMILY_CAP_INR,
        "senior_utilized_inr": senior_utilized,
        "senior_cap_remaining_inr": senior_cap_remaining,
        "members": members,
        "member_count": len(family_rows),
        "note": "Senior citizens (70+) have an additional ₹5L cap separate from the family floater.",
    }
