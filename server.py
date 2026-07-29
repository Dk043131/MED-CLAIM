#!/usr/bin/env python3
"""
MED-CLAIM Mock API Server
Zero external dependencies — stdlib only (Python 3.8+).
File uploads handled as Base64-encoded JSON to avoid multipart parsing.

Routes:
  GET  /                          -> serves index.html
  GET  /assets/<file>             -> serves image assets
  GET  /<file>.css|js             -> serves static files
  GET  /api/claims/review-queue   -> flagged claims
  POST /api/claims/<id>/approve   -> approve a flagged claim
  GET  /api/dashboard/metrics     -> live computed metrics
  POST /api/claims/submit         -> simulate pipeline for a new claim (Base64 JSON)
  POST /api/claims/surge          -> bulk inject N synthetic claims for surge demo
"""

import json
import os
import re
import uuid
import random
import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer

# ─────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────
PORT = 8080
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CLAIMS_FILE = os.path.join(BASE_DIR, "claims.json")

MIME_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css":  "text/css; charset=utf-8",
    ".js":   "application/javascript; charset=utf-8",
    ".json": "application/json",
    ".png":  "image/png",
    ".jpg":  "image/jpeg",
    ".jpeg": "image/jpeg",
    ".svg":  "image/svg+xml",
    ".ico":  "image/x-icon",
}

# ─────────────────────────────────────────────
# Data helpers
# ─────────────────────────────────────────────
def load_claims():
    with open(CLAIMS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)["claims"]

def save_claims(claims):
    with open(CLAIMS_FILE, "w", encoding="utf-8") as f:
        json.dump({"claims": claims}, f, indent=2, ensure_ascii=False)

def compute_metrics(claims):
    total = len(claims)
    approved  = sum(1 for c in claims if c["status"] == "APPROVED")
    flagged   = sum(1 for c in claims if c["status"] == "FLAGGED")
    rejected  = sum(1 for c in claims if c["status"] == "REJECTED")
    auto_rate = round((approved / total * 100), 1) if total else 0.0

    # Last-7-days daily volume (for bar chart)
    today = datetime.date.today()
    daily = {}
    for i in range(6, -1, -1):
        day = (today - datetime.timedelta(days=i)).isoformat()
        daily[day] = {"APPROVED": 0, "FLAGGED": 0, "REJECTED": 0}
    for c in claims:
        ts = c.get("submitted_at", "")[:10]
        if ts in daily:
            s = c["status"]
            if s in daily[ts]:
                daily[ts][s] += 1

    return {
        "total_claims": total,
        "approved": approved,
        "flagged": flagged,
        "rejected": rejected,
        "pending_review": flagged,
        "auto_adjudication_rate": auto_rate,
        "avg_confidence": round(
            sum(c["confidence_score"] for c in claims) / total, 3
        ) if total else 0,
        "daily_volume": [
            {"date": d, **counts} for d, counts in daily.items()
        ],
    }

def generate_surge_claim(index):
    """Generate a single synthetic approved claim for surge demo."""
    names = ["Amit S.", "Priya R.", "Ravi K.", "Deepa M.", "Suresh P.",
             "Ananya L.", "Karthik N.", "Pooja V.", "Rahul T.", "Sneha B."]
    hospitals = ["City Hospital", "District Hospital", "Apollo Clinic",
                 "ESI Hospital", "Civil Hospital", "KGH", "AIIMS OPD"]
    icd_pool = [
        {"code": "J06.9", "description": "Acute upper respiratory infection", "confidence": 0.92},
        {"code": "E11.9", "description": "Type 2 diabetes mellitus", "confidence": 0.91},
        {"code": "K37",   "description": "Unspecified appendicitis", "confidence": 0.88},
        {"code": "A91",   "description": "Dengue haemorrhagic fever", "confidence": 0.93},
        {"code": "M17.11","description": "Primary osteoarthritis, right knee", "confidence": 0.87},
    ]
    conf = round(random.uniform(0.82, 0.98), 2)
    now  = datetime.datetime.utcnow().isoformat() + "Z"
    return {
        "id": f"CLM-SURGE-{str(uuid.uuid4())[:8].upper()}",
        "patient_name": random.choice(names),
        "patient_id": f"PT-SURGE-{1000 + index}",
        "submitted_at": now,
        "status": "APPROVED",
        "confidence_score": conf,
        "raw_ocr": f"Auto-generated surge claim #{index}",
        "extracted_json": {"hospital": random.choice(hospitals), "total": random.randint(500, 15000)},
        "icd_codes": [random.choice(icd_pool)],
        "eligibility_result": {"eligible": True, "scheme": "Ayushman Bharat PM-JAY", "coverage_percent": 100},
        "flags": [],
        "audit_log": [{"timestamp": now, "stage": "DECISION", "note": "Auto-approved (surge)"}],
        "image_url": "/assets/mock_bill_clean.png",
    }

# ─────────────────────────────────────────────
# Pipeline simulator
# ─────────────────────────────────────────────
PIPELINE_STAGES = ["SUBMITTED", "OCR", "CODING", "ELIGIBILITY", "DECISION"]

def simulate_pipeline(filename, file_type):
    """Deterministically decide outcome based on filename to support demo flow."""
    messy_keywords = ["messy", "rural", "handwritten", "phc", "noisy"]
    is_messy = any(kw in filename.lower() for kw in messy_keywords)

    conf = round(random.uniform(0.44, 0.62), 2) if is_messy else round(random.uniform(0.84, 0.97), 2)
    now  = datetime.datetime.utcnow()
    claim_id = f"CLM-{now.strftime('%Y%m%d')}-{str(uuid.uuid4())[:6].upper()}"

    status = "FLAGGED" if (conf < 0.75 or is_messy) else "APPROVED"
    flags  = []
    if conf < 0.75:
        flags.append(f"OCR confidence below threshold ({conf} < 0.75)")
    if is_messy:
        flags.append("Handwritten document — OCR accuracy reduced")
        flags.append("ICD-10 top candidate confidence insufficient for auto-approval")

    stages_log = []
    for i, stage in enumerate(PIPELINE_STAGES):
        ts = (now + datetime.timedelta(seconds=i * 3)).isoformat() + "Z"
        note = "Processing complete"
        if stage == "OCR":
            note = f"OCR confidence {conf}" + (" — LOW" if conf < 0.75 else "")
        elif stage == "DECISION":
            note = "Auto-approved" if status == "APPROVED" else "Flagged for human review"
        stages_log.append({"timestamp": ts, "stage": stage, "note": note})

    icd_candidates = [
        {"code": "J06.9", "description": "Acute upper respiratory infection", "confidence": round(conf * 0.98, 2)},
        {"code": "R50.9", "description": "Fever, unspecified",               "confidence": round(conf * 0.91, 2)},
        {"code": "A09",   "description": "Infectious gastroenteritis",        "confidence": round(conf * 0.72, 2)},
    ]

    claim = {
        "id": claim_id,
        "patient_name": "Demo Patient",
        "patient_id": f"PT-DEMO-{random.randint(1000, 9999)}",
        "submitted_at": now.isoformat() + "Z",
        "status": status,
        "confidence_score": conf,
        "raw_ocr": f"[OCR output for {filename} — confidence {conf}]",
        "extracted_json": {
            "hospital": "Demo Hospital",
            "patient": "Demo Patient",
            "date": now.strftime("%Y-%m-%d"),
            "line_items": [
                {"description": "Consultation Fee", "amount": 500},
                {"description": "Diagnostic Test",  "amount": 800},
            ],
            "total": 1300,
            "currency": "INR",
        },
        "icd_codes": icd_candidates,
        "eligibility_result": {
            "eligible": True,
            "scheme": "Ayushman Bharat PM-JAY",
            "coverage_percent": 100 if status == "APPROVED" else 80,
        },
        "flags": flags,
        "audit_log": stages_log,
        "image_url": "/assets/mock_bill_messy.png" if is_messy else "/assets/mock_bill_clean.png",
    }
    return claim

# ─────────────────────────────────────────────
# HTTP Handler
# ─────────────────────────────────────────────
class MedClaimHandler(BaseHTTPRequestHandler):

    def log_message(self, fmt, *args):
        print(f"[{self.log_date_time_string()}] {fmt % args}")

    # ── helpers ──────────────────────────────
    def send_json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def send_error_json(self, message, status=400):
        self.send_json({"error": message}, status)

    def read_json_body(self):
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        raw = self.rfile.read(length)
        return json.loads(raw.decode("utf-8"))

    def serve_static(self, path):
        """Serve a file from BASE_DIR."""
        full = os.path.normpath(os.path.join(BASE_DIR, path.lstrip("/")))
        # Safety: don't serve outside BASE_DIR
        if not full.startswith(BASE_DIR):
            self.send_response(403); self.end_headers(); return
        if not os.path.isfile(full):
            self.send_response(404); self.end_headers(); return
        ext = os.path.splitext(full)[1].lower()
        mime = MIME_TYPES.get(ext, "application/octet-stream")
        with open(full, "rb") as f:
            data = f.read()
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(data)

    # ── OPTIONS preflight ────────────────────
    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    # ── GET ──────────────────────────────────
    def do_GET(self):
        p = self.path.split("?")[0]  # strip query string

        # Root → index.html
        if p == "/" or p == "":
            return self.serve_static("index.html")

        # API routes
        if p == "/api/auth/check-session":
            return self.send_json({
                "id": "USR-001",
                "email": "admin@medclaim.gov.in",
                "full_name": "Dr. Rajesh Varma",
                "role": "Senior Adjudicator"
            })

        if p == "/api/claims/review-queue":
            claims = load_claims()
            flagged = [c for c in claims if c["status"] == "FLAGGED"]
            return self.send_json({"claims": flagged, "count": len(flagged)})

        if p == "/api/dashboard/metrics":
            claims = load_claims()
            return self.send_json(compute_metrics(claims))


        # Static files
        return self.serve_static(p)

    # ── POST ─────────────────────────────────
    def do_POST(self):
        p = self.path.split("?")[0]

        # Auth routes
        if p == "/api/auth/login":
            body = self.read_json_body()
            email = body.get("email", "admin@medclaim.gov.in")
            role = "Senior Adjudicator"
            name = "Dr. Rajesh Varma"
            if "caseworker" in email:
                role = "HITL Caseworker"
                name = "Ananya Roy"
            elif "hospital" in email:
                role = "Hospital Billing Clerk"
                name = "Suresh Mehta"
            
            return self.send_json({
                "access_token": f"mock_token_{uuid.uuid4().hex[:12]}",
                "token_type": "bearer",
                "user": {
                    "id": f"USR-{random.randint(100,999)}",
                    "email": email,
                    "full_name": name,
                    "role": role
                }
            })

        if p == "/api/auth/register":
            body = self.read_json_body()
            return self.send_json({
                "access_token": f"mock_token_{uuid.uuid4().hex[:12]}",
                "token_type": "bearer",
                "user": {
                    "id": f"USR-{random.randint(100,999)}",
                    "email": body.get("email", "user@medclaim.gov.in"),
                    "full_name": body.get("full_name", "Registered User"),
                    "role": body.get("role", "HITL Caseworker")
                }
            })

        if p == "/api/auth/logout":
            return self.send_json({"success": True, "message": "Logged out successfully"})

        # Approve a claim  POST /api/claims/<id>/approve

        m = re.match(r"^/api/claims/([^/]+)/approve$", p)
        if m:
            claim_id = m.group(1)
            claims = load_claims()
            updated = False
            for c in claims:
                if c["id"] == claim_id and c["status"] == "FLAGGED":
                    c["status"] = "APPROVED"
                    c["flags"]  = []
                    ts = datetime.datetime.utcnow().isoformat() + "Z"
                    c.setdefault("audit_log", []).append({
                        "timestamp": ts,
                        "stage": "HITL_REVIEW",
                        "note": "Manually approved by caseworker",
                    })
                    updated = True
                    break
            if not updated:
                return self.send_error_json("Claim not found or not in FLAGGED state", 404)
            save_claims(claims)
            return self.send_json({"success": True, "claim_id": claim_id})

        # Submit new claim  POST /api/claims/submit
        if p == "/api/claims/submit":
            body = self.read_json_body()
            filename  = body.get("filename", "unknown.png")
            file_type = body.get("file_type", "image/png")
            # file_data (base64) not used server-side in mock — just simulate
            claim = simulate_pipeline(filename, file_type)
            claims = load_claims()
            claims.insert(0, claim)   # newest first
            save_claims(claims)
            return self.send_json({"success": True, "claim": claim})

        # Surge mode  POST /api/claims/surge
        if p == "/api/claims/surge":
            body  = self.read_json_body()
            count = min(int(body.get("count", 50)), 100)
            claims = load_claims()
            new_claims = [generate_surge_claim(i) for i in range(count)]
            claims = new_claims + claims
            save_claims(claims)
            metrics = compute_metrics(claims)
            return self.send_json({
                "success": True,
                "injected": count,
                "metrics": metrics,
                "new_claims": new_claims,
            })

        self.send_error_json("Not found", 404)


# ─────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    server = HTTPServer(("localhost", PORT), MedClaimHandler)
    print(f"==============================================")
    print(f"  MED-CLAIM Mock Server -> http://localhost:{PORT}")
    print(f"==============================================")
    print(f"  Ctrl+C to stop\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.")

