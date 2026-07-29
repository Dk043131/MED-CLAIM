# conftest.py — shared pytest configuration
import sys
import os
import pytest

# Make sure 'backend/' is always on the Python path when running tests
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.database import engine, claims_table, clinic_fingerprints_table, init_db

@pytest.fixture(autouse=True)
def reset_db_between_tests():
    init_db()
    with engine.begin() as conn:
        conn.execute(claims_table.delete())
        conn.execute(clinic_fingerprints_table.delete())
    engine.dispose()
    yield
    with engine.begin() as conn:
        conn.execute(claims_table.delete())
        conn.execute(clinic_fingerprints_table.delete())
    engine.dispose()
