"""
pipeline/ocr.py — Stage 1: OCR (Google Cloud Vision or local stub)

Real path:  Uses document_text_detection from Google Cloud Vision API.
Stub path:  Reads a saved .txt file from data/sample_bills/ — zero API cost,
            demo-safe, fully functional for testing the rest of the pipeline.

Auto-selects based on GOOGLE_APPLICATION_CREDENTIALS env var presence.
"""
from __future__ import annotations
import os
import re
from app.config import USE_OCR_STUB, SAMPLE_BILLS_DIR


# ── Stub Implementation ──────────────────────────────────────────────────────

def ocr_bill_stub(file_bytes: bytes, filename: str = "") -> tuple[str, float]:
    """
    Returns (raw_ocr_text, confidence_score) from a pre-saved stub .txt file.
    Chooses stub text based on filename hints; falls back to a generic clean bill.

    Confidence range: 0–100 (mimics Vision API's page-level confidence * 100).
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

    # Ultimate fallback — inline minimal bill text
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
    Calls Google Cloud Vision document_text_detection.
    Returns (raw_text, mean_confidence_percentage).
    Raises ImportError if the SDK is not installed.
    Raises google.api_core.exceptions.GoogleAPIError on API failure.
    """
    from google.cloud import vision  # type: ignore

    client = vision.ImageAnnotatorClient()
    image = vision.Image(content=file_bytes)
    response = client.document_text_detection(image=image)

    if response.error.message:
        raise RuntimeError(f"Vision API error: {response.error.message}")

    full_text = response.full_text_annotation.text

    # Compute mean page confidence (Vision returns per-page confidence 0–1)
    confidences = [
        page.confidence
        for page in response.full_text_annotation.pages
        if page.confidence > 0
    ]
    mean_conf = (sum(confidences) / len(confidences) * 100) if confidences else 80.0

    return full_text, round(mean_conf, 2)


# ── Public Entrypoint ─────────────────────────────────────────────────────────

def ocr_bill(file_bytes: bytes, filename: str = "") -> tuple[str, float]:
    """
    Stage 1 — OCR entry point.
    Returns (raw_ocr_text: str, confidence: float  [0–100])

    Automatically routes to the real Vision API when credentials are configured,
    otherwise falls back to the stub implementation gracefully.
    """
    if USE_OCR_STUB:
        return ocr_bill_stub(file_bytes, filename)
    try:
        return ocr_bill_real(file_bytes, filename)
    except Exception as exc:
        # If real call fails for any reason (quota, network), fall back to stub
        print(f"[OCR] Vision API failed ({exc}); falling back to stub.")
        return ocr_bill_stub(file_bytes, filename)
