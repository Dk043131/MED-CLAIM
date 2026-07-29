"""
pipeline/clean_ocr.py — Stage 2: Structure Raw OCR Text

Priority order for structuring:
  1. Gemini 3-flash-preview combined OCR+structure (one call via orchestrator)
  2. Gemini 3-flash-preview text-only structuring (from raw OCR text)
  3. Stub regex parser (zero API cost — fallback)
"""
from __future__ import annotations
import json
import re
from datetime import date
from app.config import USE_LLM_STUB, USE_GEMINI, GEMINI_API_KEY
from app.models import ExtractedJSON, LineItem


# ── Shared JSON schema for Claude structuring ────────────────────────────────

_EXTRACTION_SCHEMA = {
    "patient_name": "string",
    "patient_id": "UHID or IP number if present",
    "hospital_name": "hospital/clinic name",
    "age": "integer",
    "sex": "M or F",
    "date": "YYYY-MM-DD",
    "doctor_name": "doctor name with title",
    "doctor_id": "doctor registration/signature ID if visible",
    "symptoms": ["list of symptoms from c/o or complaints section"],
    "diagnosis": ["list of diagnoses from Imp/Impression/Assessment section"],
    "vitals": {"bp": "blood pressure", "pulse": "pulse rate", "rbs": "blood sugar"},
    "line_items": [{"description": "billable item", "raw_text": "exact text"}],
    "medications": [{"name": "drug", "dose": "dose", "route": "oral/IV/IM", "frequency": "frequency", "raw_text": "exact text"}],
    "advice": ["list of non-medication instructions"],
    "consultation_fee": "number",
    "ocr_confidence_notes": "describe any illegible/unclear parts",
}

_EXTRACTION_PROMPT = """You are a clinical document extraction AI for Indian hospital prescriptions/bills.
Extract structured information from this raw OCR text.
Output ONLY valid JSON matching this exact schema (no markdown, no extra keys):

{schema}

Rules:
- Indian prescriptions use abbreviations: c/o = complaints of, Imp = impression/diagnosis, Adv = advice, h/o = history of
- If a field is unclear or missing, use empty string "" or 0 for numbers, [] for lists.
- sex must be "M" or "F" only; infer from pronouns/name if not explicit.
- date must be YYYY-MM-DD; Indian date 22/12/22 → 2022-12-22
- symptoms: ONLY from c/o or Complaints section
- diagnosis: ONLY from Imp/Impression/Diagnosis/Assessment section
- vitals: extract BP (e.g. 110/70), PR/pulse (e.g. 60bpm), RBS (blood sugar value)
- medications: all drugs with dose/route/frequency
- advice: non-medication instructions (e.g. "adequate fluid intake", "bed rest")
- line_items: billable items with amounts
- ocr_confidence_notes: note any blurry or ambiguous parts

Raw OCR text:
\"\"\"
{raw_ocr}
\"\"\"

Output JSON:""".format(
    schema=json.dumps(_EXTRACTION_SCHEMA, indent=2), raw_ocr="{raw_ocr}"
)


# ── Real Implementation (Gemini text-only structuring) ───────────────────────────

def extract_real(raw_ocr: str) -> ExtractedJSON:
    """
    Calls Gemini 3-flash-preview (text-only) to structure the raw OCR text.
    Used when image bytes are unavailable for combined extraction.
    """
    from app.pipeline.gemini_ocr import extract_text_with_gemini, gemini_dict_to_extracted
    data = extract_text_with_gemini(raw_ocr)
    return gemini_dict_to_extracted(data)



# ── Stub Implementation (Deterministic Regex Parser) ─────────────────────────

def extract_stub(raw_ocr: str) -> ExtractedJSON:
    """
    Pure-Python deterministic extraction — no API needed.
    Handles typical patterns found in Indian handwritten medical bills AND
    PANDA-style prescriptions (Adichunchanagiri, etc.).
    """
    text = raw_ocr

    # ── Hospital/Clinic Name ─────────────────────────────────────────────────
    hospital_name = ""
    # First non-empty line is often the hospital name
    for line in text.strip().split('\n'):
        line = line.strip()
        if len(line) > 10 and any(kw in line.lower() for kw in ['hospital', 'clinic', 'institute', 'medical', 'centre', 'center', 'university', 'nursing']):
            hospital_name = line.strip()
            break

    # ── Patient name ─────────────────────────────────────────────────────────
    # Try "Name: Vivek S." or "Patient Name: ..."
    name_match = re.search(
        r"^\s*(?:patient\s+)?name\s*[:\-]\s*([A-Za-z][A-Za-z\s\.]{1,40})",
        text, re.IGNORECASE | re.MULTILINE
    )
    if name_match:
        # Strip trailing words that look like field labels (Age, Sex, Date…)
        raw_name = re.split(r"\s{2,}|\t|\bAge\b|\bSex\b|\bDate\b", name_match.group(1), flags=re.IGNORECASE)[0]
        patient_name = raw_name.strip().title()
    else:
        patient_name = ""

    # ── Patient ID (UHID / IP number) ────────────────────────────────────────
    patient_id = ""
    pid_match = re.search(
        r"(?:uhid|ip\s*no|ipno|patient\s*id|reg\s*no|registration)\s*[:\-\/]?\s*(\w+)",
        text, re.IGNORECASE
    )
    if pid_match:
        patient_id = pid_match.group(1).strip()

    # ── Age ──────────────────────────────────────────────────────────────────
    # Try "Age: 34" or "34/M" pattern (Indian prescription shorthand)
    age = 0
    age_match = re.search(r"\bAge\s*[:\-]?\s*(\d{1,3})", text, re.IGNORECASE)
    if age_match:
        age = int(age_match.group(1))
    else:
        # Try "19/M" or "34/F" shorthand
        shorthand = re.search(r"\b(\d{1,3})\/([MF])", text, re.IGNORECASE)
        if shorthand:
            age = int(shorthand.group(1))

    # ── Sex ──────────────────────────────────────────────────────────────────
    sex_match = re.search(r"\b(?:Sex|Gender)\s*[:\-]?\s*([MF](?:ale)?(?:emale)?)", text, re.IGNORECASE)
    if sex_match:
        raw_sex = sex_match.group(1).upper()
        sex = "F" if raw_sex.startswith("F") else "M"
    else:
        # Try shorthand 19/M or 34/F
        sh = re.search(r"\b\d{1,3}\/([MF])\b", text, re.IGNORECASE)
        sex = sh.group(1).upper() if sh else "M"

    # ── Date ─────────────────────────────────────────────────────────────────
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

    # ── Symptoms — comprehensive Indian medical + PANDA keyword list ─────────
    symptom_keywords = [
        # Fever / infection family
        "fever", "pyrexia", "chills",
        # Head / neuro
        "headache", "giddiness", "dizziness", "vertigo", "syncope", "fainting", "seizure",
        # Respiratory
        "cough", "cold", "breathlessness", "dyspnoea", "dyspnea", "wheezing", "asthma", "bronchitis", "pneumonia",
        # GI
        "vomiting", "nausea", "diarrhoea", "diarrhea", "loose stools", "constipation",
        "abdominal pain", "stomach ache", "indigestion", "jaundice",
        # Musculoskeletal
        "back pain", "joint pain", "body pain", "muscle pain", "fracture", "sprain", "injury", "gout",
        # Fatigue / weakness
        "fatigue", "weakness", "lethargy", "malaise",
        # Metabolic / endocrine
        "hypoglycemia", "hypoglycaemia", "diabetes", "low blood sugar", "low rbs",
        "hypertension", "high blood pressure", "prediabetes",
        "hypothyroidism", "hyperthyroidism", "thyroid disorder",
        # Blood disorders (CBC parameters)
        "anaemia", "anemia", "low hemoglobin", "hemoglobin low", "hb low",
        "iron deficiency anemia", "megaloblastic anemia", "b12 deficiency", "folate deficiency",
        "leukocytosis", "leukopenia", "high wbc", "low wbc", "neutrophilia", "lymphocytosis",
        "thrombocytopenia", "low platelets", "thrombocytosis", "high platelets",
        "bleeding", "wound",
        # Lipid profile
        "dyslipidemia", "hyperlipidemia", "high cholesterol", "hypercholesterolemia",
        "high triglycerides", "hypertriglyceridemia", "low hdl", "high ldl",
        # Liver function (LFT)
        "elevated sgpt", "elevated sgot", "elevated alt", "elevated ast",
        "raised bilirubin", "liver function abnormal",
        # Kidney function (KFT / RFT)
        "elevated creatinine", "high creatinine", "elevated urea",
        "ckd", "chronic kidney disease", "renal impairment",
        # Vitamins / minerals
        "vitamin d deficiency", "vitamin d low", "low vitamin d",
        "calcium deficiency", "low calcium", "iron deficiency",
        # Uric acid / gout
        "high uric acid", "hyperuricemia",
        # Infection / inflammation markers
        "elevated crp", "high esr", "abnormal blood count",
        "elevated hba1c", "high hba1c",
        # Psychiatric / behavioral
        "restlessness", "agitation", "anxiety", "nervousness", "irritability",
        # Cardiovascular
        "chest pain", "palpitations", "bradycardia", "tachycardia",
        # Skin / allergy
        "rash", "allergy", "itching", "urticaria",
        # Infectious disease
        "malaria", "typhoid", "dengue", "covid", "infection",
        # Urological
        "urinary", "uti", "burning micturition", "stone",
        # Dehydration
        "dehydration",
    ]
    symptoms_found = [
        kw.title()
        for kw in symptom_keywords
        if re.search(r"\b" + re.escape(kw) + r"\b", text, re.IGNORECASE)
    ]

    # Also grab lines labelled "c/o", "Symptoms:", "Complaints:"
    # Specifically handles Indian prescription "c/o giddiness, restlessness"
    labelled_match = re.findall(
        r"(?:c\/o|c\.o\.|symptoms?|complaints?|presenting complaints?)\s*[:\-]?\s*(.+?)(?:\n|$)",
        text, re.IGNORECASE
    )
    for line in labelled_match:
        for part in re.split(r"[,;/]", line):
            s = part.strip().title()
            # Only add short symptom phrases (≤ 3 words) to avoid long diagnosis strings
            if s and len(s) > 2 and s not in symptoms_found and len(s.split()) <= 3:
                symptoms_found.append(s)

    # Also extract from "Imp:" (Impression/Diagnosis) section
    imp_match = re.findall(
        r"(?:imp|impression|diagnosis|assessment)\s*[:\-]?\s*(.+?)(?:\n|\(|$)",
        text, re.IGNORECASE
    )
    for line in imp_match:
        s = line.strip().title()
        if s and len(s) > 2 and s not in symptoms_found and len(s.split()) <= 4:
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

    # ── Vitals extraction (BP, PR/pulse, RBS) ─────────────────────────────
    vitals = {}
    bp_match = re.search(r"\bBP\s*[:\-]?\s*(\d{2,3}\/\d{2,3})", text, re.IGNORECASE)
    if bp_match:
        vitals["bp"] = bp_match.group(1)
    pr_match = re.search(r"\b(?:PR|Pulse)\s*[:\-]?\s*(\d{2,3})\s*(?:bpm|/min)?", text, re.IGNORECASE)
    if pr_match:
        vitals["pulse"] = pr_match.group(1) + " bpm"
    rbs_match = re.search(r"\bRBS\s*[:\-]?\s*(\d+)\s*(?:mg|mg\/dl|mg\/dL)?", text, re.IGNORECASE)
    if rbs_match:
        vitals["rbs"] = rbs_match.group(1) + " mg/dL"
    spo2_match = re.search(r"\bSpO2\s*[:\-]?\s*(\d+)\s*%?", text, re.IGNORECASE)
    if spo2_match:
        vitals["spo2"] = spo2_match.group(1) + "%"

    # ── Advice (Adv: lines) ─────────────────────────────────────────
    advice = []
    adv_match = re.search(
        r"\b(?:adv|advice|instructions?)\s*[:\-]?\s*(.+)",
        text, re.IGNORECASE | re.DOTALL
    )
    if adv_match:
        adv_lines = adv_match.group(1).strip().split('\n')
        for line in adv_lines[:5]:  # Cap at 5 advice items
            stripped = line.strip().strip('-').strip()
            if stripped and len(stripped) > 3:
                advice.append(stripped)

    # OCR confidence notes
    has_unclear = any(w in text.lower() for w in ["illegible", "unclear", "???", "??", "unreadable"])
    vitals_note = " | ".join(f"{k.upper()}: {v}" for k, v in vitals.items())
    if not has_unclear:
        ocr_notes = vitals_note if vitals_note else "OCR text appears clean and well-structured."
    elif vitals_note:
        ocr_notes = f"{vitals_note} | Some fields partially illegible."
    else:
        ocr_notes = "Some fields appear unclear or partially illegible in the original bill."

    # ── Doctor ID ─────────────────────────────────────────────────────
    doctor_id = ""
    did_match = re.search(r"(?:signature of doctor|reg no|dr\. id|doctor id)\s*[:\-\(]?\s*([A-Z0-9]{4,12})", text, re.IGNORECASE)
    if did_match:
        doctor_id = did_match.group(1).strip()


    return ExtractedJSON(
        patient_name=patient_name,
        patient_id=patient_id,
        hospital_name=hospital_name,
        age=age,
        sex=sex,
        date=bill_date,
        symptoms=symptoms_found[:10],   # Cap at 10
        line_items=line_items[:15],      # Cap at 15
        doctor_name=doctor_name,
        doctor_id=doctor_id,
        consultation_fee=consultation_fee,
        ocr_confidence_notes=ocr_notes,
        vitals=vitals,
        advice=advice,
    )


def _dict_to_extracted(data: dict) -> ExtractedJSON:
    """Convert raw dict from Claude/Gemini JSON into ExtractedJSON model."""
    line_items = [
        LineItem(
            description=li.get("description", ""),
            raw_text=li.get("raw_text", ""),
        )
        for li in data.get("line_items", [])
    ]
    # Also add medications as line items
    for med in data.get("medications", []):
        line_items.append(LineItem(
            description=f"{med.get('name', '')} {med.get('dose', '')} {med.get('route', '')}".strip(),
            raw_text=med.get("raw_text", ""),
        ))

    # Merge symptoms + diagnosis for ICD-10 harmonization
    symptoms = list(data.get("symptoms", []))
    diagnoses = list(data.get("diagnosis", []))
    all_symptoms = symptoms + [d for d in diagnoses if d not in symptoms]

    # Vitals as notes
    vitals = data.get("vitals", {})
    vitals_note = ""
    if vitals:
        parts = []
        if vitals.get("bp"): parts.append(f"BP: {vitals['bp']}")
        if vitals.get("pulse"): parts.append(f"PR: {vitals['pulse']}")
        if vitals.get("rbs"): parts.append(f"RBS: {vitals['rbs']}")
        vitals_note = " | ".join(parts)

    ocr_notes = str(data.get("ocr_confidence_notes", ""))
    if vitals_note:
        ocr_notes = f"{vitals_note} | {ocr_notes}" if ocr_notes else vitals_note

    return ExtractedJSON(
        patient_name=str(data.get("patient_name", "")),
        patient_id=str(data.get("patient_id", "")),
        hospital_name=str(data.get("hospital_name", "")),
        age=int(data.get("age", 0)),
        sex=str(data.get("sex", "M")),
        date=str(data.get("date", "")),
        symptoms=all_symptoms[:12],
        line_items=line_items[:20],
        doctor_name=str(data.get("doctor_name", "")),
        doctor_id=str(data.get("doctor_id", "")),
        consultation_fee=float(data.get("consultation_fee", 0)),
        ocr_confidence_notes=ocr_notes,
        vitals=vitals,
        advice=data.get("advice", []),
    )


# ── Public Entrypoint ─────────────────────────────────────────────────────────

def structure_ocr(raw_ocr: str) -> ExtractedJSON:
    """
    Stage 2 — Structure raw OCR text into ExtractedJSON.
    Priority: Gemini text call → stub regex parser.
    (Gemini combined image extraction is handled in the orchestrator)
    """
    if USE_LLM_STUB or not GEMINI_API_KEY:
        return extract_stub(raw_ocr)
    try:
        return extract_real(raw_ocr)
    except Exception as exc:
        print(f"[CleanOCR] Gemini structuring failed ({exc}); falling back to stub.")
        return extract_stub(raw_ocr)


def structure_ocr_from_raw(raw_ocr: str) -> ExtractedJSON:
    """Alias for backwards compatibility."""
    return structure_ocr(raw_ocr)
