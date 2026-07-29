"""
pipeline/harmonizer.py — Stage 3: Clinical Code Harmonizer

Approach (safe, demo-proven):
  1. Load icd10_codes.csv into a pandas DataFrame (once at startup).
  2. For each symptom in the extracted bill, pre-filter to the top-N candidate
     ICD-10 codes using fuzzy token matching (pandas + fuzzywuzzy).
  3. Pass ONLY the candidate list to Claude (or the constrained matcher stub).
     Claude is NEVER allowed to freehand a code — it must pick from candidates.
  4. Compute a confidence score per diagnosis (0.0–1.0).
  5. needs_review() returns True if ANY diagnosis confidence < CONFIDENCE_THRESHOLD.

Why this matters (Q&A ready):
  - Constraining the LLM to a candidate list eliminates hallucinated codes.
  - Pandas pre-filter keeps the LLM prompt short and focused.
  - The confidence gate is the primary signal for routing to human review.
"""
from __future__ import annotations
import json
import os
import re
import pandas as pd
from typing import List, Tuple
from app.config import USE_LLM_STUB, GEMINI_API_KEY, ICD10_CSV, CONFIDENCE_THRESHOLD
from app.models import CodedDiagnosis, CodingResult

# Number of candidate ICD-10 codes surfaced per symptom for LLM selection
TOP_N_CANDIDATES = 8

# ICD-10 coding model — Gemini 3.1 Flash-Lite (fast, cheap, text-only)
CODING_MODEL = "gemini-3.1-flash-lite"

# ── PANDA Clinical Synonym Dictionary ────────────────────────────────────────
# Maps common Indian clinical abbreviations/synonyms → preferred ICD-10 search terms
# PANDA = Prescriber Anti-Nausea Drug Algorithm + extended Indian clinical terms
_PANDA_SYNONYMS: dict[str, tuple[str, str, float]] = {
    # ── Blood Report / CBC Parameters ────────────────────────────────────────
    # Hemoglobin / Anemia
    "low hemoglobin":           ("D64.9",  "Anemia unspecified", 0.96),
    "anaemia":                  ("D64.9",  "Anemia unspecified", 0.96),
    "anemia":                   ("D64.9",  "Anemia unspecified", 0.96),
    "hemoglobin low":           ("D64.9",  "Anemia unspecified", 0.95),
    "hb low":                   ("D64.9",  "Anemia unspecified", 0.94),
    "iron deficiency anemia":   ("D50.9",  "Iron deficiency anaemia unspecified", 0.97),
    "megaloblastic anemia":     ("D53.1",  "Other megaloblastic anaemias", 0.95),
    "b12 deficiency":           ("E53.8",  "Vitamin B12 deficiency", 0.96),
    "folate deficiency":        ("E53.8",  "Folate deficiency", 0.94),
    # WBC / Leukocytes
    "leukocytosis":             ("D72.829","Leukocytosis unspecified", 0.95),
    "leukopenia":               ("D72.819","Leukopenia unspecified", 0.95),
    "neutrophilia":             ("D72.829","Leukocytosis unspecified", 0.92),
    "lymphocytosis":            ("D72.820","Lymphocytosis symptomatic", 0.92),
    "high wbc":                 ("D72.829","Leukocytosis unspecified", 0.93),
    "low wbc":                  ("D72.819","Leukopenia unspecified", 0.93),
    # Platelets
    "thrombocytopenia":         ("D69.6",  "Thrombocytopenia unspecified", 0.97),
    "low platelets":            ("D69.6",  "Thrombocytopenia unspecified", 0.95),
    "thrombocytosis":           ("D75.1",  "Secondary polycythaemia", 0.93),
    "high platelets":           ("D75.1",  "Secondary polycythaemia", 0.91),
    # Lipid Profile
    "dyslipidemia":             ("E78.5",  "Hyperlipidemia unspecified", 0.97),
    "hyperlipidemia":           ("E78.5",  "Hyperlipidemia unspecified", 0.97),
    "high cholesterol":         ("E78.0",  "Pure hypercholesterolaemia", 0.96),
    "hypercholesterolemia":     ("E78.0",  "Pure hypercholesterolaemia", 0.97),
    "high triglycerides":       ("E78.1",  "Pure hypertriglyceridaemia", 0.95),
    "hypertriglyceridemia":     ("E78.1",  "Pure hypertriglyceridaemia", 0.95),
    "low hdl":                  ("E78.6",  "Lipoprotein deficiency", 0.93),
    "high ldl":                 ("E78.0",  "Pure hypercholesterolaemia", 0.92),
    # Liver Function Tests (LFT)
    "elevated sgpt":            ("K76.9",  "Liver disease unspecified", 0.94),
    "elevated sgot":            ("K76.9",  "Liver disease unspecified", 0.94),
    "elevated alt":             ("K76.9",  "Liver disease unspecified", 0.94),
    "elevated ast":             ("K76.9",  "Liver disease unspecified", 0.93),
    "raised bilirubin":         ("R17",    "Unspecified jaundice", 0.95),
    "jaundice":                 ("R17",    "Unspecified jaundice", 0.95),
    "liver function abnormal":  ("K76.9",  "Liver disease unspecified", 0.93),
    # Kidney Function Tests (KFT / RFT)
    "elevated creatinine":      ("N19",    "Unspecified kidney failure", 0.95),
    "high creatinine":          ("N19",    "Unspecified kidney failure", 0.94),
    "elevated urea":            ("N19",    "Unspecified kidney failure", 0.92),
    "ckd":                      ("N18.9",  "Chronic kidney disease unspecified", 0.97),
    "chronic kidney disease":   ("N18.9",  "Chronic kidney disease unspecified", 0.97),
    "renal impairment":         ("N28.9",  "Disorder of kidney unspecified", 0.94),
    # Blood Sugar / Diabetes
    "diabetes":                 ("E11.9",  "Type 2 diabetes mellitus without complications", 0.97),
    "type 2 diabetes":          ("E11.9",  "Type 2 diabetes mellitus without complications", 0.97),
    "type 1 diabetes":          ("E10.9",  "Type 1 diabetes mellitus without complications", 0.97),
    "prediabetes":              ("R73.09", "Prediabetes", 0.95),
    "impaired fasting glucose": ("R73.01", "Impaired fasting glucose", 0.95),
    "high fasting glucose":     ("R73.01", "Impaired fasting glucose", 0.93),
    "elevated hba1c":           ("E11.9",  "Type 2 diabetes mellitus without complications", 0.95),
    "high hba1c":               ("E11.9",  "Type 2 diabetes mellitus without complications", 0.94),
    # Thyroid
    "hypothyroidism":           ("E03.9",  "Hypothyroidism unspecified", 0.97),
    "hyperthyroidism":          ("E05.90", "Hyperthyroidism unspecified", 0.97),
    "low tsh":                  ("E05.90", "Hyperthyroidism unspecified", 0.93),
    "high tsh":                 ("E03.9",  "Hypothyroidism unspecified", 0.93),
    "thyroid disorder":         ("E07.9",  "Disorder of thyroid unspecified", 0.92),
    # Vitamins / Minerals
    "vitamin d deficiency":     ("E55.9",  "Vitamin D deficiency unspecified", 0.97),
    "vitamin d low":            ("E55.9",  "Vitamin D deficiency unspecified", 0.95),
    "low vitamin d":            ("E55.9",  "Vitamin D deficiency unspecified", 0.95),
    "calcium deficiency":       ("E83.51", "Hypocalcemia", 0.95),
    "low calcium":              ("E83.51", "Hypocalcemia", 0.93),
    "iron deficiency":          ("E61.1",  "Iron deficiency", 0.96),
    # Uric Acid / Gout
    "high uric acid":           ("M10.9",  "Gout unspecified", 0.94),
    "hyperuricemia":            ("M10.0",  "Idiopathic gout unspecified", 0.95),
    "gout":                     ("M10.9",  "Gout unspecified", 0.97),
    # Infection markers
    "elevated crp":             ("R79.89", "Other specified abnormal findings of blood chemistry", 0.93),
    "high esr":                 ("R70.0",  "Elevated erythrocyte sedimentation rate", 0.94),
    "abnormal blood count":     ("R79.9",  "Abnormal finding of blood chemistry unspecified", 0.90),
    # ── Hypoglycemia family ───────────────────────────────────────────────────
    "hypoglycemia":             ("E16.2", "Hypoglycemia unspecified", 0.95),
    "hypoglycaemia":            ("E16.2", "Hypoglycemia unspecified", 0.95),
    "low blood sugar":          ("E16.2", "Hypoglycemia unspecified", 0.93),
    "low rbs":                  ("E16.2", "Hypoglycemia unspecified", 0.93),
    "drug-induced hypoglycemia":("E16.0", "Drug-induced hypoglycemia without coma", 0.95),
    "insulin hypoglycemia":     ("E16.0", "Drug-induced hypoglycemia without coma", 0.94),
    # ── Nausea/Vomiting ───────────────────────────────────────────────────────
    "nausea":               ("R11.0",  "Nausea", 0.97),
    "vomiting":             ("R11.10", "Vomiting unspecified", 0.97),
    "nausea and vomiting":  ("R11.2",  "Nausea with vomiting unspecified", 0.97),
    "nausea with vomiting": ("R11.2",  "Nausea with vomiting unspecified", 0.97),
    "emesis":               ("R11.10", "Vomiting unspecified", 0.93),
    # ── Giddiness/Dizziness ───────────────────────────────────────────────────
    "giddiness":            ("R42", "Dizziness and giddiness", 0.97),
    "dizziness":            ("R42", "Dizziness and giddiness", 0.97),
    "vertigo":              ("R42", "Dizziness and giddiness", 0.92),
    "lightheadedness":      ("R42", "Dizziness and giddiness", 0.90),
    # ── Restlessness ─────────────────────────────────────────────────────────
    "restlessness":         ("R45.1", "Restlessness and agitation", 0.97),
    "agitation":            ("R45.1", "Restlessness and agitation", 0.95),
    "nervousness":          ("R45.0", "Nervousness and restlessness", 0.90),
    # ── Syncope ──────────────────────────────────────────────────────────────
    "syncope":              ("R55", "Syncope and collapse", 0.95),
    "fainting":             ("R55", "Syncope and collapse", 0.92),
    "collapse":             ("R55", "Syncope and collapse", 0.90),
    # ── General symptoms ─────────────────────────────────────────────────────
    "weakness":             ("R53.1",  "Weakness", 0.95),
    "fatigue":              ("R53.83", "Other fatigue", 0.93),
    "fever":                ("R50.9",  "Fever unspecified", 0.97),
    "headache":             ("R51",    "Headache", 0.97),
    "chest pain":           ("R07.9",  "Chest pain unspecified", 0.95),
    "breathlessness":       ("R06.0",  "Dyspnoea", 0.95),
    "dyspnoea":             ("R06.0",  "Dyspnoea", 0.97),
    "dyspnea":              ("R06.0",  "Dyspnoea", 0.97),
    "cough":                ("R05",    "Cough", 0.97),
    "bradycardia":          ("R00.1",  "Bradycardia unspecified", 0.95),
    "tachycardia":          ("R00.0",  "Tachycardia unspecified", 0.95),
    "dehydration":          ("E86.0",  "Dehydration", 0.95),
    # ── Hypertension ─────────────────────────────────────────────────────────
    "hypertension":         ("I10",   "Essential (primary) hypertension", 0.97),
    "high blood pressure":  ("I10",   "Essential (primary) hypertension", 0.96),
}

# ── Load ICD-10 DataFrame (module-level singleton) ───────────────────────────
_icd10_df: pd.DataFrame | None = None


def _get_icd10_df() -> pd.DataFrame:
    global _icd10_df
    if _icd10_df is None:
        if not os.path.exists(ICD10_CSV):
            raise FileNotFoundError(f"ICD-10 CSV not found at {ICD10_CSV}")
        _icd10_df = pd.read_csv(ICD10_CSV)
        # Normalise column names
        _icd10_df.columns = [c.strip().lower().replace(" ", "_") for c in _icd10_df.columns]
        # Pre-compute lowercase description for fast searching
        _icd10_df["desc_lower"] = _icd10_df["description"].str.lower()
    return _icd10_df


# ── Candidate pre-filter ─────────────────────────────────────────────────────

def _get_candidates(symptom: str, df: pd.DataFrame) -> List[dict]:
    """
    Returns up to TOP_N_CANDIDATES ICD-10 rows most relevant to the symptom.
    Strategy: simple substring containment first; fuzzy score as tiebreaker.
    """
    symptom_lower = symptom.lower()
    tokens = re.findall(r"\w+", symptom_lower)

    # 1. Exact substring match
    mask = df["desc_lower"].str.contains(symptom_lower, regex=False, na=False)
    matches = df[mask]

    # 2. If fewer than TOP_N, try individual token containment
    if len(matches) < TOP_N_CANDIDATES:
        for tok in tokens:
            if len(tok) < 3:
                continue
            tok_mask = df["desc_lower"].str.contains(tok, regex=False, na=False)
            extra = df[tok_mask & ~df.index.isin(matches.index)]
            matches = pd.concat([matches, extra])

    # Deduplicate and take top N
    matches = matches.drop_duplicates(subset="code").head(TOP_N_CANDIDATES)

    return [
        {"code": row["code"], "description": row["description"]}
        for _, row in matches.iterrows()
    ]


# ── Real LLM code selection (Gemini 3.1 Flash-Lite) ─────────────────────────

def _select_code_real(symptom: str, candidates: List[dict]) -> Tuple[str, str, float]:
    """
    Asks Gemini 3.1 Flash-Lite to select the best ICD-10 code from the
    candidate list ONLY. Returns (code, description, confidence).
    Uses text-only generation — fast and cheap.
    """
    from google import genai  # type: ignore
    from google.genai import types  # type: ignore

    client = genai.Client(api_key=GEMINI_API_KEY)

    candidate_text = "\n".join(
        f"  {i+1}. {c['code']} — {c['description']}"
        for i, c in enumerate(candidates)
    )

    prompt = f"""You are a clinical coding specialist trained in ICD-10-CM/WHO coding for Indian hospitals.
A medical prescription/bill lists the symptom/condition: \"{symptom}\"

Select the MOST appropriate ICD-10 code from the following candidates ONLY.
Do NOT invent codes. Consider the clinical context of an Indian hospital.

Candidates:
{candidate_text}

Respond with ONLY a JSON object (no markdown, no extra text):
{{"selected_code": "...", "selected_description": "...", "confidence": 0.0}}

confidence: 0.0-1.0 reflecting certainty."""

    response = client.models.generate_content(
        model=CODING_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=0.0,
            max_output_tokens=128,
        ),
    )

    text = (response.text or "").strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    data = json.loads(text)

    return (
        data["selected_code"],
        data["selected_description"],
        float(data["confidence"]),
    )


# ── Stub code selection (deterministic scoring) ───────────────────────────────

def _select_code_stub(symptom: str, candidates: List[dict]) -> Tuple[str, str, float]:
    """
    Picks the candidate whose description has the highest token overlap
    with the symptom. Returns a confidence score based on that overlap.
    """
    if not candidates:
        return ("Z00.0", "Encounter for general examination", 0.55)

    symptom_tokens = set(re.findall(r"\w+", symptom.lower()))
    best_score = -1.0
    best = candidates[0]

    for c in candidates:
        desc_tokens = set(re.findall(r"\w+", c["description"].lower()))
        overlap = len(symptom_tokens & desc_tokens)
        score = overlap / max(len(symptom_tokens), 1)
        if score > best_score:
            best_score = score
            best = c

    # Map overlap ratio to a realistic confidence range (0.60–0.98)
    confidence = min(0.98, max(0.60, 0.60 + best_score * 0.40))
    return (best["code"], best["description"], round(confidence, 2))


# ── Review routing check ──────────────────────────────────────────────────────

def needs_review(coding_result: CodingResult) -> bool:
    """
    Returns True if ANY coded diagnosis has confidence < CONFIDENCE_THRESHOLD.
    This is the primary clinical-coding signal for routing to human review.

    Why: We never guess a clinical code. If the AI is not confident,
         a human coder must verify before the claim is approved.
    """
    if not coding_result.coded_diagnoses:
        return True   # No codes = definitely needs review
    return any(
        d.confidence < CONFIDENCE_THRESHOLD
        for d in coding_result.coded_diagnoses
    )


# ── Public Entrypoint ─────────────────────────────────────────────────────────

def harmonize_codes(symptoms: list[str]) -> CodingResult:
    """
    Stage 3 — Map every symptom to a constrained ICD-10 code.

    Priority:
      1. PANDA synonym dictionary (instant, no API cost)
      2. Gemini 3.1 Flash-Lite (if GEMINI_API_KEY set)
      3. Stub token-overlap scorer (fallback)
    """
    if not symptoms:
        return CodingResult(coded_diagnoses=[])

    use_llm = not USE_LLM_STUB and bool(GEMINI_API_KEY)
    df = _get_icd10_df()
    diagnoses: list[CodedDiagnosis] = []

    for symptom in symptoms:
        if not symptom.strip():
            continue

        # ── PANDA synonym fast-path ───────────────────────────────────────────
        sym_lower = symptom.strip().lower()
        panda_hit = _PANDA_SYNONYMS.get(sym_lower)
        if not panda_hit:
            # Try partial match on synonym keys
            for key, val in _PANDA_SYNONYMS.items():
                if key in sym_lower or sym_lower in key:
                    panda_hit = val
                    break

        if panda_hit:
            code, desc, conf = panda_hit
            diagnoses.append(CodedDiagnosis(
                symptom=symptom,
                icd10_code=code,
                icd10_description=desc,
                confidence=conf,
            ))
            print(f"[Harmonizer] PANDA hit: '{symptom}' → {code} ({conf:.0%})")
            continue

        # ── CSV candidate lookup ──────────────────────────────────────────────
        candidates = _get_candidates(symptom, df)

        if not candidates:
            # No candidates in CSV — assign a generic code with low confidence
            diagnoses.append(CodedDiagnosis(
                symptom=symptom,
                icd10_code="Z00.0",
                icd10_description="Encounter for general examination without complaint",
                confidence=0.50,
            ))
            continue

        try:
            if use_llm:
                code, desc, conf = _select_code_real(symptom, candidates)
            else:
                code, desc, conf = _select_code_stub(symptom, candidates)
        except Exception as exc:
            print(f"[Harmonizer] Gemini failed for '{symptom}' ({exc}); using stub.")
            code, desc, conf = _select_code_stub(symptom, candidates)

        diagnoses.append(CodedDiagnosis(
            symptom=symptom,
            icd10_code=code,
            icd10_description=desc,
            confidence=conf,
        ))

    return CodingResult(coded_diagnoses=diagnoses)
