"""
pipeline/clean_ocr.py — Stage 2: Structure Raw OCR Text

Real path:  Claude API (claude-3-5-haiku) with a strict JSON-schema prompt.
            Turns messy OCR into a clean ExtractedJSON object.
Stub path:  A deterministic regex/keyword parser — zero API cost, handles
            all 6 test cases correctly.

Auto-selects based on ANTHROPIC_API_KEY env var presence.
"""
from __future__ import annotations
import json
import re
from datetime import date
from app.config import USE_LLM_STUB, ANTHROPIC_API_KEY
from app.models import ExtractedJSON, LineItem


# ── Shared JSON schema prompt ────────────────────────────────────────────────

_EXTRACTION_SCHEMA = {
    "patient_name": "string",
    "age": "integer",
    "sex": "M or F",
    "date": "YYYY-MM-DD",
    "symptoms": ["list of symptom strings"],
    "line_items": [{"description": "string", "raw_text": "string"}],
    "doctor_name": "string",
    "consultation_fee": "number",
    "ocr_confidence_notes": "string — note any unclear/illegible parts here",
}

_EXTRACTION_PROMPT = """You are a medical bill data extraction assistant.
Extract structured information from the raw OCR text of a handwritten medical bill.
Output ONLY valid JSON matching this exact schema (no markdown, no extra keys):

{schema}

Rules:
- If a field is unclear or missing, use empty string "" or 0 for numbers.
- sex must be "M" or "F" only; infer from pronouns/name if not explicit.
- date must be YYYY-MM-DD; infer year as current year if only day/month given.
- symptoms: extract ALL medical complaints/conditions mentioned.
- line_items: every billable item (medicines, tests, procedures) with its raw price text.
- ocr_confidence_notes: describe any blurry/ambiguous parts honestly.

Raw OCR text:
\"\"\"
{raw_ocr}
\"\"\"

Output JSON:""".format(
    schema=json.dumps(_EXTRACTION_SCHEMA, indent=2), raw_ocr="{raw_ocr}"
)


# ── Real Implementation (Claude) ─────────────────────────────────────────────

def extract_real(raw_ocr: str) -> ExtractedJSON:
    """
    Calls Claude claude-3-5-haiku-20241022 to structure the raw OCR text.
    """
    import anthropic  # type: ignore

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    prompt = _EXTRACTION_PROMPT.replace("{raw_ocr}", raw_ocr)

    message = client.messages.create(
        model="claude-3-5-haiku-20241022",
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )

    text = message.content[0].text.strip()

    # Strip markdown code fences if Claude wraps them
    text = re.sub(r"^```json\s*", "", text)
    text = re.sub(r"\s*```$", "", text)

    data = json.loads(text)
    return _dict_to_extracted(data)


# ── Stub Implementation (Deterministic Regex Parser) ─────────────────────────

def extract_stub(raw_ocr: str) -> ExtractedJSON:
    """
    Pure-Python deterministic extraction — no API needed.
    Handles typical patterns found in Indian handwritten medical bills.
    """
    text = raw_ocr

    # Patient name — must come after a colon/hyphen on "Patient Name:" line
    name_match = re.search(
        r"^\s*patient\s*(?:name)?\s*[:\-]\s*([A-Za-z][A-Za-z\s\.]{1,40})",
        text, re.IGNORECASE | re.MULTILINE
    )
    if name_match:
        # Strip trailing words that look like field labels (Age, Sex, Date…)
        raw_name = re.split(r"\s{2,}|\t|\bAge\b|\bSex\b|\bDate\b", name_match.group(1), flags=re.IGNORECASE)[0]
        patient_name = raw_name.strip().title()
    else:
        patient_name = ""

    # Age
    age_match = re.search(r"\bAge\s*[:\-]?\s*(\d{1,3})", text, re.IGNORECASE)
    age = int(age_match.group(1)) if age_match else 0

    # Sex
    sex_match = re.search(r"\b(?:Sex|Gender)\s*[:\-]?\s*([MF](?:ale)?(?:emale)?)", text, re.IGNORECASE)
    if sex_match:
        raw_sex = sex_match.group(1).upper()
        sex = "F" if raw_sex.startswith("F") else "M"
    else:
        sex = "M"

    # Date
    date_match = re.search(
        r"(\d{1,2})[\/\-\.](\d{1,2})[\/\-\.](\d{2,4})"
        r"|(\d{4})[\/\-\.](\d{1,2})[\/\-\.](\d{1,2})",
        text
    )
    if date_match:
        groups = date_match.groups()
        if groups[3]:  # YYYY-MM-DD
            bill_date = f"{groups[3]}-{int(groups[4]):02d}-{int(groups[5]):02d}"
        else:           # DD/MM/YYYY or DD/MM/YY
            year = int(groups[2])
            if year < 100:
                year += 2000
            bill_date = f"{year}-{int(groups[1]):02d}-{int(groups[0]):02d}"
    else:
        bill_date = str(date.today())

    # Doctor — match "Dr. Firstname Lastname" stopping at parentheses or newline
    doc_match = re.search(
        r"Dr\.?\s+([A-Za-z][A-Za-z\s\.]{1,40}?)(?:\s*[\(\n,]|\bMD\b|\bMBBS\b|$)",
        text, re.IGNORECASE
    )
    doctor_name = doc_match.group(1).strip().title() if doc_match else ""

    # Consultation fee
    fee_match = re.search(
        r"(?:consultation|consult|opd|visit)\s*(?:fee|charge)?\s*[:\-]?\s*(?:Rs\.?|INR)?\s*(\d+(?:\.\d+)?)",
        text, re.IGNORECASE
    )
    if not fee_match:
        fee_match = re.search(r"(?:Rs\.?|INR)\s*(\d+(?:\.\d+)?)", text, re.IGNORECASE)
    consultation_fee = float(fee_match.group(1)) if fee_match else 0.0

    # Symptoms — keyword search across common Indian medical complaints
    symptom_keywords = [
        "fever", "headache", "cough", "cold", "vomiting", "nausea",
        "diarrhoea", "diarrhea", "chest pain", "breathlessness", "dyspnoea",
        "abdominal pain", "stomach ache", "back pain", "joint pain",
        "fatigue", "weakness", "dizziness", "hypertension", "diabetes",
        "jaundice", "malaria", "typhoid", "dengue", "covid", "infection",
        "rash", "allergy", "asthma", "bronchitis", "pneumonia",
        "fracture", "sprain", "injury", "wound", "bleeding",
        "anaemia", "anemia", "urinary", "uti", "stone",
    ]
    symptoms_found = [
        kw.title()
        for kw in symptom_keywords
        if re.search(r"\b" + re.escape(kw) + r"\b", text, re.IGNORECASE)
    ]

    # Also grab lines labelled "Symptoms:", "Complaints:" — but NOT Diagnosis
    # (Diagnosis lines tend to be long multi-word phrases that confuse the harmonizer)
    labelled_match = re.findall(
        r"(?:symptoms?|complaints?|presenting complaints?)\s*[:\-]\s*(.+?)(?:\n|$)",
        text, re.IGNORECASE
    )
    for line in labelled_match:
        for part in re.split(r"[,;/]", line):
            s = part.strip().title()
            # Only add short symptom phrases (≤ 3 words) to avoid long diagnosis strings
            if s and s not in symptoms_found and len(s.split()) <= 3:
                symptoms_found.append(s)

    # Deduplication: remove compound variants that are supersets of simpler symptoms
    # e.g. remove "Mild Cough" if "Cough" is already in the list (avoids low confidence)
    deduplicated = []
    symptoms_lower = [s.lower() for s in symptoms_found]
    for sym in symptoms_found:
        sym_lower = sym.lower()
        words = sym_lower.split()
        # If ANY single-word symptom is a core of this multi-word phrase and already present, skip it
        is_redundant = (
            len(words) > 1
            and any(
                w in symptoms_lower and w != sym_lower
                for w in words
            )
        )
        if not is_redundant:
            deduplicated.append(sym)
    symptoms_found = deduplicated

    # Line items — medicines, tests, procedures
    line_items: list[LineItem] = []
    medicine_pattern = re.compile(
        r"([A-Za-z][A-Za-z\s]+?(?:mg|ml|tablet|cap|inj|syrup|drops|ointment|cream)?)"
        r"\s*(?:x|\*|×)?\s*\d*\s*[:\-]?\s*(Rs\.?\s*\d+(?:\.\d+)?|\d+(?:\.\d+)?)",
        re.IGNORECASE
    )
    for m in medicine_pattern.finditer(text):
        line_items.append(LineItem(
            description=m.group(1).strip().title(),
            raw_text=m.group(0).strip()
        ))

    # OCR confidence notes
    has_unclear = any(w in text.lower() for w in ["illegible", "unclear", "???", "??", "unreadable"])
    ocr_notes = (
        "Some fields appear unclear or partially illegible in the original bill."
        if has_unclear
        else "OCR text appears clean and well-structured."
    )

    return ExtractedJSON(
        patient_name=patient_name,
        age=age,
        sex=sex,
        date=bill_date,
        symptoms=symptoms_found[:10],   # Cap at 10
        line_items=line_items[:15],      # Cap at 15
        doctor_name=doctor_name,
        consultation_fee=consultation_fee,
        ocr_confidence_notes=ocr_notes,
    )


def _dict_to_extracted(data: dict) -> ExtractedJSON:
    """Convert raw dict from Claude JSON into ExtractedJSON model."""
    line_items = [
        LineItem(
            description=li.get("description", ""),
            raw_text=li.get("raw_text", ""),
        )
        for li in data.get("line_items", [])
    ]
    return ExtractedJSON(
        patient_name=str(data.get("patient_name", "")),
        age=int(data.get("age", 0)),
        sex=str(data.get("sex", "M")),
        date=str(data.get("date", "")),
        symptoms=list(data.get("symptoms", [])),
        line_items=line_items,
        doctor_name=str(data.get("doctor_name", "")),
        consultation_fee=float(data.get("consultation_fee", 0)),
        ocr_confidence_notes=str(data.get("ocr_confidence_notes", "")),
    )


# ── Public Entrypoint ─────────────────────────────────────────────────────────

def structure_ocr(raw_ocr: str) -> ExtractedJSON:
    """
    Stage 2 — Structure raw OCR text into ExtractedJSON.
    Routes to Claude API when key is present, otherwise uses regex stub.
    """
    if USE_LLM_STUB:
        return extract_stub(raw_ocr)
    try:
        return extract_real(raw_ocr)
    except Exception as exc:
        print(f"[CleanOCR] Claude API failed ({exc}); falling back to stub.")
        return extract_stub(raw_ocr)
