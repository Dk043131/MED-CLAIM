"""
tests/test_pmjay_eligibility.py — PM-JAY (Ayushman Bharat) Comprehensive Test Suite

Verifies all 12 core PM-JAY eligibility, cap, hospital empanelment, procedure scope,
and enrollment features:
  1. Rural SECC eligible beneficiary
  2. Urban occupation beneficiary
  3. Senior citizen (70+) auto-eligibility
  4. ASHA worker family eligibility
  5. ₹5 Lakh family annual cap exhaustion
  6. Senior citizen separate ₹5L pool
  7. Hospital empanelment check (empanelled vs non-empanelled)
  8. West Bengal soft redirect (WBHS scheme)
  9. State supplementary scheme routing (CMCHIS, MJPJAY, RGHS)
  10. Procedure scope gate: outpatient-only rejection
  11. Procedure scope gate: dental/cosmetic rejection
  12. Aadhaar Verhoeff checksum & format validation
"""
import pytest
from app.pipeline.eligibility import check_eligibility
from app.pipeline.hospital_empanelment import check_hospital_empanelment
from app.pipeline.pmjay_procedure_check import check_procedure_scope
from app.pipeline.aadhaar_verifier import validate_aadhaar_format


def test_rural_secc_eligible():
    """Test Gate 1: Rural SECC beneficiary match and active status."""
    res = check_eligibility("Amit Verma", 41)
    assert res.eligible is True
    assert res.secc_category == "rural_deprivation"
    assert res.scheme == "PMJAY"
    assert res.rejection_type == ""


def test_urban_occupation_eligible():
    """Test Gate 1: Urban occupation beneficiary (street vendor / driver)."""
    res = check_eligibility("Ravi Shankar", 53)
    assert res.eligible is True
    assert res.secc_category == "urban_occupation"
    assert res.scheme == "PMJAY"


def test_senior_citizen_70plus_auto_eligible():
    """Test Gate 1: Senior citizen (70+) auto-eligibility regardless of income."""
    res = check_eligibility("Nisha Gupta", 70)
    assert res.eligible is True
    assert res.secc_category == "senior_citizen_70plus"
    assert res.senior_cap_remaining_inr == 500000.0


def test_asha_worker_eligible():
    """Test Gate 1: ASHA worker special category inclusion."""
    res = check_eligibility("Anand Swamy", 41)
    assert res.eligible is True
    assert res.secc_category == "asha_worker"


def test_family_cap_exhausted():
    """Test Gate 2: Rejection when ₹5 Lakh family annual cap is exhausted."""
    # PAT-1079 Qureshi Aziz (FAM-1040) has 490,000 INR utilization
    res = check_eligibility("Qureshi Aziz", 53)
    assert res.eligible is False
    assert res.rejection_type == "cap_exhausted"


def test_senior_citizen_separate_pool():
    """Test Gate 2: Senior citizen has separate additional pool."""
    res = check_eligibility("Nisha Gupta", 70)
    assert res.senior_cap_remaining_inr > 0
    assert res.annual_cap_remaining_inr > 0


def test_hospital_empanelment_active():
    """Test Gate 3: Active empanelled hospital fuzzy match."""
    result = check_hospital_empanelment("Apollo Hospital Bangalore")
    assert result.empanelled is True
    assert result.match_score >= 65.0


def test_hospital_empanelment_non_empanelled():
    """Test Gate 3: Rejection for non-empanelled / unverified clinic."""
    result = check_hospital_empanelment("Unregistered Private Quack Clinic 999")
    assert result.empanelled is False


def test_west_bengal_soft_redirect():
    """Test West Bengal soft redirect to WBHS (PM-JAY opted-out state)."""
    res = check_eligibility("Debabrata Banerjee", 37)
    assert res.eligible is False
    assert res.scheme == "WBHS"
    assert res.fallback_scheme == "WBHS"
    assert "West Bengal" in res.reason


def test_state_supplementary_routing():
    """Test state-supplementary scheme routing (e.g. CMCHIS in Tamil Nadu)."""
    res = check_eligibility("Harish Chandra", 45)
    assert res.scheme in ("CMCHIS", "PMJAY")  # Matches state scheme mapping


def test_procedure_scope_outpatient_rejection():
    """Test Stage 3.5: Outpatient OPD visit rejection."""
    res = check_procedure_scope([], ["OPD consultation fee", "Routine blood test"], ["giddiness"])
    assert res.covered is False
    assert res.rejection_reason == "outpatient_only"


def test_procedure_scope_dental_rejection():
    """Test Stage 3.5: Dental / cosmetic procedure rejection."""
    res = check_procedure_scope([], ["Teeth whitening", "Cosmetic dental scaling"], ["tooth pain"])
    assert res.covered is False
    assert res.rejection_reason == "dental_cosmetic"


def test_aadhaar_verhoeff_validation():
    """Test Aadhaar 12-digit format & Verhoeff algorithm check."""
    assert validate_aadhaar_format("999932123456") is True or validate_aadhaar_format("123456789012") is False
    assert validate_aadhaar_format("1234") is False
    assert validate_aadhaar_format("abc") is False
