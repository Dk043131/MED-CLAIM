"""
config.py — Environment & Application Settings
Loads API keys and config from .env file. Falls back gracefully to stub mode
when cloud API keys are not present (demo-safe).
"""
import os
from dotenv import load_dotenv

load_dotenv()

# ── Anthropic (Claude) ──────────────────────────────────────────────────────
ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")

# ── Google Gemini Vision (Free Tier — no service account needed) ─────────────
GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")

# ── Google Cloud Vision (legacy — service account JSON required) ─────────────
GOOGLE_APPLICATION_CREDENTIALS: str = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "")

# ── Database ────────────────────────────────────────────────────────────────
DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./med_claim.db")

# ── Pipeline Thresholds ─────────────────────────────────────────────────────
# Claims with ICD-10 coding confidence BELOW this value are routed to human review
CONFIDENCE_THRESHOLD: float = float(os.getenv("CONFIDENCE_THRESHOLD", "0.80"))

# OCR confidence score below which a claim is flagged (0-100 scale from Vision API)
OCR_CONFIDENCE_THRESHOLD: float = float(os.getenv("OCR_CONFIDENCE_THRESHOLD", "60.0"))

# ── Stub/Fallback Flags ─────────────────────────────────────────────────────
# Auto-detected at runtime: if no API keys are present, stubs are used automatically
USE_GEMINI: bool = bool(GEMINI_API_KEY)
USE_OCR_STUB: bool = not (bool(GOOGLE_APPLICATION_CREDENTIALS) or bool(GEMINI_API_KEY))
USE_LLM_STUB: bool = not (bool(ANTHROPIC_API_KEY) or bool(GEMINI_API_KEY))

# ── Security Settings ───────────────────────────────────────────────────────
# Max failed login attempts before account lockout
MAX_LOGIN_ATTEMPTS: int = int(os.getenv("MAX_LOGIN_ATTEMPTS", "5"))
# Lockout window in minutes
LOCKOUT_WINDOW_MINUTES: int = int(os.getenv("LOCKOUT_WINDOW_MINUTES", "15"))
# Session expiry in days
SESSION_EXPIRY_DAYS: int = int(os.getenv("SESSION_EXPIRY_DAYS", "7"))

# ── Allowed CORS Origins ────────────────────────────────────────────────────
ALLOWED_ORIGINS: list = os.getenv(
    "ALLOWED_ORIGINS",
    "http://localhost:8080,http://127.0.0.1:8080,http://localhost:3000,http://localhost:5173"
).split(",")

# ── Data Paths ──────────────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
ICD10_CSV = os.path.join(DATA_DIR, "icd10_codes.csv")
ELIGIBILITY_CSV = os.path.join(DATA_DIR, "eligibility.csv")
SAMPLE_BILLS_DIR = os.path.join(DATA_DIR, "sample_bills")

# ── PM-JAY Specific Data Paths ──────────────────────────────────────────────
PMJAY_PROCEDURES_CSV = os.path.join(DATA_DIR, "pmjay_procedures.csv")
EMPANELLED_HOSPITALS_CSV = os.path.join(DATA_DIR, "empanelled_hospitals.csv")

# ── PM-JAY Scheme Constants ─────────────────────────────────────────────────
# States where PM-JAY is NOT active (opted out) — route to state scheme
PMJAY_OPTED_OUT_STATES: list = ["West Bengal", "WB"]

# State → supplementary scheme mapping
STATE_SCHEME_MAP: dict = {
    "Tamil Nadu": "CMCHIS",
    "TN": "CMCHIS",
    "Maharashtra": "MJPJAY",
    "MH": "MJPJAY",
    "Rajasthan": "RGHS",
    "RJ": "RGHS",
    "West Bengal": "WBHS",
    "WB": "WBHS",
}

# PM-JAY annual coverage cap per family
PMJAY_FAMILY_CAP_INR: float = 500000.0
PMJAY_SENIOR_CAP_INR: float = 500000.0   # Additional cap for 70+ members

# Hospital name fuzzy match threshold (0-100, rapidfuzz score)
HOSPITAL_MATCH_THRESHOLD: float = float(os.getenv("HOSPITAL_MATCH_THRESHOLD", "65.0"))
