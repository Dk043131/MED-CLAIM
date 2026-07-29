"""
pipeline/gemini_ocr.py — Gemini Vision: Combined OCR + Structured Extraction

Uses the new `google-genai` SDK (not deprecated `google-generativeai`).

Model split:
  OCR + Extraction  → gemini-3-flash-preview  (multimodal, high accuracy)
  Text-only fallback → gemini-3-flash-preview  (if bytes unavailable)

Returns a tuple: (raw_ocr_text, structured_dict, confidence_score)
The structured_dict maps directly onto ExtractedJSON fields.
"""
from __future__ import annotations
import base64
import json
import re
from typing import Any

from app.config import GEMINI_API_KEY

# ── Model names ───────────────────────────────────────────────────────────────
OCR_MODEL = "gemini-2.0-flash"

# ── Combined extraction prompt ────────────────────────────────────────────────
_COMBINED_PROMPT = """You are an expert clinical vision AI for Indian hospital records, discharge summaries, lab reports, prescriptions, and medical bills.
Extract ALL information from this medical document image with 100% precision.

Return ONLY valid JSON (no markdown fences, no commentary) with this exact structure:
{
  "raw_text": "complete verbatim text extracted from the document",
  "document_type": "Discharge Summary / Medical Report / Lab Report / Doctor Prescription / Hospital Bill",
  "patient_name": "full patient name",
  "patient_id": "UHID, IP Number, or Patient ID if visible",
  "hospital_name": "hospital, clinic, or diagnostic center name",
  "age": 0,
  "sex": "M or F",
  "date": "YYYY-MM-DD",
  "doctor_name": "doctor name with title",
  "doctor_id": "doctor registration ID if visible",
  "symptoms": ["chief complaint 1", "complaint 2"],
  "diagnosis": ["diagnosis 1", "diagnosis 2"],
  "procedure_performed": "name of surgery or procedure performed (e.g. CABG x 3, Appendectomy)",
  "vitals": {"bp": "110/70", "pulse": "60 bpm", "rbs": "50 mg/dL", "ef": "LVEF 45%"},
  "medications": [{"name": "drug name", "dose": "dosage e.g. 75mg", "route": "oral/IV", "frequency": "OD/BD/TID", "duration": "duration", "raw_text": "original string"}],
  "lab_results": [{"parameter": "test name e.g. Hb / LAD Stenosis", "result": "result value", "reference_range": "normal range", "status": "NORMAL/HIGH/LOW"}],
  "line_items": [{"description": "bill item name", "amount": 500.0, "raw_text": "original string"}],
  "advice": ["advice or discharge instruction 1", "advice 2"],
  "consultation_fee": 0.0,
  "total": 0.0,
  "ocr_confidence_notes": "describe any blurry or unclear parts"
}

Extraction Guidelines:
- Chief complaints / c/o → "symptoms" list
- Diagnosis / Impression / Imp → "diagnosis" list
- Surgical / Procedure performed → "procedure_performed" string
- Medications section → "medications" list (Do NOT place medications inside "line_items" unless they have explicit prices on a bill!)
- Financial bill line items → ONLY place items with monetary values into "line_items" (e.g., {"description": "Bed Charges", "amount": 1500.0}). Never put raw non-financial text lines in line_items!
- If a field is not present: use "" for strings, 0 for numbers, [] for lists, {} for objects
"""

# ── Text-only structuring prompt (when no image bytes available) ──────────────
_TEXT_PROMPT = """You are a clinical document AI for Indian hospital prescriptions.
Extract structured information from this raw OCR text.

Return ONLY valid JSON (no markdown) with this structure:
{
  "patient_name": "", "patient_id": "", "hospital_name": "",
  "age": 0, "sex": "M", "date": "",
  "doctor_name": "", "doctor_id": "",
  "symptoms": [], "diagnosis": [],
  "vitals": {}, "medications": [], "line_items": [], "advice": [],
  "consultation_fee": 0.0, "ocr_confidence_notes": ""
}

Indian abbreviations: c/o=complaints, Imp=impression/diagnosis, Adv=advice, 
RBS=blood sugar, PR=pulse, UHID/IP=patient ID. 
Date format 22/12/22 → 2022-12-22. Age/Sex shorthand 19/M → age=19, sex=M.

Raw OCR text:
\"\"\"{raw_ocr}\"\"\"

Output JSON:"""


def _get_client():
    """Lazily construct google-genai client."""
    from google import genai  # type: ignore
    return genai.Client(api_key=GEMINI_API_KEY)


def _clean_json(text: str) -> str:
    """Strip markdown fences and leading/trailing whitespace from LLM output."""
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


def extract_with_gemini(file_bytes: bytes, filename: str = "") -> tuple[str, dict, float]:
    """
    Combined OCR + structured extraction in ONE Gemini API call.
    Tries multiple model versions when quota is exhausted.

    Args:
        file_bytes: Raw bytes of the medical bill image/PDF
        filename:   Original filename (used for MIME type detection)

    Returns:
        (raw_ocr_text: str, structured_data: dict, confidence: float)
    """
    from google import genai  # type: ignore
    from google.genai import types  # type: ignore

    client = _get_client()

    filename_lower = (filename or "").lower()
    if filename_lower.endswith(".pdf"):
        mime_type = "application/pdf"
    elif filename_lower.endswith(".png"):
        mime_type = "image/png"
    elif filename_lower.endswith(".webp"):
        mime_type = "image/webp"
    elif filename_lower.endswith(".gif"):
        mime_type = "image/gif"
    else:
        mime_type = "image/jpeg"

    image_part = types.Part.from_bytes(data=file_bytes, mime_type=mime_type)

    response = client.models.generate_content(
        model=OCR_MODEL,
        contents=[image_part, _COMBINED_PROMPT],
        config=types.GenerateContentConfig(
            temperature=0.0,
            max_output_tokens=2048,
        ),
    )
    print(f"[GeminiOCR] Used model: {OCR_MODEL}")

    raw_text = response.text or ""
    cleaned = _clean_json(raw_text)

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        # Try to extract JSON from somewhere in the response
        match = re.search(r"\{[\s\S]+\}", raw_text)
        if match:
            data = json.loads(match.group(0))
        else:
            raise ValueError(f"Gemini returned non-JSON: {raw_text[:200]}")

    # raw_text field from the model
    raw_ocr = data.pop("raw_text", raw_text)

    # Estimate confidence from richness of extraction
    words = len(raw_ocr.split())
    n_symptoms = len(data.get("symptoms", [])) + len(data.get("diagnosis", []))
    confidence = min(97.0, 65.0 + min(words, 50) * 0.4 + n_symptoms * 2.0)

    return raw_ocr, data, round(confidence, 1)



def extract_text_with_gemini(raw_ocr: str) -> dict:
    """
    Text-only Gemini call for structuring (when image bytes not available).
    Tries multiple model versions when quota is exhausted.
    """
    from google import genai  # type: ignore
    from google.genai import types  # type: ignore

    client = _get_client()
    prompt = _TEXT_PROMPT.replace("{raw_ocr}", raw_ocr)

    response = client.models.generate_content(
        model=OCR_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=0.0,
            max_output_tokens=1536,
        ),
    )
    print(f"[GeminiOCR text] Used model: {OCR_MODEL}")

    cleaned = _clean_json(response.text or "")
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{[\s\S]+\}", response.text or "")
        if match:
            return json.loads(match.group(0))
        raise ValueError(f"Gemini text structuring returned non-JSON: {(response.text or '')[:200]}")


def gemini_dict_to_extracted(data: dict):
    """
    Convert the Gemini JSON response dict into an ExtractedJSON model.
    Merges symptoms + diagnosis + procedures into symptom list for ICD harmonization.
    """
    from app.models import ExtractedJSON, LineItem

    # Build line items (only items that have financial amounts or valid bill items)
    line_items = []
    for li in data.get("line_items", []):
        if isinstance(li, dict):
            desc = li.get("description", "") or li.get("item", "") or li.get("raw_text", "")
            try:
                amt = float(li.get("amount", 0.0) or li.get("price", 0.0) or 0.0)
            except (ValueError, TypeError):
                amt = 0.0
            if desc:
                line_items.append(LineItem(
                    description=desc,
                    raw_text=li.get("raw_text", desc),
                    amount=amt
                ))

    # Medications list
    medications = data.get("medications", []) or []
    prescribed_medications = []
    for med in medications:
        if isinstance(med, dict):
            prescribed_medications.append({
                "medication": med.get("name", "") or med.get("medication", ""),
                "dosage": med.get("dose", "") or med.get("dosage", ""),
                "duration": med.get("duration", "") or med.get("frequency", ""),
                "quantity": med.get("quantity", "1")
            })

    # Lab results list
    lab_results = data.get("lab_results", []) or []

    # Merge symptoms + diagnosis + procedure performed (deduplicated)
    symptoms = list(data.get("symptoms", []))
    for d in data.get("diagnosis", []):
        if d and d not in symptoms:
            symptoms.append(d)
    procedure = str(data.get("procedure_performed", "") or "")
    if procedure and procedure not in symptoms:
        symptoms.append(procedure)

    # Vitals dict
    vitals = data.get("vitals", {}) or {}

    # Build OCR notes
    vitals_parts = []
    if vitals.get("bp"):    vitals_parts.append(f"BP: {vitals['bp']}")
    if vitals.get("pulse"): vitals_parts.append(f"PR: {vitals['pulse']}")
    if vitals.get("rbs"):   vitals_parts.append(f"RBS: {vitals['rbs']}")
    if vitals.get("ef"):    vitals_parts.append(f"EF: {vitals['ef']}")
    vitals_note = " | ".join(vitals_parts)
    ocr_note = str(data.get("ocr_confidence_notes", "") or "")
    full_note = f"{vitals_note} | {ocr_note}" if vitals_note and ocr_note else (vitals_note or ocr_note)

    # Safely parse numeric fields
    try:
        age = int(data.get("age", 0) or 0)
    except (ValueError, TypeError):
        age = 0

    try:
        consultation_fee = float(data.get("consultation_fee", 0) or 0)
    except (ValueError, TypeError):
        consultation_fee = 0.0

    try:
        total_amt = float(data.get("total", 0) or 0)
    except (ValueError, TypeError):
        total_amt = 0.0

    return ExtractedJSON(
        document_type=str(data.get("document_type", "") or ""),
        patient_name=str(data.get("patient_name", "") or ""),
        patient_id=str(data.get("patient_id", "") or ""),
        hospital_name=str(data.get("hospital_name", "") or ""),
        age=age,
        sex=str(data.get("sex", "M") or "M").upper()[:1],
        date=str(data.get("date", "") or ""),
        doctor_name=str(data.get("doctor_name", "") or ""),
        doctor_id=str(data.get("doctor_id", "") or ""),
        symptoms=symptoms[:12],
        diagnosis=list(data.get("diagnosis", []) or []),
        procedure_performed=procedure,
        line_items=line_items[:20],
        prescribed_medications=prescribed_medications[:15],
        lab_results=lab_results[:15],
        consultation_fee=consultation_fee,
        total=total_amt,
        ocr_confidence_notes=full_note,
        vitals=vitals,
        advice=list(data.get("advice", []) or []),
    )
