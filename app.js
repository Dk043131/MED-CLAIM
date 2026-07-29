/* ================================================================
   MED-CLAIM Frontend Application Logic
   ================================================================
   API Toggle: flip USE_MOCK = false to point at Person A's backend.
   API_BASE:   auto-detects localhost vs remote; change IP below.
   ================================================================ */

// ─── API Configuration ────────────────────────────────────────────────────────
const USE_MOCK = true; // ← set false to switch to Person A's real API

const API_BASE = (
  window.location.hostname === 'localhost' ||
  window.location.hostname === '127.0.0.1'
)
  ? '/api'
  : 'http://<person-a-machine-ip>:8000/api'; // ← update IP when deploying

// ─── App State ────────────────────────────────────────────────────────────────
const state = {
  currentScreen: 'submit',
  selectedFile: null,
  charts: { volume: null, status: null },
  surgeRunning: false,
  hitlClaims: [],
  dashMetrics: null,
};

// ─── Helpers ──────────────────────────────────────────────────────────────────
function $(id) { return document.getElementById(id); }

function toast(message, type = 'info', duration = 3500) {
  const container = $('toast-container');
  const el = document.createElement('div');
  el.className = `toast ${type}`;
  const icons = { success: '✅', error: '❌', info: 'ℹ️', warning: '⚠️' };
  el.innerHTML = `<span>${icons[type] || 'ℹ️'}</span><span>${message}</span>`;
  container.appendChild(el);
  setTimeout(() => {
    el.classList.add('toast-exit');
    setTimeout(() => el.remove(), 400);
  }, duration);
}

async function apiFetch(path, options = {}) {
  const url = API_BASE + path;
  try {
    const res = await fetch(url, {
      headers: { 'Content-Type': 'application/json', ...options.headers },
      ...options,
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return await res.json();
  } catch (err) {
    console.error('API error:', url, err);
    throw err;
  }
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
  dashboard: { el: 'screen-dashboard', title: 'Observability Dashboard', sub: 'Live metrics for the claims processing pipeline' },
  pitch:     { el: 'screen-pitch',     title: 'Pitch Prep',            sub: 'Demo script, verification checklist, and Q&A preparation' },
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
  if (screenId === 'dashboard') loadDashboard();
}

// Wire nav clicks
['submit', 'hitl', 'dashboard', 'pitch'].forEach(id => {
  const el = $('nav-' + id);
  if (!el) return;
  el.addEventListener('click', () => navigate(id));
  el.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') navigate(id); });
});

$('btn-refresh').addEventListener('click', () => {
  if (state.currentScreen === 'hitl')      loadHITLQueue();
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
  await runDemoSubmission('mock_bill_clean.png', 'image/png');
});
$('btn-demo-messy').addEventListener('click', async () => {
  await runDemoSubmission('mock_bill_messy.png', 'image/png');
});

async function runDemoSubmission(filename, fileType) {
  // Set preview
  uploadPreview.style.display = 'block';
  $('preview-name').textContent = filename;
  $('preview-size').textContent = 'Demo file';
  $('preview-thumb').src = '/assets/' + filename;
  resetPipeline();

  // Trigger submit with a fake file descriptor (base64 is empty placeholder for demo)
  await submitClaim(filename, fileType, '');
}

// ── Submit button ──
$('btn-submit').addEventListener('click', async () => {
  if (!state.selectedFile) return;
  const file = state.selectedFile;

  // Read file as base64
  const reader = new FileReader();
  reader.onload = async (e) => {
    const base64 = e.target.result.split(',')[1] || '';
    await submitClaim(file.name, file.type, base64);
  };
  reader.readAsDataURL(file);
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
    dot.innerHTML = '✓';
    prev.querySelector('.step-sublabel').textContent = 'Complete';
  }

  // Mark current
  const isLast = stageIndex === STAGES.length - 1;
  if (isLast && finalStatus === 'FLAGGED') {
    el.className = 'pipeline-step flagged';
    el.querySelector('.step-dot').innerHTML = '⚑';
    el.querySelector('.step-sublabel').textContent = 'Flagged';
  } else if (isLast) {
    el.className = 'pipeline-step done';
    el.querySelector('.step-dot').innerHTML = '✓';
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
  const isApproved = claim.status === 'APPROVED';

  rc.className = 'result-card show ' + (isApproved ? 'approved' : 'flagged');
  $('result-icon').textContent  = isApproved ? '✅' : '⚑';
  $('result-title').textContent = isApproved ? 'Auto-Approved' : 'Flagged for Caseworker Review';
  $('result-id').textContent    = claim.id;
  $('result-body').textContent  = isApproved
    ? `Claim auto-adjudicated with ${formatConf(claim.confidence_score)} confidence. Eligible under ${claim.eligibility_result?.scheme || 'government scheme'} (${claim.eligibility_result?.coverage_percent || 0}% coverage).`
    : `OCR confidence ${formatConf(claim.confidence_score)} — below auto-approval threshold. This claim has been routed to the HITL review queue.`;

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

async function submitClaim(filename, fileType, base64Data) {
  const btn = $('btn-submit');
  if (btn) { btn.disabled = true; btn.innerHTML = '<div class="spinner"></div> Processing…'; }

  resetPipeline();

  try {
    // Animate stages up to DECISION
    let claimResult = null;
    for (let i = 0; i < STAGES.length; i++) {
      // Don't animate last step until response arrives
      if (i < STAGES.length - 1) {
        activateStep(i, null);
        await delay(STAGE_DELAYS[i + 1] - STAGE_DELAYS[i]);
      }
    }

    // POST to API (base64 JSON)
    const data = await apiFetch('/claims/submit', {
      method: 'POST',
      body: JSON.stringify({ filename, file_type: fileType, file_data: base64Data }),
    });
    claimResult = data.claim;

    // Animate final DECISION step
    activateStep(STAGES.length - 1, claimResult.status);

    // Complete line
    const line = $('pipeline-line');
    if (line) line.style.width = '100%';

    // Show result card
    setTimeout(() => showResult(claimResult), 400);

    const isApproved = claimResult.status === 'APPROVED';
    toast(
      isApproved ? `Claim ${claimResult.id} auto-approved ✅` : `Claim flagged for review — added to HITL queue ⚑`,
      isApproved ? 'success' : 'warning',
      4000
    );

    // Update HITL badge
    refreshHITLBadge();

  } catch (err) {
    toast('Failed to submit claim. Is the mock server running? (python server.py)', 'error');
    console.error(err);
  } finally {
    if (btn) { btn.disabled = false; btn.innerHTML = '<span>🚀</span> Process Claim'; }
  }
}

function delay(ms) { return new Promise(res => setTimeout(res, ms)); }

// ─── Screen 2: HITL Review Queue ──────────────────────────────────────────────
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
    $('hitl-loading').innerHTML = '<span style="color:var(--rose)">⚠ Could not load queue — is the server running?</span>';
    console.error(err);
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
      <td><span class="expand-icon">▼</span></td>
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
        <button class="btn btn-success" id="approve-btn-${claim.id}" aria-label="Approve claim ${claim.id}">✓ Approve</button>
      </td>`;

    // Detail row
    const detailTr = document.createElement('tr');
    detailTr.className = 'claim-detail-row';
    detailTr.id = `detail-${claim.id}`;
    detailTr.innerHTML = `<td colspan="7">
      <div class="claim-detail-inner">
        <div class="detail-panel">
          <div class="detail-panel-title">📷 Original Document</div>
          <img class="bill-image" src="${claim.image_url || '/assets/mock_bill_messy.png'}" alt="Original bill for ${claim.patient_name}" />
          <div class="flags-section">
            <div class="detail-panel-title" style="margin-top:12px">⚑ Flag Reasons</div>
            ${(claim.flags || []).map(f =>
              `<div class="flag-reason-item"><span class="icon">⚑</span>${f}</div>`
            ).join('')}
          </div>
        </div>
        <div class="detail-panel">
          <div class="detail-panel-title">📋 Extracted JSON</div>
          <div class="json-viewer">${syntaxHighlightJSON(claim.extracted_json || {})}</div>
          <div class="detail-panel-title" style="margin-top:12px">🧬 ICD-10 Candidates</div>
          <div class="icd-chips" style="margin-top:4px">
            ${(claim.icd_codes || []).map(icd =>
              `<div class="icd-chip">
                <span class="icd-code">${icd.code}</span>
                <span class="icd-desc">${icd.description}</span>
                <span class="icd-conf">${formatConf(icd.confidence)}</span>
              </div>`
            ).join('')}
          </div>
          <div class="detail-panel-title" style="margin-top:12px">📜 Audit Trail</div>
          <div class="audit-mini">
            ${(claim.audit_log || []).map(entry =>
              `<div class="audit-entry">
                <span class="audit-stage">${entry.stage}</span>
                <span class="audit-note">${entry.note}</span>
              </div>`
            ).join('')}
          </div>
          <div class="detail-actions" style="margin-top:16px">
            <button class="btn btn-success" id="approve-detail-btn-${claim.id}" aria-label="Approve claim ${claim.id} from detail view">✓ Approve Claim</button>
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

    // Approve buttons (both in row and detail panel)
    [`approve-btn-${claim.id}`, `approve-detail-btn-${claim.id}`].forEach(btnId => {
      const el = document.getElementById(btnId);
      if (el) el.addEventListener('click', () => approveClaim(claim.id));
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

async function approveClaim(claimId) {
  const btns = [
    document.getElementById(`approve-btn-${claimId}`),
    document.getElementById(`approve-detail-btn-${claimId}`),
  ];
  btns.forEach(b => { if (b) { b.disabled = true; b.innerHTML = '<div class="spinner"></div>'; } });

  try {
    await apiFetch(`/claims/${claimId}/approve`, { method: 'POST', body: '{}' });

    toast(`Claim ${claimId} approved ✅ — removed from review queue`, 'success');

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
      $('queue-count-num').textContent = state.hitlClaims.length;
      if (state.hitlClaims.length === 0) {
        $('hitl-table').style.display = 'none';
        $('hitl-empty').style.display = 'block';
      }
      // Refresh dashboard metrics silently
      refreshDashboardMetrics();
    }, 500);

  } catch (err) {
    toast('Failed to approve claim — check server', 'error');
    btns.forEach(b => { if (b) { b.disabled = false; b.innerHTML = '✓ Approve'; } });
  }
}

// ─── Screen 3: Observability Dashboard ────────────────────────────────────────
async function loadDashboard() {
  try {
    const data = await apiFetch('/dashboard/metrics');
    state.dashMetrics = data;
    renderDashboardMetrics(data);
    renderCharts(data);
    renderRecentClaims();
  } catch (err) {
    toast('Could not load dashboard metrics — is the server running?', 'error');
    console.error(err);
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
      plugins: { legend: { labels: { color: '#94a3b8', font: { family: 'Inter', size: 12 } } } },
      scales: {
        x: { stacked: true, ticks: { color: '#475569' }, grid: { color: 'rgba(255,255,255,0.04)' } },
        y: { stacked: true, ticks: { color: '#475569' }, grid: { color: 'rgba(255,255,255,0.06)' } },
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
          'rgba(16,185,129,0.85)',
          'rgba(245,158,11,0.85)',
          'rgba(244,63,94,0.85)',
        ],
        borderColor: '#0a1628',
        borderWidth: 3,
        hoverBorderWidth: 5,
      }],
    },
    options: {
      responsive: true, maintainAspectRatio: false, cutout: '65%',
      plugins: {
        legend: { position: 'bottom', labels: { color: '#94a3b8', font: { family: 'Inter', size: 12 }, padding: 16 } },
      },
    },
  });
}

function updateCharts(m) {
  if (!state.charts.volume || !state.charts.status) {
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
}

async function renderRecentClaims() {
  // Pull 5 most recent from review queue + reconstruct from available data
  try {
    const data = await apiFetch('/dashboard/metrics');
    // We don't have a /recent endpoint — just show queue for now
    // In real integration this would be GET /claims?limit=5&sort=recent
  } catch (_) {}
}

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

// ─── Initialise ───────────────────────────────────────────────────────────────
async function init() {
  // Check server health
  try {
    await apiFetch('/dashboard/metrics');
    $('server-dot').style.background   = 'var(--green)';
    $('server-status-text').textContent = USE_MOCK ? 'Mock server ✓' : 'Live API ✓';
  } catch (_) {
    $('server-dot').style.background   = 'var(--rose)';
    $('server-dot').style.animation    = 'none';
    $('server-status-text').textContent = 'Server offline';
    toast('⚠ Mock server not detected. Run: python server.py', 'warning', 8000);
  }

  // Load HITL badge count on startup
  refreshHITLBadge();

  // Default screen
  navigate('submit');
}

document.addEventListener('DOMContentLoaded', init);
