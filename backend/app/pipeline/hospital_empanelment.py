"""
pipeline/hospital_empanelment.py — PM-JAY Hospital Empanelment Checker

Checks whether a given hospital name matches the PM-JAY empanelled hospital list.
Uses fuzzy matching (rapidfuzz if available, else difflib fallback) to handle
OCR spelling variations in hospital names.
"""
from __future__ import annotations
import os
import pandas as pd
from datetime import date
from dataclasses import dataclass
from app.config import EMPANELLED_HOSPITALS_CSV

try:
    from rapidfuzz import process, fuzz
    HAS_RAPIDFUZZ = True
except ImportError:
    import difflib
    HAS_RAPIDFUZZ = False

@dataclass
class HospitalEmpanelmentResult:
    empanelled: bool
    hospital_id: str
    matched_name: str
    match_score: float
    empanelment_expiry: str
    state: str

_hospitals_df: pd.DataFrame | None = None

def _load_hospitals_df() -> pd.DataFrame:
    global _hospitals_df
    if _hospitals_df is None:
        if not os.path.exists(EMPANELLED_HOSPITALS_CSV):
            raise FileNotFoundError(f"Empanelled hospitals CSV not found at {EMPANELLED_HOSPITALS_CSV}")
        _hospitals_df = pd.read_csv(EMPANELLED_HOSPITALS_CSV)
        _hospitals_df.columns = [c.strip().lower().replace(" ", "_") for c in _hospitals_df.columns]
        if "empanelment_expiry" in _hospitals_df.columns:
            _hospitals_df["empanelment_expiry"] = pd.to_datetime(
                _hospitals_df["empanelment_expiry"], errors="coerce"
            )
    return _hospitals_df

def check_hospital_empanelment(hospital_name: str) -> HospitalEmpanelmentResult:
    try:
        df = _load_hospitals_df()
    except FileNotFoundError:
        return HospitalEmpanelmentResult(False, "", "", 0.0, "", "")

    if df.empty or not hospital_name:
        return HospitalEmpanelmentResult(False, "", "", 0.0, "", "")

    names = df["hospital_name"].tolist()
    norm_input = hospital_name.strip().lower()
    best_match = None
    best_score = 0.0

    # 1. Exact case-insensitive match check first
    for name in names:
        if name.strip().lower() == norm_input or norm_input in name.strip().lower() or name.strip().lower() in norm_input:
            best_match = name
            best_score = 100.0
            break

    if best_score < 100.0:
        if HAS_RAPIDFUZZ:
            name_map = {n.strip().lower(): n for n in names}
            result = process.extractOne(norm_input, list(name_map.keys()), scorer=fuzz.WRatio)
            if result:
                matched_key = result[0]
                best_match = name_map.get(matched_key, result[0])
                best_score = float(result[1])
        else:
            for name in names:
                score = difflib.SequenceMatcher(None, norm_input, name.strip().lower()).ratio() * 100
                if score > best_score:
                    best_score = score
                    best_match = name

    from app.config import HOSPITAL_MATCH_THRESHOLD
    threshold = HOSPITAL_MATCH_THRESHOLD or 65.0

    if best_score < threshold or not best_match:
        return HospitalEmpanelmentResult(
            empanelled=False,
            hospital_id="",
            matched_name="",
            match_score=best_score,
            empanelment_expiry="",
            state=""
        )

    matched_row = df[df["hospital_name"] == best_match].iloc[0]
    expiry = matched_row.get("empanelment_expiry")
    hospital_id = str(matched_row.get("hospital_id", ""))
    state = str(matched_row.get("state", ""))
    
    is_empanelled = True
    expiry_str = ""
    if pd.notna(expiry):
        expiry_str = expiry.strftime("%Y-%m-%d")
        if expiry.date() < date.today():
            is_empanelled = False

    return HospitalEmpanelmentResult(
        empanelled=is_empanelled,
        hospital_id=hospital_id,
        matched_name=best_match,
        match_score=best_score,
        empanelment_expiry=expiry_str,
        state=state
    )
