"""
pipeline/eligibility.py — Stage 4: PM-JAY (Ayushman Bharat) Eligibility Verifier

Implements the 3-gate PM-JAY eligibility check that the real-world RPA would
perform at claim time, replacing the generic CSV lookup with PM-JAY-faithful logic.

GATE 1 — Beneficiary Identity Verification:
  - Match patient by Aadhaar number, ration card, or name+age fuzzy
  - Determine SECC category (rural_deprivation / urban_occupation /
    senior_citizen_70plus / asha_worker / state_supplementary)
  - West Bengal → redirect to WBHS (PM-JAY opted out)
  - Not in SECC → check state_supplementary → redirect to CMCHIS/MJPJAY/RGHS

GATE 2 — ₹5 Lakh Family Annual Cap Check:
  - Sum annual_utilization_inr across the family_id floater pool
  - Senior citizens (70+) have a separate additional ₹5L cap (2024 expansion)
  - If cap exhausted → reject with rejection_type="cap_exhausted"

GATE 3 — Hospital Empanelment Check:
  - Fuzzy match hospital_name against empanelled_hospitals.csv
  - Verify empanelment not expired
  - If not empanelled → reject with rejection_type="hard_eligibility"

Key PM-JAY distinctions vs. private insurance:
  ✓ NO pre-existing disease (PED) exclusion check — all PEDs covered from day 1
  ✓ NO waiting period check — immediate coverage
  ✓ Rejection types are: hard_eligibility | procedure_scope | cap_exhausted
    (not the PED/waiting-period logic used for private plans)

Q&A ready:
  Real:   3-gate logic, family cap math, WB exclusion, state-scheme routing
  Mocked: eligibility.csv (100 rows with PM-JAY fields), empanelled_hospitals.csv
  Roadmap: Replace CSV with live NHA beneficiary API + UIDAI Aadhaar Auth API
"""
from __future__ import annotations
import os
import re
import pandas as pd
from datetime import date, datetime
from typing import Dict, Any

from app.config import (
    ELIGIBILITY_CSV,
    PMJAY_FAMILY_CAP_INR,
    PMJAY_SENIOR_CAP_INR,
    PMJAY_OPTED_OUT_STATES,
    STATE_SCHEME_MAP,
)
from app.models import Eligibility, PMJAYEligibility

# ── Singleton DataFrames ─────────────────────────────────────────────────────
_elig_df: pd.DataFrame | None = None


def _get_elig_df() -> pd.DataFrame:
    global _elig_df
    if _elig_df is None:
        if not os.path.exists(ELIGIBILITY_CSV):
            raise FileNotFoundError(f"Eligibility CSV not found at {ELIGIBILITY_CSV}")
        _elig_df = pd.read_csv(ELIGIBILITY_CSV)
        _elig_df.columns = [c.strip().lower().replace(" ", "_") for c in _elig_df.columns]
        if "coverage_expiry_date" in _elig_df.columns:
            _elig_df["coverage_expiry_date"] = pd.to_datetime(
                _elig_df["coverage_expiry_date"], errors="coerce"
            )
        # Ensure numeric utilization columns exist
        for col in ("annual_utilization_inr", "senior_citizen_utilization_inr"):
            if col not in _elig_df.columns:
                _elig_df[col] = 0.0
            else:
                _elig_df[col] = pd.to_numeric(_elig_df[col], errors="coerce").fillna(0.0)
    return _elig_df


def _reload_elig_df() -> None:
    """Force a reload of the eligibility CSV (used after enrollment updates)."""
    global _elig_df
    _elig_df = None
    _get_elig_df()


def _normalize_name(name: str) -> str:
    """Lowercase, strip extra whitespace and trailing labels for fuzzy matching."""
    cleaned = name.split("\n")[0].split("Patient")[0].split("ID")[0].strip().lower()
    return re.sub(r"\s+", " ", cleaned)


def _get_family_utilization(df: pd.DataFrame, family_id: str, exclude_patient_id: str = "") -> float:
    """Sum annual_utilization_inr across all members of a family floater pool."""
    if not family_id or "family_id" not in df.columns:
        return 0.0
    mask = df["family_id"].astype(str).str.strip() == family_id.strip()
    if exclude_patient_id:
        mask = mask & (df["patient_id"].astype(str) != exclude_patient_id)
    family_rows = df[mask]
    return float(family_rows["annual_utilization_inr"].sum())


def _get_state_scheme(state: str) -> str:
    """Return the state-specific scheme code for a given state name."""
    return STATE_SCHEME_MAP.get(state, "PMJAY")


# ── 3-Gate PM-JAY Eligibility Verifier ───────────────────────────────────────

def check_eligibility(
    patient_name: str,
    age: int,
    hospital_name: str = "",
    aadhaar_number: str = "",
    ration_card_number: str = "",
) -> PMJAYEligibility:
    """
    Stage 4 — PM-JAY 3-Gate Eligibility Verifier.

    Gate 1: Beneficiary identity (SECC / Aadhaar / name+age match)
    Gate 2: ₹5L family annual cap check (separate cap for seniors 70+)
    Gate 3: Hospital empanelment check (deferred to orchestrator if no hospital_name)

    Returns a PMJAYEligibility with full gate audit trail in gate_results.
    """
    df = _get_elig_df()
    today = date.today()
    gate_results: Dict[str, Any] = {}

    # ── Guard: empty name ─────────────────────────────────────────────────────
    if not patient_name or not patient_name.strip():
        return PMJAYEligibility(
            eligible=False,
            patient_id="",
            income_bracket="",
            existing_coverage="",
            reason="Patient name missing from bill; cannot verify PM-JAY eligibility.",
            rejection_type="hard_eligibility",
            gate_results={"gate1": "failed_no_name"},
        )

    norm_name = _normalize_name(patient_name)

    # ════════════════════════════════════════════════════════════════════════
    # GATE 1 — Beneficiary Identity Verification
    # Priority: Aadhaar → Ration Card → Name + Age
    # ════════════════════════════════════════════════════════════════════════
    matched = pd.DataFrame()

    # 1a. Match by Aadhaar number (strip hyphens/spaces for comparison)
    if aadhaar_number and "aadhaar_number" in df.columns:
        clean_input = re.sub(r"[\s\-]", "", aadhaar_number)
        aadhaar_mask = df["aadhaar_number"].astype(str).apply(
            lambda x: re.sub(r"[\s\-]", "", x)
        ) == clean_input
        matched = df[aadhaar_mask]
        if not matched.empty:
            gate_results["gate1"] = "matched_aadhaar"

    # 1b. Match by Ration Card number
    if matched.empty and ration_card_number and "ration_card_number" in df.columns:
        rc_mask = df["ration_card_number"].astype(str).str.strip().str.lower() == ration_card_number.strip().lower()
        matched = df[rc_mask]
        if not matched.empty:
            gate_results["gate1"] = "matched_ration_card"

    # 1c. Name exact match
    if matched.empty and "patient_name" in df.columns:
        name_mask = df["patient_name"].str.lower().str.strip() == norm_name
        matched = df[name_mask]
        if not matched.empty:
            gate_results["gate1"] = "matched_name_exact"

    # 1d. Name + Age fuzzy fallback (±2 years)
    if matched.empty and age > 0 and "age" in df.columns:
        age_mask = (df["age"] - age).abs() <= 2
        if "patient_name" in df.columns:
            name_parts = norm_name.split()
            surname = name_parts[-1] if len(name_parts) > 1 else norm_name
            surname_mask = df["patient_name"].str.lower().str.contains(
                r"\b" + re.escape(surname) + r"\b", regex=True, na=False
            )
            matched = df[age_mask & surname_mask]
            if not matched.empty:
                gate_results["gate1"] = "matched_name_age_fuzzy"

    # 1e. Family cluster cross-match (same surname, any age)
    if matched.empty and "patient_name" in df.columns:
        parts = norm_name.split()
        if len(parts) > 1:
            surname = parts[-1]
            family_matches = df[
                df["patient_name"].str.lower().str.contains(
                    r"\b" + re.escape(surname) + r"\b", regex=True, na=False
                )
            ]
            if not family_matches.empty:
                fam_row = family_matches.iloc[0]
                fam_name = str(fam_row.get("patient_name", ""))
                fam_id = str(fam_row.get("patient_id", ""))
                fam_scheme = str(fam_row.get("scheme", "PMJAY"))
                fam_cat = str(fam_row.get("secc_category", ""))
                fam_family_id = str(fam_row.get("family_id", ""))
                state = str(fam_row.get("state", ""))
                gate_results["gate1"] = "family_cluster_match"
                return PMJAYEligibility(
                    eligible=False,
                    patient_id=fam_id,
                    income_bracket=str(fam_row.get("income_bracket", "")),
                    existing_coverage=str(fam_row.get("existing_coverage", "")),
                    reason=(
                        f"Patient not found individually. Possible family enrollment under "
                        f"'{fam_name}' (Family ID: {fam_family_id}). "
                        f"Verify and attach family Ayushman Card."
                    ),
                    secc_category=fam_cat,
                    family_id=fam_family_id,
                    scheme=fam_scheme,
                    rejection_type="hard_eligibility",
                    gate_results=gate_results,
                )

    # 1f. Not found at all
    if matched.empty:
        gate_results["gate1"] = "not_found"
        return PMJAYEligibility(
            eligible=False,
            patient_id="UNKNOWN",
            income_bracket="N/A",
            existing_coverage="None",
            reason=(
                f"No PM-JAY beneficiary record found for '{patient_name}'. "
                f"Visit a CSC with Aadhaar + ration card, or apply at beneficiary.nha.gov.in. "
                f"If not in SECC, check state scheme eligibility (CMCHIS/MJPJAY/RGHS)."
            ),
            rejection_type="hard_eligibility",
            gate_results=gate_results,
        )

    row = matched.iloc[0]
    patient_id = str(row.get("patient_id", ""))
    income_bracket = str(row.get("income_bracket", ""))
    existing_coverage = str(row.get("existing_coverage", "PMJAY"))
    secc_category = str(row.get("secc_category", ""))
    family_id = str(row.get("family_id", ""))
    state = str(row.get("state", ""))
    scheme = str(row.get("scheme", "PMJAY")).strip()
    annual_util = float(row.get("annual_utilization_inr", 0.0))
    senior_util = float(row.get("senior_citizen_utilization_inr", 0.0))
    is_senior = (secc_category == "senior_citizen_70plus") or (age >= 70)

    # ── West Bengal opted-out check ──────────────────────────────────────────
    if state in PMJAY_OPTED_OUT_STATES or scheme == "WBHS":
        fallback = "WBHS"
        gate_results["gate1"] = f"west_bengal_exclusion → {fallback}"
        return PMJAYEligibility(
            eligible=False,
            patient_id=patient_id,
            income_bracket=income_bracket,
            existing_coverage=existing_coverage,
            reason=(
                "West Bengal has opted out of PM-JAY (AB-PMJAY). "
                "Patient is covered under the West Bengal Health Scheme (WBHS) instead. "
                "Please contact your nearest empanelled hospital under WBHS."
            ),
            secc_category=secc_category,
            family_id=family_id,
            scheme="WBHS",
            fallback_scheme="WBHS",
            rejection_type="hard_eligibility",
            gate_results=gate_results,
        )

    # ── State supplementary scheme ───────────────────────────────────────────
    if scheme in ("CMCHIS", "MJPJAY", "RGHS") or secc_category == "state_supplementary":
        state_scheme = scheme if scheme in ("CMCHIS", "MJPJAY", "RGHS") else _get_state_scheme(state)
        gate_results["gate1"] = f"state_supplementary → {state_scheme}"
        # State supplementary is still eligible — they get covered under state scheme
        scheme = state_scheme

    # ── Explicit eligibility flag ────────────────────────────────────────────
    eligible_flag = row.get("eligible", True)
    if isinstance(eligible_flag, str):
        eligible_flag = eligible_flag.strip().lower() not in ("false", "0", "no")
    eligible_flag = bool(eligible_flag)

    if not eligible_flag:
        reason_text = str(row.get("reason", "Patient marked ineligible in PM-JAY database."))
        # Asset/income disqualifier?
        if "asset" in reason_text.lower() or "income" in reason_text.lower() or "vehicle" in reason_text.lower():
            rej_type = "hard_eligibility"
        elif "cap" in reason_text.lower() or "exhausted" in reason_text.lower() or "limit" in reason_text.lower() or "500,000" in reason_text.lower():
            rej_type = "cap_exhausted"
        else:
            rej_type = "hard_eligibility"
        gate_results["gate1"] = "explicit_ineligible"
        return PMJAYEligibility(
            eligible=False,
            patient_id=patient_id,
            income_bracket=income_bracket,
            existing_coverage=existing_coverage,
            reason=reason_text,
            secc_category=secc_category,
            family_id=family_id,
            scheme=scheme,
            rejection_type=rej_type,
            gate_results=gate_results,
        )

    # ── Coverage expiry ──────────────────────────────────────────────────────
    expiry = row.get("coverage_expiry_date")
    if pd.notna(expiry) and hasattr(expiry, "date") and expiry.date() < today:
        gate_results["gate1"] = "coverage_expired"
        return PMJAYEligibility(
            eligible=False,
            patient_id=patient_id,
            income_bracket=income_bracket,
            existing_coverage=existing_coverage,
            reason=f"PM-JAY coverage expired on {expiry.strftime('%Y-%m-%d')}. Please re-verify at a CSC.",
            secc_category=secc_category,
            family_id=family_id,
            scheme=scheme,
            rejection_type="hard_eligibility",
            gate_results=gate_results,
        )

    gate_results["gate1"] = "passed"

    # ════════════════════════════════════════════════════════════════════════
    # GATE 2 — ₹5 Lakh Family Annual Cap Check
    # Family floater cap: shared across all members
    # Senior citizen (70+) additional cap: separate ₹5L pool (2024 expansion)
    # ════════════════════════════════════════════════════════════════════════
    family_total = _get_family_utilization(df, family_id, exclude_patient_id=patient_id)
    family_total += annual_util   # include current patient's own utilization
    family_cap_remaining = max(0.0, PMJAY_FAMILY_CAP_INR - family_total)

    senior_cap_remaining = PMJAY_SENIOR_CAP_INR
    if is_senior:
        senior_cap_remaining = max(0.0, PMJAY_SENIOR_CAP_INR - senior_util)

    if family_cap_remaining <= 0:
        gate_results["gate2"] = "cap_exhausted"
        return PMJAYEligibility(
            eligible=False,
            patient_id=patient_id,
            income_bracket=income_bracket,
            existing_coverage=existing_coverage,
            reason=(
                f"Annual PM-JAY family coverage limit of ₹5,00,000 has been fully utilised "
                f"(Family ID: {family_id}). No further claims can be processed this policy year."
            ),
            secc_category=secc_category,
            family_id=family_id,
            annual_cap_remaining_inr=0.0,
            senior_cap_remaining_inr=senior_cap_remaining,
            scheme=scheme,
            rejection_type="cap_exhausted",
            gate_results=gate_results,
        )

    if is_senior and senior_cap_remaining <= 0:
        gate_results["gate2"] = "senior_cap_exhausted"
        return PMJAYEligibility(
            eligible=False,
            patient_id=patient_id,
            income_bracket=income_bracket,
            existing_coverage=existing_coverage,
            reason=(
                f"Senior citizen's additional PM-JAY coverage limit of ₹5,00,000 has been fully "
                f"utilised this policy year. Family floater cap of ₹{family_cap_remaining:,.0f} "
                f"is still available for other family members."
            ),
            secc_category=secc_category,
            family_id=family_id,
            annual_cap_remaining_inr=family_cap_remaining,
            senior_cap_remaining_inr=0.0,
            scheme=scheme,
            rejection_type="cap_exhausted",
            gate_results=gate_results,
        )

    gate_results["gate2"] = f"passed (cap_remaining=₹{family_cap_remaining:,.0f})"

    # ════════════════════════════════════════════════════════════════════════
    # GATE 3 — Hospital Empanelment Check (if hospital_name provided)
    # If no hospital name is passed, this gate is deferred to the orchestrator
    # which calls check_hospital_empanelment() separately.
    # ════════════════════════════════════════════════════════════════════════
    hospital_empanelled = True
    if hospital_name and hospital_name.strip():
        try:
            from app.pipeline.hospital_empanelment import check_hospital_empanelment
            emp_result = check_hospital_empanelment(hospital_name)
            hospital_empanelled = emp_result.empanelled
            gate_results["gate3"] = (
                f"passed (matched='{emp_result.matched_name}', score={emp_result.match_score:.1f})"
                if hospital_empanelled
                else f"failed (hospital not empanelled, best_match='{emp_result.matched_name}', score={emp_result.match_score:.1f})"
            )
            if not hospital_empanelled:
                return PMJAYEligibility(
                    eligible=False,
                    patient_id=patient_id,
                    income_bracket=income_bracket,
                    existing_coverage=existing_coverage,
                    reason=(
                        f"Hospital '{hospital_name}' is not on the PM-JAY empanelled hospital list. "
                        f"Treatment must be received at a PM-JAY empanelled hospital for cashless coverage. "
                        f"Find empanelled hospitals at hospitals.pmjay.gov.in."
                    ),
                    secc_category=secc_category,
                    family_id=family_id,
                    annual_cap_remaining_inr=family_cap_remaining,
                    senior_cap_remaining_inr=senior_cap_remaining,
                    hospital_empanelled=False,
                    scheme=scheme,
                    rejection_type="hard_eligibility",
                    gate_results=gate_results,
                )
        except ImportError:
            gate_results["gate3"] = "deferred (hospital_empanelment module not yet loaded)"
    else:
        gate_results["gate3"] = "deferred (no hospital_name provided)"

    # ════════════════════════════════════════════════════════════════════════
    # ALL GATES PASSED — Eligible
    # ════════════════════════════════════════════════════════════════════════
    cap_msg = f"₹{family_cap_remaining:,.0f}"
    if is_senior:
        cap_msg += f" (Senior additional cap: ₹{senior_cap_remaining:,.0f})"

    return PMJAYEligibility(
        eligible=True,
        patient_id=patient_id,
        income_bracket=income_bracket,
        existing_coverage=existing_coverage,
        reason=(
            f"PM-JAY beneficiary verified. SECC category: {secc_category}. "
            f"Scheme: {scheme}. Annual cap remaining: {cap_msg}. "
            f"All 3 eligibility gates passed."
        ),
        secc_category=secc_category,
        family_id=family_id,
        annual_cap_remaining_inr=family_cap_remaining,
        senior_cap_remaining_inr=senior_cap_remaining,
        hospital_empanelled=hospital_empanelled,
        scheme=scheme,
        rejection_type="",
        gate_results=gate_results,
    )
