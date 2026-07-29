"""
pipeline/aadhaar_verifier.py — Mock Aadhaar KYC + OTP Verifier

Simulates the Aadhaar verification flow from beneficiary.nha.gov.in:
  Step 1: Validate Aadhaar format (12-digit Verhoeff algorithm)
  Step 2: Mock OTP dispatch (deterministic hash-based for demo)
  Step 3: OTP verification
  Step 4: Lookup beneficiary by Aadhaar number

Q&A ready:
  Real: Aadhaar format validation (Verhoeff check digit algorithm)
  Mocked: OTP (deterministic SHA-256 hash of aadhaar+mobile+date for reproducibility)
  Roadmap: Replace with UIDAI's Auth API for production
"""
from __future__ import annotations
import re
import hashlib
from datetime import date, datetime, timedelta
import pandas as pd
from app.config import ELIGIBILITY_CSV

# Verhoeff algorithm tables
d = (
    (0, 1, 2, 3, 4, 5, 6, 7, 8, 9),
    (1, 2, 3, 4, 0, 6, 7, 8, 9, 5),
    (2, 3, 4, 0, 1, 7, 8, 9, 5, 6),
    (3, 4, 0, 1, 2, 8, 9, 5, 6, 7),
    (4, 0, 1, 2, 3, 9, 5, 6, 7, 8),
    (5, 9, 8, 7, 6, 0, 4, 3, 2, 1),
    (6, 5, 9, 8, 7, 1, 0, 4, 3, 2),
    (7, 6, 5, 9, 8, 2, 1, 0, 4, 3),
    (8, 7, 6, 5, 9, 3, 2, 1, 0, 4),
    (9, 8, 7, 6, 5, 4, 3, 2, 1, 0)
)

p = (
    (0, 1, 2, 3, 4, 5, 6, 7, 8, 9),
    (1, 5, 7, 6, 2, 8, 3, 0, 9, 4),
    (5, 8, 0, 3, 7, 9, 6, 1, 4, 2),
    (8, 9, 1, 6, 0, 4, 3, 5, 2, 7),
    (9, 4, 5, 3, 1, 2, 6, 8, 7, 0),
    (4, 2, 8, 6, 5, 7, 3, 9, 0, 1),
    (2, 7, 9, 3, 8, 0, 6, 4, 1, 5),
    (7, 0, 4, 6, 9, 1, 3, 2, 5, 8)
)

inv = (0, 4, 3, 2, 1, 5, 6, 7, 8, 9)

def _verhoeff_check(digits: str) -> bool:
    """Implement the real Verhoeff check digit algorithm."""
    c = 0
    for i, item in enumerate(reversed(digits)):
        c = d[c][p[i % 8][int(item)]]
    return c == 0

def validate_aadhaar_format(aadhaar: str) -> bool:
    """Strip hyphens/spaces, check 12 digits, and validate via Verhoeff."""
    clean_aadhaar = re.sub(r'[\s-]', '', aadhaar)
    if not re.match(r'^\d{12}$', clean_aadhaar):
        return False
    return _verhoeff_check(clean_aadhaar)

def generate_otp_token(aadhaar: str, mobile: str) -> dict:
    """Mock OTP dispatch (deterministic hash-based for demo)."""
    date_str = date.today().isoformat()
    raw_str = f"{aadhaar}{mobile}{date_str}".encode('utf-8')
    
    hash_val = hashlib.sha256(raw_str).hexdigest()
    otp = str(int(hash_val, 16) % 9000 + 1000)
    
    token_str = f"{aadhaar}{mobile}TOKEN".encode('utf-8')
    otp_token = hashlib.sha256(token_str).hexdigest()[:16]
    
    expires_at = (datetime.now() + timedelta(minutes=10)).isoformat()
    
    return {
        "otp_token": otp_token,
        "otp": otp,
        "expires_at": expires_at
    }

def verify_otp(otp_token: str, entered_otp: str, aadhaar: str, mobile: str) -> bool:
    """Verify OTP and Token."""
    expected_data = generate_otp_token(aadhaar, mobile)
    return expected_data["otp_token"] == otp_token and expected_data["otp"] == entered_otp

def lookup_by_aadhaar(aadhaar: str) -> dict | None:
    """Lookup beneficiary by Aadhaar number in the mock eligibility DB."""
    try:
        df = pd.read_csv(ELIGIBILITY_CSV)
        df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]
    except Exception:
        return None
        
    clean_aadhaar = re.sub(r'[\s-]', '', aadhaar)
    
    if "aadhaar_number" not in df.columns:
        return None
        
    df['clean_aadhaar'] = df['aadhaar_number'].astype(str).str.replace(r'[\s-]', '', regex=True)
    
    matched = df[df['clean_aadhaar'] == clean_aadhaar]
    if matched.empty:
        return None
        
    return matched.iloc[0].to_dict()

def generate_ecard_data(patient_row: dict, family_members: list[dict]) -> dict:
    """Generate a dict representing the Ayushman Card."""
    return {
        "card_number": f"AB-{patient_row.get('patient_id', 'UNKNOWN')}",
        "patient_name": patient_row.get('patient_name', ''),
        "family_id": patient_row.get('family_id', 'FAM-DEFAULT'),
        "scheme": "PM-JAY",
        "secc_category": patient_row.get('income_bracket', 'Unknown'),
        "issued_at": datetime.now().isoformat(),
        "members": family_members
    }
