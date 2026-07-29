"""
pipeline/snomed_mapper.py — Clinical Medical Ontology Mapping (ICD-10 to SNOMED-CT)

Provides automated mapping from ICD-10-CM codes and clinical symptoms
to standardized SNOMED-CT concept codes for healthcare interoperability.
"""
from __future__ import annotations
from typing import Tuple

# ICD-10 code -> (SNOMED-CT Concept ID, SNOMED-CT Preferred Description)
_ICD10_TO_SNOMED: dict[str, Tuple[str, str]] = {
    "R42": ("404640003", "Dizziness (finding)"),
    "E16.2": ("302866003", "Hypoglycemia (disorder)"),
    "R45.1": ("48348007", "Restlessness (finding)"),
    "R50.9": ("386661006", "Fever (finding)"),
    "R51": ("25064002", "Headache (finding)"),
    "R51.9": ("25064002", "Headache (finding)"),
    "R05": ("49727002", "Cough (finding)"),
    "R05.9": ("49727002", "Cough (finding)"),
    "B34.9": ("34014006", "Viral disease (disorder)"),
    "R11.0": ("422587007", "Nausea (finding)"),
    "R11.10": ("422400008", "Vomiting (disorder)"),
    "E86.0": ("34486009", "Dehydration (disorder)"),
    "R53.1": ("13791008", "Asthenia (finding)"),
    "R53.83": ("84229001", "Fatigue (finding)"),
    "J22": ("50417007", "Lower respiratory tract infection (disorder)"),
    "J18.9": ("233604007", "Pneumonia (disorder)"),
    "J06.9": ("54150009", "Upper respiratory tract infection (disorder)"),
    "I10": ("38341003", "Hypertensive disorder (disorder)"),
    "E11.9": ("44054006", "Diabetes mellitus type 2 (disorder)"),
    "R06.02": ("267036007", "Dyspnea (finding)"),
    "R10.9": ("21522001", "Abdominal pain (finding)"),
    "M54.5": ("279039007", "Low back pain (finding)"),
    "M25.50": ("57676002", "Joint pain (finding)"),
    "R21": ("271807003", "Eruption of skin (finding)"),
    "N39.0": ("68566005", "Urinary tract infection (disorder)"),
    "A97.9": ("38362002", "Dengue (disorder)"),
    "B54": ("61462000", "Malaria (disorder)"),
    "A01.00": ("4834000", "Typhoid fever (disorder)"),
}


def lookup_snomed_ct(icd10_code: str, symptom: str = "") -> Tuple[str, str]:
    """
    Returns (snomed_ct_code, snomed_ct_description) for a given ICD-10 code.
    If not found in exact map, attempts prefix matching or generic symptom mapping.
    """
    code_clean = icd10_code.strip().upper()
    if code_clean in _ICD10_TO_SNOMED:
        return _ICD10_TO_SNOMED[code_clean]

    # Try matching first 3 characters of ICD-10 (category level)
    cat_code = code_clean[:3]
    if cat_code in _ICD10_TO_SNOMED:
        return _ICD10_TO_SNOMED[cat_code]

    # Fallback based on symptom keywords
    sym_lower = symptom.lower().strip()
    if "dizz" in sym_lower or "gidd" in sym_lower:
        return ("404640003", "Dizziness (finding)")
    elif "hypoglyc" in sym_lower or "sugar" in sym_lower:
        return ("302866003", "Hypoglycemia (disorder)")
    elif "fever" in sym_lower or "pyrex" in sym_lower:
        return ("386661006", "Fever (finding)")
    elif "pain" in sym_lower:
        return ("22253000", "Pain (finding)")
    elif "infect" in sym_lower:
        return ("40733004", "Infectious disease (disorder)")

    # Default fallback SNOMED CT concept for general clinical finding
    return ("404684003", "Clinical finding (finding)")
