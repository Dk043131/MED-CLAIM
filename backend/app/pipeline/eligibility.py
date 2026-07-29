"""
pipeline/eligibility.py — Stage 4: Eligibility Check

Performs a lookup in eligibility.csv (mock insurance DB).
Returns an Eligibility object describing whether the patient is covered
and why.

What's real vs. mocked (Q&A ready):
  - Real:    CSV lookup by patient_name + age matching (deterministic).
  - Mocked:  The CSV itself is synthetic data (50 rows), not a live insurer DB.
  - Roadmap: Replace CSV with a REST call to an actual insurer API (PMJAY etc.)
"""
from __future__ import annotations
import os
import re
import pandas as pd
from datetime import date
from app.config import ELIGIBILITY_CSV
from app.models import Eligibility

# ── Singleton DataFrame ──────────────────────────────────────────────────────
_elig_df: pd.DataFrame | None = None


def _get_elig_df() -> pd.DataFrame:
    global _elig_df
    if _elig_df is None:
        if not os.path.exists(ELIGIBILITY_CSV):
            raise FileNotFoundError(f"Eligibility CSV not found at {ELIGIBILITY_CSV}")
        _elig_df = pd.read_csv(ELIGIBILITY_CSV)
        _elig_df.columns = [c.strip().lower().replace(" ", "_") for c in _elig_df.columns]
        # Ensure coverage_expiry_date is parsed as date strings
        if "coverage_expiry_date" in _elig_df.columns:
            _elig_df["coverage_expiry_date"] = pd.to_datetime(
                _elig_df["coverage_expiry_date"], errors="coerce"
            )
    return _elig_df


def _normalize_name(name: str) -> str:
    """Lowercase, strip extra spaces — for fuzzy name matching."""
    return re.sub(r"\s+", " ", name.strip().lower())


# ── Eligibility Logic ─────────────────────────────────────────────────────────

def check_eligibility(patient_name: str, age: int) -> Eligibility:
    """
    Stage 4 — Lookup patient in eligibility.csv.

    Matching logic (in order):
      1. Exact normalised name match.
      2. Age ± 2 year tolerance (handles OCR age-read errors).
      3. If still no match, the patient is considered ineligible (no record).

    Coverage checks (when a record is found):
      - coverage_expiry_date: if today > expiry → ineligible (expired).
      - eligible flag in CSV (can be pre-set to False for test cases).
    """
    df = _get_elig_df()
    norm_name = _normalize_name(patient_name)
    today = date.today()

    if not norm_name:
        return Eligibility(
            eligible=False,
            patient_id="",
            income_bracket="",
            existing_coverage="",
            reason="Patient name missing from bill; cannot verify eligibility.",
        )

    # Step 1: name match
    name_mask = df["patient_name"].str.lower().str.strip() == norm_name
    matched = df[name_mask]

    # Step 2: age tolerance fallback
    if matched.empty and "age" in df.columns and age > 0:
        age_mask = (df["age"] - age).abs() <= 2
        matched = df[age_mask]

    if matched.empty:
        # Family Record Cross-Match Assistant
        # Search by surname / family cluster proxy
        parts = norm_name.split()
        if len(parts) > 1:
            surname = parts[-1]
            family_matches = df[df["patient_name"].str.lower().str.contains(r"\b" + re.escape(surname) + r"\b", regex=True)]
            if not family_matches.empty:
                fam_row = family_matches.iloc[0]
                fam_name = str(fam_row.get("patient_name", ""))
                fam_id = str(fam_row.get("patient_id", ""))
                fam_cov = str(fam_row.get("existing_coverage", "PMJAY Gold"))
                return Eligibility(
                    eligible=False,
                    patient_id=fam_id,
                    income_bracket=str(fam_row.get("income_bracket", "")),
                    existing_coverage=fam_cov,
                    reason=f"Family match found: Patient not found individually, but possible family enrollment found under relative '{fam_name}' ({fam_cov}). Verify and attach family policy."
                )

        return Eligibility(
            eligible=False,
            patient_id="UNKNOWN",
            income_bracket="N/A",
            existing_coverage="None",
            reason=f"No eligibility record found for patient '{patient_name}'.",
        )

    row = matched.iloc[0]

    patient_id = str(row.get("patient_id", ""))
    income_bracket = str(row.get("income_bracket", ""))
    existing_coverage = str(row.get("existing_coverage", ""))

    # Step 3: expiry check
    expiry = row.get("coverage_expiry_date")
    if pd.notna(expiry) and expiry.date() < today:
        return Eligibility(
            eligible=False,
            patient_id=patient_id,
            income_bracket=income_bracket,
            existing_coverage=existing_coverage,
            reason=f"Coverage expired on {expiry.strftime('%Y-%m-%d')}.",
        )

    # Step 4: explicit eligible flag
    eligible_flag = row.get("eligible", True)
    if isinstance(eligible_flag, str):
        eligible_flag = eligible_flag.strip().lower() not in ("false", "0", "no")
    eligible_flag = bool(eligible_flag)

    if not eligible_flag:
        reason_text = str(row.get("reason", "Patient marked ineligible in the insurance database."))
        return Eligibility(
            eligible=False,
            patient_id=patient_id,
            income_bracket=income_bracket,
            existing_coverage=existing_coverage,
            reason=reason_text,
        )

    return Eligibility(
        eligible=True,
        patient_id=patient_id,
        income_bracket=income_bracket,
        existing_coverage=existing_coverage,
        reason="Patient is eligible and coverage is active.",
    )
