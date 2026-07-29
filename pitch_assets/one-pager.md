# MED-CLAIM — One-Page Overview
## Cognitive Automation for Universal Healthcare Claims Processing · SDGIAP002

---

### The Problem

Administrative errors in healthcare claims push millions of low-income families into medical debt. In India alone, **70% of healthcare costs are paid out-of-pocket**, and claim rejection rates from manual processing errors exceed 15%. Rural clinics produce handwritten, ambiguous bills that existing automated systems cannot read.

---

### The Solution

MED-CLAIM is an **agentic AI pipeline** that takes a scanned or photographed hospital bill, extracts structured data, maps it to clinical codes, verifies eligibility, and either **auto-submits the claim** or **escalates to a human reviewer** — all in under 10 seconds.

---

### Architecture

```
Bill Upload (image/PDF/scan)
         ↓
  IDP Bot: OCR + LLM cleanup           ← Google Vision + GPT-4 class LLM
         ↓
  Clinical Code Bot: ICD-10 mapping    ← LLM + CMS ICD-10-CM reference
         ↓
  Eligibility Bot: welfare DB check    ← Mock Ayushman Bharat / ESIC API
         ↓
  Orchestrator Agent (LangGraph)       ← Confidence scoring + routing logic
       ↙           ↘
Auto-Approve    HITL Queue             ← Confidence > 0.75 → auto; else human
       ↓               ↓
  Claims DB       Caseworker UI
       ↓
  Observability Dashboard
```

**State machine:** `SUBMITTED → OCR → CODING → ELIGIBILITY → DECISION`
**Confidence threshold:** 0.75 — above = auto-approve; below = route to human review

---

### Tech Stack

| Layer | Technology |
|---|---|
| Frontend | HTML5, CSS3, Vanilla JS, Chart.js |
| Mock API Server | Python stdlib `http.server` (zero dependencies) |
| OCR | Google Cloud Vision API / Azure Document Intelligence |
| LLM (coding + cleanup) | GPT-4 / Claude 3 (function-calling) |
| Agent Framework | LangGraph / hand-rolled tool loop |
| Clinical Codes | CMS ICD-10-CM (public dataset) |
| Database | SQLite / PostgreSQL |
| Eligibility | Mock REST APIs simulating PM-JAY, ESIC, CGHS, JSY |

---

### Core Features Addressed

| Spec Requirement | How We Meet It |
|---|---|
| Handwritten IDP Bot | Cloud OCR + LLM correction pass |
| Clinical Code Harmonizer | ICD-10 mapping with confidence scoring |
| Eligibility Verification RPA | Mock welfare DB with real scheme names |
| Audit & Submission Bot | State machine + full audit trail per claim |
| Dynamic Tool Execution | LangGraph orchestrator agent |
| Agentic State Management | `claims` table with `audit_log[]` per claim |
| HITL & Safety Guardrails | Confidence threshold → caseworker review queue |
| Live Observability Dashboard | Chart.js charts, live metric polling |

---

### Impact & SDG Alignment

- **SDG 3 (Good Health):** Reduces claim processing time from **days → seconds**
- **SDG 10 (Reduced Inequalities):** Restores access to benefits for rural and low-income patients
- **Estimated impact:** If auto-adjudication reaches 90%+, a district hospital processing 500 claims/month saves **~450 caseworker-hours/month** — redirected to patient care

---

### Compliance Design

- PII fields AES-encrypted at rest (field-level mock)
- Full audit log per claim (HIPAA-aligned design intent)
- Role-based access model (caseworker vs. manager)
- Designed for compliance — not yet certified for production (honest roadmap)

---

### Roadmap

1. Real SNOMED CT integration (license pending)
2. Live government API adapters (NHA sandbox)
3. Fraud detection model (anomaly scoring on line items)
4. Multi-language OCR for regional language bills (Tamil, Hindi, Telugu)

---

*Team: SDGIAP002 · MED-CLAIM · Hackathon submission*
