"""
database.py — SQLite persistence layer
Uses SQLAlchemy Core (no ORM classes) — keeps it simple and
dependency-light for a hackathon / demo context.
"""
import json
from sqlalchemy import (
    create_engine, MetaData, Table, Column,
    String, Text, DateTime, Integer, func
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
    """Create all tables if they don't exist yet."""
    metadata.create_all(engine)
