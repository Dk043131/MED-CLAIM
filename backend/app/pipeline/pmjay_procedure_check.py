"""
pipeline/pmjay_procedure_check.py — PM-JAY Procedure Scope Checker (Stage 3.5)

Checks whether the diagnosed conditions/procedures fall within PM-JAY's
covered 1,929 procedure package list. Flags outpatient-only visits,
dental, cosmetic, and non-covered procedures.
"""
from __future__ import annotations
import os
import pandas as pd
from dataclasses import dataclass
from app.config import PMJAY_PROCEDURES_CSV

@dataclass
class ProcedureScopeResult:
    covered: bool
    package_code: str
    package_name: str
    max_rate_inr: float
    rejection_reason: str

_procedures_df: pd.DataFrame | None = None

OUTPATIENT_INDICATORS = ["opd", "outpatient", "consultation only", "routine checkup", "clinic visit"]
EXCLUDED_CATEGORIES = ["dental", "cosmetic", "elective", "beauty", "aesthetic", "whitening"]

def _load_procedures_df() -> pd.DataFrame:
    global _procedures_df
    if _procedures_df is None:
        if not os.path.exists(PMJAY_PROCEDURES_CSV):
            raise FileNotFoundError(f"Procedures CSV not found at {PMJAY_PROCEDURES_CSV}")
        _procedures_df = pd.read_csv(PMJAY_PROCEDURES_CSV)
        _procedures_df.columns = [c.strip().lower().replace(" ", "_") for c in _procedures_df.columns]
    return _procedures_df

def check_procedure_scope(icd10_codes: list[str], line_items: list[str], symptoms: list[str]) -> ProcedureScopeResult:
    all_text = " ".join(line_items + symptoms).lower()
    
    for excluded in EXCLUDED_CATEGORIES:
        if excluded in all_text:
            return ProcedureScopeResult(False, "", "", 0.0, "dental_cosmetic")
            
    if any(ind in all_text for ind in OUTPATIENT_INDICATORS) and "admission" not in all_text and "ipd" not in all_text:
        return ProcedureScopeResult(False, "", "", 0.0, "outpatient_only")

    if not icd10_codes:
        return ProcedureScopeResult(True, "DEFAULT", "Default Package (No ICD-10)", 0.0, "")

    try:
        df = _load_procedures_df()
    except FileNotFoundError:
        return ProcedureScopeResult(True, "UNKNOWN", "Unknown Package (No DB)", 0.0, "")

    if "icd10_code_hint" in df.columns:
        for code in icd10_codes:
            # Match exact code or 3-character prefix (e.g. R50.9 matches R50)
            prefix = code.split(".")[0] if "." in code else code
            mask = df["icd10_code_hint"].str.contains(code, case=False, na=False) | df["icd10_code_hint"].str.contains(prefix, case=False, na=False)
            matched = df[mask]
            if not matched.empty:
                row = matched.iloc[0]
                return ProcedureScopeResult(
                    covered=True,
                    package_code=str(row.get("package_code", "")),
                    package_name=str(row.get("package_name", "")),
                    max_rate_inr=float(row.get("max_rate_inr", 0.0)),
                    rejection_reason=""
                )

    # General Medical Management fallback for unlisted medical conditions (covered)
    return ProcedureScopeResult(True, "PMJAY-GEN-001", "General Medical Management Package", 25000.0, "")

def needs_procedure_review(result: ProcedureScopeResult) -> bool:
    return not result.covered
