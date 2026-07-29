"""
main.py — Stage 7: FastAPI Application & Contract Endpoints

Implements all 5 endpoints from the API contract exactly:
  POST /claims/upload           — multipart file → ClaimRecord
  GET  /claims                  — list[ClaimRecord]
  GET  /claims/review-queue     — list[ClaimRecord] (pending_review only)
  POST /claims/{claim_id}/approve — ApproveResponse
  GET  /dashboard/metrics       — DashboardMetrics

Compliance:
  - CORS enabled (allow all origins in dev; restrict in prod)
  - Request logging via middleware
  - TLS handled by reverse proxy (nginx/caddy) in production
"""
from __future__ import annotations
import logging
import time
from contextlib import asynccontextmanager
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from app.database import init_db
from app.models import ClaimRecord, DashboardMetrics, ApproveResponse
from app.pipeline.orchestrator import process_claim
from app import storage

# ── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("med_claim")


# ── Lifespan (startup / shutdown) ────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("MED-CLAIM backend starting up — initialising database...")
    init_db()
    logger.info("Database ready.")
    yield
    logger.info("MED-CLAIM backend shutting down.")


# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="MED-CLAIM API",
    description="Automated Medical Claim Adjudication System — AI-powered OCR, ICD-10 coding, and eligibility verification.",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS — allow frontend dev server and any deployed origin
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Request timing middleware ─────────────────────────────────────────────────

@app.middleware("http")
async def log_requests(request, call_next):
    t0 = time.perf_counter()
    response = await call_next(request)
    elapsed = time.perf_counter() - t0
    logger.info(f"{request.method} {request.url.path} → {response.status_code} ({elapsed:.3f}s)")
    return response


# ── Health check ──────────────────────────────────────────────────────────────

@app.get("/health", tags=["System"])
def health_check():
    """Quick liveness probe. Returns 200 if the server is running."""
    return {"status": "ok", "service": "med-claim-api"}


# ── Contract Endpoint 1: Upload & process a claim ─────────────────────────────

@app.post(
    "/claims/upload",
    response_model=ClaimRecord,
    summary="Upload a medical bill image/document and process it through the AI pipeline",
    tags=["Claims"],
)
async def upload_claim(file: UploadFile = File(...)):
    """
    Accepts a multipart-uploaded medical bill (image or text file).

    Runs the full 5-stage AI pipeline:
      1. OCR (Google Cloud Vision or stub)
      2. Structuring (Claude or regex parser)
      3. ICD-10 harmonization (constrained to CSV candidates)
      4. Eligibility check (CSV lookup)
      5. Routing decision (auto_approve vs human_review)

    Returns the complete ClaimRecord which is also persisted to the database.
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file provided.")

    allowed_types = {
        "image/jpeg", "image/png", "image/webp", "image/tiff",
        "application/pdf", "text/plain",
    }
    if file.content_type and file.content_type not in allowed_types:
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported file type: {file.content_type}. Upload an image or PDF.",
        )

    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    try:
        claim = process_claim(file_bytes, file.filename or "")
    except Exception as exc:
        logger.exception(f"Pipeline error processing {file.filename}: {exc}")
        raise HTTPException(status_code=500, detail=f"Pipeline error: {str(exc)}")

    storage.save_claim(claim)
    logger.info(f"Claim {claim.claim_id} processed → route={claim.route}, status={claim.status}")
    return claim


# ── Contract Endpoint 2: List all claims ──────────────────────────────────────

@app.get(
    "/claims",
    response_model=list[ClaimRecord],
    summary="Retrieve all processed claims",
    tags=["Claims"],
)
def list_claims():
    """Returns all claim records from the database, newest first."""
    return storage.get_claims()


# ── Contract Endpoint 3: Review queue ─────────────────────────────────────────

@app.get(
    "/claims/review-queue",
    response_model=list[ClaimRecord],
    summary="Retrieve all claims awaiting human review",
    tags=["Claims"],
)
def review_queue():
    """
    Returns only claims with status == 'pending_review'.
    These are the claims that require a human adjudicator to inspect,
    verify, and approve before they can be processed.
    """
    return storage.get_review_queue()


from app.models import ClaimRecord, DashboardMetrics, ApproveResponse, ApproveRequest
from app.pipeline.fingerprint import save_correction_to_fingerprint


# ── Contract Endpoint 4: Approve a claim ─────────────────────────────────────

@app.post(
    "/claims/{claim_id}/approve",
    response_model=ApproveResponse,
    summary="Approve a pending claim",
    tags=["Claims"],
)
def approve_claim(claim_id: str, payload: Optional[ApproveRequest] = None):
    """
    Sets the status of a pending claim to 'approved'.
    If caseworker corrections are provided in payload, feeds them into clinic_fingerprints memory cache!
    """
    existing_claim = storage.get_claim(claim_id)
    if existing_claim is None:
        raise HTTPException(status_code=404, detail=f"Claim '{claim_id}' not found.")

    fingerprint_updated = False
    if payload and payload.corrections:
        clinic_id = payload.clinic_id or existing_claim.extracted_json.clinic_id or "CLINIC-DEFAULT"
        for field_type, corrected_val in payload.corrections.items():
            original_val = getattr(existing_claim.extracted_json, field_type, "") or existing_claim.raw_ocr
            if original_val and corrected_val:
                saved = save_correction_to_fingerprint(clinic_id, str(original_val), str(corrected_val), field_type)
                if saved:
                    fingerprint_updated = True

    updated = storage.approve_claim(claim_id)
    return ApproveResponse(
        claim_id=claim_id,
        status="approved",
        fingerprint_updated=fingerprint_updated
    )


# ── Contract Endpoint 5: Dashboard metrics ────────────────────────────────────

@app.get(
    "/dashboard/metrics",
    response_model=DashboardMetrics,
    summary="Get real-time dashboard metrics",
    tags=["Dashboard"],
)
def dashboard_metrics():
    """
    Returns aggregate metrics for the dashboard:
      - total_claims
      - auto_approved
      - pending_review
      - auto_adjudication_rate (percentage, 0–100)
    """
    return storage.get_metrics()
