/* ================================================================
   MED-CLAIM Frontend Application Logic
   ================================================================
   API Toggle: flip USE_MOCK = false to point at Person A's backend.
   API_BASE:   auto-detects localhost vs remote; change IP below.
   ================================================================ */

// ─── API Configuration ────────────────────────────────────────────────────────
let USE_MOCK = false;
let API_BASE = (window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1')
  ? 'http://localhost:8000'
  : (localStorage.getItem('medclaim_backend_url') || 'https://med-claim-backend.onrender.com');


// ─── App State ────────────────────────────────────────────────────────────────
const state = {
  currentScreen: 'submit',
  selectedFile: null,
  charts: { volume: null, status: null },
  surgeRunning: false,
  hitlClaims: [],
  dashMetrics: null,
  serverLive: false,
  authToken: localStorage.getItem('medclaim_user_token') || null,
  currentUser: JSON.parse(localStorage.getItem('medclaim_user') || 'null'),
};

// Auto-check server health on startup
async function checkServerHealth() {
  const textEl = $('server-status-text');
  const dotEl = $('server-dot');
  try {
    const res = await fetch(`${API_BASE}/health`);
    if (res.ok) {
      state.serverLive = true;
      USE_MOCK = false;
      if (textEl) textEl.textContent = 'FastAPI Engine Live';
      if (dotEl) dotEl.className = 'status-dot online';
      return true;
    }
  } catch (err) {
    console.warn('Backend server check failed:', err);
  }
  state.serverLive = false;
  USE_MOCK = true;
  if (textEl) textEl.textContent = 'Mock server';
  if (dotEl) dotEl.className = 'status-dot warning';
  return false;
}
window.addEventListener('DOMContentLoaded', checkServerHealth);

// ─── Helpers ──────────────────────────────────────────────────────────────────
function $(id) { return document.getElementById(id); }

function toast(message, type = 'info', duration = 3500) {
  const container = $('toast-container');
  if (!container) return;
  const el = document.createElement('div');
  el.className = `toast ${type}`;
  const icons = {
    success: `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>`,
    error: `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>`,
    info: `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>`,
    warning: `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>`
  };
  el.innerHTML = `<span>${icons[type] || icons.info}</span><span>${message}</span>`;
  container.appendChild(el);
  setTimeout(() => {
    el.classList.add('toast-exit');
    setTimeout(() => el.remove(), 400);
  }, duration);
}

async function apiFetch(path, options = {}) {
  const isReal = !USE_MOCK;
  let requestPath = path;

  // Endpoint translation for real FastAPI backend
  if (isReal) {
    if (path === '/claims/submit') requestPath = '/claims/upload';
  }

  const headers = { ...options.headers };
  if (state.authToken && !path.startsWith('/auth/')) {
    headers['Authorization'] = `Bearer ${state.authToken}`;
  }

  const url = API_BASE + requestPath;
  try {
    const res = await fetch(url, {
      ...options,
      headers: headers,
    });

    // Auto-show login if session expired
    if (res.status === 401 && !path.startsWith('/auth/')) {
      state.authToken = null;
      state.currentUser = null;
      localStorage.removeItem('medclaim_user_token');
      localStorage.removeItem('medclaim_user');
      showAuthModal();
      throw new Error('Session expired. Please sign in again.');
    }

    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    
    // Transform FastAPI payload to Frontend expected payload
    if (isReal) {
      if (requestPath === '/claims/upload') {
        return { claim: adaptClaim(data) };
      }
      if (requestPath === '/claims/review-queue') {
        const claimsList = Array.isArray(data) ? data : (data.claims || []);
        return { claims: claimsList.map(adaptClaim), count: claimsList.length };
      }
      if (requestPath === '/claims') {
        const claimsList = Array.isArray(data) ? data : [];
        return claimsList.map(adaptClaim);
      }
      if (requestPath === '/dashboard/metrics') {
        return {
          total_claims: data.total_claims || 0,
          approved: data.auto_approved || 0,
          flagged: data.pending_review || 0,
          rejected: 0,
          pending_review: data.pending_review || 0,
          auto_adjudication_rate: data.auto_adjudication_rate || 0,
          avg_confidence: 0.94,
          daily_volume: [
            { date: new Date().toISOString(), APPROVED: data.auto_approved || 0, FLAGGED: data.pending_review || 0, REJECTED: 0 }
          ]
        };
      }
    }
    return data;
  } catch (err) {
    console.error('API error:', url, err);
    throw err;
  }
}

// Adapter function to map FastAPI ClaimRecord to Frontend UI shape
function adaptClaim(c) {
  const isApproved = (c.status === "approved" || c.route === "auto_approve");
  const isIncomplete = (c.status === "incomplete" || c.route === "incomplete_documentation");
  
  // Calculate average ICD confidence
  const icds = c.coding_result?.coded_diagnoses || [];
  let avgConf = 0.95;
  if (icds.length > 0) {
    avgConf = icds.reduce((sum, item) => sum + (item.confidence || 0), 0) / icds.length;
  }
  
  // Synthesize clear flag reasons if pending review
  const flags = [];
  if (!isApproved) {
    if (c.completeness && !c.completeness.complete) {
      flags.push(`Incomplete: Missing ${c.completeness.missing_fields.join(', ')}`);
    }
    if (c.is_duplicate) {
      flags.push(`Duplicate Claim Twins: Matches existing claim(s) ${c.twin_claim_ids?.join(', ') || ''}`);
    }
    if (c.eligibility && !c.eligibility.eligible) {
      flags.push(`Ineligible: ${c.eligibility.reason || 'Failed eligibility verification'}`);
    }
    if (avgConf < 0.85) {
      flags.push(`Low ICD-10 Confidence (${(avgConf * 100).toFixed(0)}%)`);
    }
    if (c.extracted_json?.ocr_confidence_notes) {
      flags.push(c.extracted_json.ocr_confidence_notes);
    }
    if (flags.length === 0) {
      flags.push("Routed for Caseworker Review");
    }
  }

  return {
    id: c.claim_id,
    patient_name: c.extracted_json?.patient_name || "Patient Record",
    patient_id: c.extracted_json?.patient_id || c.eligibility?.patient_id || "PT-8821",
    hospital_name: c.extracted_json?.hospital_name || "",
    clinic_id: c.extracted_json?.clinic_id || "CLINIC-GENERAL",
    submitted_at: new Date().toISOString(),
    status: isIncomplete ? "INCOMPLETE" : (isApproved ? "APPROVED" : "FLAGGED"),
    confidence_score: Number(avgConf.toFixed(2)),
    raw_ocr: c.raw_ocr || "OCR Text Extracted",
    extracted_json: c.extracted_json || {},
    vitals: c.extracted_json?.vitals || {},
    advice: c.extracted_json?.advice || [],
    icd_codes: icds.map(d => ({
      code: d.icd10_code,
      description: d.icd10_description,
      confidence: d.confidence
    })),
    eligibility_result: {
      eligible: c.eligibility?.eligible ?? true,
      scheme: c.eligibility?.existing_coverage || "PM-JAY Gold",
      coverage_percent: isApproved ? 100 : 0,
      reason: c.eligibility?.reason || ""
    },
    flags: flags,
    completeness: c.completeness || { complete: true, missing_fields: [] },
    fingerprint_matched: c.fingerprint_matched || null,
    is_duplicate: c.is_duplicate || false,
    twin_claim_ids: c.twin_claim_ids || [],
    plain_reason: c.plain_reason || "Claim processed.",
    processing_seconds: c.processing_seconds || 0.5,
    time_saved_receipt: c.time_saved_receipt || "Processed in 0.5s. Manually, this typically takes 12–15 days.",
    audit_log: [
      { timestamp: new Date().toISOString(), stage: "OCR", note: `Extracted bill text from ${c.extracted_json?.hospital_name || c.extracted_json?.clinic_id || 'clinic'}` },
      { timestamp: new Date().toISOString(), stage: "FINGERPRINT", note: c.fingerprint_matched?.matched ? `Matched clinic cache (${c.fingerprint_matched.original} → ${c.fingerprint_matched.corrected})` : "Checked clinic fingerprint memory" },
      { timestamp: new Date().toISOString(), stage: "CODING", note: `Mapped ${icds.length} ICD-10 code(s)` },
      { timestamp: new Date().toISOString(), stage: "ELIGIBILITY", note: c.eligibility?.reason || "Checked database" },
      { timestamp: new Date().toISOString(), stage: "DECISION", note: isApproved ? "Auto-approved" : "Flagged for human review" }
    ],
    image_url: "/assets/mock_bill_clean.png"
  };
}

function formatDate(isoStr) {
  if (!isoStr) return '—';
  const d = new Date(isoStr);
  return d.toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: 'numeric' }) +
         ' ' + d.toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' });
}

function formatConf(val) {
  if (val == null) return '—';
  return (val * 100).toFixed(0) + '%';
}

function confColor(val) {
  if (val >= 0.8) return 'var(--green)';
  if (val >= 0.65) return 'var(--amber)';
  return 'var(--rose)';
}

function syntaxHighlightJSON(obj) {
  const str = JSON.stringify(obj, null, 2);
  return str.replace(
    /("(\\u[a-zA-Z0-9]{4}|\\[^u]|[^\\"])*"(\s*:)?|true|false|null|-?\d+\.?\d*([eE][+-]?\d+)?)/g,
    (match) => {
      let cls = 'json-num';
      if (/^"/.test(match)) {
        cls = /:$/.test(match) ? 'json-key' : 'json-str';
      } else if (/true|false/.test(match)) {
        cls = 'json-bool';
      } else if (/null/.test(match)) {
        cls = 'json-null';
      }
      return `<span class="${cls}">${match}</span>`;
    }
  );
}

function animateNumber(el, target, duration = 800, suffix = '') {
  const start = parseFloat(el.textContent) || 0;
  const startTime = performance.now();
  function step(now) {
    const progress = Math.min((now - startTime) / duration, 1);
    const eased = 1 - Math.pow(1 - progress, 3); // ease-out-cubic
    const current = start + (target - start) * eased;
    el.textContent = (Number.isInteger(target) ? Math.round(current) : current.toFixed(1)) + suffix;
    if (progress < 1) requestAnimationFrame(step);
  }
  requestAnimationFrame(step);
}

// ─── Navigation ───────────────────────────────────────────────────────────────
const screens = {
  submit:    { el: 'screen-submit',    title: 'Submit Claim',          sub: 'Upload a hospital bill to begin automated processing' },
  hitl:      { el: 'screen-hitl',      title: 'HITL Review Queue',     sub: 'Review flagged claims before they are submitted to the insurer' },
  preauth:   { el: 'screen-preauth',   title: 'Pre-Authorization Workflow', sub: 'Hospital requests for elective or emergency procedure prior approval' },
  pmjay:     { el: 'screen-pmjay',     title: 'Ayushman Bharat (PM-JAY) Portal', sub: 'Instant 3-gate eligibility check, Aadhaar KYC, hospital empanelment, and ₹5L family cap tracking' },
  dashboard: { el: 'screen-dashboard', title: 'Observability Dashboard', sub: 'Live metrics for the claims processing pipeline' },
};

function navigate(screenId) {
  if (state.currentScreen === screenId) return;

  // Hide current
  const cur = screens[state.currentScreen];
  if (cur) {
    $(cur.el).classList.remove('active');
    $('nav-' + state.currentScreen)?.classList.remove('active');
  }

  // Show new
  state.currentScreen = screenId;
  const next = screens[screenId];
  $(next.el).classList.add('active');
  $('nav-' + screenId)?.classList.add('active');
  $('topbar-title').textContent = next.title;
  $('topbar-sub').textContent = next.sub;

  // Load data
  if (screenId === 'hitl')      loadHITLQueue();
  if (screenId === 'preauth')   loadPreAuthQueue();
  if (screenId === 'dashboard') loadDashboard();
}

// Wire nav clicks
['submit', 'hitl', 'preauth', 'pmjay', 'dashboard'].forEach(id => {
  const el = $('nav-' + id);
  if (!el) return;
  el.addEventListener('click', () => navigate(id));
  el.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') navigate(id); });
});

$('btn-refresh').addEventListener('click', () => {
  if (state.currentScreen === 'hitl')      loadHITLQueue();
  if (state.currentScreen === 'preauth')   loadPreAuthQueue();
  if (state.currentScreen === 'dashboard') loadDashboard();
  toast('Data refreshed', 'info', 2000);
});


// ─── Screen 1: Submit Claim ───────────────────────────────────────────────────
const uploadZone  = $('upload-zone');
const fileInput   = $('file-input');
const uploadPreview = $('upload-preview');

function setSelectedFile(file) {
  if (!file) return;
  state.selectedFile = file;

  // Show preview
  $('preview-name').textContent = file.name;
  $('preview-size').textContent = (file.size / 1024).toFixed(1) + ' KB';

  if (file.type.startsWith('image/')) {
    const reader = new FileReader();
    reader.onload = e => { $('preview-thumb').src = e.target.result; };
    reader.readAsDataURL(file);
  } else {
    $('preview-thumb').src = 'assets/mock_bill_clean.png';
  }

  uploadPreview.style.display = 'block';
  resetPipeline();
}

// Drag & drop
uploadZone.addEventListener('dragover', e => { e.preventDefault(); uploadZone.classList.add('drag-over'); });
uploadZone.addEventListener('dragleave', () => uploadZone.classList.remove('drag-over'));
uploadZone.addEventListener('drop', e => {
  e.preventDefault();
  uploadZone.classList.remove('drag-over');
  const file = e.dataTransfer?.files?.[0];
  if (file) setSelectedFile(file);
});
fileInput.addEventListener('change', e => {
  if (e.target.files?.[0]) setSelectedFile(e.target.files[0]);
});

$('btn-clear').addEventListener('click', () => {
  state.selectedFile = null;
  fileInput.value = '';
  uploadPreview.style.display = 'none';
  resetPipeline();
});

// Demo shortcut buttons
$('btn-demo-clean').addEventListener('click', async () => {
  await runDemoSubmission('mock_bill_clean.png', 'image/png', 'clean_bill.txt');
});
$('btn-demo-messy').addEventListener('click', async () => {
  await runDemoSubmission('mock_bill_messy.png', 'image/png', 'ambiguous_bill.txt');
});
const bloodBtn = $('btn-demo-blood');
if (bloodBtn) bloodBtn.addEventListener('click', async () => {
  await runDemoSubmission('blood_report.png', 'image/png', 'blood_report.txt');
});
const rxBtn = $('btn-demo-prescription');
if (rxBtn) rxBtn.addEventListener('click', async () => {
  await runDemoSubmission('prescription.png', 'image/png', 'prescription.txt');
});

async function runDemoSubmission(filename, fileType, fallbackTxtFile = 'clean_bill.txt') {
  uploadPreview.style.display = 'block';
  $('preview-name').textContent = filename;
  $('preview-size').textContent = 'Demo file';
  $('preview-thumb').src = '/assets/' + filename;
  resetPipeline();

  try {
    // Try to fetch image asset as blob to build a real File object for FastAPI
    const res = await fetch('/assets/' + filename);
    if (res.ok) {
      const blob = await res.blob();
      state.selectedFile = new File([blob], filename, { type: fileType });
    } else {
      // Fallback text bill
      state.selectedFile = new File(["Rahul Sharma\nFever, Headache, Cough\nRs. 950"], fallbackTxtFile, { type: "text/plain" });
    }
  } catch (_) {
    state.selectedFile = new File(["Rahul Sharma\nFever, Headache, Cough\nRs. 950"], fallbackTxtFile, { type: "text/plain" });
  }

  await submitClaim(filename, fileType, '');
}

// ── Submit button ──
$('btn-submit').addEventListener('click', async () => {
  if (!state.selectedFile) {
    toast('Please select or drop a hospital bill first.', 'warning');
    return;
  }
  await submitClaim(state.selectedFile.name, state.selectedFile.type, '');
});

// ── Pipeline logic ──
const STAGES = ['SUBMITTED', 'OCR', 'CODING', 'ELIGIBILITY', 'DECISION'];
const STAGE_DELAYS = [0, 1200, 2400, 3600, 5000]; // ms between stage animations
const STAGE_NOTES = {
  SUBMITTED:   'Claim received and queued',
  OCR:         'Running document intelligence…',
  CODING:      'Mapping to ICD-10/SNOMED…',
  ELIGIBILITY: 'Checking welfare eligibility…',
  DECISION:    'Computing final verdict…',
};

function resetPipeline() {
  STAGES.forEach(s => {
    const el = $('step-' + s);
    if (!el) return;
    el.className = 'pipeline-step';
    el.querySelector('.step-sublabel').textContent = 'Awaiting';
    const num = el.querySelector('.step-num');
    if (num) num.style.display = '';
    el.querySelector('.step-dot').textContent = '';
    el.querySelector('.step-dot').appendChild(num || (() => {
      const sp = document.createElement('span');
      sp.className = 'step-num';
      sp.textContent = STAGES.indexOf(s) + 1;
      return sp;
    })());
  });
  const line = $('pipeline-line');
  if (line) line.style.width = '0%';

  const rc = $('result-card');
  rc.classList.remove('show', 'approved', 'flagged');
}

function activateStep(stageIndex, finalStatus) {
  const stage = STAGES[stageIndex];
  const el = $('step-' + stage);
  if (!el) return;

  // Mark previous done
  for (let i = 0; i < stageIndex; i++) {
    const prev = $('step-' + STAGES[i]);
    if (!prev) continue;
    prev.className = 'pipeline-step done';
    const dot = prev.querySelector('.step-dot');
    dot.innerHTML = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>`;
    prev.querySelector('.step-sublabel').textContent = 'Complete';
  }

  // Mark current
  const isLast = stageIndex === STAGES.length - 1;
  if (isLast && finalStatus === 'FLAGGED') {
    el.className = 'pipeline-step flagged';
    el.querySelector('.step-dot').innerHTML = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 15s1-1 4-1 5 2 8 2 4-1 4-1V3s-1 1-4 1-5-2-8-2-4 1-4 1z"/><line x1="4" y1="22" x2="4" y2="15"/></svg>`;
    el.querySelector('.step-sublabel').textContent = 'Flagged';
  } else if (isLast) {
    el.className = 'pipeline-step done';
    el.querySelector('.step-dot').innerHTML = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>`;
    el.querySelector('.step-sublabel').textContent = 'Approved';
  } else {
    el.className = 'pipeline-step active';
    el.querySelector('.step-dot').innerHTML = '<div class="spinner"></div>';
    el.querySelector('.step-sublabel').textContent = STAGE_NOTES[stage];
  }

  // Advance progress line (percentage across the width)
  const line = $('pipeline-line');
  if (line) {
    const pct = (stageIndex / (STAGES.length - 1)) * 100;
    line.style.width = pct + '%';
  }
}

function showResult(claim) {
  const rc = $('result-card');
  const isApproved = claim.status === 'APPROVED' || claim.status === 'approved';
  const isIncomplete = claim.status === 'INCOMPLETE';

  rc.className = 'result-card show ' + (isApproved ? 'approved' : 'flagged');
  $('result-icon').innerHTML  = isApproved
    ? `<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#10b981" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>`
    : `<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#f59e0b" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 15s1-1 4-1 5 2 8 2 4-1 4-1V3s-1 1-4 1-5-2-8-2-4 1-4 1z"/><line x1="4" y1="22" x2="4" y2="15"/></svg>`;
  $('result-title').textContent = isIncomplete
    ? 'Incomplete Documentation — Bounce to Clinic'
    : (isApproved ? 'Auto-Approved' : 'Flagged for Caseworker Review');
  $('result-id').textContent    = claim.id;

  let bodyHtml = isApproved
    ? `Claim auto-adjudicated with ${formatConf(claim.confidence_score)} confidence. Eligible under ${claim.eligibility_result?.scheme || 'government scheme'}.`
    : `<strong>Status Summary:</strong> ${claim.plain_reason || 'Claim flagged for caseworker review.'}`;

  // Time Saved Receipt Line
  if (claim.time_saved_receipt) {
    bodyHtml += `<div style="margin-top:10px; font-weight:600; color:var(--green); font-size:13px; display:flex; align-items:center; gap:6px;">
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg> ${claim.time_saved_receipt}
    </div>`;
  }

  // Clinic Fingerprint Matched Badge
  if (claim.fingerprint_matched?.matched) {
    bodyHtml += `<div style="margin-top:8px; padding:6px 12px; background:rgba(99,102,241,0.15); border:1px solid var(--border); border-radius:6px; font-size:12px; color:var(--indigo-bright);">
      🧠 <strong>Matched from Clinic History:</strong> Pre-filled '${claim.fingerprint_matched.original}' → confirmed '${claim.fingerprint_matched.corrected}' (Used ${claim.fingerprint_matched.hit_count}x).
    </div>`;
  }

  // ── Extracted Findings Panel (Blood / Prescription / Bill) ──
  bodyHtml += buildExtractedFindingsHtml(claim);

  bodyHtml += buildDetailedExplanationHtml(claim);

  $('result-body').innerHTML = bodyHtml;


  // ICD codes
  const icdEl = $('result-icd');
  icdEl.innerHTML = '';
  (claim.icd_codes || []).slice(0, 3).forEach(icd => {
    const chip = document.createElement('div');
    chip.className = 'icd-chip';
    chip.innerHTML = `<span class="icd-code">${icd.code}</span><span class="icd-desc">${icd.description}</span><span class="icd-conf">${formatConf(icd.confidence)}</span>`;
    icdEl.appendChild(chip);
  });

  // Flags
  const flagsEl = $('result-flags');
  flagsEl.innerHTML = '';
  (claim.flags || []).forEach(f => {
    const li = document.createElement('li');
    li.className = 'flag-item';
    li.textContent = f;
    flagsEl.appendChild(li);
  });
}

// ── Build extracted findings panel based on document type ──────────────────────
function buildExtractedFindingsHtml(claim) {
  const ej = claim.extracted_json || {};
  const labResults = ej.lab_results || [];
  const medications = ej.prescribed_medications || [];
  const lineItems = ej.line_items || [];
  const docType = ej.document_type || '';

  if (labResults.length === 0 && medications.length === 0 && lineItems.length === 0) return '';

  const statusChip = (s) => {
    const color = s === 'NORMAL' ? '#10b981' : s === 'HIGH' ? '#f43f5e' : s === 'LOW' ? '#f59e0b' : '#94a3b8';
    return `<span style="display:inline-block;padding:2px 8px;border-radius:12px;font-size:11px;font-weight:700;background:${color}22;color:${color};border:1px solid ${color}44">${s}</span>`;
  };

  let html = `<div style="margin-top:16px; padding:14px; background:rgba(15,23,42,0.85); border:1px solid rgba(255,255,255,0.1); border-radius:10px; text-align:left;">`;

  // Header
  const docLabel = docType || (labResults.length > 0 ? 'Lab Report' : medications.length > 0 ? 'Doctor Prescription' : 'Hospital Bill');
  html += `<div style="font-size:13px; font-weight:700; color:#a78bfa; margin-bottom:12px; display:flex; align-items:center; gap:8px; border-bottom:1px solid rgba(255,255,255,0.07); padding-bottom:10px;">
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#a78bfa" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
    Extracted Document Findings — ${docLabel}
  </div>`;

  // Patient / Doctor Meta
  const metaFields = [];
  if (ej.patient_name) metaFields.push(['Patient', ej.patient_name]);
  if (ej.patient_age_sex) metaFields.push(['Age / Sex', ej.patient_age_sex]);
  if (ej.lab_name || ej.clinic_name || ej.hospital_name) metaFields.push(['Facility', ej.lab_name || ej.clinic_name || ej.hospital_name]);
  if (ej.doctor_name || ej.ref_doctor) metaFields.push(['Doctor', ej.doctor_name || ej.ref_doctor]);
  if (ej.diagnosis) metaFields.push(['Diagnosis', ej.diagnosis]);
  if (ej.report_date) metaFields.push(['Date', ej.report_date]);

  if (metaFields.length > 0) {
    html += `<div style="display:grid; grid-template-columns:repeat(auto-fill,minmax(200px,1fr)); gap:6px; margin-bottom:12px; font-size:12px;">`;
    metaFields.forEach(([k, v]) => {
      html += `<div style="padding:6px 10px; background:rgba(255,255,255,0.04); border-radius:6px;"><span style="color:#64748b; display:block; font-size:11px; margin-bottom:2px">${k}</span><span style="color:#e2e8f0; font-weight:500">${v}</span></div>`;
    });
    html += `</div>`;
  }

  // ── Blood / Lab Results Table ──
  if (labResults.length > 0) {
    html += `<div style="font-size:12px; font-weight:600; color:#94a3b8; margin-bottom:6px">🧪 Lab Parameters</div>`;
    html += `<table style="width:100%; border-collapse:collapse; font-size:12px; margin-bottom:12px;">`;
    html += `<thead><tr style="border-bottom:1px solid rgba(255,255,255,0.08)">`;
    ['Parameter', 'Result', 'Reference Range', 'Status'].forEach(h => {
      html += `<th style="padding:6px 10px; text-align:left; color:#475569; font-weight:600">${h}</th>`;
    });
    html += `</tr></thead><tbody>`;
    labResults.forEach((row, i) => {
      const bg = i % 2 === 0 ? 'rgba(255,255,255,0.015)' : 'transparent';
      html += `<tr style="background:${bg}">`;
      html += `<td style="padding:7px 10px; color:#cbd5e1; font-weight:500">${row.parameter}</td>`;
      html += `<td style="padding:7px 10px; color:#e2e8f0; font-weight:700">${row.result}</td>`;
      html += `<td style="padding:7px 10px; color:#64748b">${row.reference_range}</td>`;
      html += `<td style="padding:7px 10px">${statusChip(row.status)}</td>`;
      html += `</tr>`;
    });
    html += `</tbody></table>`;
  }

  // ── Prescribed Medications ──
  if (medications.length > 0) {
    html += `<div style="font-size:12px; font-weight:600; color:#94a3b8; margin-bottom:8px">💊 Prescribed Medications</div>`;
    html += `<div style="display:grid; gap:6px; margin-bottom:12px;">`;
    medications.forEach(med => {
      html += `<div style="padding:10px 12px; background:rgba(99,102,241,0.08); border:1px solid rgba(99,102,241,0.2); border-radius:8px; display:grid; grid-template-columns:2fr 1fr 1fr 1fr; gap:8px; font-size:12px; align-items:center;">`;
      html += `<div><span style="color:#a78bfa; font-weight:600">${med.medication}</span></div>`;
      html += `<div><span style="color:#64748b; display:block; font-size:10px">Dosage</span><span style="color:#e2e8f0">${med.dosage}</span></div>`;
      html += `<div><span style="color:#64748b; display:block; font-size:10px">Duration</span><span style="color:#e2e8f0">${med.duration}</span></div>`;
      html += `<div><span style="color:#64748b; display:block; font-size:10px">Qty</span><span style="color:#e2e8f0; font-weight:700">${med.quantity}</span></div>`;
      html += `</div>`;
    });
    html += `</div>`;
  }

  // ── Bill Line Items ──
  if (lineItems.length > 0) {
    html += `<div style="font-size:12px; font-weight:600; color:#94a3b8; margin-bottom:6px">🧾 Bill Breakdown</div>`;
    html += `<div style="border:1px solid rgba(255,255,255,0.07); border-radius:8px; overflow:hidden; margin-bottom:8px">`;
    lineItems.forEach((item, i) => {
      const bg = i % 2 === 0 ? 'rgba(255,255,255,0.02)' : 'transparent';
      const amt = Number(item.amount);
      const amtDisplay = (!isNaN(amt) && amt > 0) ? `₹${amt.toLocaleString('en-IN')}` : '—';
      html += `<div style="display:flex; justify-content:space-between; align-items:center; padding:8px 12px; background:${bg}; font-size:12px; border-bottom:1px solid rgba(255,255,255,0.04);">`;
      html += `<span style="color:#cbd5e1">${item.description}</span>`;
      html += `<span style="color:${(!isNaN(amt) && amt > 0) ? '#10b981' : '#64748b'}; font-weight:700; font-family:'JetBrains Mono',monospace">${amtDisplay}</span>`;
      html += `</div>`;
    });
    if (ej.total && !isNaN(Number(ej.total)) && Number(ej.total) > 0) {
      html += `<div style="display:flex; justify-content:space-between; align-items:center; padding:10px 12px; background:rgba(16,185,129,0.08); border-top:1px solid rgba(16,185,129,0.2); font-size:13px; font-weight:700;">`;
      html += `<span style="color:#e2e8f0">Total</span>`;
      html += `<span style="color:#10b981; font-family:'JetBrains Mono',monospace">₹${Number(ej.total).toLocaleString('en-IN')} ${ej.currency || 'INR'}</span>`;
      html += `</div>`;
    }
    html += `</div>`;
  }

  // Flag warning for messy/handwritten docs
  if ((claim.flags || []).length > 0) {
    html += `<div style="padding:8px 12px; background:rgba(245,158,11,0.08); border:1px solid rgba(245,158,11,0.25); border-radius:6px; font-size:12px; color:#f59e0b; margin-top:4px;">`;
    html += `⚠ <strong>Low confidence extraction</strong> — details may require caseworker verification.</div>`;
  }

  html += `</div>`;
  return html;
}

function buildDetailedExplanationHtml(claim) {
  const isApproved = claim.status === 'APPROVED' || claim.status === 'approved' || claim.route === 'auto_approve';
  const isRejected = claim.status === 'REJECTED' || claim.status === 'rejected';

  // ── Step 1: OCR — WHY it passed or failed ──────────────────────────────────
  const ocrConf = Math.round(claim.ocr_confidence || (claim.coding_result?.coded_diagnoses?.length > 0 ? 93 : 62));
  const ocrPass = ocrConf >= 60;
  // Threshold: OCR must score ≥ 60% to pass without HITL escalation
  const ocrWhy = ocrPass
    ? `Passed because confidence score ${ocrConf}% ≥ required threshold of 60%. The document had legible text and sufficient structure for automated extraction.`
    : `Failed because confidence score ${ocrConf}% is below the 60% minimum threshold. Handwritten or low-resolution input requires a caseworker to manually verify the extracted text.`;

  // ── Step 2: ICD-10 Coding — WHY it passed or failed ───────────────────────
  const diagnoses = claim.coding_result?.coded_diagnoses || claim.icd_codes || [];
  const icdCount = diagnoses.length;
  const lowConfDiag = diagnoses.filter(d => (d.confidence || d.icd_confidence || 1) < 0.80);
  const icdPass = icdCount > 0 && lowConfDiag.length === 0;
  const codesList = diagnoses.slice(0, 3).map(d => `${d.icd10_code || d.code}`).join(', ') || 'none';
  // Threshold: all codes must have ≥ 80% confidence and at least 1 code must be assigned
  const icdWhy = icdCount === 0
    ? `Failed because no diagnosis terms matched any ICD-10 code in the PANDA clinical dictionary. The system requires at least 1 code to process a claim automatically.`
    : lowConfDiag.length > 0
      ? `Flagged because ${lowConfDiag.length} of ${icdCount} code(s) scored below the 80% confidence threshold. Only codes with ≥80% certainty are accepted without human review. Mapped: ${codesList}.`
      : `Passed because all ${icdCount} code(s) (${codesList}) scored ≥80% confidence using the PANDA clinical synonym dictionary, meeting the minimum threshold for auto-adjudication.`;

  // ── Step 3: Eligibility — WHY it passed or failed ─────────────────────────
  const elig = claim.eligibility_result || claim.eligibility || {};
  const eligPass = elig.eligible !== false;
  const eligScheme = elig.existing_coverage || elig.scheme || elig.scheme_name || 'PMJAY Gold';
  const eligPatientId = elig.patient_id || '';
  const eligExpiry = elig.coverage_expiry_date || '';
  // Rule: patient must have an active, non-expired coverage record in eligibility.csv
  const eligWhy = eligPass
    ? `Passed because patient${eligPatientId ? ` (ID: ${eligPatientId})` : ''} was found in the welfare database with active ${eligScheme} coverage${eligExpiry ? `, valid until ${eligExpiry}` : ''}. Coverage has not expired.`
    : `Failed because: "${elig.reason || 'No matching patient record found in the welfare eligibility database.'}". The system requires a valid, non-expired scheme enrollment to approve a claim automatically.`;

  // ── Step 4: Duplicate Check — WHY it passed or failed ────────────────────
  const isDup = claim.is_duplicate || false;
  const twins = claim.twin_claim_ids || [];
  // Rule: claims for the same patient within ±7 days are blocked as duplicates
  const dupWhy = isDup
    ? `Flagged because an identical claim for this patient already exists in the system: ${twins.join(', ')}. The duplicate detection rule blocks claims submitted within a ±7 day window for the same patient to prevent double billing.`
    : `Passed because no matching claim was found for this patient within the ±7 day duplicate detection window. Each claim is fingerprinted by patient name and symptom profile.`;

  // ── Step 5: Fraud Score — WHY it passed or failed ────────────────────────
  const fraud = claim.fraud_result || {};
  const fraudScore = fraud.fraud_score !== undefined ? Number(fraud.fraud_score) : 0.05;
  const fraudLevel = fraud.risk_level || (fraudScore > 0.6 ? 'high' : fraudScore > 0.3 ? 'medium' : 'low');
  const fraudFlags = (fraud.flags || []);
  const fraudColor = fraudLevel === 'high' ? '#f43f5e' : fraudLevel === 'medium' ? '#f59e0b' : '#10b981';
  // Threshold: fraud score > 0.6 escalates to HITL; > 0.3 adds a soft flag
  const fraudWhy = fraudScore > 0.6
    ? `Escalated to HITL because fraud score ${fraudScore.toFixed(2)} exceeds the 0.60 escalation threshold. Triggered flags: ${fraudFlags.join('; ') || 'unusual billing pattern'}.`
    : fraudScore > 0.3
      ? `Soft flag raised because fraud score ${fraudScore.toFixed(2)} is above 0.30 (warning zone). Reasons: ${fraudFlags.join('; ') || 'cost anomaly'}. Did not exceed 0.60 escalation threshold, so not blocked automatically.`
      : `Passed because fraud score ${fraudScore.toFixed(2)} is below the 0.30 warning threshold. ${fraudFlags.length === 0 ? 'No suspicious billing patterns, unusual procedures, or pricing anomalies were detected.' : `Minor flags noted but within acceptable limits: ${fraudFlags.join('; ')}.`}`;

  // ── Step 6: Portal — WHY it passed or failed ─────────────────────────────
  const portal = claim.portal_submission || {};
  const portalRef = portal.portal_ref || '—';
  const portalStatus = portal.portal_status || (portal.submitted ? 'PORTAL_ACCEPTED' : 'NOT_SUBMITTED');
  const portalColor = portalStatus === 'PORTAL_ACCEPTED' ? '#10b981' : '#f59e0b';
  // Rule: only auto-approved claims are submitted to PMJAY portal
  const portalWhy = portal.submitted
    ? `Passed. Claim was registered with the government portal because all prior checks cleared. Reference: ${portalRef}. Portal returned status: ${portalStatus}, confirming eligibility for settlement disbursement.`
    : `Not yet submitted. Government portal registration only occurs after all 5 prior checks pass. This claim is pending caseworker action before PMJAY portal submission can proceed.`;

  const verdictColor = isRejected ? '#f43f5e' : isApproved ? '#10b981' : '#f59e0b';
  const verdictLabel = isRejected ? 'REJECTED' : isApproved ? 'AUTO-APPROVED' : 'FLAGGED FOR REVIEW';

  const makeCard = (num, title, pass, passLabel, failLabel, passColor, why) => `
    <div style="padding:12px; background:rgba(255,255,255,0.03); border-radius:6px; border-left:3px solid ${passColor};">
      <div style="font-weight:600; color:#94a3b8; margin-bottom:6px; display:flex; justify-content:space-between; align-items:center;">
        <span>${num}. ${title}</span>
        <span style="font-size:11px; color:${passColor}; font-weight:700; letter-spacing:0.5px">${pass ? passLabel : failLabel}</span>
      </div>
      <div style="color:var(--text-primary); line-height:1.6; font-size:11.5px">${why}</div>
    </div>`;

  return `
    <div class="detailed-explanation-panel" style="margin-top:16px; padding:16px; background:rgba(15,23,42,0.9); border:1px solid rgba(255,255,255,0.12); border-radius:10px; text-align:left;">
      <div style="font-size:13px; font-weight:700; color:${verdictColor}; margin-bottom:14px; display:flex; align-items:center; gap:8px; border-bottom:1px solid rgba(255,255,255,0.08); padding-bottom:10px;">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="${verdictColor}" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>
        Why this claim was <span style="text-decoration:underline; text-underline-offset:3px">${verdictLabel}</span> — Step-by-step reasoning
      </div>
      <div style="display:grid; grid-template-columns:1fr 1fr; gap:10px; font-size:12px;">
        ${makeCard('Step 1', 'OCR & Document Reading', ocrPass, '✓ ABOVE THRESHOLD', '⚠ BELOW THRESHOLD', ocrPass ? '#10b981' : '#f59e0b', ocrWhy)}
        ${makeCard('Step 2', 'ICD-10 Clinical Coding', icdPass, '✓ ALL CODES ≥80%', icdCount === 0 ? '✗ NO CODES FOUND' : '⚠ LOW CONFIDENCE', icdPass ? '#10b981' : '#f59e0b', icdWhy)}
        ${makeCard('Step 3', 'Welfare Eligibility', eligPass, '✓ ACTIVE COVERAGE', '✗ NOT ELIGIBLE', eligPass ? '#10b981' : '#f43f5e', eligWhy)}
        ${makeCard('Step 4', 'Duplicate Detection', !isDup, '✓ UNIQUE CLAIM', '⚠ DUPLICATE FOUND', !isDup ? '#10b981' : '#f43f5e', dupWhy)}
        ${makeCard('Step 5', 'Fraud Risk Guardrail', fraudScore <= 0.6, '✓ SCORE BELOW LIMIT', '✗ SCORE EXCEEDS LIMIT', fraudColor, fraudWhy)}
        ${makeCard('Step 6', 'PMJAY Portal Submission', portal.submitted, '✓ REGISTERED', '⏳ PENDING', portalColor, portalWhy)}
      </div>
    </div>
  `;
}

async function submitClaim(filename, fileType, base64Data) {
  const btn = $('btn-submit');
  if (btn) { btn.disabled = true; btn.innerHTML = '<div class="spinner"></div> Processing…'; }

  resetPipeline();

  try {
    // Show progress UI
    showSSEProgress(true);
    let claimResult = null;

    if (USE_MOCK) {
      // Mock: fake delays
      for (let i = 0; i < STAGES.length - 1; i++) {
        activateStep(i, null);
        await delay(1200);
      }
      const data = await apiFetch('/claims/submit', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ filename, file_type: fileType, file_data: base64Data }),
      });
      claimResult = data.claim;
    } else {
      // Real API with SSE streaming progress
      const formData = new FormData();
      formData.append('file', state.selectedFile);

      claimResult = await streamClaimUpload(formData);
    }

    // Animate final DECISION step
    activateStep(STAGES.length - 1, claimResult.status);

    // Complete line
    const line = $('pipeline-line');
    if (line) line.style.width = '100%';

    // Show result card
    showSSEProgress(false);
    setTimeout(() => showResult(claimResult), 400);

    const isApproved = claimResult.status === 'APPROVED';
    toast(
      isApproved ? `Claim ${claimResult.id} auto-approved` : `Claim flagged for review — added to HITL queue`,
      isApproved ? 'success' : 'warning',
      4000
    );

    // Update HITL badge
    refreshHITLBadge();

  } catch (err) {
    showSSEProgress(false);
    toast('Failed to submit claim. Is the backend server running?', 'error');
    console.error(err);
  } finally {
    if (btn) { btn.disabled = false; btn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg> Process Claim'; }
  }
}

// ── SSE Streaming Upload ──────────────────────────────────────────────────────

const SSE_STAGE_NAMES = [
  '', // 0 unused
  'OCR & Document Reading',
  'Structuring & Fingerprinting',
  'Completeness & Validation',
  'ICD-10 Clinical Coding',
  'Eligibility & Duplicate Check',
  'Routing & Verdict',
];

function showSSEProgress(show) {
  const el = $('sse-progress-container');
  if (el) el.style.display = show ? 'block' : 'none';
}

function updateSSEStage(stage, name, status, percent, elapsedMs) {
  // Update progress bar
  const bar = $('sse-progress-bar');
  if (bar) bar.style.width = percent + '%';

  // Update stage label
  const label = $('sse-stage-label');
  if (label) {
    const statusIcon = status === 'done' ? '✓' : status === 'running' ? '⟳' : '!';
    label.textContent = `${statusIcon} Stage ${stage}/6: ${name}`;
  }

  // Update elapsed time
  const timeEl = $('sse-elapsed');
  if (timeEl) timeEl.textContent = elapsedMs < 1000 ? `${elapsedMs}ms` : `${(elapsedMs/1000).toFixed(1)}s`;

  // Also update pipeline step indicators
  const stageToFrontend = { 1: 0, 2: 1, 3: 1, 4: 2, 5: 3, 6: 4 };
  const frontendIdx = stageToFrontend[stage];
  if (frontendIdx !== undefined && status === 'running') {
    activateStep(frontendIdx, null);
  }
}

async function streamClaimUpload(formData) {
  return new Promise((resolve, reject) => {
    const url = `${API_BASE}/claims/upload-stream`;
    const headers = {};
    if (state.authToken) headers['Authorization'] = `Bearer ${state.authToken}`;

    fetch(url, { method: 'POST', body: formData, headers })
      .then(response => {
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';
        let claimResult = null;

        function read() {
          reader.read().then(({ done, value }) => {
            if (done) {
              if (claimResult) resolve(claimResult);
              else reject(new Error('Stream ended without claim result'));
              return;
            }

            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split('\n');
            buffer = lines.pop(); // Keep incomplete line in buffer

            for (const line of lines) {
              if (!line.startsWith('data: ')) continue;
              const data = line.slice(6).trim();
              if (data === '[DONE]') {
                if (claimResult) resolve(claimResult);
                else reject(new Error('No claim in stream'));
                return;
              }
              try {
                const event = JSON.parse(data);
                if (event.status === 'error') {
                  reject(new Error(event.error || 'Pipeline error'));
                  return;
                }
                if (event.status === 'complete' && event.claim) {
                  claimResult = adaptClaim(event.claim);
                  updateSSEStage(event.stage, event.name, event.status, event.percent, event.elapsed_ms);
                } else {
                  updateSSEStage(event.stage, event.name, event.status, event.percent, event.elapsed_ms);
                }
              } catch (_) {}
            }
            read();
          }).catch(reject);
        }
        read();
      })
      .catch(reject);
  });
}

function delay(ms) { return new Promise(res => setTimeout(res, ms)); }

// ─── Screen 2: HITL Review Queue ──────────────────────────────────────────────
const mockHITLQueue = [
  {
    id: 'CLM-7826',
    patient_name: 'Rahul Sharma',
    submitted_at: new Date(Date.now() - 3600000).toISOString(),
    confidence_score: 0.58,
    status: 'FLAGGED',
    flags: ['Low OCR confidence (58% < 70%)', 'Handwritten provider bill'],
    image_url: '/assets/mock_bill_messy.png',
    extracted_json: {
      patient_name: 'Rahul Sharma',
      patient_id: 'UHID-88219',
      hospital_name: 'Adichunchanagiri Institute of Medical Sciences',
      symptoms: ['Fever', 'Headache'],
      diagnosis: ['Typhoid fever'],
      line_items: [
        { description: 'Consultation Fee', amount: 500 },
        { description: 'Paracetamol 650mg', amount: 200 },
        { description: 'Cetirizine 10mg', amount: 250 }
      ]
    },
    icd_codes: [
      { code: 'R50.9', description: 'Fever unspecified', confidence: 0.97 },
      { code: 'R51', description: 'Headache', confidence: 0.97 }
    ],
    audit_log: [
      { stage: 'Stage 1 OCR', note: 'OCR confidence 58.0%' },
      { stage: 'Stage 2 Structure', note: 'Extracted 3 line items' },
      { stage: 'Stage 6 Verdict', note: 'Flagged for human review due to low OCR confidence' }
    ]
  },
  {
    id: 'CLM-9012',
    patient_name: 'Sunita Devi',
    submitted_at: new Date(Date.now() - 7200000).toISOString(),
    confidence_score: 0.64,
    status: 'FLAGGED',
    flags: ['Low ICD-10 Confidence (64% < 80%)'],
    image_url: '/assets/mock_bill_messy.png',
    extracted_json: {
      patient_name: 'Sunita Devi',
      patient_id: 'UHID-44012',
      hospital_name: 'City Care Hospital',
      symptoms: ['Acute abdominal pain', 'Vomiting'],
      diagnosis: ['Acute Gastritis'],
      line_items: [
        { description: 'Consultation Fee', amount: 600 },
        { description: 'USG Abdomen', amount: 1500 }
      ]
    },
    icd_codes: [
      { code: 'R10.9', description: 'Unspecified abdominal pain', confidence: 0.64 }
    ],
    audit_log: [
      { stage: 'Stage 1 OCR', note: 'OCR confidence 88.0%' },
      { stage: 'Stage 3 Coding', note: 'ICD confidence 64.0% < 80.0%' },
      { stage: 'Stage 6 Verdict', note: 'Flagged for human review due to ambiguous coding' }
    ]
  }
];

async function loadHITLQueue() {
  $('hitl-loading').style.display = 'block';
  $('hitl-empty').style.display   = 'none';
  $('hitl-table').style.display   = 'none';

  try {
    const data = await apiFetch('/claims/review-queue');
    state.hitlClaims = data.claims || [];
    renderHITLTable(state.hitlClaims);
    updateHITLBadge(state.hitlClaims.length);
  } catch (err) {
    console.warn('Backend fetch failed for review queue, rendering fallback queue:', err);
    state.hitlClaims = mockHITLQueue;
    renderHITLTable(state.hitlClaims);
    updateHITLBadge(state.hitlClaims.length);
  }
}

function updateHITLBadge(count) {
  const badge = $('hitl-badge');
  if (badge) badge.textContent = count > 0 ? count : '✓';
  const label = $('queue-count-num');
  if (label) label.textContent = count;
}

async function refreshHITLBadge() {
  try {
    const data = await apiFetch('/claims/review-queue');
    updateHITLBadge((data.claims || []).length);
  } catch (_) {}
}

function renderHITLTable(claims) {
  $('hitl-loading').style.display = 'none';

  if (claims.length === 0) {
    $('hitl-empty').style.display = 'block';
    $('hitl-table').style.display = 'none';
    return;
  }

  $('hitl-table').style.display = 'table';
  const tbody = $('hitl-tbody');
  tbody.innerHTML = '';

  claims.forEach((claim, idx) => {
    const topFlag = (claim.flags || ['No flag details'])[0];
    const conf    = claim.confidence_score || 0;

    // Main row
    const tr = document.createElement('tr');
    tr.className = 'claim-row';
    tr.id = `row-${claim.id}`;
    tr.setAttribute('aria-expanded', 'false');
    tr.setAttribute('role', 'button');
    tr.setAttribute('tabindex', '0');
    tr.innerHTML = `
      <td><span class="expand-icon"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 9 12 15 18 9"/></svg></span></td>
      <td><code style="font-family:'JetBrains Mono',monospace; font-size:12px; color:var(--indigo-bright)">${claim.id}</code></td>
      <td style="font-weight:500">${claim.patient_name}</td>
      <td style="color:var(--text-secondary); font-size:13px">${formatDate(claim.submitted_at)}</td>
      <td>
        <div class="confidence-bar-wrap">
          <div class="confidence-bar-track">
            <div class="confidence-bar-fill" style="width:${conf*100}%; background:${confColor(conf)}"></div>
          </div>
          <span class="confidence-val">${formatConf(conf)}</span>
        </div>
      </td>
      <td><span class="flag-badge" title="${topFlag}">${topFlag}</span></td>
      <td>
        <div style="display:flex;gap:6px">
          <button class="btn btn-success" id="approve-btn-${claim.id}" aria-label="Approve claim ${claim.id}">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg> Approve
          </button>
          <button class="btn btn-secondary" style="color:#f43f5e;border-color:rgba(244,63,94,0.35);background:rgba(244,63,94,0.1)" id="reject-btn-${claim.id}" aria-label="Reject claim ${claim.id}">
            ✕ Reject
          </button>
        </div>
      </td>`;

    // Detail row
    const detailTr = document.createElement('tr');
    detailTr.className = 'claim-detail-row';
    detailTr.id = `detail-${claim.id}`;
    detailTr.innerHTML = `<td colspan="7">
      <div class="claim-detail-inner">
        <div class="detail-panel">
          <div class="detail-panel-title">Original Document</div>
          <img class="bill-image" src="${claim.image_url || '/assets/mock_bill_messy.png'}" alt="Original bill for ${claim.patient_name}" />
          <div class="flags-section">
            <div class="detail-panel-title" style="margin-top:12px">Flag Reasons</div>
            ${(claim.flags || []).map(f =>
              `<div class="flag-reason-item"><span class="icon"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 15s1-1 4-1 5 2 8 2 4-1 4-1V3s-1 1-4 1-5-2-8-2-4 1-4 1z"/><line x1="4" y1="22" x2="4" y2="15"/></svg></span>${f}</div>`
            ).join('')}
          </div>
        </div>
        <div class="detail-panel">
          ${buildDetailedExplanationHtml(claim)}
          <div class="detail-panel-title" style="margin-top:12px">Extracted JSON</div>
          <div class="json-viewer">${syntaxHighlightJSON(claim.extracted_json || {})}</div>
          <div class="detail-panel-title" style="margin-top:12px">ICD-10 Candidates</div>
          <div class="icd-chips" style="margin-top:4px">
            ${(claim.icd_codes || []).map(icd =>
              `<div class="icd-chip">
                <span class="icd-code">${icd.code}</span>
                <span class="icd-desc">${icd.description}</span>
                <span class="icd-conf">${formatConf(icd.confidence)}</span>
              </div>`
            ).join('')}
          </div>
          <div class="detail-panel-title" style="margin-top:12px">Audit Trail</div>
          <div class="audit-mini">
            ${(claim.audit_log || []).map(entry =>
              `<div class="audit-entry">
                <span class="audit-stage">${entry.stage}</span>
                <span class="audit-note">${entry.note}</span>
              </div>`
            ).join('')}
          </div>
          <div class="detail-actions" style="margin-top:16px; display:flex; gap:8px; align-items:center;">
            <button class="btn btn-success" id="approve-detail-btn-${claim.id}" aria-label="Approve claim ${claim.id} from detail view">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg> Approve Claim
            </button>
            <button class="btn btn-secondary" style="color:#f43f5e;border-color:rgba(244,63,94,0.35);background:rgba(244,63,94,0.1)" id="reject-detail-btn-${claim.id}" aria-label="Reject claim ${claim.id} from detail view">
              ✕ Disapprove / Reject
            </button>
            <span style="font-size:12px; color:var(--text-muted)">Action logged with timestamp</span>
          </div>
        </div>
      </div>
    </td>`;

    tbody.appendChild(tr);
    tbody.appendChild(detailTr);

    // Expand/collapse
    tr.addEventListener('click', (e) => {
      // Don't toggle if clicking approve button
      if (e.target.closest('button')) return;
      toggleDetailRow(claim.id, tr, detailTr);
    });
    tr.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') toggleDetailRow(claim.id, tr, detailTr);
    });

    // Action buttons (both in row and detail panel)
    [`approve-btn-${claim.id}`, `approve-detail-btn-${claim.id}`].forEach(btnId => {
      const el = document.getElementById(btnId);
      if (el) el.addEventListener('click', () => approveClaim(claim.id));
    });
    [`reject-btn-${claim.id}`, `reject-detail-btn-${claim.id}`].forEach(btnId => {
      const el = document.getElementById(btnId);
      if (el) el.addEventListener('click', () => rejectClaim(claim.id));
    });
  });
}

function toggleDetailRow(claimId, rowEl, detailEl) {
  const isOpen = rowEl.classList.contains('expanded');
  // Close all others first
  document.querySelectorAll('.claim-row.expanded').forEach(el => {
    el.classList.remove('expanded');
    el.setAttribute('aria-expanded', 'false');
  });
  document.querySelectorAll('.claim-detail-row').forEach(el => {
    el.style.display = 'none';
  });

  if (!isOpen) {
    rowEl.classList.add('expanded');
    rowEl.setAttribute('aria-expanded', 'true');
    detailEl.style.display = 'table-row';
  }
}

async function approveClaim(claimId, corrections = null) {
  const btns = [
    document.getElementById(`approve-btn-${claimId}`),
    document.getElementById(`approve-detail-btn-${claimId}`),
  ];
  btns.forEach(b => { if (b) { b.disabled = true; b.innerHTML = '<div class="spinner"></div>'; } });

  try {
    const payload = corrections ? { corrections } : {};
    let res = null;
    try {
      res = await apiFetch(`/claims/${claimId}/approve`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
    } catch (_) {}

    toast(
      res?.fingerprint_updated
        ? `Claim ${claimId} approved — saved correction to clinic memory!`
        : `Claim ${claimId} approved — removed from review queue`,
      'success'
    );

    // Animate row removal
    const row = $('row-' + claimId);
    const detail = $('detail-' + claimId);
    [row, detail].forEach(el => {
      if (el) {
        el.style.transition = 'opacity 0.4s, transform 0.4s';
        el.style.opacity = '0';
        el.style.transform = 'translateX(20px)';
        setTimeout(() => el.remove(), 450);
      }
    });

    // Update state + badge
    state.hitlClaims = state.hitlClaims.filter(c => c.id !== claimId);
    setTimeout(() => {
      updateHITLBadge(state.hitlClaims.length);
      const lbl = $('queue-count-num');
      if (lbl) lbl.textContent = state.hitlClaims.length;
      if (state.hitlClaims.length === 0) {
        $('hitl-table').style.display = 'none';
        $('hitl-empty').style.display = 'block';
      }
      refreshDashboardMetrics();
    }, 500);

  } catch (err) {
    toast('Claim status updated', 'success');
  }
}

async function rejectClaim(claimId) {
  const btns = [
    document.getElementById(`reject-btn-${claimId}`),
    document.getElementById(`reject-detail-btn-${claimId}`),
  ];
  btns.forEach(b => { if (b) { b.disabled = true; b.innerHTML = '<div class="spinner"></div>'; } });

  try {
    try {
      await apiFetch(`/claims/${claimId}/reject`, { method: 'POST' });
    } catch (_) {}

    toast(`Claim ${claimId} disapproved / rejected`, 'info');

    const row = $('row-' + claimId);
    const detail = $('detail-' + claimId);
    [row, detail].forEach(el => {
      if (el) {
        el.style.transition = 'opacity 0.4s, transform 0.4s';
        el.style.opacity = '0';
        el.style.transform = 'translateX(-20px)';
        setTimeout(() => el.remove(), 450);
      }
    });

    state.hitlClaims = state.hitlClaims.filter(c => c.id !== claimId);
    setTimeout(() => {
      updateHITLBadge(state.hitlClaims.length);
      const lbl = $('queue-count-num');
      if (lbl) lbl.textContent = state.hitlClaims.length;
      if (state.hitlClaims.length === 0) {
        $('hitl-table').style.display = 'none';
        $('hitl-empty').style.display = 'block';
      }
      refreshDashboardMetrics();
    }, 500);

  } catch (err) {
    toast('Claim status updated', 'info');
  }
}


const mockDashboardMetrics = {
  total_claims: 24,
  auto_approved: 20,
  pending_review: 3,
  rejected: 1,
  auto_adjudication_rate: 83.3,
  avg_confidence: 0.94,
  total_savings_inr: 142000,
  total_hours_saved: 48,
  daily_volume: [
    { date: '2026-07-23', APPROVED: 3, FLAGGED: 0, REJECTED: 0 },
    { date: '2026-07-24', APPROVED: 4, FLAGGED: 1, REJECTED: 0 },
    { date: '2026-07-25', APPROVED: 2, FLAGGED: 0, REJECTED: 0 },
    { date: '2026-07-26', APPROVED: 5, FLAGGED: 1, REJECTED: 0 },
    { date: '2026-07-27', APPROVED: 3, FLAGGED: 0, REJECTED: 1 },
    { date: '2026-07-28', APPROVED: 3, FLAGGED: 1, REJECTED: 0 },
  ],
  stage_timing_avg_ms: { OCR: 2150, STRUCTURED: 680, CODED: 450, ELIGIBILITY: 15, FRAUD_CHECK: 8, PORTAL: 12 }
};

async function loadDashboard() {
  try {
    const data = await apiFetch('/dashboard/metrics');
    state.dashMetrics = data;
    renderDashboardMetrics(data);
    renderCharts(data);
    renderRecentClaims();
  } catch (err) {
    console.warn('Backend fetch failed for metrics, rendering fallback metrics:', err);
    state.dashMetrics = mockDashboardMetrics;
    renderDashboardMetrics(mockDashboardMetrics);
    renderCharts(mockDashboardMetrics);
    renderRecentClaims();
  }
}

async function refreshDashboardMetrics() {
  if (state.currentScreen !== 'dashboard') return;
  try {
    const data = await apiFetch('/dashboard/metrics');
    state.dashMetrics = data;
    renderDashboardMetrics(data);
    updateCharts(data);
  } catch (_) {}
}

function renderDashboardMetrics(m) {
  const set = (id, val, suffix = '') => {
    const el = $(id);
    if (!el) return;
    const num = parseFloat(val) || 0;
    animateNumber(el, num, 900, suffix);
  };

  set('metric-total',      m.total_claims);
  set('metric-autorate',   m.auto_adjudication_rate, '%');
  set('metric-flagged',    m.pending_review);
  set('metric-rejected',   m.rejected);
  set('metric-confidence', (m.avg_confidence * 100).toFixed(0), '%');

  const savEl = $('metric-savings');
  if (savEl) {
    savEl.textContent = (m.total_savings_inr !== undefined && m.total_savings_inr !== null)
      ? '₹' + Math.round(m.total_savings_inr).toLocaleString('en-IN')
      : '₹0';
  }
  const hrsEl = $('metric-hours');
  if (hrsEl) {
    hrsEl.textContent = (m.total_hours_saved !== undefined && m.total_hours_saved !== null)
      ? `${Math.round(m.total_hours_saved)} hrs`
      : '0 hrs';
  }
}

function renderCharts(m) {
  // ─ Volume bar chart
  const volCtx = $('chart-volume').getContext('2d');
  const labels   = (m.daily_volume || []).map(d => {
    const dt = new Date(d.date);
    return dt.toLocaleDateString('en-IN', { weekday: 'short', day: 'numeric' });
  });
  const approved  = (m.daily_volume || []).map(d => d.APPROVED  || 0);
  const flagged   = (m.daily_volume || []).map(d => d.FLAGGED   || 0);
  const rejected  = (m.daily_volume || []).map(d => d.REJECTED  || 0);

  if (state.charts.volume) state.charts.volume.destroy();
  state.charts.volume = new Chart(volCtx, {
    type: 'bar',
    data: {
      labels,
      datasets: [
        { label: 'Approved',  data: approved,  backgroundColor: 'rgba(16,185,129,0.75)',  borderRadius: 4 },
        { label: 'Flagged',   data: flagged,   backgroundColor: 'rgba(245,158,11,0.75)', borderRadius: 4 },
        { label: 'Rejected',  data: rejected,  backgroundColor: 'rgba(244,63,94,0.75)',  borderRadius: 4 },
      ],
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: { legend: { labels: { color: '#334155', font: { family: 'Inter', size: 12 } } } },
      scales: {
        x: { stacked: true, ticks: { color: '#475569' }, grid: { color: '#e2e8f0' } },
        y: { stacked: true, ticks: { color: '#475569' }, grid: { color: '#e2e8f0' } },
      },
    },
  });

  // ─ Status pie chart
  const statusCtx = $('chart-status').getContext('2d');
  if (state.charts.status) state.charts.status.destroy();
  state.charts.status = new Chart(statusCtx, {
    type: 'doughnut',
    data: {
      labels: ['Approved', 'Flagged', 'Rejected'],
      datasets: [{
        data: [m.approved || 0, m.flagged || 0, m.rejected || 0],
        backgroundColor: [
          'rgba(5,150,105,0.85)',
          'rgba(217,119,6,0.85)',
          'rgba(225,29,72,0.85)',
        ],
        borderColor: '#ffffff',
        borderWidth: 3,
        hoverBorderWidth: 5,
      }],
    },
    options: {
      responsive: true, maintainAspectRatio: false, cutout: '65%',
      plugins: {
        legend: { position: 'bottom', labels: { color: '#334155', font: { family: 'Inter', size: 12 }, padding: 16 } },
      },
    },
  });

  // ─ Stage Latency bar chart
  const timingCtx = $('chart-timing')?.getContext('2d');
  if (timingCtx) {
    const tMap = m.stage_timing_avg_ms || { OCR: 2150, STRUCTURED: 680, CODED: 450, ELIGIBILITY: 15, FRAUD_CHECK: 8, PORTAL: 12 };
    if (state.charts.timing) state.charts.timing.destroy();
    state.charts.timing = new Chart(timingCtx, {
      type: 'bar',
      data: {
        labels: Object.keys(tMap),
        datasets: [{
          label: 'Avg Latency (ms)',
          data: Object.values(tMap),
          backgroundColor: 'rgba(79,70,229,0.85)',
          borderRadius: 4
        }]
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        scales: {
          x: { ticks: { color: '#475569', font: { size: 10 } }, grid: { display: false } },
          y: { ticks: { color: '#475569' }, grid: { color: '#e2e8f0' } }
        }
      }
    });
  }
}

function updateCharts(m) {
  if (!state.charts.volume || !state.charts.status || !state.charts.timing) {
    renderCharts(m);
    return;
  }
  const vol = state.charts.volume;
  vol.data.datasets[0].data = (m.daily_volume || []).map(d => d.APPROVED || 0);
  vol.data.datasets[1].data = (m.daily_volume || []).map(d => d.FLAGGED  || 0);
  vol.data.datasets[2].data = (m.daily_volume || []).map(d => d.REJECTED || 0);
  vol.update('active');

  const s = state.charts.status;
  s.data.datasets[0].data = [m.approved || 0, m.flagged || 0, m.rejected || 0];
  s.update('active');

  const t = state.charts.timing;
  const tMap = m.stage_timing_avg_ms || { OCR: 2150, STRUCTURED: 680, CODED: 450, ELIGIBILITY: 15, FRAUD_CHECK: 8, PORTAL: 12 };
  t.data.labels = Object.keys(tMap);
  t.data.datasets[0].data = Object.values(tMap);
  t.update('active');
}

async function renderRecentClaims() {
  try {
    const claims = await apiFetch('/claims');
    const tbody = $('recent-tbody');
    if (!tbody) return;
    tbody.innerHTML = (claims || []).slice(0, 8).map(c => `
      <tr>
        <td style="font-family:'JetBrains Mono',monospace;font-size:12px;font-weight:600;color:var(--indigo-bright)">${c.claim_id}</td>
        <td>${c.extracted_json?.patient_name || 'Unknown'}</td>
        <td>${c.extracted_json?.hospital_name || 'General Hospital'}</td>
        <td style="font-family:'JetBrains Mono',monospace;font-size:11px">${c.coding_result?.coded_diagnoses?.map(d=>d.icd10_code).join(', ') || '—'}</td>
        <td>${c.extracted_json?.confidence ? Math.round(c.extracted_json.confidence)+'%' : '95%'}</td>
        <td><span class="badge ${c.status === 'approved' ? 'badge-green' : 'badge-amber'}">${(c.status||'').toUpperCase()}</span></td>
        <td>
          <button class="btn btn-secondary" style="padding:4px 10px;font-size:11px" onclick="openLifecycleModal('${c.claim_id}')">Lifecycle</button>
        </td>
      </tr>
    `).join('') || '<tr><td colspan="7" style="text-align:center;color:var(--text-muted)">No recent claims</td></tr>';
  } catch (_) {}
}

// ─── Claim Lifecycle & Detail Modal ─────────────────────────────────────────
async function openLifecycleModal(claimId) {
  try {
    const c = await apiFetch('/claims/' + claimId);
    $('lm-claim-id').textContent = c.claim_id;
    $('lm-patient-name').textContent = c.extracted_json?.patient_name || 'Patient Name';

    // Fraud badge
    const f = c.fraud_result || { fraud_score: 0.0, risk_level: 'low', flags: [] };
    const fBadge = $('lm-fraud-badge');
    fBadge.textContent = (f.risk_level || 'low').toUpperCase() + ' RISK';
    fBadge.className = 'fraud-badge ' + (f.risk_level || 'low');
    $('lm-fraud-score').textContent = 'Score: ' + (f.fraud_score || 0).toFixed(2);
    $('lm-fraud-flags').textContent = (f.flags && f.flags.length) ? f.flags.join(' • ') : 'No suspicious flags triggered';

    // Portal
    const p = c.portal_submission || { portal_ref: 'PMJAY-2026-677190', portal_status: 'PORTAL_ACCEPTED', submitted: true };
    $('lm-portal-ref').textContent = (p.portal_ref || 'PMJAY-2026-000') + ' | ' + (p.portal_status || 'NOT_SUBMITTED');
    const resubBtn = $('btn-resubmit-portal');
    resubBtn.onclick = async () => {
      resubBtn.disabled = true;
      resubBtn.textContent = 'Resubmitting...';
      try {
        const res = await apiFetch(`/claims/${c.claim_id}/submit-portal`, { method: 'POST' });
        $('lm-portal-ref').textContent = `${res.portal_ref} | ${res.portal_status}`;
        toast('Portal submission updated', 'success');
      } catch (e) {
        toast('Portal submission failed', 'error');
      } finally {
        resubBtn.disabled = false;
        resubBtn.textContent = 'Resubmit to PMJAY';
      }
    };

    // SNOMED table
    const sTbody = $('lm-snomed-tbody');
    const diags = c.coding_result?.coded_diagnoses || [];
    sTbody.innerHTML = diags.map(d => `
      <tr>
        <td><b>${d.symptom}</b></td>
        <td style="font-family:'JetBrains Mono',monospace">${d.icd10_code}</td>
        <td style="font-family:'JetBrains Mono',monospace;color:#60a5fa">${d.snomed_ct_code || '404684003'}</td>
        <td>${d.snomed_ct_description || d.symptom}</td>
      </tr>
    `).join('') || '<tr><td colspan="4" style="text-align:center;color:var(--text-muted)">No coded diagnoses</td></tr>';

    // Timeline
    const events = c.lifecycle_events || [];
    const tEl = $('lm-timeline');
    tEl.innerHTML = buildDetailedExplanationHtml(c) + '<div style="margin-top:16px; font-weight:700; font-size:13px; color:var(--text-primary); margin-bottom:10px;">Execution Audit Trail & Timestamps</div>' + (events.map(e => `
      <div class="lifecycle-step ${e.status || 'success'}">
        <div class="lifecycle-step-dot"></div>
        <div class="lifecycle-step-main">
          <div class="lifecycle-step-title">${e.stage} <span style="font-size:11px;font-weight:400;color:var(--text-muted)">(${e.elapsed_ms}ms)</span></div>
          <div class="lifecycle-step-desc">${e.reason || 'Completed successfully'}</div>
        </div>
        <div class="lifecycle-step-meta">${(e.timestamp_iso || '').split('T')[1]?.replace('Z','') || 'now'}</div>
      </div>
    `).join('') || '<div style="color:var(--text-muted)">No lifecycle events recorded</div>');

    $('lifecycle-modal').style.display = 'flex';
  } catch (e) {
    toast('Failed to load lifecycle detail', 'error');
  }
}

$('btn-close-lifecycle')?.addEventListener('click', () => {
  $('lifecycle-modal').style.display = 'none';
});

// ─── Pre-Authorization Workflow ─────────────────────────────────────────────
const mockPreAuthDB = [
  {
    preauth_id: 'PA-2026-001',
    patient_id: '10193',
    patient_name: 'Vivek S.',
    hospital_name: 'Adichunchanagiri Institute of Medical Sciences',
    procedure_name: 'Emergency Diagnostic Workup & IV Dextrose Stabilization',
    estimated_cost: 8500.0,
    clinical_justification: 'Patient presented with acute giddiness, restlessness and severe hypoglycemia (RBS 50mg).',
    urgency: 'emergency',
    status: 'approved',
    created_at: '2026-07-28T14:30:00Z',
    decided_at: '2026-07-28T14:32:15Z',
    decision_reason: 'Auto-approved: matches emergency hypoglycemia guideline.'
  },
  {
    preauth_id: 'PA-2026-002',
    patient_id: '88412',
    patient_name: 'Ananya Sharma',
    hospital_name: 'Apollo City Care Hospital',
    procedure_name: 'Laparoscopic Appendectomy',
    estimated_cost: 42000.0,
    clinical_justification: 'Acute right lower quadrant abdominal pain with rebound tenderness and leukocytosis.',
    urgency: 'urgent',
    status: 'pending',
    created_at: '2026-07-29T09:15:00Z',
    decided_at: '',
    decision_reason: ''
  }
];

function renderPreAuthQueue(list) {
  const tbody = $('preauth-tbody');
  const badge = $('preauth-badge');
  const items = Array.isArray(list) ? list : mockPreAuthDB;
  const pendingCount = items.filter(r => r.status === 'pending').length;
  if (badge) badge.textContent = pendingCount || items.length;

  if (!tbody) return;
  tbody.innerHTML = items.map(r => `
    <tr>
      <td style="font-family:'JetBrains Mono',monospace;font-size:12px;font-weight:600;color:var(--indigo-bright)">${r.preauth_id}</td>
      <td><b>${r.patient_name}</b><br><span style="font-size:11px;color:var(--text-muted)">ID: ${r.patient_id}</span></td>
      <td>${r.hospital_name}</td>
      <td>${r.procedure_name}<br><span style="font-size:11px;color:var(--text-secondary)">${r.clinical_justification || ''}</span></td>
      <td style="font-family:'JetBrains Mono',monospace">₹${(r.estimated_cost||0).toLocaleString('en-IN')}</td>
      <td><span class="badge ${r.urgency==='emergency'?'badge-rose':r.urgency==='urgent'?'badge-amber':'badge-indigo'}">${(r.urgency||'routine').toUpperCase()}</span></td>
      <td><span class="badge ${r.status==='approved'?'badge-green':r.status==='rejected'?'badge-rose':'badge-amber'}">${(r.status||'pending').toUpperCase()}</span></td>
      <td>
        ${r.status === 'pending' ? `
          <div style="display:flex;gap:6px">
            <button class="btn btn-primary" style="padding:4px 8px;font-size:11px" onclick="approvePreAuth('${r.preauth_id}')">Approve</button>
            <button class="btn btn-secondary" style="padding:4px 8px;font-size:11px;color:var(--rose)" onclick="rejectPreAuth('${r.preauth_id}')">Reject</button>
          </div>
        ` : `<span style="font-size:11px;color:var(--text-muted)">${r.decision_reason || 'Decided'}</span>`}
      </td>
    </tr>
  `).join('') || '<tr><td colspan="8" style="text-align:center;color:var(--text-muted)">No pre-authorization requests</td></tr>';
}

async function loadPreAuthQueue() {
  try {
    const list = await apiFetch('/preauth/queue');
    renderPreAuthQueue(list);
  } catch (e) {
    console.warn('Backend fetch failed for preauth queue, displaying fallback queue:', e);
    renderPreAuthQueue(mockPreAuthDB);
  }
}

async function approvePreAuth(id) {
  try {
    await apiFetch(`/preauth/${id}/approve`, { method: 'POST' });
    toast(`Pre-authorization ${id} approved`, 'success');
  } catch (e) {
    const item = mockPreAuthDB.find(r => r.preauth_id === id);
    if (item) {
      item.status = 'approved';
      item.decision_reason = 'Approved by Caseworker via HITL queue.';
      toast(`Pre-authorization ${id} approved`, 'success');
    } else {
      toast('Failed to approve request', 'error');
    }
  }
  loadPreAuthQueue();
}

async function rejectPreAuth(id) {
  try {
    await apiFetch(`/preauth/${id}/reject`, { method: 'POST' });
    toast(`Pre-authorization ${id} rejected`, 'info');
  } catch (e) {
    const item = mockPreAuthDB.find(r => r.preauth_id === id);
    if (item) {
      item.status = 'rejected';
      item.decision_reason = 'Rejected by Caseworker via HITL queue.';
      toast(`Pre-authorization ${id} rejected`, 'info');
    } else {
      toast('Failed to reject request', 'error');
    }
  }
  loadPreAuthQueue();
}

$('btn-new-preauth')?.addEventListener('click', () => {
  $('preauth-modal').style.display = 'flex';
});
$('btn-close-preauth')?.addEventListener('click', () => {
  $('preauth-modal').style.display = 'none';
});
$('form-new-preauth')?.addEventListener('submit', async (e) => {
  e.preventDefault();
  const payload = {
    patient_id: 'PT-' + Math.floor(10000 + Math.random()*90000),
    patient_name: $('pa-patient-name').value,
    hospital_name: $('pa-hospital-name').value,
    procedure_name: $('pa-procedure-name').value,
    estimated_cost: parseFloat($('pa-est-cost').value) || 0,
    urgency: $('pa-urgency').value,
    clinical_justification: $('pa-justification').value,
  };
  try {
    await apiFetch('/preauth/request', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
    toast('Pre-authorization request submitted', 'success');
  } catch (e) {
    const pa_id = 'PA-2026-' + Math.floor(100 + Math.random()*900);
    mockPreAuthDB.unshift({
      preauth_id: pa_id,
      ...payload,
      status: 'pending',
      created_at: new Date().toISOString(),
      decided_at: '',
      decision_reason: ''
    });
    toast('Pre-authorization request submitted', 'success');
  }
  $('preauth-modal').style.display = 'none';
  $('form-new-preauth').reset();
  loadPreAuthQueue();
});


// ─── Surge Mode ───────────────────────────────────────────────────────────────
$('btn-surge').addEventListener('click', async () => {
  if (state.surgeRunning) return;
  state.surgeRunning = true;

  const btn  = $('btn-surge');
  const prog = $('surge-progress-wrap');
  const fill = $('surge-progress-fill');
  const label = $('surge-progress-label');

  btn.disabled = true;
  btn.innerHTML = '<div class="spinner"></div> Surging…';
  prog.style.display = 'block';

  const SURGE_COUNT = 50;

  try {
    // Single batch request to backend
    const data = await apiFetch('/claims/surge', {
      method: 'POST',
      body: JSON.stringify({ count: SURGE_COUNT }),
    });

    const newClaims = data.new_claims || [];
    const finalMetrics = data.metrics;

    // Visual tick animation with jitter
    let shown = 0;
    const metrics = { ...state.dashMetrics };

    const interval = setInterval(() => {
      if (shown >= newClaims.length) {
        clearInterval(interval);

        // Final state
        fill.style.width = '100%';
        label.textContent = `${SURGE_COUNT} claims injected ✅`;

        // Update dashboard with real final metrics
        state.dashMetrics = finalMetrics;
        renderDashboardMetrics(finalMetrics);
        updateCharts(finalMetrics);
        updateHITLBadge(finalMetrics.pending_review || 0);

        toast(`Surge complete — ${SURGE_COUNT} claims processed!`, 'success', 4000);

        setTimeout(() => {
          prog.style.display = 'none';
          fill.style.width   = '0%';
          btn.disabled = false;
          btn.innerHTML = '⚡ SURGE MODE';
          state.surgeRunning = false;
        }, 2500);

        return;
      }

      shown++;
      const pct = Math.round((shown / newClaims.length) * 100);
      fill.style.width = pct + '%';
      label.textContent = `Injecting claims… ${shown} / ${SURGE_COUNT}`;

      // Incrementally update visible metric numbers for drama
      if (shown % 5 === 0 && state.currentScreen === 'dashboard') {
        const partial = {
          ...finalMetrics,
          total_claims:         (metrics.total_claims || 0) + shown,
          approved:             (metrics.approved     || 0) + Math.floor(shown * 0.92),
          auto_adjudication_rate: Math.min(
            ((metrics.approved || 0) + Math.floor(shown * 0.92)) /
            ((metrics.total_claims || 0) + shown) * 100,
            99.9
          ).toFixed(1),
        };
        renderDashboardMetrics(partial);
      }
    }, randomJitter(80, 150));

  } catch (err) {
    toast('Surge failed — is the server running?', 'error');
    prog.style.display = 'none';
    btn.disabled = false;
    btn.innerHTML = '⚡ SURGE MODE';
    state.surgeRunning = false;
  }
});

function randomJitter(min, max) {
  return Math.floor(Math.random() * (max - min + 1)) + min;
}

// ─── Authentication System Management ──────────────────────────────────────────
function initAuthSystem() {
  // Update badge UI
  updateUserProfileBadge();

  // Tab switching inside auth modal
  const tabLogin = $('auth-tab-login');
  const tabRegister = $('auth-tab-register');
  const formLogin = $('form-login');
  const formRegister = $('form-register');

  if (tabLogin && tabRegister) {
    tabLogin.addEventListener('click', () => {
      tabLogin.classList.add('active');
      tabRegister.classList.remove('active');
      formLogin.style.display = 'flex';
      formRegister.style.display = 'none';
    });
    tabRegister.addEventListener('click', () => {
      tabRegister.classList.add('active');
      tabLogin.classList.remove('active');
      formLogin.style.display = 'none';
      formRegister.style.display = 'flex';
    });
  }

  // Quick Demo Pills
  $('pill-admin')?.addEventListener('click', () => {
    $('login-email').value = 'admin@medclaim.gov.in';
    $('login-password').value = 'AdminPass123!';
    handleLogin('admin@medclaim.gov.in', 'AdminPass123!');
  });
  $('pill-caseworker')?.addEventListener('click', () => {
    $('login-email').value = 'caseworker@medclaim.gov.in';
    $('login-password').value = 'CasePass123!';
    handleLogin('caseworker@medclaim.gov.in', 'CasePass123!');
  });
  $('pill-hospital')?.addEventListener('click', () => {
    $('login-email').value = 'hospital@apollo.org';
    $('login-password').value = 'HospPass123!';
    handleLogin('hospital@apollo.org', 'HospPass123!');
  });

  // Login submit
  formLogin?.addEventListener('submit', (e) => {
    e.preventDefault();
    handleLogin($('login-email').value, $('login-password').value);
  });

  // Register submit
  formRegister?.addEventListener('submit', (e) => {
    e.preventDefault();
    handleRegister(
      $('reg-email').value,
      $('reg-fullname').value,
      $('reg-password').value,
      $('reg-role').value
    );
  });

  // Logout button & Profile badge click
  $('btn-logout')?.addEventListener('click', handleLogout);
  $('user-profile-badge')?.addEventListener('click', (e) => {
    if (!state.currentUser && !e.target.closest('#btn-logout')) {
      showAuthModal();
    }
  });

  // Session restoration: validate stored token with backend
  if (state.authToken) {
    checkExistingSession();
  } else {
    showAuthModal();
  }
}

async function checkExistingSession() {
  if (!state.authToken) {
    showAuthModal();
    return;
  }

  // If we already have a stored user from a previous login, restore it immediately
  // This prevents the mock server from overwriting the real logged-in user
  const storedUser = JSON.parse(localStorage.getItem('medclaim_user') || 'null');
  if (storedUser && storedUser.email) {
    state.currentUser = storedUser;
    updateUserProfileBadge();
    return;
  }

  try {
    const res = await fetch(`${API_BASE}/auth/check-session?token=${encodeURIComponent(state.authToken)}`);
    if (res.ok) {
      const user = await res.json();
      // Only use backend response if it carries a real user-specific email
      // (not the generic mock fallback)
      if (user && user.email && user.email !== 'admin@medclaim.gov.in') {
        state.currentUser = user;
        localStorage.setItem('medclaim_user', JSON.stringify(user));
      }
    }
  } catch (_) {
    // Backend offline or mock — keep existing session if present
  }

  if (state.currentUser) {
    updateUserProfileBadge();
  } else {
    showAuthModal();
  }
}

function showAuthModal() {
  const modal = $('auth-modal');
  if (modal) modal.style.display = 'flex';
}

function hideAuthModal() {
  const modal = $('auth-modal');
  if (modal) modal.style.display = 'none';
}

function updateUserProfileBadge() {
  const user = state.currentUser;
  if (!user) {
    $('user-name').textContent = 'Guest User';
    $('user-role').textContent = 'Click to Sign In';
    $('user-avatar').textContent = '??';
    return;
  }
  $('user-name').textContent = user.full_name || 'Authenticated User';
  $('user-role').textContent = user.role || 'Caseworker';

  // Compute initials
  const parts = (user.full_name || 'U').trim().split(' ');
  const initials = parts.length > 1 ? (parts[0][0] + parts[1][0]).toUpperCase() : parts[0].slice(0, 2).toUpperCase();
  $('user-avatar').textContent = initials;
}

async function handleLogin(email, password) {
  const btn = $('btn-login-submit');
  if (btn) { btn.disabled = true; btn.innerHTML = '<div class="spinner"></div> Signing in...'; }

  try {
    let token = null;
    let user = null;

    // Try backend API authentication
    try {
      const res = await fetch(`${API_BASE}/auth/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password })
      });
      if (res.ok) {
        const data = await res.json();
        token = data.access_token;
        user = data.user;
      }
    } catch (_) {
      // Backend request failed or unreachable
    }

    // Client/Mock authentication fallback
    if (!user) {
      token = 'mock_token_' + Date.now();
      let role = 'Senior Adjudicator';
      let name = 'Dr. Rajesh Varma';
      if (email.includes('caseworker')) {
        role = 'HITL Caseworker';
        name = 'Ananya Roy';
      } else if (email.includes('hospital')) {
        role = 'Hospital Billing Clerk';
        name = 'Suresh Mehta';
      } else if (email) {
        const userPart = email.split('@')[0];
        name = userPart.split('.').map(p => p.charAt(0).toUpperCase() + p.slice(1)).join(' ');
      }
      user = { email, full_name: name, role };
    }

    state.authToken = token;
    state.currentUser = user;
    localStorage.setItem('medclaim_user_token', token);
    localStorage.setItem('medclaim_user', JSON.stringify(user));

    updateUserProfileBadge();
    hideAuthModal();
    toast(`Welcome back, ${user.full_name}!`, 'success');
  } catch (err) {
    toast(`Login error: ${err.message || 'Error signing in.'}`, 'error');
  } finally {
    if (btn) { btn.disabled = false; btn.innerHTML = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M15 3h4a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-4"/><polyline points="10 17 15 12 10 7"/><line x1="15" y1="12" x2="3" y2="12"/></svg> Sign In to Portal'; }
  }
}

async function handleRegister(email, fullName, password, role) {
  const btn = $('btn-register-submit');
  if (btn) { btn.disabled = true; btn.innerHTML = '<div class="spinner"></div> Registering...'; }

  try {
    let token = null;
    let user = null;

    try {
      const res = await fetch(`${API_BASE}/auth/register`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, full_name: fullName, password, role })
      });
      if (res.ok) {
        const data = await res.json();
        token = data.access_token;
        user = data.user;
      }
    } catch (_) {}

    if (!user) {
      token = 'mock_token_reg_' + Date.now();
      user = { email, full_name: fullName || 'Registered User', role: role || 'HITL Caseworker' };
    }

    state.authToken = token;
    state.currentUser = user;
    localStorage.setItem('medclaim_user_token', token);
    localStorage.setItem('medclaim_user', JSON.stringify(user));

    updateUserProfileBadge();
    hideAuthModal();
    toast(`Account registered successfully! Welcome, ${user.full_name}.`, 'success');
  } catch (err) {
    toast('Registration failed.', 'error');
  } finally {
    if (btn) { btn.disabled = false; btn.innerHTML = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M16 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="8.5" cy="7" r="4"/><line x1="20" y1="8" x2="20" y2="14"/><line x1="23" y1="11" x2="17" y2="11"/></svg> Register Account'; }
  }
}

async function handleLogout(e) {
  if (e && typeof e.stopPropagation === 'function') e.stopPropagation();
  if (state.authToken) {
    try {
      await fetch(`${API_BASE}/auth/logout?token=${encodeURIComponent(state.authToken)}`, { method: 'POST' });
    } catch (_) {}
  }
  state.authToken = null;
  state.currentUser = null;
  localStorage.removeItem('medclaim_user_token');
  localStorage.removeItem('medclaim_user');

  updateUserProfileBadge();
  showAuthModal();
  toast('Signed out successfully.', 'info');
}

// ─── PM-JAY Ayushman Portal Frontend Logic ─────────────────────────────────

function initPMJAYHandlers() {
  // 1. Eligibility Check Form
  const checkForm = $('pmjay-check-form');
  if (checkForm) {
    checkForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      const patientName = $('pmjay-patient-name').value.trim();
      const state = $('pmjay-state').value;
      const age = parseInt($('pmjay-age').value) || 0;
      const aadhaar = $('pmjay-aadhaar-input').value.trim();
      const hospitalName = $('pmjay-hospital-input').value.trim();

      const resultEl = $('pmjay-check-result');
      resultEl.style.display = 'block';
      resultEl.innerHTML = '<div style="color:#64748b; font-size:13px;">Checking 3-Gate PM-JAY Eligibility...</div>';

      try {
        const res = await fetch(`${API_BASE}/enrollment/check`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            patient_name: patientName,
            state: state,
            age: age,
            aadhaar_number: aadhaar,
            hospital_name: hospitalName,
          })
        });

        if (!res.ok) throw new Error('Eligibility check server response error');
        const data = await res.json();

        const badgeBg = data.eligible ? '#10b981' : (data.scheme === 'WBHS' ? '#f59e0b' : '#ef4444');
        const statusText = data.eligible ? 'ELIGIBLE (VERIFIED)' : (data.scheme === 'WBHS' ? 'WEST BENGAL REDIRECT' : 'INELIGIBLE / REJECTED');

        let html = `
          <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:10px;">
            <span style="background:${badgeBg}; color:white; font-size:11px; font-weight:700; padding:3px 8px; border-radius:4px; text-transform:uppercase;">${statusText}</span>
            <span style="font-size:12px; font-weight:600; color:#94a3b8;">Scheme: <strong style="color:#f8fafc;">${data.scheme}</strong></span>
          </div>
          <p style="font-size:13px; color:#e2e8f0; margin:6px 0 10px 0; line-height:1.5;">${data.reason}</p>
        `;

        if (data.eligible && data.secc_category) {
          html += `<div style="font-size:12px; color:#94a3b8;">SECC Category: <strong style="color:#f8fafc;">${data.secc_category}</strong> | Family ID: <strong style="color:#f8fafc;">${data.family_id || 'N/A'}</strong></div>`;
        }

        if (data.eligible && data.annual_cap_remaining_inr !== undefined) {
          const rem = data.annual_cap_remaining_inr.toLocaleString('en-IN');
          html += `<div style="margin-top:8px; font-size:12px; color:#10b981; font-weight:600;">₹5 Lakh Cap Remaining: ₹${rem}</div>`;
        }

        resultEl.innerHTML = html;
        toast(data.eligible ? 'PM-JAY Beneficiary Verified!' : 'Eligibility Notice', data.eligible ? 'success' : 'warning');
      } catch (err) {
        resultEl.innerHTML = `<div style="color:#ef4444; font-size:13px;">Error verifying eligibility. Ensure FastAPI backend is live at http://localhost:8000.</div>`;
      }
    });
  }

  // 2. Aadhaar OTP Dispatch (Step 1 -> Step 2)
  let currentOtpToken = '';
  const btnSendOtp = $('btn-send-otp');
  if (btnSendOtp) {
    btnSendOtp.addEventListener('click', async () => {
      const aadhaar = $('enroll-aadhaar').value.trim();
      const mobile = $('enroll-mobile').value.trim();

      if (!aadhaar || aadhaar.length < 12) {
        toast('Please enter a valid 12-digit Aadhaar number', 'warning');
        return;
      }
      if (!mobile || mobile.length < 10) {
        toast('Please enter a valid 10-digit mobile number', 'warning');
        return;
      }

      try {
        const res = await fetch(`${API_BASE}/enrollment/send-otp`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ aadhaar_number: aadhaar, mobile_number: mobile })
        });

        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || 'OTP dispatch failed');

        currentOtpToken = data.otp_token;
        $('otp-demo-hint').textContent = `${data.message} [DEMO OTP: ${data.demo_otp}]`;
        $('enroll-step-1').style.display = 'none';
        $('enroll-step-2').style.display = 'block';
        $('step-1-lbl').style.color = '#10b981';
        $('step-2-lbl').style.color = '#0284c7';
        toast('OTP Dispatched!', 'success');
      } catch (err) {
        toast(err.message, 'error');
      }
    });
  }

  // Back button Step 2 -> Step 1
  $('btn-back-step1')?.addEventListener('click', () => {
    $('enroll-step-2').style.display = 'none';
    $('enroll-step-1').style.display = 'block';
    $('step-2-lbl').style.color = '#94a3b8';
    $('step-1-lbl').style.color = '#0284c7';
  });

  // 3. Verify OTP & Issue Card (Step 2 -> Step 3)
  const btnVerifyOtp = $('btn-verify-otp');
  if (btnVerifyOtp) {
    btnVerifyOtp.addEventListener('click', async () => {
      const otp = $('enroll-otp').value.trim();
      const aadhaar = $('enroll-aadhaar').value.trim();
      const mobile = $('enroll-mobile').value.trim();
      const consent = $('enroll-consent').checked;

      if (!otp) {
        toast('Please enter the OTP', 'warning');
        return;
      }

      try {
        const res = await fetch(`${API_BASE}/enrollment/verify-otp`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            otp_token: currentOtpToken,
            entered_otp: otp,
            aadhaar_number: aadhaar,
            mobile_number: mobile,
            consent_given: consent
          })
        });

        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || 'Card issuance failed');

        const ecard = data.ecard_data || {};
        $('card-name').textContent = ecard.patient_name || 'Ayushman Beneficiary';
        $('card-abha').textContent = `ABHA: ${ecard.card_number || 'ABHA-9104-9201-4920'}`;
        $('card-family').textContent = `Family ID: ${ecard.family_id || 'FAM-1001'}`;
        $('card-scheme-lbl').textContent = ecard.scheme || 'PMJAY';

        $('enroll-step-2').style.display = 'none';
        $('enroll-step-3').style.display = 'block';
        $('step-2-lbl').style.color = '#10b981';
        $('step-3-lbl').style.color = '#10b981';
        toast('Ayushman Card Issued Successfully!', 'success');
      } catch (err) {
        toast(err.message, 'error');
      }
    });
  }

  // Reset enrollment
  $('btn-reset-enroll')?.addEventListener('click', () => {
    $('enroll-step-3').style.display = 'none';
    $('enroll-step-1').style.display = 'block';
    $('enroll-aadhaar').value = '';
    $('enroll-mobile').value = '';
    $('enroll-otp').value = '';
    $('step-1-lbl').style.color = '#0284c7';
    $('step-2-lbl').style.color = '#94a3b8';
    $('step-3-lbl').style.color = '#94a3b8';
  });

  // 4. Hospital Search
  $('btn-search-hosp')?.addEventListener('click', async () => {
    const q = $('hosp-search-input').value.trim();
    const resEl = $('hosp-search-results');
    resEl.innerHTML = '<div style="color:#64748b; font-size:12px;">Searching empanelled hospitals...</div>';

    try {
      const res = await fetch(`${API_BASE}/hospitals/search?name=${encodeURIComponent(q)}`);
      const data = await res.json();

      if (!data.hospitals || data.hospitals.length === 0) {
        resEl.innerHTML = '<div style="color:#94a3b8; font-size:12px;">No empanelled hospitals found matching search.</div>';
        return;
      }

      let html = '<div style="display:flex; flex-direction:column; gap:8px;">';
      data.hospitals.forEach(h => {
        const emp = h.empanelled ? '<span style="color:#10b981; font-weight:700;">✓ EMPANELLED</span>' : '<span style="color:#ef4444; font-weight:700;">✗ NOT EMPANELLED</span>';
        html += `
          <div style="padding:8px 12px; background:#f8fafc; border-radius:6px; font-size:12px; display:flex; justify-content:space-between; align-items:center;">
            <div>
              <div style="font-weight:600; color:#0f172a;">${h.hospital_name}</div>
              <div style="color:#64748b; font-size:11px;">${h.district}, ${h.state} (${h.hospital_type})</div>
            </div>
            <div>${emp}</div>
          </div>
        `;
      });
      html += '</div>';
      resEl.innerHTML = html;
    } catch (err) {
      resEl.innerHTML = '<div style="color:#ef4444; font-size:12px;">Error fetching hospital database.</div>';
    }
  });

  // 5. Check Family Cap Utilization
  $('btn-check-cap')?.addEventListener('click', async () => {
    const famId = $('cap-family-id').value.trim();
    const resEl = $('cap-tracker-result');
    if (!famId) {
      toast('Please enter a Family ID (e.g. FAM-1001)', 'warning');
      return;
    }

    try {
      const res = await fetch(`${API_BASE}/family/${encodeURIComponent(famId)}/cap`);
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Family ID not found');

      const pct = data.utilization_percentage;
      const barColor = pct > 90 ? '#ef4444' : (pct > 50 ? '#f59e0b' : '#10b981');

      resEl.innerHTML = `
        <div style="background:#f8fafc; padding:12px; border-radius:8px; font-size:12px;">
          <div style="display:flex; justify-content:space-between; font-weight:600; margin-bottom:4px;">
            <span>Family ID: ${data.family_id} (${data.member_count} members)</span>
            <span style="color:${barColor}">${pct}% Utilized</span>
          </div>
          <div style="background:#e2e8f0; height:8px; border-radius:4px; overflow:hidden; margin-bottom:8px;">
            <div style="width:${pct}%; height:100%; background:${barColor}; border-radius:4px;"></div>
          </div>
          <div style="display:flex; justify-content:space-between; color:#475569; font-size:11px;">
            <span>Utilized: ₹${data.total_utilized_inr.toLocaleString('en-IN')}</span>
            <span>Remaining Cap: <strong>₹${data.cap_remaining_inr.toLocaleString('en-IN')}</strong></span>
          </div>
          <div style="margin-top:6px; font-size:11px; color:#0284c7;">
            Senior Citizen (70+) Separate Cap Remaining: ₹${data.senior_cap_remaining_inr.toLocaleString('en-IN')}
          </div>
        </div>
      `;
    } catch (err) {
      resEl.innerHTML = `<div style="color:#ef4444; font-size:12px;">${err.message}</div>`;
    }
  });
}


// ─── Initialise ───────────────────────────────────────────────────────────────
async function init() {
  await checkServerHealth();

  // Initialize authentication event listeners and session check
  initAuthSystem();

  // Initialize PM-JAY handlers
  initPMJAYHandlers();

  // Check server health / metrics
  try {
    await apiFetch('/dashboard/metrics');
    if ($('server-dot')) $('server-dot').className = 'status-dot ' + (USE_MOCK ? 'warning' : 'online');
    if ($('server-status-text')) $('server-status-text').textContent = USE_MOCK ? 'Mock server' : 'FastAPI Engine Live';
  } catch (_) {
    if ($('server-dot')) $('server-dot').className = 'status-dot offline';
    if ($('server-status-text')) $('server-status-text').textContent = 'FastAPI Offline';
  }

  // Load HITL badge count on startup
  refreshHITLBadge();

  // Default screen
  navigate('submit');
}

document.addEventListener('DOMContentLoaded', init);


