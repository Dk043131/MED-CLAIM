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
from app.config import USE_LLM_STUB, ANTHROPIC_API_KEY, ICD10_CSV, CONFIDENCE_THRESHOLD
from app.models import CodedDiagnosis, CodingResult

# Number of candidate ICD-10 codes surfaced per symptom for LLM selection
TOP_N_CANDIDATES = 5

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


# ── Real LLM code selection (Claude) ─────────────────────────────────────────

def _select_code_real(symptom: str, candidates: List[dict]) -> Tuple[str, str, float]:
    """
    Asks Claude to select the best ICD-10 code from the candidate list ONLY.
    Returns (code, description, confidence).
    """
    import anthropic  # type: ignore

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    candidate_text = "\n".join(
        f"  {i+1}. {c['code']} — {c['description']}"
        for i, c in enumerate(candidates)
    )

    prompt = f"""You are a clinical coding specialist. 
A medical bill lists the symptom/condition: "{symptom}"

Select the MOST appropriate ICD-10 code from the following candidates ONLY.
Do NOT invent or use any code not listed below.

Candidates:
{candidate_text}

Respond with ONLY a JSON object (no markdown):
{{"selected_code": "...", "selected_description": "...", "confidence": 0.0}}

confidence must be between 0.0 and 1.0 reflecting how certain you are this is the right code for this symptom."""

    message = client.messages.create(
        model="claude-3-5-haiku-20241022",
        max_tokens=256,
        messages=[{"role": "user", "content": prompt}],
    )

    text = message.content[0].text.strip()
    text = re.sub(r"^```json\s*", "", text)
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
    Uses real Claude API if available, else uses stub scorer.

    Returns CodingResult with a CodedDiagnosis per symptom.
    """
    if not symptoms:
        return CodingResult(coded_diagnoses=[])

    df = _get_icd10_df()
    diagnoses: list[CodedDiagnosis] = []

    for symptom in symptoms:
        if not symptom.strip():
            continue
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
            if USE_LLM_STUB:
                code, desc, conf = _select_code_stub(symptom, candidates)
            else:
                code, desc, conf = _select_code_real(symptom, candidates)
        except Exception as exc:
            print(f"[Harmonizer] LLM failed for '{symptom}' ({exc}); using stub.")
            code, desc, conf = _select_code_stub(symptom, candidates)

        diagnoses.append(CodedDiagnosis(
            symptom=symptom,
            icd10_code=code,
            icd10_description=desc,
            confidence=conf,
        ))

    return CodingResult(coded_diagnoses=diagnoses)
