"""
auth.py — Authentication business logic & session token security
Handles user creation, credential validation, and session management against auth.db.
"""
from __future__ import annotations
import secrets
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from sqlalchemy import select, delete
from app.auth_db import auth_engine, users_table, sessions_table, _hash_pass


def hash_password(password: str) -> tuple[str, str]:
    """Returns (hash_hex, salt_hex)"""
    salt = secrets.token_hex(16)
    pwd_hash = _hash_pass(password, salt)
    return pwd_hash, salt


def verify_password(password: str, salt_hex: str, expected_hash: str) -> bool:
    """Verifies plaintext password against stored salt and hash."""
    computed = _hash_pass(password, salt_hex)
    return secrets.compare_digest(computed, expected_hash)


def get_user_by_email(email: str) -> Optional[Dict[str, Any]]:
    """Retrieves user row from auth.db by email address."""
    norm_email = email.strip().lower()
    with auth_engine.connect() as conn:
        stmt = select(users_table).where(users_table.c.email == norm_email)
        row = conn.execute(stmt).first()
        if row:
            return {
                "id": row.id,
                "email": row.email,
                "full_name": row.full_name,
                "password_hash": row.password_hash,
                "salt": row.salt,
                "role": row.role,
                "clinic_id": row.clinic_id,
            }
    return None


def get_user_by_id(user_id: str) -> Optional[Dict[str, Any]]:
    """Retrieves user row from auth.db by user ID."""
    with auth_engine.connect() as conn:
        stmt = select(users_table).where(users_table.c.id == user_id)
        row = conn.execute(stmt).first()
        if row:
            return {
                "id": row.id,
                "email": row.email,
                "full_name": row.full_name,
                "role": row.role,
                "clinic_id": row.clinic_id,
            }
    return None


def register_user(
    email: str,
    full_name: str,
    password: str,
    role: str = "Caseworker",
    clinic_id: Optional[str] = None
) -> Dict[str, Any]:
    """Registers a new user in auth.db."""
    norm_email = email.strip().lower()
    if get_user_by_email(norm_email):
        raise ValueError(f"User with email '{email}' already exists.")

    user_id = f"USR-{secrets.randbelow(8999) + 1000}"
    pwd_hash, salt = hash_password(password)

    with auth_engine.begin() as conn:
        conn.execute(
            users_table.insert().values(
                id=user_id,
                email=norm_email,
                full_name=full_name.strip(),
                password_hash=pwd_hash,
                salt=salt,
                role=role,
                clinic_id=clinic_id or "CLINIC-GENERAL",
            )
        )

    return {
        "id": user_id,
        "email": norm_email,
        "full_name": full_name,
        "role": role,
        "clinic_id": clinic_id or "CLINIC-GENERAL",
    }


def authenticate_user(email: str, password: str) -> Optional[Dict[str, Any]]:
    """Validates email & password credentials against auth.db."""
    user = get_user_by_email(email)
    if not user:
        return None

    if verify_password(password, user["salt"], user["password_hash"]):
        return {
            "id": user["id"],
            "email": user["email"],
            "full_name": user["full_name"],
            "role": user["role"],
            "clinic_id": user["clinic_id"],
        }
    return None


def create_session(user_id: str, expiry_days: int = 7) -> str:
    """Generates a secure random session token in auth.db."""
    token = f"medclaim_session_{secrets.token_urlsafe(32)}"
    expires_at = datetime.now() + timedelta(days=expiry_days)

    with auth_engine.begin() as conn:
        conn.execute(
            sessions_table.insert().values(
                token=token,
                user_id=user_id,
                expires_at=expires_at,
            )
        )
    return token


def verify_session(token: str) -> Optional[Dict[str, Any]]:
    """Validates session token and returns associated user profile if valid."""
    with auth_engine.connect() as conn:
        stmt = select(sessions_table).where(sessions_table.c.token == token)
        sess = conn.execute(stmt).first()
        if not sess:
            return None

        if sess.expires_at < datetime.now():
            return None

        return get_user_by_id(sess.user_id)


def revoke_session(token: str) -> bool:
    """Deletes session token from auth.db."""
    with auth_engine.begin() as conn:
        res = conn.execute(delete(sessions_table).where(sessions_table.c.token == token))
        return res.rowcount > 0
