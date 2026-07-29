# MED-CLAIM — Demo Script
**90-Second Live Judging Demo · Rehearse twice with a stopwatch**

---

## Pre-Demo Checklist (5 minutes before judging)

- [ ] Server running: `python server.py` in terminal — confirm green dot in sidebar
- [ ] Browser open to `http://localhost:8080` in full screen, sidebar visible
- [ ] `mock_bill_clean.png` and `mock_bill_messy.png` available in `assets/` folder
- [ ] HITL queue has at least 1 flagged claim (check badge on sidebar)
- [ ] Dashboard loaded — charts populated, auto-adjudication rate visible
- [ ] Backup demo video ready to play if network/server fails
- [ ] Terminal hidden (Alt+Tab plan if needed)

---

## The Script

### Beat 1 — Hook (0:00 – 0:15) · 15 seconds

**Say:** *"A single coding error on a hospital bill can push a rural family into medical debt they can't repay. That's what MED-CLAIM solves."*

Point to the dashboard on Screen 3 (if pre-loaded). Mention: *"We process claims end-to-end — OCR, ICD-10 coding, eligibility check — automatically, in under 6 seconds."*

Switch to **Submit Claim**.

---

### Beat 2 — Clean Bill Auto-Approval (0:15 – 0:35) · 20 seconds

1. Click **"Clean Bill (Auto-Approve)"** demo button.
2. Point at each stage lighting up green as it passes: *"Submitted → OCR → Clinical Coding → Eligibility → Decision."*
3. Result card appears: **Auto-Approved ✅**
4. **Say:** *"9 out of 10 clean claims like this need zero human time."*

---

### Beat 3 — Handwritten Bill HITL Escalation (0:35 – 0:55) · 20 seconds

1. Click **"Messy Handwritten (Flag for HITL)"** demo button.
2. Watch stages — OCR stage shows low confidence, DECISION shows amber ⚑.
3. **Say:** *"This rural clinic bill had ambiguous handwriting and OCR confidence of 55%. The system flagged it rather than guess wrong."*
4. Click **HITL Review Queue** in sidebar.

---

### Beat 4 — Caseworker Review (0:55 – 1:10) · 15 seconds

1. The flagged claim appears in the table. Click to **expand it**.
2. Show image on left, extracted JSON on right. Point to the flag reasons.
3. **Say:** *"A caseworker sees the original document and the extracted data side-by-side. One click to approve with a full audit trail."*
4. Click **✓ Approve**. Row animates out. Badge drops.

---

### Beat 5 — Surge Mode (1:10 – 1:25) · 15 seconds

1. Switch to **Observability Dashboard**.
2. Click **⚡ SURGE MODE**.
3. Progress bar climbs, metric numbers tick upward live. Charts update.
4. **Say:** *"During a regional dengue outbreak, we simulated 50 claims in one batch — auto-adjudication held above 90%."*

---

### Beat 6 — Close (1:25 – 1:30) · 5 seconds

Point at the big green **Auto-Adjudication Rate** number.

**Say:** *"90%+ of claims processed without a caseworker. That's time returned to patients, and errors that never become debt."*

---

## Backup Plan (if server is down)

1. Immediately say: *"Let me show you the recorded demo"* — don't fumble or apologize.
2. Play the backup `.mp4` video (record this in advance, full successful run).
3. Keep talking over the video — don't let silence build.
4. Judges at hackathons understand infrastructure issues; composure matters more than the live demo.

---

## If a Judge Interrupts to Ask a Question

Stop the demo gracefully. Answer clearly and directly (max 2 sentences). Resume from the nearest logical beat — don't backtrack.

---

*Record the backup video on the final working build. Aim for 2 minutes, so you have 30 seconds of buffer.*
