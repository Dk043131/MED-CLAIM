"""
tests/test_pending_features.py — Verification tests for 6 pending features:
1. Claim Lifecycle State Machine
2. Fraud Probability & Safety Guardrails
3. SNOMED-CT Medical Ontology Mapping
4. Government Portal Submission Simulation
5. Observability Dashboard Charts & Savings
6. Pre-Authorization Request & HITL Workflow
"""
from fastapi.testclient import TestClient
from app.main import app
from app.models import ExtractedJSON
from app.pipeline.snomed_mapper import lookup_snomed_ct
from app.pipeline.fraud_scorer import evaluate_fraud_risk
from app.pipeline.portal import submit_to_government_portal
from app.pipeline.orchestrator import process_claim

client = TestClient(app)


def test_snomed_mapper():
    code, desc = lookup_snomed_ct("R42", "Giddiness")
    assert code == "404640003"
    assert "Dizziness" in desc

    code2, desc2 = lookup_snomed_ct("E16.2", "Hypoglycemia")
    assert code2 == "302866003"


def test_fraud_scorer():
    extracted = ExtractedJSON(
        patient_name="Test Patient",
        patient_id="10193",
        consultation_fee=3500.0,  # exceeds 3000 -> +0.30
        doctor_name="",           # missing -> +0.15
        symptoms=["fever", "headache"]  # generic -> +0.15
    )
    fraud = evaluate_fraud_risk(extracted, is_duplicate=True)  # duplicate -> +0.60
    assert fraud.fraud_score >= 0.80
    assert fraud.risk_level == "high"
    assert fraud.escalated_to_hitl is True
    assert len(fraud.flags) >= 3


def test_lifecycle_and_portal_on_pipeline():
    claim = process_claim(b"test content", "test.png")
    assert len(claim.lifecycle_events) >= 6
    stages = [e.stage for e in claim.lifecycle_events]
    assert "SUBMITTED" in stages
    assert "OCR" in stages
    assert "STRUCTURED" in stages
    assert "CODED" in stages
    assert "PORTAL" in stages

    if claim.status == "approved":
        assert claim.portal_submission.submitted is True
        assert claim.portal_submission.portal_ref.startswith("PMJAY-")
    else:
        assert claim.portal_submission.submitted is False


def test_dashboard_metrics_enhanced():
    resp = client.get("/dashboard/metrics")
    assert resp.status_code == 200
    data = resp.json()
    assert "total_savings_inr" in data
    assert "total_hours_saved" in data
    assert "volume_series" in data
    assert len(data["volume_series"]) >= 1
    assert "stage_timing_avg_ms" in data


def test_preauth_workflow():
    # 1. List preauths
    resp = client.get("/preauth/queue")
    assert resp.status_code == 200
    queue = resp.json()
    assert len(queue) >= 1

    # 2. Submit new request
    new_req = {
        "patient_id": "99999",
        "patient_name": "Rohan Verma",
        "hospital_name": "City Care Hospital",
        "procedure_name": "CT Angiography",
        "estimated_cost": 15000.0,
        "clinical_justification": "Rule out aneurysm",
        "urgency": "urgent"
    }
    resp2 = client.post("/preauth/request", json=new_req)
    assert resp2.status_code == 200
    created = resp2.json()
    assert created["status"] == "pending"
    pa_id = created["preauth_id"]

    # 3. Approve preauth
    resp3 = client.post(f"/preauth/{pa_id}/approve")
    assert resp3.status_code == 200
    assert resp3.json()["status"] == "approved"
