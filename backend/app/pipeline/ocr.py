"""
pipeline/ocr.py — Stage 1: OCR (Gemini Vision → Google Cloud Vision → Stub)

Priority order:
  1. Gemini 1.5 Flash Vision (FREE tier — just GEMINI_API_KEY in .env)
  2. Google Cloud Vision API (requires service account JSON)
  3. Stub (pre-saved .txt files — zero API cost, demo-safe)

Gemini is preferred because:
  - Free tier with no service account setup
  - Handles handwritten Indian medical prescriptions better
  - Single API call does OCR + structuring simultaneously
"""
from __future__ import annotations
import os
from app.config import USE_OCR_STUB, USE_GEMINI, SAMPLE_BILLS_DIR, GEMINI_API_KEY


# ── Stub Implementation ──────────────────────────────────────────────────────

def ocr_bill_stub(file_bytes: bytes, filename: str = "") -> tuple[str, float]:
    """
    Returns (raw_ocr_text, confidence_score) from a pre-saved stub .txt file.
    Chooses stub text based on filename hints; falls back to a generic clean bill.
    """
    name_lower = filename.lower()

    if "ambiguous" in name_lower or "illegible" in name_lower:
        stub_file = "ambiguous_bill.txt"
        confidence = 48.0
    elif "ineligible" in name_lower:
        stub_file = "ineligible_bill.txt"
        confidence = 88.0
    elif "duplicate" in name_lower:
        stub_file = "duplicate_bill.txt"
        confidence = 91.0
    elif "rare" in name_lower or "complex" in name_lower:
        stub_file = "rare_symptom_bill.txt"
        confidence = 74.0
    elif "high" in name_lower:
        stub_file = "high_claim_bill.txt"
        confidence = 85.0
    else:
        stub_file = "clean_bill.txt"
        confidence = 96.5

    stub_path = os.path.join(SAMPLE_BILLS_DIR, stub_file)
    if os.path.exists(stub_path):
        with open(stub_path, "r", encoding="utf-8") as f:
            return f.read(), confidence

    return _minimal_bill_text(), 92.0


def _minimal_bill_text() -> str:
    return (
        "CITY GENERAL HOSPITAL\n"
        "Patient: Rahul Sharma\nAge: 34 Sex: M\nDate: 2024-06-15\n"
        "Doctor: Dr. Priya Mehta\n"
        "Symptoms: Fever, headache, mild cough\n"
        "Consultation Fee: 500\n"
        "Medicines: Paracetamol 500mg x 10 - 80\n"
        "Total: 580"
    )


# ── Real Implementation (Google Cloud Vision) ────────────────────────────────

def ocr_bill_real(file_bytes: bytes, filename: str = "") -> tuple[str, float]:
    """
    Calls Google Cloud Vision document_text_detection (legacy path).
    Returns (raw_text, mean_confidence_percentage).
    """
    from google.cloud import vision  # type: ignore

    client = vision.ImageAnnotatorClient()
    image = vision.Image(content=file_bytes)
    response = client.document_text_detection(image=image)

    if response.error.message:
        raise RuntimeError(f"Vision API error: {response.error.message}")

    full_text = response.full_text_annotation.text

    confidences = [
        page.confidence
        for page in response.full_text_annotation.pages
        if page.confidence > 0
    ]
    mean_conf = (sum(confidences) / len(confidences) * 100) if confidences else 80.0

    return full_text, round(mean_conf, 2)


# ── Gemini Vision OCR (raw text only) ────────────────────────────────────────

def ocr_bill_gemini_raw(file_bytes: bytes, filename: str = "") -> tuple[str, float]:
    """
    Uses Gemini 3-flash-preview Vision to extract raw text only (Stage 1 OCR).
    Uses new google-genai SDK. For combined OCR+structure use gemini_ocr.extract_with_gemini().
    """
    from google import genai  # type: ignore
    from google.genai import types  # type: ignore

    client = genai.Client(api_key=GEMINI_API_KEY)

    filename_lower = (filename or "").lower()
    if filename_lower.endswith(".pdf"):
        mime_type = "application/pdf"
    elif filename_lower.endswith(".png"):
        mime_type = "image/png"
    elif filename_lower.endswith(".webp"):
        mime_type = "image/webp"
    else:
        mime_type = "image/jpeg"

    image_part = types.Part.from_bytes(data=file_bytes, mime_type=mime_type)

    prompt = (
        "You are an OCR engine specialized in handwritten Indian medical prescriptions. "
        "Extract ALL text from this image exactly as written, including:\n"
        "- Patient name, UHID/IP number, age, sex, date\n"
        "- Hospital name, doctor name and signature ID\n"
        "- Complaints (c/o), Impression/Diagnosis, Vitals (BP, PR, RBS, SpO2)\n"
        "- Medications, dosages, routes, advice\n\n"
        "Return ONLY the raw extracted text, nothing else. Preserve line breaks."
    )

    response = client.models.generate_content(
        model="gemini-3-flash-preview",
        contents=[image_part, prompt],
        config=types.GenerateContentConfig(
            temperature=0.0,
            max_output_tokens=1024,
        ),
    )

    raw_text = (response.text or "").strip()

    # Estimate confidence based on text richness
    words = len(raw_text.split())
    confidence = min(96.0, 60.0 + min(words, 60) * 0.6)

    return raw_text, round(confidence, 1)



# ── Public Entrypoint ─────────────────────────────────────────────────────────

def ocr_bill(file_bytes: bytes, filename: str = "") -> tuple[str, float]:
    """
    Stage 1 — OCR entry point.
    Returns (raw_ocr_text: str, confidence: float  [0–100])

    Priority: Gemini (free) → Cloud Vision (requires credentials) → Stub
    """
    if USE_OCR_STUB:
        print("[OCR] No API keys configured — using stub.")
        return ocr_bill_stub(file_bytes, filename)

    # Try Gemini first (free, no service account)
    if USE_GEMINI:
        try:
            return ocr_bill_gemini_raw(file_bytes, filename)
        except Exception as exc:
            print(f"[OCR] Gemini failed ({exc}); trying Cloud Vision...")

    # Try Google Cloud Vision (legacy)
    try:
        return ocr_bill_real(file_bytes, filename)
    except Exception as exc:
        print(f"[OCR] Cloud Vision failed ({exc}); falling back to stub.")

    return ocr_bill_stub(file_bytes, filename)
