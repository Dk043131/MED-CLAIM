"""
database.py — SQLite persistence layer
Uses SQLAlchemy Core (no ORM classes) — keeps it simple and
dependency-light for a hackathon / demo context.
"""
import json
from sqlalchemy import (
    create_engine, MetaData, Table, Column,
    String, Text, DateTime, Integer, func, select
)
from sqlalchemy.pool import StaticPool
from app.config import DATABASE_URL

# ── Engine ──────────────────────────────────────────────────────────────────
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},   # SQLite needs this for FastAPI threads
    poolclass=StaticPool,
)
metadata = MetaData()

# ── Claims Table ─────────────────────────────────────────────────────────────
claims_table = Table(
    "claims",
    metadata,
    Column("claim_id",       String(32),  primary_key=True),
    Column("raw_ocr",        Text,        nullable=False),
    Column("extracted_json", Text,        nullable=False),   # JSON string
    Column("coding_result",  Text,        nullable=False),   # JSON string
    Column("eligibility",    Text,        nullable=False),   # JSON string
    Column("route",          String(20),  nullable=False),
    Column("status",         String(20),  nullable=False),
    Column("created_at",     DateTime,    server_default=func.now()),
)

# ── Clinic Fingerprints Table ────────────────────────────────────────────────
clinic_fingerprints_table = Table(
    "clinic_fingerprints",
    metadata,
    Column("id",                Integer,     primary_key=True, autoincrement=True),
    Column("clinic_id",         String(64),  nullable=False, index=True),
    Column("field_type",        String(32),  nullable=False),
    Column("raw_ocr_snippet",   Text,        nullable=False),
    Column("corrected_value",   Text,        nullable=False),
    Column("hit_count",         Integer,     server_default="1"),
    Column("created_at",        DateTime,    server_default=func.now()),
)


def init_db() -> None:
    """Create all tables if they don't exist yet and seed demo data."""
    metadata.create_all(engine)
    seed_initial_claims()


def seed_initial_claims() -> None:
    """Populate database with initial claims if empty."""
    with engine.connect() as conn:
        result = conn.execute(select(claims_table.c.claim_id).limit(1))
        if result.fetchone():
            return

    demo_claims = [
        {
            "claim_id": "CLM-7826",
            "raw_ocr": "Adichunchanagiri Institute of Medical Sciences. Patient Rahul Sharma, Age 19, Male. Complaints: Fever, Headache. Diagnosis: Typhoid fever. Consultation Rs. 500, Paracetamol Rs. 200, Cetirizine Rs. 250.",
            "extracted_json": json.dumps({
                "patient_name": "Rahul Sharma",
                "patient_id": "UHID-88219",
                "hospital_name": "Adichunchanagiri Institute of Medical Sciences",
                "age": 19, "sex": "M",
                "symptoms": ["Fever", "Headache"],
                "diagnosis": ["Typhoid fever"],
                "consultation_fee": 500.0,
                "line_items": [{"description": "Consultation Fee", "raw_text": "Rs 500", "amount": 500.0}, {"description": "Paracetamol 650mg", "raw_text": "Rs 200", "amount": 200.0}, {"description": "Cetirizine 10mg", "raw_text": "Rs 250", "amount": 250.0}]
            }),
            "coding_result": json.dumps({
                "coded_diagnoses": [
                    {"symptom": "Fever unspecified", "icd10_code": "R50.9", "icd10_description": "Fever unspecified", "confidence": 0.97},
                    {"symptom": "Headache", "icd10_code": "R51", "icd10_description": "Headache", "confidence": 0.97}
                ]
            }),
            "eligibility": json.dumps({
                "eligible": True,
                "scheme": "PMJAY Gold",
                "existing_coverage": "PMJAY Gold",
                "reason": "Active coverage under Ayushman Bharat PM-JAY Gold."
            }),
            "route": "human_review",
            "status": "pending_review",
        },
        {
            "claim_id": "CLM-9012",
            "raw_ocr": "City Care Hospital. Patient Sunita Devi, Age 42, Female. Complaints: Acute abdominal pain, Vomiting. Consultation Rs. 600, Abdominal Ultrasound Rs. 1500.",
            "extracted_json": json.dumps({
                "patient_name": "Sunita Devi",
                "patient_id": "UHID-44012",
                "hospital_name": "City Care Hospital",
                "age": 42, "sex": "F",
                "symptoms": ["Acute abdominal pain", "Vomiting"],
                "diagnosis": ["Acute Gastritis"],
                "consultation_fee": 600.0,
                "line_items": [{"description": "Consultation Fee", "raw_text": "Rs 600", "amount": 600.0}, {"description": "USG Abdomen", "raw_text": "Rs 1500", "amount": 1500.0}]
            }),
            "coding_result": json.dumps({
                "coded_diagnoses": [
                    {"symptom": "Abdominal pain", "icd10_code": "R10.9", "icd10_description": "Unspecified abdominal pain", "confidence": 0.72}
                ]
            }),
            "eligibility": json.dumps({
                "eligible": True,
                "scheme": "PMJAY Gold",
                "existing_coverage": "PMJAY Gold",
                "reason": "Active PMJAY coverage."
            }),
            "route": "human_review",
            "status": "pending_review",
        },
        {
            "claim_id": "CLM-1001",
            "raw_ocr": "Metropolis PathLabs. Patient Amit Verma, Age 34, Male. CBC Report: Hemoglobin 13.8 g/dL, WBC 7,200 /mcL, Platelets 240,000 /mcL.",
            "extracted_json": json.dumps({
                "patient_name": "Amit Verma",
                "patient_id": "PAT-1001",
                "hospital_name": "Metropolis PathLabs",
                "age": 34, "sex": "M",
                "symptoms": ["Routine Blood Examination"],
                "diagnosis": ["Normal Blood Panel"],
                "consultation_fee": 300.0,
                "line_items": [{"description": "Complete Blood Count", "raw_text": "Rs 450", "amount": 450.0}]
            }),
            "coding_result": json.dumps({
                "coded_diagnoses": [
                    {"symptom": "Blood examination", "icd10_code": "Z01.7", "icd10_description": "Encounter for laboratory examination", "confidence": 0.96}
                ]
            }),
            "eligibility": json.dumps({
                "eligible": True,
                "scheme": "PMJAY Gold",
                "existing_coverage": "PMJAY Gold",
                "reason": "Active coverage under PM-JAY Gold."
            }),
            "route": "auto_approve",
            "status": "approved",
        },
    ]

    with engine.begin() as conn:
        for claim in demo_claims:
            conn.execute(claims_table.insert().values(**claim))

