"""
pipeline/fingerprint.py — Headline Differentiator: Clinic Handwriting Fingerprinting

Implements correction-memory caching per clinic:
1. Every time a caseworker corrects OCR/coding output in HITL, store:
   (clinic_id, raw_ocr_snippet, corrected_value, field_type).
2. When a new bill arrives from the clinic, check fuzzy similarity using rapidfuzz.
3. If score >= threshold, pre-fill field with confirmed value and mark high-confidence!
"""
from __future__ import annotations
import logging
from typing import Optional, Dict, Any
from sqlalchemy import select, update, insert
from rapidfuzz import fuzz, process
from app.database import engine, clinic_fingerprints_table

logger = logging.getLogger("med_claim.fingerprint")


def check_clinic_fingerprint(
    clinic_id: str,
    raw_snippet: str,
    field_type: str,
    threshold: int = 80
) -> Optional[Dict[str, Any]]:
    """
    Check if this clinic has a previously confirmed human correction for similar OCR text.

    Args:
        clinic_id: Unique identifier for the hospital/clinic (e.g. "CLINIC-MENON").
        raw_snippet: The raw, messy OCR text seen for a field.
        field_type: Category of field ("doctor_name", "symptom", "line_item", etc.).
        threshold: Fuzzy ratio similarity cutoff (0-100). Default 80.

    Returns:
        Dict with corrected_value, match_confidence, hit_count, source if match found, else None.
    """
    if not clinic_id or not raw_snippet:
        return None

    try:
        with engine.connect() as conn:
            stmt = select(
                clinic_fingerprints_table.c.raw_ocr_snippet,
                clinic_fingerprints_table.c.corrected_value,
                clinic_fingerprints_table.c.hit_count
            ).where(
                clinic_fingerprints_table.c.clinic_id == clinic_id,
                clinic_fingerprints_table.c.field_type == field_type
            )
            rows = conn.execute(stmt).fetchall()

        if not rows:
            return None

        candidates = {row.raw_ocr_snippet: (row.corrected_value, row.hit_count) for row in rows}
        match = process.extractOne(raw_snippet, list(candidates.keys()), scorer=fuzz.ratio)

        if match and match[1] >= threshold:
            matched_snippet, score, _ = match
            corrected_value, hit_count = candidates[matched_snippet]
            logger.info(f"Fingerprint match for {clinic_id} [{field_type}]: '{raw_snippet}' -> '{corrected_value}' (conf: {score}%)")
            return {
                "corrected_value": corrected_value,
                "match_confidence": round(score / 100.0, 2),
                "hit_count": hit_count,
                "raw_ocr_snippet": matched_snippet,
                "source": "clinic_fingerprint"
            }
    except Exception as exc:
        logger.warning(f"Error checking clinic fingerprint: {exc}")

    return None


def save_correction_to_fingerprint(
    clinic_id: str,
    raw_snippet: str,
    corrected_value: str,
    field_type: str
) -> bool:
    """
    Saves a caseworker confirmed correction into the clinic's fingerprint memory.
    If the snippet already exists, increments its hit count.
    """
    if not clinic_id or not raw_snippet or not corrected_value:
        return False

    try:
        with engine.begin() as conn:
            stmt = select(clinic_fingerprints_table.c.id, clinic_fingerprints_table.c.hit_count).where(
                clinic_fingerprints_table.c.clinic_id == clinic_id,
                clinic_fingerprints_table.c.raw_ocr_snippet == raw_snippet,
                clinic_fingerprints_table.c.field_type == field_type
            )
            existing = conn.execute(stmt).fetchone()

            if existing:
                conn.execute(
                    update(clinic_fingerprints_table)
                    .where(clinic_fingerprints_table.c.id == existing.id)
                    .values(hit_count=existing.hit_count + 1, corrected_value=corrected_value)
                )
            else:
                conn.execute(
                    insert(clinic_fingerprints_table).values(
                        clinic_id=clinic_id,
                        field_type=field_type,
                        raw_ocr_snippet=raw_snippet,
                        corrected_value=corrected_value,
                        hit_count=1
                    )
                )
        logger.info(f"Saved fingerprint correction for {clinic_id} [{field_type}]: '{raw_snippet}' -> '{corrected_value}'")
        return True
    except Exception as exc:
        logger.error(f"Failed to save clinic fingerprint: {exc}")
        return False
