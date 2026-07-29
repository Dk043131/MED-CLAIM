"""
pipeline/portal.py — Government Insurance Portal Submission Simulation

Simulates real-time automated submission of approved public health insurance
claims to PMJAY / Ayushman Bharat / State Health Agency portals.
"""
from __future__ import annotations
import datetime
import hashlib
from app.models import ClaimRecord, PortalSubmission


def submit_to_government_portal(claim: ClaimRecord) -> PortalSubmission:
    """
    Submits an adjudicated claim to the simulated national health insurance portal.
    Only error-free, approved claims without high fraud risk are accepted.
    """
    now_iso = datetime.datetime.utcnow().isoformat() + "Z"

    # 1. Check if claim is approved and not flagged for high fraud risk
    if claim.status != "approved":
        return PortalSubmission(
            submitted=False,
            portal_ref="",
            submitted_at=now_iso,
            portal_status="NOT_SUBMITTED",
            expected_settlement_days=0,
            rejection_reason=f"Claim status is '{claim.status}'; only approved claims can be submitted to portal."
        )

    if claim.fraud_result.risk_level == "high":
        return PortalSubmission(
            submitted=False,
            portal_ref="",
            submitted_at=now_iso,
            portal_status="PORTAL_REJECTED",
            expected_settlement_days=0,
            rejection_reason="Portal automated audit rejected claim due to high fraud probability score."
        )

    # 2. Generate deterministic reference number based on claim_id
    hash_suffix = hashlib.sha256(claim.claim_id.encode("utf-8")).hexdigest()[:6].upper()
    year = datetime.datetime.utcnow().year
    portal_ref = f"PMJAY-{year}-{hash_suffix}"

    # 3. Successful submission
    return PortalSubmission(
        submitted=True,
        portal_ref=portal_ref,
        submitted_at=now_iso,
        portal_status="PORTAL_ACCEPTED",
        expected_settlement_days=3,
        rejection_reason=""
    )
