# MED-CLAIM — Automated Medical Claim Adjudication System

AI-powered backend that processes handwritten medical bills through a 5-stage pipeline:
OCR → Structuring → ICD-10 Coding → Eligibility Check → Auto-Routing.

## Quick Start (Backend — Person A)

```bash
cd backend

# 1. Create virtualenv & install deps
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# 2. (Optional) Set API keys — system works fully without them via stubs
cp .env.example .env
# Edit .env and add ANTHROPIC_API_KEY and GOOGLE_APPLICATION_CREDENTIALS

# 3. Seed sample data (6 test cases)
python seed_data.py

# 4. Start the API server
uvicorn app.main:app --reload --port 8000
```

API docs available at: http://localhost:8000/docs

## API Contract (5 Endpoints)

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/claims/upload` | Upload bill image → runs full AI pipeline → returns ClaimRecord |
| `GET` | `/claims` | List all claims |
| `GET` | `/claims/review-queue` | List pending_review claims only |
| `POST` | `/claims/{claim_id}/approve` | Approve a pending claim |
| `GET` | `/dashboard/metrics` | Real-time dashboard metrics |

## AI Pipeline Stages

```
Image Upload
    │
    ▼
Stage 1: OCR (Google Cloud Vision / stub)
    │  raw_ocr text + confidence score (0–100)
    ▼
Stage 2: Structure OCR (Claude / regex parser)
    │  patient_name, age, sex, date, symptoms, line_items, doctor_name, fee
    ▼
Stage 3: ICD-10 Harmonizer (pandas filter → constrained LLM selection)
    │  coded_diagnoses with confidence scores — NEVER freehands a code
    ▼
Stage 4: Eligibility Check (eligibility.csv lookup)
    │  eligible, patient_id, income_bracket, coverage, reason
    ▼
Stage 5: Orchestrator — Routing Decision
    │  auto_approve  → status: "approved"
    └  human_review  → status: "pending_review"
```

## Routing Logic

A claim is routed to **human_review** if ANY of:
- OCR confidence < 70% (illegible bill)
- Any ICD-10 diagnosis confidence < 0.85 (ambiguous coding)
- Patient eligibility = False (no/expired coverage)

Otherwise: **auto_approve**.

## Run Tests

```bash
cd backend
source venv/bin/activate
python -m pytest tests/ -v
```

All 11 tests verify the 6 checklist items from the spec.

## Data Files

| File | Description |
|------|-------------|
| `data/icd10_codes.csv` | 350+ ICD-10 codes (cardiology, respiratory, GI, neuro, ortho, derma) |
| `data/eligibility.csv` | 50 mock patient eligibility records (active/expired coverage) |
| `data/sample_bills/` | 6 deliberate test cases: clean, ambiguous, ineligible, rare, high-value, duplicate |

## Project Structure

```
backend/
├── app/
│   ├── main.py          # FastAPI server + 5 API endpoints
│   ├── config.py        # Settings & smart stub fallback flags
│   ├── database.py      # SQLite engine + schema
│   ├── models.py        # Pydantic models (exact contract shapes)
│   ├── storage.py       # CRUD operations + metrics
│   └── pipeline/
│       ├── ocr.py       # Stage 1: Google Vision / stub
│       ├── clean_ocr.py # Stage 2: Claude / regex parser
│       ├── harmonizer.py# Stage 3: ICD-10 coding (constrained)
│       ├── eligibility.py# Stage 4: CSV lookup
│       └── orchestrator.py# Stage 5: Wires all stages + routing
├── data/
│   ├── icd10_codes.csv
│   ├── eligibility.csv
│   └── sample_bills/   # 6 test case .txt files
├── tests/
│   ├── test_pipeline.py # Unit tests (11 tests)
│   └── test_api.py      # API integration tests
├── seed_data.py         # Populate DB with 6 sample claims
├── requirements.txt
└── .env.example
```

## Q&A Prep (Person A)

**Why does low OCR confidence route to HITL instead of guessing?**
> Medical codes have direct financial and clinical impact. If the bill is illegible, guessing the wrong diagnosis could lead to fraudulent approvals or deny legitimate claims. A human must verify the source document.

**Why is the LLM constrained to candidate ICD-10 codes only?**
> LLMs can hallucinate clinical codes that look plausible but don't exist or refer to different conditions. By pre-filtering with pandas to real CSV candidates, we guarantee every code in the output is a valid, real ICD-10 code. The LLM only selects, never invents.

**What's real vs. mocked in the eligibility check?**
> Real: The lookup logic (name match, age tolerance, expiry check). Mocked: The data source (50-row CSV instead of a live insurer API). Roadmap: Replace the CSV read with a REST call to PMJAY or equivalent insurer API.

**What compliance is implemented vs. roadmap?**
> Implemented: TLS (via reverse proxy), basic request logging, no raw PII in error responses.
> Roadmap: Full PHI tokenization, HIPAA-compliant audit logs, role-based access, encryption at rest, NABH/ISO 27001 certification.
