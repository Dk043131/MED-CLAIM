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

# ── Google Cloud Vision ─────────────────────────────────────────────────────
GOOGLE_APPLICATION_CREDENTIALS: str = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "")

# ── Database ────────────────────────────────────────────────────────────────
DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./med_claim.db")

# ── Pipeline Thresholds ─────────────────────────────────────────────────────
# Claims with ICD-10 coding confidence BELOW this value are routed to human review
CONFIDENCE_THRESHOLD: float = float(os.getenv("CONFIDENCE_THRESHOLD", "0.85"))

# OCR confidence score below which a claim is flagged (0-100 scale from Vision API)
OCR_CONFIDENCE_THRESHOLD: float = float(os.getenv("OCR_CONFIDENCE_THRESHOLD", "70.0"))

# ── Stub/Fallback Flags ─────────────────────────────────────────────────────
# Auto-detected at runtime: if no API keys are present, stubs are used automatically
USE_OCR_STUB: bool = not bool(GOOGLE_APPLICATION_CREDENTIALS)
USE_LLM_STUB: bool = not bool(ANTHROPIC_API_KEY)

# ── Data Paths ──────────────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
ICD10_CSV = os.path.join(DATA_DIR, "icd10_codes.csv")
ELIGIBILITY_CSV = os.path.join(DATA_DIR, "eligibility.csv")
SAMPLE_BILLS_DIR = os.path.join(DATA_DIR, "sample_bills")
