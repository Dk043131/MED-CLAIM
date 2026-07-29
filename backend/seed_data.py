"""
seed_data.py — Populate the DB with sample claims for demo / Day 1 testing.

Run:  python seed_data.py   (from inside the backend/ directory)

Inserts one claim for each of the 6 test scenarios so the dashboard
starts with meaningful data immediately.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.database import init_db
from app.pipeline.orchestrator import process_claim
from app import storage
from app.config import SAMPLE_BILLS_DIR


TEST_BILLS = [
    ("clean_bill.txt",        "Standard clean bill — auto-approve"),
    ("ambiguous_bill.txt",    "Illegible bill — human review"),
    ("ineligible_bill.txt",   "Expired coverage — human review"),
    ("rare_symptom_bill.txt", "Complex neurology — human review"),
    ("high_claim_bill.txt",   "High-value cardiac — human review"),
    ("duplicate_bill.txt",    "Duplicate submission — human review"),
]


def main():
    print("Initialising database...")
    init_db()

    existing = storage.get_claims()
    if existing:
        print(f"Database already has {len(existing)} claims. Skipping seed.")
        return

    print(f"Seeding {len(TEST_BILLS)} sample claims...\n")
    for filename, description in TEST_BILLS:
        filepath = os.path.join(SAMPLE_BILLS_DIR, filename)
        if not os.path.exists(filepath):
            print(f"  [SKIP] {filename} — file not found")
            continue

        with open(filepath, "rb") as f:
            file_bytes = f.read()

        print(f"  Processing: {description} ({filename})")
        claim = process_claim(file_bytes, filename)
        storage.save_claim(claim)
        print(f"    → {claim.claim_id} | route={claim.route} | status={claim.status}\n")

    metrics = storage.get_metrics()
    print("=" * 50)
    print("Seed complete. Dashboard metrics:")
    print(f"  Total claims:          {metrics.total_claims}")
    print(f"  Auto-approved:         {metrics.auto_approved}")
    print(f"  Pending review:        {metrics.pending_review}")
    print(f"  Auto-adjudication rate:{metrics.auto_adjudication_rate}%")


if __name__ == "__main__":
    main()
