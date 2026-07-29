"""
tests/test_auth.py — Unit and Integration tests for Authentication System (auth.db)
"""
import pytest
from app.auth_db import init_auth_db, auth_engine, users_table, sessions_table
from app.auth import authenticate_user, register_user, create_session, verify_session, revoke_session


@pytest.fixture(autouse=True)
def setup_auth_db():
    init_auth_db()
    with auth_engine.begin() as conn:
        conn.execute(sessions_table.delete())
        conn.execute(users_table.delete())
    init_auth_db()
    yield
    with auth_engine.begin() as conn:
        conn.execute(sessions_table.delete())
        conn.execute(users_table.delete())


def test_init_auth_db_seeds_demo_accounts():
    """Verify auth.db seeds default demo accounts."""
    admin = authenticate_user("admin@medclaim.gov.in", "AdminPass123!")
    assert admin is not None
    assert admin["role"] == "Senior Adjudicator"
    assert admin["full_name"] == "Dr. Rajesh Varma"

    caseworker = authenticate_user("caseworker@medclaim.gov.in", "CasePass123!")
    assert caseworker is not None
    assert caseworker["role"] == "HITL Caseworker"


def test_login_invalid_password():
    """Verify invalid password returns None."""
    res = authenticate_user("admin@medclaim.gov.in", "WrongPassword!")
    assert res is None


def test_register_new_user():
    """Verify registration creates new user in auth.db."""
    user = register_user(
        email="doctor.mehta@cityhospital.in",
        full_name="Dr. Priya Mehta",
        password="PriyaPassword123!",
        role="Clinic Doctor",
        clinic_id="CLINIC-CITY-GENERAL"
    )
    assert user["id"].startswith("USR-")
    assert user["email"] == "doctor.mehta@cityhospital.in"

    # Verify login with new user
    auth_user = authenticate_user("doctor.mehta@cityhospital.in", "PriyaPassword123!")
    assert auth_user is not None
    assert auth_user["full_name"] == "Dr. Priya Mehta"


def test_session_creation_and_verification():
    """Verify session token generation and lookup."""
    user = authenticate_user("caseworker@medclaim.gov.in", "CasePass123!")
    token = create_session(user["id"])
    assert token.startswith("medclaim_session_")

    profile = verify_session(token)
    assert profile is not None
    assert profile["email"] == "caseworker@medclaim.gov.in"

    # Test logout
    revoked = revoke_session(token)
    assert revoked is True
    assert verify_session(token) is None
