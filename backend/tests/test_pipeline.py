"""
tests/test_pipeline.py — Unit tests for the 5-stage AI pipeline

Tests cover all 6 verification checklist items from the spec:
  1. Clean bill → route: "auto_approve"
  2. Ambiguous bill → route: "human_review"
  3. Review queue shows flagged claims
  4. Approve action updates status correctly
  5. Dashboard metrics are correct after each action
  6. Full pipeline runs in < 10 seconds
"""
import sys, os, time, pytest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import init_db, engine, claims_table
from app.pipeline.orchestrator import process_claim
from app.pipeline.ocr import ocr_bill_stub
from app.pipeline.clean_ocr import extract_stub
from app.pipeline.harmonizer import harmonize_codes, needs_review
from app.pipeline.eligibility import check_eligibility
from app.models import CodingResult, CodedDiagnosis
from app import storage

SAMPLE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "sample_bills")


@pytest.fixture(autouse=True)
def fresh_db(tmp_path, monkeypatch):
    """Each test gets its own in-memory SQLite DB so tests don't interfere."""
    db_url = f"sqlite:///{tmp_path}/test.db"
    monkeypatch.setenv("DATABASE_URL", db_url)

    # Re-import database module so engine uses the new URL
    import importlib
    import app.database as db_mod
    db_mod.engine = __import__("sqlalchemy", fromlist=["create_engine"]).create_engine(
        db_url,
        connect_args={"check_same_thread": False},
    )
    db_mod.metadata.create_all(db_mod.engine)

    # Patch storage to use the fresh engine
    import app.storage as storage_mod
    storage_mod.engine = db_mod.engine
    storage_mod.claims_table = db_mod.claims_table

    yield

    db_mod.metadata.drop_all(db_mod.engine)


def _read_bill(filename: str) -> bytes:
    path = os.path.join(SAMPLE_DIR, filename)
    with open(path, "rb") as f:
        return f.read()


# ── Test 1: Clean bill auto-approves ─────────────────────────────────────────

def test_clean_bill_auto_approved():
    """A clean, clear bill with eligible patient must route to auto_approve."""
    bill = _read_bill("clean_bill.txt")
    claim = process_claim(bill, "clean_bill.txt")

    assert claim.route == "auto_approve", (
        f"Expected route='auto_approve' but got '{claim.route}'"
    )
    assert claim.status == "approved", (
        f"Expected status='approved' but got '{claim.status}'"
    )
    assert claim.claim_id.startswith("CLM-")
    assert len(claim.extracted_json.symptoms) > 0
    assert len(claim.coding_result.coded_diagnoses) > 0


# ── Test 2: Ambiguous bill goes to human review ───────────────────────────────

def test_ambiguous_bill_human_review():
    """An illegible bill with low OCR confidence must route to human_review."""
    bill = _read_bill("ambiguous_bill.txt")
    claim = process_claim(bill, "ambiguous_bill.txt")

    assert claim.route == "human_review", (
        f"Expected route='human_review' but got '{claim.route}'"
    )
    assert claim.status == "pending_review"


# ── Test 3: Ineligible patient goes to human review ──────────────────────────

def test_ineligible_patient_human_review():
    """A patient with expired coverage must route to human_review."""
    bill = _read_bill("ineligible_bill.txt")
    claim = process_claim(bill, "ineligible_bill.txt")

    assert claim.route == "human_review"
    assert claim.eligibility.eligible is False


# ── Test 4: Review queue shows pending_review claims ─────────────────────────

def test_review_queue_shows_pending():
    """GET /claims/review-queue should return only pending_review claims."""
    clean_bill = _read_bill("clean_bill.txt")
    ambiguous_bill = _read_bill("ambiguous_bill.txt")

    claim_auto = process_claim(clean_bill, "clean_bill.txt")
    claim_review = process_claim(ambiguous_bill, "ambiguous_bill.txt")

    storage.save_claim(claim_auto)
    storage.save_claim(claim_review)

    queue = storage.get_review_queue()
    queue_ids = [c.claim_id for c in queue]

    assert claim_review.claim_id in queue_ids, "Pending claim not in review queue"
    assert claim_auto.claim_id not in queue_ids, "Auto-approved claim should NOT be in review queue"


# ── Test 5: Approve action updates status ─────────────────────────────────────

def test_approve_claim_updates_status():
    """POST /claims/{id}/approve must change status from pending_review to approved."""
    bill = _read_bill("ambiguous_bill.txt")
    claim = process_claim(bill, "ambiguous_bill.txt")
    assert claim.status == "pending_review"

    storage.save_claim(claim)
    updated = storage.approve_claim(claim.claim_id)

    assert updated is not None
    assert updated.status == "approved"
    assert updated.claim_id == claim.claim_id

    # Also verify it disappears from queue
    queue = storage.get_review_queue()
    assert all(c.claim_id != claim.claim_id for c in queue)


# ── Test 6: Dashboard metrics are correct ─────────────────────────────────────

def test_dashboard_metrics_accuracy():
    """GET /dashboard/metrics numbers must reflect actual DB state."""
    clean_bill = _read_bill("clean_bill.txt")
    ambiguous_bill = _read_bill("ambiguous_bill.txt")

    c1 = process_claim(clean_bill, "clean_bill.txt")
    c2 = process_claim(ambiguous_bill, "ambiguous_bill.txt")
    storage.save_claim(c1)
    storage.save_claim(c2)

    metrics = storage.get_metrics()
    assert metrics.total_claims == 2
    assert metrics.auto_approved == 1
    assert metrics.pending_review == 1
    assert metrics.auto_adjudication_rate == 50.0

    # Now approve the pending one
    storage.approve_claim(c2.claim_id)
    metrics2 = storage.get_metrics()
    assert metrics2.auto_approved == 2
    assert metrics2.pending_review == 0
    assert metrics2.auto_adjudication_rate == 100.0


# ── Test 7: Full pipeline runs in under 10 seconds ───────────────────────────

def test_pipeline_execution_time():
    """Full pipeline (all 5 stages) must complete in < 10 seconds for demo safety."""
    bill = _read_bill("clean_bill.txt")

    t0 = time.perf_counter()
    claim = process_claim(bill, "clean_bill.txt")
    elapsed = time.perf_counter() - t0

    assert elapsed < 10.0, f"Pipeline took {elapsed:.2f}s — exceeds 10s demo limit!"
    print(f"\n  Pipeline completed in {elapsed:.3f}s ✓")


# ── Test 8: ICD-10 harmonizer never freehands a code ─────────────────────────

def test_harmonizer_constrained_to_candidates():
    """All coded diagnoses must have ICD-10 codes that exist in the CSV."""
    import pandas as pd
    from app.config import ICD10_CSV

    result = harmonize_codes(["Fever", "Headache", "Cough"])
    assert len(result.coded_diagnoses) > 0

    df = pd.read_csv(ICD10_CSV)
    valid_codes = set(df["code"].str.strip().tolist())

    for d in result.coded_diagnoses:
        assert d.icd10_code in valid_codes, (
            f"Code '{d.icd10_code}' for symptom '{d.symptom}' not found in ICD-10 CSV!"
        )


# ── Test 9: Eligibility check — expired coverage ─────────────────────────────

def test_eligibility_expired_coverage():
    """Fatima Shaikh has expired coverage — must return eligible=False."""
    result = check_eligibility("Fatima Shaikh", 52)
    assert result.eligible is False
    assert "expired" in result.reason.lower()


# ── Test 10: Eligibility check — active coverage ─────────────────────────────

def test_eligibility_active_coverage():
    """Rahul Sharma has active coverage — must return eligible=True."""
    result = check_eligibility("Rahul Sharma", 34)
    assert result.eligible is True
    assert result.patient_id == "PAT-1001"


# ── Test 11: needs_review threshold ──────────────────────────────────────────

def test_needs_review_threshold():
    """needs_review() must return True when any confidence < 0.85."""
    high_conf = CodingResult(coded_diagnoses=[
        CodedDiagnosis(symptom="Fever", icd10_code="R50.9",
                       icd10_description="Fever unspecified", confidence=0.95),
    ])
    low_conf = CodingResult(coded_diagnoses=[
        CodedDiagnosis(symptom="Fever", icd10_code="R50.9",
                       icd10_description="Fever unspecified", confidence=0.95),
        CodedDiagnosis(symptom="Dementia", icd10_code="F03.90",
                       icd10_description="Unspecified dementia", confidence=0.60),
    ])

    assert needs_review(high_conf) is False
    assert needs_review(low_conf) is True
