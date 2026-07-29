"""
pipeline/fraud_scorer.py — Fraud Probability & Safety Guardrails

Evaluates extracted claims against fraud risk rules and safety guardrails:
  - Duplicate signature/twin claim detection (+0.60)
  - Excessive consultation fee (> Rs. 3000: +0.30, > Rs. 1500: +0.15)
  - Missing prescribing doctor details (+0.15)
  - Missing UHID/IP patient identifier (+0.10)
  - Generic/unspecific symptom profiles without clear diagnosis (+0.15)
"""
from __future__ import annotations
from typing import List
from app.models import ExtractedJSON, FraudResult


def evaluate_fraud_risk(extracted: ExtractedJSON, is_duplicate: bool = False) -> FraudResult:
    """
    Evaluates fraud probability score (0.0 to 1.0) and determines if the claim
    requires immediate escalation to human-in-the-loop (HITL) review.
    """
    score = 0.0
    flags: List[str] = []

    # 1. Duplicate claim check
    if is_duplicate:
        score += 0.60
        flags.append("Duplicate claim signature detected across recent submissions")

    # 2. Consultation fee anomalies
    if extracted.consultation_fee > 3000.0:
        score += 0.30
        flags.append(f"Consultation fee (Rs. {extracted.consultation_fee:.0f}) exceeds regional maximum threshold")
    elif extracted.consultation_fee > 1500.0:
        score += 0.15
        flags.append(f"Consultation fee (Rs. {extracted.consultation_fee:.0f}) higher than regional clinic average")

    # 3. Missing doctor details
    if not extracted.doctor_name.strip() and not extracted.doctor_id.strip():
        score += 0.15
        flags.append("Missing prescribing doctor name and signature ID")

    # 4. Missing patient identifier
    if not extracted.patient_id.strip():
        score += 0.10
        flags.append("Missing UHID / IP patient registration identifier")

    # 5. Generic symptoms check (without specific diagnosis)
    generic_symptoms = {"fever", "headache", "cold", "cough", "body pain", "weakness"}
    symptom_set = {s.strip().lower() for s in extracted.symptoms if s.strip()}
    if symptom_set and symptom_set.issubset(generic_symptoms):
        score += 0.15
        flags.append("Claim lists only generic/unspecific symptoms without clinical diagnosis")

    # Cap score at 1.0
    final_score = min(round(score, 2), 1.0)

    # Determine risk level
    if final_score >= 0.60:
        risk_level = "high"
    elif final_score >= 0.30:
        risk_level = "medium"
    else:
        risk_level = "low"

    # Auto-escalate to HITL if score >= 0.50 or risk_level == "high"
    escalate = final_score >= 0.50

    return FraudResult(
        fraud_score=final_score,
        risk_level=risk_level,
        flags=flags,
        escalated_to_hitl=escalate
    )
