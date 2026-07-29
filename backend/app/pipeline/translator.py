"""
pipeline/translator.py — Rejection Reason Translator (PM-JAY extended)

Translates technical rejection flags into a single, empathetic, plain-language sentence
that patients and clinic submitters without medical/insurance backgrounds can understand.

PM-JAY extension: Adds bilingual (English + Hindi) translations for PM-JAY specific
rejection types — critical for rural/low-income beneficiaries who are the primary
target group for Ayushman Bharat.

Rejection type taxonomy (PM-JAY):
  hard_eligibility  — not in SECC, hospital not empanelled, WB exclusion, asset threshold
  cap_exhausted     — ₹5L family floater used up, or senior's separate ₹5L used up
  procedure_scope   — outpatient-only, dental, cosmetic, not in 1,929-procedure list
  (None)            — all other flags: OCR quality, ICD-10 confidence, duplicates
"""
from __future__ import annotations
from typing import List


def translate_rejection_reasons(reasons: List[str]) -> str:
    """
    Translates technical pipeline flags into a single patient-friendly sentence.

    PM-JAY rejections are checked first (they are actionable and specific).
    General checks (OCR, ICD-10 confidence, duplicates) follow as fallbacks.
    """
    if not reasons:
        return "Your claim was flagged for standard administrative review by a caseworker."

    combined = " ".join(reasons).lower()

    # ── PM-JAY: ₹5 Lakh Cap Exhausted ────────────────────────────────────────
    if "cap exhausted" in combined or "5,00,000" in combined or "annual pm-jay family coverage limit" in combined:
        return (
            "आपके परिवार की ₹5,00,000 की वार्षिक आयुष्मान भारत सीमा इस वर्ष समाप्त हो गई है। "
            "Your family's ₹5,00,000 annual PM-JAY coverage limit has been fully used for this policy year. "
            "No further cashless claims can be processed until the next policy year. "
            "Contact your nearest Ayushman Mitra or call helpline 14555."
        )

    # ── PM-JAY: Senior Citizen Separate Cap ──────────────────────────────────
    if "senior citizen" in combined and ("cap" in combined or "limit" in combined):
        return (
            "The senior citizen's additional ₹5,00,000 PM-JAY coverage (for members aged 70+) "
            "has been fully utilised this year. The regular family floater may still have remaining balance. "
            "Call helpline 14555 for assistance."
        )

    # ── PM-JAY: Hospital Not Empanelled ──────────────────────────────────────
    if "empanelled" in combined or "hospitals.pmjay.gov.in" in combined:
        return (
            "यह अस्पताल PM-JAY की अनुमोदित सूची में नहीं है। "
            "This hospital is not on the PM-JAY empanelled list — cashless treatment is only available "
            "at empanelled hospitals. Find approved hospitals near you at hospitals.pmjay.gov.in "
            "or call 14555."
        )

    # ── PM-JAY: West Bengal / WBHS Redirect ──────────────────────────────────
    if "west bengal" in combined or "wbhs" in combined:
        return (
            "West Bengal has opted out of Ayushman Bharat PM-JAY. "
            "You are covered under the West Bengal Health Scheme (WBHS) instead. "
            "Please visit a WBHS-empanelled hospital for cashless treatment."
        )

    # ── PM-JAY: State Supplementary Scheme Routing ───────────────────────────
    if "cmchis" in combined or "mjpjay" in combined or "rghs" in combined:
        scheme = (
            "CMCHIS (Chief Minister's Comprehensive Health Insurance Scheme)"
            if "cmchis" in combined
            else "MJPJAY (Mahatma Jyotiba Phule Jan Arogya Yojana)"
            if "mjpjay" in combined
            else "RGHS (Rajasthan Government Health Scheme)"
        )
        return (
            f"You are not enrolled in central PM-JAY, but you may be covered under your state scheme: {scheme}. "
            f"Please visit a {scheme.split('(')[0].strip()}-empanelled hospital or call helpline 14555."
        )

    # ── PM-JAY: Procedure Scope — Outpatient Only ─────────────────────────────
    if "outpatient" in combined or "outpatient-only" in combined:
        return (
            "PM-JAY covers hospitalisation (in-patient admission) only. "
            "Outpatient (OPD) consultations, diagnostic tests without admission, and pharmacy-only visits "
            "are not reimbursed under this scheme. If hospitalisation is required, the claim can be resubmitted."
        )

    # ── PM-JAY: Procedure Scope — Dental / Cosmetic ──────────────────────────
    if "dental" in combined or "cosmetic" in combined or "elective" in combined or "aesthetic" in combined:
        return (
            "Routine dental, cosmetic, and elective aesthetic procedures are not covered under PM-JAY. "
            "The scheme covers 1,929 medical and surgical package procedures for serious conditions "
            "requiring hospitalisation. Please consult your Ayushman Mitra for covered procedure options."
        )

    # ── PM-JAY: Procedure Not in 1,929-Package List ───────────────────────────
    if "1,929" in combined or "package list" in combined or "not in pm-jay" in combined:
        return (
            "The procedure billed is not included in PM-JAY's covered package list "
            "(1,929 medical and surgical procedures across 27 specialties). "
            "Your caseworker will verify if there is an equivalent covered procedure code."
        )

    # ── PM-JAY: Not in SECC / Beneficiary Not Found ──────────────────────────
    if "secc" in combined or "beneficiary.nha.gov.in" in combined or "csc" in combined:
        return (
            "आपका नाम PM-JAY लाभार्थी सूची में नहीं मिला। "
            "Your name was not found in the PM-JAY (SECC 2011) beneficiary database. "
            "Visit beneficiary.nha.gov.in to check eligibility, or visit a Common Service Centre (CSC) "
            "with your Aadhaar and ration card. Helpline: 14555 / 1800-111-565."
        )

    # ── General: Missing / Incomplete ────────────────────────────────────────
    if "missing" in combined or "incomplete" in combined:
        return (
            "The bill is missing required administrative details (such as doctor signature or date) "
            "and needs to be completed before processing."
        )

    # ── General: Duplicate ───────────────────────────────────────────────────
    if "duplicate" in combined:
        return "This bill appears to match a claim already submitted in our system and is flagged for duplicate review."

    # ── General: Family match ─────────────────────────────────────────────────
    if "family match" in combined:
        return "Individual coverage was not found, but a family member's policy was detected for caseworker verification."

    # ── General: Coverage expired ─────────────────────────────────────────────
    if "expired" in combined:
        return "The patient's PM-JAY coverage appears to have expired. Please re-verify at a CSC."

    # ── General: OCR / bill quality ──────────────────────────────────────────
    if "ocr" in combined:
        return "The bill handwriting or image quality was low, so a caseworker is double-checking the extracted details."

    # ── General: ICD-10 / coding confidence ──────────────────────────────────
    if "icd-10" in combined or "confidence" in combined:
        return "Specific diagnosis codes require manual confirmation by a caseworker to guarantee maximum insurance benefit."

    return "Claim flagged for routine caseworker verification to ensure accurate coverage."
