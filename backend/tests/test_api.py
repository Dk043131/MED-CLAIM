"""
tests/test_api.py — Integration tests for all 5 FastAPI contract endpoints.

Uses TestClient (httpx-based) — no real server needed.
"""
import sys, os, pytest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient
from app.main import app
import app.database as db_mod
import app.storage as storage_mod

SAMPLE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "sample_bills")

client = TestClient(app)


@pytest.fixture(autouse=True)
def fresh_db(tmp_path, monkeypatch):
    """Each test gets its own clean SQLite DB."""
    from sqlalchemy import create_engine
    from app.database import metadata

    db_url = f"sqlite:///{tmp_path}/test_api.db"
    fresh_engine = create_engine(db_url, connect_args={"check_same_thread": False})
    metadata.create_all(fresh_engine)

    db_mod.engine = fresh_engine
    storage_mod.engine = fresh_engine
    storage_mod.claims_table = db_mod.claims_table

    yield

    metadata.drop_all(fresh_engine)


def _upload_bill(filename: str):
    filepath = os.path.join(SAMPLE_DIR, filename)
    with open(filepath, "rb") as f:
        content = f.read()
    return client.post(
        "/claims/upload",
        files={"file": (filename, content, "text/plain")},
    )


# ── Endpoint 1: POST /claims/upload ──────────────────────────────────────────

def test_upload_returns_claim_record():
    resp = _upload_bill("clean_bill.txt")
    assert resp.status_code == 200, resp.text

    data = resp.json()
    assert "claim_id" in data
    assert data["claim_id"].startswith("CLM-")
    assert "raw_ocr" in data
    assert "extracted_json" in data
    assert "coding_result" in data
    assert "eligibility" in data
    assert data["route"] in ("auto_approve", "human_review")
    assert data["status"] in ("approved", "pending_review")


def test_upload_clean_bill_auto_approves():
    resp = _upload_bill("clean_bill.txt")
    data = resp.json()
    assert data["route"] == "auto_approve"
    assert data["status"] == "approved"


def test_upload_ambiguous_bill_human_review():
    resp = _upload_bill("ambiguous_bill.txt")
    data = resp.json()
    assert data["route"] == "human_review"
    assert data["status"] == "pending_review"


def test_upload_no_file_returns_422():
    resp = client.post("/claims/upload")
    assert resp.status_code == 422


# ── Endpoint 2: GET /claims ───────────────────────────────────────────────────

def test_get_claims_returns_list():
    _upload_bill("clean_bill.txt")
    _upload_bill("ambiguous_bill.txt")

    resp = client.get("/claims")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) == 2


def test_get_claims_empty_initially():
    resp = client.get("/claims")
    assert resp.status_code == 200
    assert resp.json() == []


# ── Endpoint 3: GET /claims/review-queue ─────────────────────────────────────

def test_review_queue_only_pending():
    _upload_bill("clean_bill.txt")    # should be auto_approve
    _upload_bill("ambiguous_bill.txt")  # should be pending_review

    resp = client.get("/claims/review-queue")
    assert resp.status_code == 200
    queue = resp.json()

    # All items in queue must be pending_review
    for item in queue:
        assert item["status"] == "pending_review"

    # Queue must have at least the ambiguous bill
    assert len(queue) >= 1


def test_review_queue_excludes_approved():
    upload_resp = _upload_bill("clean_bill.txt")
    claim_id = upload_resp.json()["claim_id"]

    queue = client.get("/claims/review-queue").json()
    queue_ids = [c["claim_id"] for c in queue]
    assert claim_id not in queue_ids


# ── Endpoint 4: POST /claims/{claim_id}/approve ───────────────────────────────

def test_approve_claim_success():
    upload_resp = _upload_bill("ambiguous_bill.txt")
    claim_id = upload_resp.json()["claim_id"]
    assert upload_resp.json()["status"] == "pending_review"

    approve_resp = client.post(f"/claims/{claim_id}/approve")
    assert approve_resp.status_code == 200

    data = approve_resp.json()
    assert data["claim_id"] == claim_id
    assert data["status"] == "approved"


def test_approve_removes_from_review_queue():
    upload_resp = _upload_bill("ambiguous_bill.txt")
    claim_id = upload_resp.json()["claim_id"]

    client.post(f"/claims/{claim_id}/approve")

    queue = client.get("/claims/review-queue").json()
    queue_ids = [c["claim_id"] for c in queue]
    assert claim_id not in queue_ids


def test_approve_nonexistent_claim_returns_404():
    resp = client.post("/claims/CLM-9999/approve")
    assert resp.status_code == 404


# ── Endpoint 5: GET /dashboard/metrics ───────────────────────────────────────

def test_dashboard_metrics_empty():
    resp = client.get("/dashboard/metrics")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_claims"] == 0
    assert data["auto_approved"] == 0
    assert data["pending_review"] == 0
    assert data["auto_adjudication_rate"] == 0.0


def test_dashboard_metrics_after_uploads():
    _upload_bill("clean_bill.txt")    # auto_approve
    _upload_bill("ambiguous_bill.txt")  # pending_review

    resp = client.get("/dashboard/metrics")
    data = resp.json()

    assert data["total_claims"] == 2
    assert data["auto_approved"] == 1
    assert data["pending_review"] == 1
    assert data["auto_adjudication_rate"] == 50.0


def test_dashboard_metrics_after_approval():
    _upload_bill("clean_bill.txt")
    upload_resp = _upload_bill("ambiguous_bill.txt")
    claim_id = upload_resp.json()["claim_id"]

    client.post(f"/claims/{claim_id}/approve")

    resp = client.get("/dashboard/metrics")
    data = resp.json()
    assert data["auto_approved"] == 2
    assert data["pending_review"] == 0
    assert data["auto_adjudication_rate"] == 100.0


# ── Health check ──────────────────────────────────────────────────────────────

def test_health_check():
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
