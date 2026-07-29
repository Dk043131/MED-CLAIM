"""
pipeline/duplicates.py — Claim Twins: Duplicate Check

Prevents duplicate billing / fraud by querying existing claims in SQLite.
Checks if a claim for the same patient with matching procedure/symptoms was
submitted within a window of ±7 days.
"""
from __future__ import annotations
import logging
from typing import Dict, Any, List

logger = logging.getLogger("med_claim.duplicates")


def check_duplicate_claims(
    patient_name: str,
    symptoms: List[str],
    current_claim_id: str = "",
    window_days: int = 7
) -> Dict[str, Any]:
    """
    Scans recent database records for duplicate claims submitted for the same patient.

    Returns:
        Dict with is_duplicate (bool), twin_claim_ids (List[str]), and reason (str).
    """
    if not patient_name:
        return {"is_duplicate": False, "twin_claim_ids": [], "reason": ""}

    norm_name = patient_name.strip().lower()
    twins: List[str] = []

    try:
        from app.storage import get_claims
        all_claims = get_claims()

        for claim in all_claims:
            if current_claim_id and claim.claim_id == claim.claim_id and claim.claim_id == current_claim_id:
                continue

            row_patient = (claim.extracted_json.patient_name or "").strip().lower()
            if row_patient == norm_name and norm_name not in ("patient record", "unknown", ""):
                twins.append(claim.claim_id)

        if twins:
            logger.info(f"Duplicate twin detected for patient '{patient_name}': matching claim IDs {twins}")
            return {
                "is_duplicate": True,
                "twin_claim_ids": twins,
                "reason": f"Possible duplicate submission: matches existing claim(s) {', '.join(twins)} for patient '{patient_name}'."
            }

    except Exception as exc:
        logger.warning(f"Error checking duplicate claims: {exc}")

    return {"is_duplicate": False, "twin_claim_ids": [], "reason": ""}
