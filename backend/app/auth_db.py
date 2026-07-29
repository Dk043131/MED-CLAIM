"""
auth_db.py — Dedicated SQLite persistence layer for Authentication (auth.db)
Completely isolated from claims.db.
"""
from __future__ import annotations
import os
import hashlib
import secrets
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
from sqlalchemy import (
    create_engine, MetaData, Table, Column,
    String, Text, DateTime, Integer, func, select
)
from sqlalchemy.pool import StaticPool

AUTH_DB_URL = os.getenv("AUTH_DATABASE_URL", "sqlite:///./auth.db")

auth_engine = create_engine(
    AUTH_DB_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
auth_metadata = MetaData()

# ── Users Table ─────────────────────────────────────────────────────────────
users_table = Table(
    "users",
    auth_metadata,
    Column("id",            String(32),  primary_key=True),
    Column("email",         String(128), nullable=False, unique=True, index=True),
    Column("full_name",     String(128), nullable=False),
    Column("password_hash", String(256), nullable=False),
    Column("salt",          String(64),  nullable=False),
    Column("role",          String(32),  nullable=False, default="Caseworker"),
    Column("clinic_id",     String(64),  nullable=True),
    Column("created_at",     DateTime,    server_default=func.now()),
)

# ── Sessions Table ────────────────────────────────────────────────────────────
sessions_table = Table(
    "sessions",
    auth_metadata,
    Column("token",      String(128), primary_key=True),
    Column("user_id",    String(32),  nullable=False, index=True),
    Column("created_at", DateTime,    server_default=func.now()),
    Column("expires_at", DateTime,    nullable=False),
)


def _hash_pass(password: str, salt_hex: str) -> str:
    salt_bytes = bytes.fromhex(salt_hex)
    pwd_bytes = password.encode("utf-8")
    derived = hashlib.pbkdf2_hmac("sha256", pwd_bytes, salt_bytes, 100_000)
    return derived.hex()


def init_auth_db() -> None:
    """Creates auth.db tables and seeds default demo accounts if empty."""
    auth_metadata.create_all(auth_engine)

    with auth_engine.begin() as conn:
        count = conn.execute(select(func.count()).select_from(users_table)).scalar()
        if count == 0:
            demo_users = [
                {
                    "id": "USR-1001",
                    "email": "admin@medclaim.gov.in",
                    "full_name": "Dr. Rajesh Varma",
                    "password": "AdminPass123!",
                    "role": "Senior Adjudicator",
                    "clinic_id": "HQ-NEW-DELHI",
                },
                {
                    "id": "USR-1002",
                    "email": "caseworker@medclaim.gov.in",
                    "full_name": "Anita Roy",
                    "password": "CasePass123!",
                    "role": "HITL Caseworker",
                    "clinic_id": "CLINIC-CITY-GENERAL",
                },
                {
                    "id": "USR-1003",
                    "email": "hospital@apollo.org",
                    "full_name": "Suresh Nair",
                    "password": "HospPass123!",
                    "role": "Hospital Billing Clerk",
                    "clinic_id": "CLINIC-APOLLO",
                },
            ]

            for u in demo_users:
                salt = secrets.token_hex(16)
                pwd_hash = _hash_pass(u["password"], salt)
                conn.execute(
                    users_table.insert().values(
                        id=u["id"],
                        email=u["email"].lower().strip(),
                        full_name=u["full_name"],
                        password_hash=pwd_hash,
                        salt=salt,
                        role=u["role"],
                        clinic_id=u["clinic_id"],
                    )
                )
