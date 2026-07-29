"""
database.py — SQLite persistence layer
Uses SQLAlchemy Core (no ORM classes) — keeps it simple and
dependency-light for a hackathon / demo context.
"""
import json
from sqlalchemy import (
    create_engine, MetaData, Table, Column,
    String, Text, DateTime, func
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


def init_db() -> None:
    """Create all tables if they don't exist yet."""
    metadata.create_all(engine)
