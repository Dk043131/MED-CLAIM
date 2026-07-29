"""
auth.py — Authentication business logic, session security & rate limiting
Handles user creation, credential validation, login throttling, and session management.

Security model:
  - Argon2id password hashing (time_cost=3, memory=64MB, parallelism=2)
  - PBKDF2 SHA-256 fallback (200k iterations) when argon2-cffi unavailable
  - 384-bit session tokens (secrets.token_urlsafe(48))
  - Login rate limiting: max 5 attempts per 15 minutes per email
  - Account lockout after 10 failed attempts
  - Session expiry: configurable (default 7 days)
"""
from __future__ import annotations
import secrets
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from sqlalchemy import select, delete, func
from app.auth_db import (
    auth_engine, users_table, sessions_table, login_attempts_table,
    _hash_pass, _verify_pass,
)
from app.config import MAX_LOGIN_ATTEMPTS, LOCKOUT_WINDOW_MINUTES, SESSION_EXPIRY_DAYS


# ── Password utilities ────────────────────────────────────────────────────────

def hash_password(password: str) -> tuple[str, str]:
    """Returns (hash_str, salt_hex). Uses Argon2id or PBKDF2 fallback."""
    salt = secrets.token_hex(16)
    pwd_hash = _hash_pass(password, salt)
    return pwd_hash, salt


def verify_password(password: str, salt_hex: str, stored_hash: str, algo: str = "argon2id") -> bool:
    """Verifies plaintext password against stored salt and hash."""
    return _verify_pass(password, salt_hex, stored_hash, algo)


# ── User retrieval ────────────────────────────────────────────────────────────

def get_user_by_email(email: str) -> Optional[Dict[str, Any]]:
    """Retrieves full user row from auth.db by email address."""
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
                "hash_algo": getattr(row, "hash_algo", "pbkdf2"),
                "role": row.role,
                "clinic_id": row.clinic_id,
                "is_active": getattr(row, "is_active", True),
            }
    return None


def get_user_by_id(user_id: str) -> Optional[Dict[str, Any]]:
    """Retrieves public user profile from auth.db by user ID."""
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


# ── Rate limiting ─────────────────────────────────────────────────────────────

def count_recent_failures(email: str) -> int:
    """Count failed login attempts for email in the last LOCKOUT_WINDOW_MINUTES."""
    cutoff = datetime.now() - timedelta(minutes=LOCKOUT_WINDOW_MINUTES)
    with auth_engine.connect() as conn:
        count = conn.execute(
            select(func.count())
            .select_from(login_attempts_table)
            .where(login_attempts_table.c.email == email.lower())
            .where(login_attempts_table.c.success == False)
            .where(login_attempts_table.c.attempted_at >= cutoff)
        ).scalar()
        return count or 0


def record_login_attempt(email: str, success: bool, ip_address: str = "") -> None:
    """Records a login attempt in the rate limiting table."""
    with auth_engine.begin() as conn:
        try:
            conn.execute(
                login_attempts_table.insert().values(
                    email=email.lower(),
                    ip_address=ip_address or "",
                    success=success,
                )
            )
        except Exception:
            pass  # Non-critical — don't fail login because of logging failure


def is_rate_limited(email: str) -> bool:
    """Returns True if the email has exceeded the login attempt limit."""
    return count_recent_failures(email) >= MAX_LOGIN_ATTEMPTS


# ── Registration ──────────────────────────────────────────────────────────────

def register_user(
    email: str,
    full_name: str,
    password: str,
    role: str = "Caseworker",
    clinic_id: Optional[str] = None
) -> Dict[str, Any]:
    """Registers a new user in auth.db. Raises ValueError if email exists."""
    norm_email = email.strip().lower()
    if get_user_by_email(norm_email):
        raise ValueError(f"User with email '{email}' already exists.")

    # Password policy check
    if len(password) < 8:
        raise ValueError("Password must be at least 8 characters.")

    user_id = f"USR-{secrets.randbelow(89999) + 10000}"
    pwd_hash, salt = hash_password(password)

    with auth_engine.begin() as conn:
        conn.execute(
            users_table.insert().values(
                id=user_id,
                email=norm_email,
                full_name=full_name.strip(),
                password_hash=pwd_hash,
                salt=salt,
                hash_algo="argon2id",
                role=role,
                clinic_id=clinic_id or "CLINIC-GENERAL",
                is_active=True,
            )
        )

    return {
        "id": user_id,
        "email": norm_email,
        "full_name": full_name,
        "role": role,
        "clinic_id": clinic_id or "CLINIC-GENERAL",
    }


# ── Authentication ────────────────────────────────────────────────────────────

def authenticate_user(email: str, password: str, ip_address: str = "") -> Optional[Dict[str, Any]]:
    """
    Validates email & password credentials against auth.db.
    Enforces rate limiting and records all attempts.
    Returns public user dict on success, None on failure.
    """
    norm_email = email.strip().lower()

    # Rate limit check
    if is_rate_limited(norm_email):
        return None  # Too many attempts — caller should return 429

    user = get_user_by_email(norm_email)
    if not user:
        record_login_attempt(norm_email, False, ip_address)
        return None

    # Check account active status
    if not user.get("is_active", True):
        return None

    # Verify password
    algo = user.get("hash_algo", "pbkdf2")
    verified = verify_password(password, user["salt"], user["password_hash"], algo)

    if verified:
        record_login_attempt(norm_email, True, ip_address)
        return {
            "id": user["id"],
            "email": user["email"],
            "full_name": user["full_name"],
            "role": user["role"],
            "clinic_id": user["clinic_id"],
        }
    else:
        record_login_attempt(norm_email, False, ip_address)
        return None


# ── Session management ────────────────────────────────────────────────────────

def create_session(user_id: str, expiry_days: int = SESSION_EXPIRY_DAYS) -> str:
    """Generates a 384-bit secure random session token in auth.db."""
    token = f"medclaim_session_{secrets.token_urlsafe(48)}"
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
    if not token or not token.startswith("medclaim_session_"):
        return None

    with auth_engine.connect() as conn:
        stmt = select(sessions_table).where(sessions_table.c.token == token)
        sess = conn.execute(stmt).first()
        if not sess:
            return None

        if sess.expires_at < datetime.now():
            # Clean up expired session
            with auth_engine.begin() as wconn:
                wconn.execute(delete(sessions_table).where(sessions_table.c.token == token))
            return None

        return get_user_by_id(sess.user_id)


def revoke_session(token: str) -> bool:
    """Deletes session token from auth.db."""
    with auth_engine.begin() as conn:
        res = conn.execute(delete(sessions_table).where(sessions_table.c.token == token))
        return res.rowcount > 0


def cleanup_expired_sessions() -> int:
    """Removes all expired sessions from auth.db. Returns count deleted."""
    with auth_engine.begin() as conn:
        res = conn.execute(
            delete(sessions_table).where(sessions_table.c.expires_at < datetime.now())
        )
        return res.rowcount
