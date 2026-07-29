"""
auth_db.py — Dedicated SQLite persistence layer for Authentication (auth.db)
Completely isolated from claims.db.

Security upgrades:
- Argon2id password hashing (falls back to PBKDF2 if argon2-cffi unavailable)
- Deterministic demo account seeding (fixed salts — won't break on restart)
- login_attempts table for brute-force rate limiting
- is_active column for account lockout support
"""
from __future__ import annotations
import os
import hashlib
import secrets
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
from sqlalchemy import (
    create_engine, MetaData, Table, Column,
    String, Text, DateTime, Integer, Boolean, func, select
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
    Column("password_hash", String(512), nullable=False),
    Column("salt",          String(128), nullable=False),
    Column("hash_algo",     String(16),  nullable=False, default="argon2id"),
    Column("role",          String(32),  nullable=False, default="Caseworker"),
    Column("clinic_id",     String(64),  nullable=True),
    Column("is_active",     Boolean,     nullable=False, default=True),
    Column("created_at",    DateTime,    server_default=func.now()),
)

# ── Sessions Table ────────────────────────────────────────────────────────────
sessions_table = Table(
    "sessions",
    auth_metadata,
    Column("token",      String(256), primary_key=True),
    Column("user_id",    String(32),  nullable=False, index=True),
    Column("created_at", DateTime,    server_default=func.now()),
    Column("expires_at", DateTime,    nullable=False),
)

# ── Login Attempts Table (rate limiting) ──────────────────────────────────────
login_attempts_table = Table(
    "login_attempts",
    auth_metadata,
    Column("id",          Integer, primary_key=True, autoincrement=True),
    Column("email",       String(128), nullable=False, index=True),
    Column("ip_address",  String(64),  nullable=True),
    Column("success",     Boolean,     nullable=False, default=False),
    Column("attempted_at", DateTime,   server_default=func.now()),
)


# ── Password Hashing ──────────────────────────────────────────────────────────

def _hash_pass_argon2(password: str, salt_hex: str) -> str:
    """Argon2id password hashing — strongest security."""
    try:
        from argon2 import PasswordHasher  # type: ignore
        ph = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=2)
        # Use salt as pepper combined with password for extra security
        combined = f"{password}:{salt_hex}"
        return ph.hash(combined)
    except ImportError:
        return _hash_pass_pbkdf2(password, salt_hex)


def _verify_pass_argon2(password: str, salt_hex: str, stored_hash: str) -> bool:
    """Verify Argon2id hash."""
    try:
        from argon2 import PasswordHasher  # type: ignore
        from argon2.exceptions import VerifyMismatchError, InvalidHashError  # type: ignore
        ph = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=2)
        combined = f"{password}:{salt_hex}"
        try:
            return ph.verify(stored_hash, combined)
        except (VerifyMismatchError, InvalidHashError):
            return False
    except ImportError:
        return _verify_pass_pbkdf2(password, salt_hex, stored_hash)


def _hash_pass_pbkdf2(password: str, salt_hex: str) -> str:
    """PBKDF2 HMAC SHA-256 fallback hashing."""
    salt_bytes = bytes.fromhex(salt_hex)
    pwd_bytes = password.encode("utf-8")
    derived = hashlib.pbkdf2_hmac("sha256", pwd_bytes, salt_bytes, 200_000)
    return derived.hex()


def _verify_pass_pbkdf2(password: str, salt_hex: str, stored_hash: str) -> bool:
    """Verify PBKDF2 hash."""
    computed = _hash_pass_pbkdf2(password, salt_hex)
    return secrets.compare_digest(computed, stored_hash)


# ── Public API ────────────────────────────────────────────────────────────────

def _hash_pass(password: str, salt_hex: str) -> str:
    """Primary hash function — tries Argon2id, falls back to PBKDF2."""
    return _hash_pass_argon2(password, salt_hex)


def _verify_pass(password: str, salt_hex: str, stored_hash: str, algo: str = "argon2id") -> bool:
    """Verify password against stored hash using the correct algorithm."""
    if algo == "argon2id" or stored_hash.startswith("$argon2"):
        return _verify_pass_argon2(password, salt_hex, stored_hash)
    return _verify_pass_pbkdf2(password, salt_hex, stored_hash)


# ── Deterministic Demo Seeding ────────────────────────────────────────────────
# Fixed salts for demo accounts — ensures same hash across restarts
# NEVER use fixed salts in production for real users
_DEMO_FIXED_SALTS = {
    "admin@medclaim.gov.in":    "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6",
    "caseworker@medclaim.gov.in": "b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7",
    "hospital@apollo.org":      "c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8",
}


def init_auth_db() -> None:
    """Creates auth.db tables and seeds default demo accounts if not already seeded."""
    auth_metadata.create_all(auth_engine)

    # Add missing columns gracefully (migration for existing auth.db)
    _migrate_existing_db()

    with auth_engine.begin() as conn:
        count = conn.execute(select(func.count()).select_from(users_table)).scalar()
        if count == 0:
            _seed_demo_accounts(conn)
        else:
            # Ensure demo accounts still exist (idempotent re-seed)
            _ensure_demo_accounts(conn)


def _migrate_existing_db() -> None:
    """Add new columns to existing auth.db tables without data loss."""
    import sqlite3
    db_path = AUTH_DB_URL.replace("sqlite:///", "").replace("./", "")
    if not os.path.exists(db_path):
        return

    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()
        # Check if hash_algo column exists
        cursor.execute("PRAGMA table_info(users)")
        cols = [row[1] for row in cursor.fetchall()]
        if "hash_algo" not in cols:
            cursor.execute("ALTER TABLE users ADD COLUMN hash_algo TEXT DEFAULT 'pbkdf2'")
        if "is_active" not in cols:
            cursor.execute("ALTER TABLE users ADD COLUMN is_active INTEGER DEFAULT 1")
        conn.commit()

    # Create login_attempts table if not exists (already handled by create_all)


def _seed_demo_accounts(conn) -> None:
    """Seeds the 3 pre-configured demo accounts with deterministic hashes."""
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
        email = u["email"].lower().strip()
        # Use fixed salt for demo accounts (deterministic across restarts)
        salt = _DEMO_FIXED_SALTS.get(email, secrets.token_hex(16))
        pwd_hash = _hash_pass(u["password"], salt)
        conn.execute(
            users_table.insert().values(
                id=u["id"],
                email=email,
                full_name=u["full_name"],
                password_hash=pwd_hash,
                salt=salt,
                hash_algo="argon2id",
                role=u["role"],
                clinic_id=u["clinic_id"],
                is_active=True,
            )
        )


def _ensure_demo_accounts(conn) -> None:
    """Re-seeds any missing demo accounts (idempotent)."""
    demo_emails = {
        "admin@medclaim.gov.in": ("USR-1001", "Dr. Rajesh Varma", "AdminPass123!", "Senior Adjudicator", "HQ-NEW-DELHI"),
        "caseworker@medclaim.gov.in": ("USR-1002", "Anita Roy", "CasePass123!", "HITL Caseworker", "CLINIC-CITY-GENERAL"),
        "hospital@apollo.org": ("USR-1003", "Suresh Nair", "HospPass123!", "Hospital Billing Clerk", "CLINIC-APOLLO"),
    }
    for email, (uid, name, pwd, role, clinic) in demo_emails.items():
        existing = conn.execute(
            select(users_table).where(users_table.c.email == email)
        ).first()
        if not existing:
            salt = _DEMO_FIXED_SALTS.get(email, secrets.token_hex(16))
            pwd_hash = _hash_pass(pwd, salt)
            conn.execute(
                users_table.insert().values(
                    id=uid, email=email, full_name=name,
                    password_hash=pwd_hash, salt=salt, hash_algo="argon2id",
                    role=role, clinic_id=clinic, is_active=True,
                )
            )
        else:
            # Update hash_algo and is_active if columns were just added
            try:
                conn.execute(
                    users_table.update()
                    .where(users_table.c.email == email)
                    .values(is_active=True)
                )
            except Exception:
                pass
