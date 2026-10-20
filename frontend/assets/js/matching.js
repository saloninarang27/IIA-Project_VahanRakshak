/**
 * Approximate Vehicle Matching & Data Cleansing controller
 */
const TESSERACT_JS_URL = 'https://cdn.jsdelivr.net/npm/tesseract.js@5.1.1/dist/tesseract.min.js';
const PLATE_CHARSET = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789';

const SAMPLE_IMAGES = [
  { file: 'plate_clean_DL01AB1001.png', label: 'Clean' },
  { file: 'plate_blurred_DL01AB1004.png', label: 'Blurred' },
  { file: 'plate_stylised_DL01AB1008.png', label: 'Stylised O-for-0' },
  { file: 'plate_skewed_DL01AB1234.png', label: 'Skewed' },
  { file: 'plate_unregistered_MH12XY4821.png', label: 'Unregistered' },
];

const EXAMPLE_PLATES = ['DL01AB1O01', 'dl 0I-ab 1004', 'DL01A8IOO8', 'DL01AB123', 'MH12XY4821'];

// Fixed method -> colour mapping (colour follows the entity, never its rank)
const METHOD_STYLE = {
  ocr_weighted: { color: 'var(--series-ocr)', short: 'OCR-weighted' },
  hybrid: { color: 'var(--series-hybrid)', short: 'Hybrid' },
  levenshtein: { color: 'var(--series-lev)', short: 'Levenshtein' },
  jaro_winkler: { color: 'var(--series-jw)', short: 'Jaro–Winkler' },
};
const METHOD_ORDER = ['ocr_weighted', 'hybrid', 'levenshtein', 'jaro_winkler'];

const DECISION_BADGE = {
  ACCEPTED: ['badge-success', '✅ Accepted'],
  CORRECTED: ['badge-info', '✏️ Corrected'],
  PENDING_REVIEW: ['badge-warning', '⚠️ Review'],
  REJECTED: ['badge-danger', '⛔ Rejected'],
  REVIEWED_ACCEPTED: ['badge-success', '👤 Accepted'],
  REVIEWED_CORRECTED: ['badge-info', '👤 Corrected'],
  REVIEWED_REJECTED: ['badge-danger', '👤 Rejected'],
};

let matchingConfig = null;
let lastOcr = null;
let auditOffset = 0;
let evaluationLoaded = false;
let tesseractWorker = null;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
function esc(v) {
  if (v === null || v === undefined) return '';
  return String(v).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

function normalizePlate(raw) {
  return (raw || '').toUpperCase().replace(/[^A-Z0-9]/g, '');
}

function fmt(n, d = 3) {
  return (n === null || n === undefined) ? '—' : Number(n).toFixed(d);
}

function decisionBadge(status) {
  if (!status) return '<span class="badge" style="background:var(--bg-muted); color:var(--text-muted);">Unprocessed</span>';
  const [cls, label] = DECISION_BADGE[status] || ['badge-info', status];
  return `<span class="badge ${cls}">${label}</span>`;
}

function scoreCell(score) {
  if (score === null || score === undefined) return '<span class="score-num">—</span>';
  const pct = Math.max(0, Math.min(1, score)) * 100;
  return `<div class="score-cell"><div class="score-bar"><span style="width:${pct}%"></span></div><span class="score-num">${fmt(score)}</span></div>`;
}

const OCR_PAIRS = new Set(['0O', '0D', '0Q', '1I', '1L', '1T', '2Z', '4A', '5S', '6G', '7T', '8B',
  'OD', 'OQ', 'DQ', 'IL', 'IT', 'UV', 'MN', 'EF', 'PR', 'CG', 'KX', 'HN']);
function isConfusable(a, b) {
  return OCR_PAIRS.has(a + b) || OCR_PAIRS.has(b + a);
}

/**
 * Render `target` with the characters that differ from `source` highlighted
 * (Levenshtein alignment): amber = OCR-confusable substitution, red = other edit.
 */
function renderPlateDiff(source, target) {
  if (!target) return '<span class="plate-text">—</span>';
  if (!source) return `<span class="plate-text">${esc(target)}</span>`;
  const n = source.length, m = target.length;
  const dp = Array.from({ length: n + 1 }, (_, i) => Array.from({ length: m + 1 }, (_, j) => (i === 0 ? j : j === 0 ? i : 0)));
  for (let i = 1; i <= n; i++) {
    for (let j = 1; j <= m; j++) {
      dp[i][j] = Math.min(dp[i - 1][j] + 1, dp[i][j - 1] + 1, dp[i - 1][j - 1] + (source[i - 1] === target[j - 1] ? 0 : 1));
    }
  }
  const out = [];
  let i = n, j = m;
  while (j > 0) {
    if (i > 0 && dp[i][j] === dp[i - 1][j - 1] + (source[i - 1] === target[j - 1] ? 0 : 1)) {
      const ch = esc(target[j - 1]);
      if (source[i - 1] === target[j - 1]) out.push(ch);
      else out.push(`<span class="${isConfusable(source[i - 1], target[j - 1]) ? 'ch-ocr' : 'ch-edit'}" title="${esc(source[i - 1])} → ${ch}">${ch}</span>`);
      i--; j--;
    } else if (i > 0 && dp[i][j] === dp[i - 1][j] + 1) {
      i--; // character dropped from source
    } else {
      out.push(`<span class="ch-ins" title="inserted">${esc(target[j - 1])}</span>`);
      j--;
    }
  }
  return `<span class="plate-text">${out.reverse().join('')}</span>`;
}

function contextPills(context) {
  if (!context || !context.attributes) return '';
  return Object.entries(context.attributes).map(([attr, c]) => {
    const label = { make: 'Make', model: 'Model', color: 'Colour', vehicle_type: 'Type' }[attr] || attr;
    const title = c.status === 'MISSING' ? 'not observed' : `observed "${c.observed}" vs registered "${c.registered}"`;
    return `<span class="ctx-pill ctx-${c.status}" title="${esc(title)}">${label} ${c.status === 'MATCH' ? '✓' : c.status === 'MISMATCH' ? '✗' : '?'}</span>`;
  }).join('');
}

function setModalWide(wide) {
  const card = document.getElementById('app-modal-card');
  if (card) card.classList.toggle('wide', wide);
}

// ---------------------------------------------------------------------------
// Init
// ---------------------------------------------------------------------------
document.addEventListener('DOMContentLoaded', async () => {
  document.querySelectorAll('.tab-btn').forEach(btn => btn.addEventListener('click', () => switchTab(btn.dataset.tab)));

  const sampleRow = document.getElementById('sample-row');
  SAMPLE_IMAGES.forEach(s => {
    const chip = document.createElement('button');
    chip.className = 'chip';
    chip.type = 'button';
    chip.textContent = s.label;
    chip.addEventListener('click', () => loadSample(s.file));
    sampleRow.appendChild(chip);
  });

  const examples = document.getElementById('example-chips');
  EXAMPLE_PLATES.forEach(p => {
    const chip = document.createElement('button');
    chip.className = 'chip';
    chip.type = 'button';
    chip.textContent = p;
    chip.addEventListener('click', () => {
      lastOcr = null;
      document.getElementById('plate-input').value = p;
      updateNormalizedPreview();
      runMatch();
    });
    examples.appendChild(chip);
  });

  const fileInput = document.getElementById('plate-file');
  const dropzone = document.getElementById('dropzone');
  fileInput.addEventListener('change', () => fileInput.files[0] && handleImage(fileInput.files[0]));
  ['dragenter', 'dragover'].forEach(ev => dropzone.addEventListener(ev, e => { e.preventDefault(); dropzone.classList.add('dragover'); }));
  ['dragleave', 'drop'].forEach(ev => dropzone.addEventListener(ev, e => { e.preventDefault(); dropzone.classList.remove('dragover'); }));
  dropzone.addEventListener('drop', e => {
    const file = e.dataTransfer.files && e.dataTransfer.files[0];
    if (file) handleImage(file);
  });

  const plateInput = document.getElementById('plate-input');
  plateInput.addEventListener('input', () => { lastOcr = null; updateNormalizedPreview(); });
  plateInput.addEventListener('keydown', e => { if (e.key === 'Enter') runMatch(); });
  document.getElementById('btn-match').addEventListener('click', runMatch);

  document.getElementById('records-status').addEventListener('change', loadRecords);
  document.getElementById('records-source').addEventListener('change', loadRecords);
  document.getElementById('show-labels').addEventListener('change', loadRecords);
  document.getElementById('btn-cleanse').addEventListener('click', () => cleanse(false));
  document.getElementById('btn-reprocess').addEventListener('click', () => cleanse(true));
  document.getElementById('btn-run-eval').addEventListener('click', runEvaluation);
  document.getElementById('btn-audit-more').addEventListener('click', () => loadAudit(true));
  document.getElementById('btn-refresh-index').addEventListener('click', refreshPlateIndex);
  document.getElementById('btn-agency-scan').addEventListener('click', scanAgency);
  document.getElementById('btn-agency-cleanse').addEventListener('click', cleanseAgency);

  await loadConfig();
  const initial = new URLSearchParams(window.location.search);
  if (initial.get('tab')) switchTab(initial.get('tab'));
  if (initial.get('plate')) {
    plateInput.value = initial.get('plate');
    updateNormalizedPreview();
    runMatch();
  }
});

function switchTab(tab) {
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.toggle('active', b.dataset.tab === tab));
  document.querySelectorAll('.tab-panel').forEach(p => p.classList.toggle('active', p.id === `tab-${tab}`));
  if (tab === 'records') loadRecords();
  if (tab === 'agency') scanAgency();
  if (tab === 'eval' && !evaluationLoaded) loadEvaluation();
  if (tab === 'audit') loadAudit(false);
}

async function loadConfig() {
  const meta = document.getElementById('index-meta');
  const { ok, data } = await API.getMatchingConfig().catch(err => ({ ok: false, data: { error: err.message } }));
  if (!ok) {
    meta.className = 'badge badge-danger';
    meta.textContent = `Matching API unavailable: ${data.error || 'mediator offline'}`;
    return;
  }
  matchingConfig = data;
  const sources = data.index.sources || [];
  const live = sources.filter(s => s.via === 'API').length;
  meta.textContent = `${data.index.size.toLocaleString()} plates from ${sources.length} databases • ${live}/${sources.length} live`;
  meta.title = sources.map(s => `${s.label} (${s.identifier_column}): ${s.plates} plates via ${s.via}${s.error ? ' - ' + s.error : ''}`).join('\n');
  meta.className = live === sources.length ? 'badge badge-success' : 'badge badge-warning';

  const select = document.getElementById('method-select');
  select.innerHTML = data.methods.map(m =>
    `<option value="${m.key}" ${m.key === data.default_method ? 'selected' : ''}>${esc(m.label)}${m.key === data.default_method ? ' ★' : ''}</option>`).join('');
  document.getElementById('threshold-input').value = data.thresholds.candidate.toFixed(2);
}

// ---------------------------------------------------------------------------
// Scan: image upload + OCR
// ---------------------------------------------------------------------------
async function loadSample(file) {
  const res = await fetch(`/assets/samples/${file}`);
  const blob = await res.blob();
  handleImage(new File([blob], file, { type: blob.type || 'image/png' }));
}

function updateNormalizedPreview() {
  const v = normalizePlate(document.getElementById('plate-input').value);
  document.getElementById('normalized-preview').textContent = v || '—';
}

async function handleImage(file) {
  const content = document.getElementById('dropzone-content');
  const meta = document.getElementById('ocr-meta');
  const url = URL.createObjectURL(file);
  content.innerHTML = `<div class="ocr-preview"><img src="${url}" alt="Uploaded plate" id="ocr-preview-img"></div><span style="font-size:0.78rem;">${esc(file.name)} — click to replace</span>`;
  meta.innerHTML = '<span class="spinner-inline"></span> Running OCR on the server…';
  clearScanResult('Reading the plate…');

  let result = null;
  try {
    const { ok, status, data } = await API.ocrPlateImage(file);
    if (ok) {
      result = { engine: `server: ${data.engine}`, raw_text: data.raw_text, confidence: data.confidence,
        box: data.plate_box, imageSize: data.image_size, alternatives: data.alternatives || [],
        detections: (data.detections || []).length };
    } else if (status === 501) {
      meta.innerHTML = '<span class="spinner-inline"></span> No server OCR engine installed — running Tesseract.js in the browser (first run downloads ~10 MB)…';
      result = await browserOcr(file, meta);
    } else {
      throw new Error(data.error || `HTTP ${status}`);
    }
  } catch (err) {
    meta.innerHTML = `<span style="color:var(--status-danger);">OCR failed: ${esc(err.message)}. Type the plate manually below.</span>`;
    return;
  }

  lastOcr = { engine: result.engine, raw_text: result.raw_text, confidence: result.confidence, file: file.name };
  document.getElementById('plate-input').value = result.raw_text.trim();
  updateNormalizedPreview();
  drawPlateBox(result.box, result.imageSize);
  meta.innerHTML = `OCR engine <strong>${esc(result.engine)}</strong> • plate text <span class="plate-text">"${esc(result.raw_text.trim())}"</span> • confidence ${fmt(result.confidence, 2)}`
    + (result.detections ? ` • ${result.detections} text region(s) found` : '');
  if (result.alternatives && result.alternatives.length) {
    meta.innerHTML += '<br>Other readings: ';
    result.alternatives.slice(0, 3).forEach(a => {
      const chip = document.createElement('button');
      chip.type = 'button';
      chip.className = 'chip';
      chip.style.cssText = 'font-size:0.7rem; padding:0.1rem 0.5rem; margin-right:0.3rem;';
      chip.textContent = a.normalized;
      chip.addEventListener('click', () => useOcrAlternative(a.text));
      meta.appendChild(chip);
    });
  }
  if (!normalizePlate(result.raw_text)) {
    meta.insertAdjacentHTML('beforeend', ' — <span style="color:var(--status-danger);">no plate-like text found; type the plate manually below</span>');
    clearScanResult('No plate could be read from this image. Type the registration number in step 2.');
    return;
  }
  runMatch();
}

// Never leave the previous plate's decision on screen next to a new image
function clearScanResult(message) {
  document.getElementById('scan-result').innerHTML = `<div class="empty-note">${esc(message)}</div>`;
}

function loadScript(src) {
  return new Promise((resolve, reject) => {
    if (document.querySelector(`script[src="${src}"]`)) return resolve();
    const s = document.createElement('script');
    s.src = src;
    s.onload = resolve;
    s.onerror = () => reject(new Error('could not load Tesseract.js (offline?)'));
    document.head.appendChild(s);
  });
}

async function browserOcr(file, meta) {
  await loadScript(TESSERACT_JS_URL);
  if (!tesseractWorker) {
    tesseractWorker = await Tesseract.createWorker('eng', 1, {
      logger: m => {
        if (m.status && typeof m.progress === 'number') {
          meta.innerHTML = `<span class="spinner-inline"></span> Tesseract.js: ${esc(m.status)} ${Math.round(m.progress * 100)}%`;
        }
      },
    });
    // Sparse text: find text anywhere in the photo instead of treating it as one line.
    // No character whitelist - lower-case output is how watermarks and brand names get filtered out.
    await tesseractWorker.setParameters({ tessedit_pageseg_mode: '11' });
  }
  const { data } = await tesseractWorker.recognize(file);
  const detections = (data.words || []).map(w => ({
    text: w.text, confidence: (w.confidence || 0) / 100, box: [w.bbox.x0, w.bbox.y0, w.bbox.x1, w.bbox.y1],
  }));
  const selected = selectPlateText(detections);
  const img = document.getElementById('ocr-preview-img');
  return {
    engine: 'browser: tesseract.js', raw_text: selected.text, confidence: selected.confidence,
    box: selected.box, imageSize: img ? [img.naturalWidth, img.naturalHeight] : null,
    alternatives: selected.alternatives, detections: detections.length,
  };
}

/* ---- Plate selection: JS port of select_plate_text() in matching/ocr.py ---- */
const INDIAN_PLATE_RE = /^[A-Z]{2}\d{1,2}[A-Z]{1,3}\d{1,4}$/;
const BH_SERIES_RE = /^\d{2}BH\d{4}[A-Z]{1,2}$/;

function plateScore(text, height, maxHeight, confidence) {
  const norm = normalizePlate(text);
  if (norm.length < 4 || norm.length > 11 || !/\d/.test(norm)) return null;
  let score = height / maxHeight + 0.3 * confidence;
  if (/[A-Z]/.test(norm)) score += 0.15;
  score += 0.02 * norm.length;
  if (INDIAN_PLATE_RE.test(norm) || BH_SERIES_RE.test(norm)) score += 0.35;
  return score;
}

function joinRun(run) {
  const parts = [run[0].text];
  for (let i = 1; i < run.length; i++) {
    const a = run[i - 1];
    let textB = run[i].text;
    const overlap = a.x1 - run[i].x0;
    const normA = normalizePlate(a.text);
    if (overlap > 0 && normA) {
      const charWidth = (a.x1 - a.x0) / normA.length;
      for (let k = Math.min(3, normA.length); k > 0; k--) {
        const stripped = textB.replace(/^[\s.-]+/, '');
        const head = normalizePlate(stripped.slice(0, k));
        if (overlap >= 0.4 * k * charWidth && head.length === k && head === normA.slice(-k)) {
          textB = stripped.slice(k);
          break;
        }
      }
    }
    parts.push(textB.trim());
  }
  return parts.filter(Boolean).join(' ');
}

function selectPlateText(detections) {
  const empty = { text: '', confidence: 0, box: null, alternatives: [] };
  const items = detections
    // drop border strokes ("|") and real words (watermarks, brand names); short tokens such
    // as "lA" are kept because OCR often reads plate fragments in lower case
    .filter(d => normalizePlate(d.text))
    .filter(d => {
      const letters = d.text.match(/[A-Za-z]/g) || [];
      return letters.length < 4 || (d.text.match(/[a-z]/g) || []).length <= letters.length / 2;
    })
    .map(d => ({
      text: d.text.trim(), confidence: d.confidence, box: d.box, x0: d.box[0], x1: d.box[2],
      height: Math.max(1, d.box[3] - d.box[1]), cy: (d.box[1] + d.box[3]) / 2,
    }));
  if (!items.length) return empty;
  const maxHeight = Math.max(...items.map(i => i.height));

  // Group detections into rows: similar vertical centre and similar height
  const rows = [];
  [...items].sort((a, b) => b.height - a.height).forEach(d => {
    const row = rows.find(r => Math.abs(d.cy - r[0].cy) < 0.4 * r[0].height
      && d.height / r[0].height >= 0.6 && d.height / r[0].height <= 1.67);
    if (row) row.push(d); else rows.push([d]);
  });

  // Score every run of adjacent boxes in each row
  const candidates = [];
  rows.forEach(row => {
    row.sort((a, b) => a.x0 - b.x0);
    for (let start = 0; start < row.length; start++) {
      for (let end = start + 1; end <= row.length; end++) {
        const run = row.slice(start, end);
        const last = run[run.length - 1];
        const prev = run[run.length - 2];
        if (prev && last.x0 - prev.x1 > 1.5 * prev.height) break;
        const text = joinRun(run);
        const height = run.reduce((sum, r) => sum + r.height, 0) / run.length;
        const weights = run.map(r => Math.max(1, normalizePlate(r.text).length));
        const confidence = run.reduce((sum, r, i) => sum + r.confidence * weights[i], 0) / weights.reduce((a, b) => a + b, 0);
        const score = plateScore(text, height, maxHeight, confidence);
        if (score === null) continue;
        candidates.push({
          text, normalized: normalizePlate(text), confidence, score,
          box: [Math.min(...run.map(r => r.box[0])), Math.min(...run.map(r => r.box[1])),
            Math.max(...run.map(r => r.box[2])), Math.max(...run.map(r => r.box[3]))],
        });
      }
    }
  });
  if (!candidates.length) return empty;
  candidates.sort((a, b) => (b.score - a.score) || (b.normalized.length - a.normalized.length));
  const seen = new Set();
  const unique = candidates.filter(c => {
    if (seen.has(c.normalized)) return false;
    seen.add(c.normalized);
    return true;
  });
  const best = unique[0];
  return {
    text: best.text, confidence: best.confidence, box: best.box,
    alternatives: unique.slice(1, 5).map(c => ({ text: c.text, normalized: c.normalized, score: c.score })),
  };
}

function drawPlateBox(box, imageSize) {
  const wrap = document.querySelector('.ocr-preview');
  if (!wrap) return;
  wrap.querySelectorAll('.ocr-box').forEach(el => el.remove());
  if (!box || !imageSize || !imageSize[0]) return;
  const [w, h] = imageSize;
  const el = document.createElement('div');
  el.className = 'ocr-box';
  el.style.left = `${(box[0] / w) * 100}%`;
  el.style.top = `${(box[1] / h) * 100}%`;
  el.style.width = `${((box[2] - box[0]) / w) * 100}%`;
  el.style.height = `${((box[3] - box[1]) / h) * 100}%`;
  wrap.appendChild(el);
}

function useOcrAlternative(text) {
  document.getElementById('plate-input').value = text;
  updateNormalizedPreview();
  if (lastOcr) lastOcr.raw_text = text;
  runMatch();
}

// ---------------------------------------------------------------------------
// Scan: match + decision rendering
// ---------------------------------------------------------------------------
async function runMatch() {
  const plate = document.getElementById('plate-input').value;
  const out = document.getElementById('scan-result');
  if (!plate.trim()) {
    out.innerHTML = '<div class="empty-note">Enter or scan a registration number first.</div>';
    return;
  }
  out.innerHTML = '<div class="empty-note"><span class="spinner-inline"></span> Scoring against every registered vehicle…</div>';
  const payload = {
    plate,
    make: document.getElementById('ctx-make').value.trim(),
    model: document.getElementById('ctx-model').value.trim(),
    color: document.getElementById('ctx-color').value.trim(),
    vehicle_type: document.getElementById('ctx-type').value,
    method: document.getElementById('method-select').value,
    threshold: parseFloat(document.getElementById('threshold-input').value) || undefined,
    limit: 25,
    log: document.getElementById('log-decision').checked,
    source_system: lastOcr ? 'ANPR_UPLOAD' : 'MANUAL_ENTRY',
  };
  if (lastOcr) payload.ocr = lastOcr;
  const { ok, data } = await API.searchPlate(payload).catch(err => ({ ok: false, data: { error: err.message } }));
  if (!ok) {
    out.innerHTML = `<div class="empty-note" style="color:var(--status-danger);">Matching failed: ${esc(data.error)}</div>`;
    return;
  }
  out.innerHTML = renderDecisionCard(data) + renderCandidateTable(data);
}

function renderDecisionCard(a, opts = {}) {
  const headline = {
    ACCEPT: 'Accepted — registered plate',
    CORRECT: 'Corrected to a registered plate',
    REVIEW: 'Flagged for human review',
    REJECT: 'Rejected — no plausible registered vehicle',
  }[a.decision];
  const shownPlate = a.corrected_plate || a.matched_plate;
  const finalLabel = a.corrected_plate ? 'Corrected registration' : (a.decision === 'ACCEPT' ? 'Matched registration' : 'Best candidate (not applied)');
  const flags = (a.flags || []).map(f => `<span class="badge badge-warning" style="font-size:0.7rem;">${esc(f)}</span>`).join('');
  return `
    <div class="decision-card d-${a.decision}">
      <div class="toolbar" style="margin:0;">
        <strong style="font-size:1.05rem;">${headline}</strong>
        <span>${decisionBadge(a.decision_status)} <span class="badge" style="background:var(--bg-muted); color:var(--text-secondary);">Rule ${esc(a.rule)} • ${esc(a.reason_code)}</span></span>
      </div>
      <div class="plate-compare">
        <div class="plate-box">
          <div class="mini-label">Original registration</div>
          <div class="plate-text plate-big">${esc(a.original_plate ?? '∅')}</div>
          <div class="ocr-meta" style="margin:0;">normalised: <span class="plate-text">${esc(a.normalized_plate || '—')}</span>${a.format_valid ? '' : ' • non-standard format'}</div>
        </div>
        <div class="arrow">→</div>
        <div class="plate-box">
          <div class="mini-label">${finalLabel}</div>
          <div class="plate-big">${shownPlate ? renderPlateDiff(a.normalized_plate, shownPlate) : '<span class="plate-text">—</span>'}</div>
          <div class="ocr-meta" style="margin:0;">${a.suggested_plate && !a.corrected_plate ? `suggested for reviewer: <span class="plate-text">${esc(a.suggested_plate)}</span>` : '&nbsp;'}</div>
        </div>
      </div>
      <div class="reason-text">${esc(a.reason)}</div>
      ${flags ? `<div class="flag-row">${flags}</div>` : ''}
      <div class="kv-grid">
        <div><div class="k">Matched vehicle ID</div><div class="v">${a.matched_vehicle_id ?? '—'}</div></div>
        <div><div class="k">Plate similarity</div><div class="v">${fmt(a.similarity_score)}</div></div>
        <div><div class="k">Context score</div><div class="v">${fmt(a.context_score)}</div></div>
        <div><div class="k">Combined score</div><div class="v">${fmt(a.combined_score)}</div></div>
        <div><div class="k">Method</div><div class="v">${esc(METHOD_STYLE[a.method]?.short || a.method)}</div></div>
        <div><div class="k">Plausible candidates</div><div class="v">${a.candidate_count}</div></div>
        ${opts.hideAudit ? '' : `<div><div class="k">Audit entry</div><div class="v">${a.audit_id ? `#${a.audit_id}` : 'not logged'}</div></div>`}
        ${a.latency_ms !== undefined ? `<div><div class="k">Latency</div><div class="v">${a.latency_ms} ms</div></div>` : ''}
      </div>
    </div>`;
}

const SOURCE_SHORT = { VAHAN: 'VAHAN', IIB: 'IIB', POLICE: 'Police', ANPR: 'ANPR', ECHALLAN: 'Challan' };

// One marker per agency database: filled = this plate exists in that database
function sourcePills(sources) {
  const have = new Set(sources || []);
  return Object.entries(SOURCE_SHORT).map(([key, label]) =>
    `<span class="src-pill ${have.has(key) ? 'src-yes' : 'src-no'}" title="${label}: ${have.has(key) ? 'plate found' : 'no record'}">${label}</span>`).join('');
}

function renderCandidateTable(a) {
  if (!a.candidates || !a.candidates.length) {
    return '<div class="empty-note">No registered vehicle within the candidate threshold.</div>';
  }
  const more = a.candidate_count > a.candidates.length ? ` (showing top ${a.candidates.length} of ${a.candidate_count})` : '';
  const rows = a.candidates.map(c => `
    <tr>
      <td>${c.rank}</td>
      <td>${renderPlateDiff(a.normalized_plate, c.plate)}${c.exact ? ' <span class="badge badge-success" style="font-size:0.65rem;">exact</span>' : ''}</td>
      <td class="mono">${c.vehicle_id ?? '—'}</td>
      <td class="src-cell">${sourcePills(c.sources)}</td>
      <td style="font-size:0.82rem;">${esc(c.make)} ${esc(c.model)}<br><span style="color:var(--text-muted);">${esc(c.color)} • ${esc(c.vehicle_type)}</span></td>
      <td>${contextPills(c.context)}</td>
      <td>${scoreCell(c.combined_score)}</td>
      <td class="mono">${fmt(c.scores.ocr_weighted)}</td>
      <td class="mono">${fmt(c.scores.levenshtein)}</td>
      <td class="mono">${fmt(c.scores.jaro_winkler)}</td>
      <td class="mono">${fmt(c.scores.hybrid)}</td>
      <td><a href="/pages/inspector.html?plate=${encodeURIComponent(c.plate)}" class="btn btn-secondary btn-sm" style="text-decoration:none;">Dossier</a></td>
    </tr>`).join('');
  return `
    <div class="section-title" style="margin-top:0;">Ranked candidates${more}</div>
    <div class="section-sub" style="margin-bottom:0.6rem;">
      Highlighted characters differ from the reading:
      <span class="plate-text"><span class="ch-ocr">amber</span></span> = OCR-confusable glyph,
      <span class="plate-text"><span class="ch-edit">red</span></span> = substitution,
      <span class="plate-text"><span class="ch-ins">blue</span></span> = insertion.
      Combined = 65% plate similarity + 35% contextual agreement when attributes are observed.
      Candidates are drawn from all five agency databases; <em>Found in</em> shows which ones hold each plate.
    </div>
    <div class="table-container">
      <table class="data-table">
        <thead><tr>
          <th>#</th><th>Plate</th><th>Vehicle ID</th><th>Found in</th><th>Vehicle</th><th>Context</th><th>Combined</th>
          <th>OCR-wtd</th><th>Levenshtein</th><th>Jaro–W.</th><th>Hybrid</th><th></th>
        </tr></thead>
        <tbody>${rows}</tbody>
      </table>
    </div>`;
}

// ---------------------------------------------------------------------------
// Noisy records
// ---------------------------------------------------------------------------
async function loadRecords() {
  const tbody = document.getElementById('records-tbody');
  const showLabels = document.getElementById('show-labels').checked;
  document.querySelectorAll('.label-col').forEach(el => { el.style.display = showLabels ? '' : 'none'; });
  const { ok, data } = await API.getNoisyRecords({
    status: document.getElementById('records-status').value,
    source: document.getElementById('records-source').value,
  }).catch(err => ({ ok: false, data: { error: err.message } }));
  if (!ok) {
    tbody.innerHTML = `<tr><td colspan="10" class="empty-note" style="color:var(--status-danger);">${esc(data.error)}</td></tr>`;
    return;
  }
  renderRecordsSummary(data.summary);
  if (!data.records.length) {
    tbody.innerHTML = '<tr><td colspan="10" class="empty-note">No records match this filter.</td></tr>';
    return;
  }
  tbody.innerHTML = data.records.map(r => {
    const observed = [r.make, r.model, r.color, r.vehicle_type].filter(Boolean).map(esc).join(' • ') || '<span style="color:var(--text-muted);">none</span>';
    const fixPlate = r.corrected_plate
      ? renderPlateDiff(r.normalized_plate, r.corrected_plate)
      : (r.suggested_plate ? `<span style="color:var(--text-muted); font-size:0.75rem;">suggest</span> ${renderPlateDiff(r.normalized_plate, r.suggested_plate)}` : '—');
    const agree = r.decision && r.expected_decision ? (r.decision === r.expected_decision ? '✓' : `✗ expected ${r.expected_decision}`) : '';
    return `
      <tr class="clickable" onclick="openRecord(${r.record_id})">
        <td class="mono">${r.record_id}</td>
        <td style="font-size:0.78rem;">${esc(r.source_system)}<br><span style="color:var(--text-muted);">${esc(r.source_reference)}</span></td>
        <td class="mono">${r.raw_plate === null ? '<em style="color:var(--text-muted);">NULL</em>' : `"${esc(r.raw_plate)}"`}</td>
        <td style="font-size:0.8rem;">${observed}</td>
        <td>${decisionBadge(r.decision_status)}</td>
        <td>${fixPlate}</td>
        <td class="mono">${r.matched_vehicle_id ?? '—'}</td>
        <td>${scoreCell(r.similarity_score)}</td>
        <td class="reason-col">${esc(r.reason_code || '')}</td>
        <td class="label-col" style="display:${showLabels ? '' : 'none'}; font-size:0.75rem;">${esc(r.scenario)}<br><span style="color:var(--text-muted);">${esc(agree)}</span></td>
      </tr>`;
  }).join('');
}

function renderRecordsSummary(s) {
  const by = s.by_status || {};
  const reviewed = (by.REVIEWED_ACCEPTED || 0) + (by.REVIEWED_CORRECTED || 0) + (by.REVIEWED_REJECTED || 0);
  const card = (cls, label, value, sub) => `
    <div class="stat-card ${cls}" style="padding:1rem;">
      <div class="stat-label">${label}</div>
      <div class="stat-value" style="font-size:1.6rem;">${value}</div>
      <div class="stat-subtext">${sub}</div>
    </div>`;
  document.getElementById('records-summary').innerHTML = [
    card('info', 'Staged records', s.staged_records, `${s.staged_records - s.processed} unprocessed`),
    card('success', 'Accepted', by.ACCEPTED || 0, 'exact registered plate'),
    card('info', 'Corrected', by.CORRECTED || 0, 'sufficient evidence'),
    card('warning', 'Pending review', by.PENDING_REVIEW || 0, 'conflict / ambiguity / weak evidence'),
    card('danger', 'Rejected', by.REJECTED || 0, 'missing or unregistered'),
    card('info', 'Human reviewed', reviewed, `${s.audit_entries} audit entries`),
  ].join('');
}

async function cleanse(reprocess) {
  const btn = document.getElementById(reprocess ? 'btn-reprocess' : 'btn-cleanse');
  const original = btn.innerHTML;
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner-inline"></span> Running…';
  const { ok, data } = await API.runCleansing({ reprocess }).catch(err => ({ ok: false, data: { error: err.message } }));
  btn.disabled = false;
  btn.innerHTML = original;
  setModalWide(false);
  if (!ok) {
    AppModal.alert('Cleansing failed', data.error, '❌');
    return;
  }
  const outcome = Object.entries(data.outcome).map(([k, v]) => `${k}: ${v}`).join('\n') || 'nothing to do';
  AppModal.alert('Cleansing complete',
    `${data.processed} record(s) assessed in ${data.duration_ms} ms using ${data.method}.\n` +
    `${data.skipped_human_reviewed} human-reviewed record(s) left untouched.\n\n${outcome}`, '🧹');
  loadRecords();
}

async function openRecord(id) {
  const overlay = AppModal.getOverlay();
  setModalWide(true);
  document.getElementById('app-modal-title').innerHTML = `<span>🧾</span> <span>Noisy record #${id}</span>`;
  document.getElementById('app-modal-body').innerHTML = '<div class="empty-note"><span class="spinner-inline"></span> Matching record against the registry…</div>';
  document.getElementById('app-modal-footer').innerHTML = '<button class="btn btn-secondary btn-sm" onclick="AppModal.close()">Close</button>';
  overlay.classList.add('active');

  const { ok, data } = await API.getNoisyRecord(id);
  if (!ok) {
    document.getElementById('app-modal-body').innerHTML = `<div class="empty-note" style="color:var(--status-danger);">${esc(data.error)}</div>`;
    return;
  }
  const r = data.record;
  const current = data.current_decision;
  const analysis = data.analysis;
  const candidateOptions = (analysis.candidates || []).slice(0, 10)
    .map(c => `<option value="${esc(c.plate)}">${esc(c.plate)} — #${c.vehicle_id} ${esc(c.make)} ${esc(c.model)}, ${esc(c.color)} (${fmt(c.combined_score)})</option>`).join('');

  const history = data.audit.map(h => `
    <tr>
      <td class="mono">#${h.audit_id}</td><td style="font-size:0.78rem;">${esc(h.created_at)}</td>
      <td>${decisionBadge(h.decision_status)}</td><td class="mono">${esc(h.corrected_plate || '—')}</td>
      <td style="font-size:0.78rem;">${esc(h.reason)}</td><td>${esc(h.decided_by)}</td>
      <td class="mono">${h.supersedes_audit_id ? '#' + h.supersedes_audit_id : '—'}</td>
    </tr>`).join('') || '<tr><td colspan="7" class="empty-note">No decisions recorded yet — run cleansing or review below.</td></tr>';

  document.getElementById('app-modal-body').innerHTML = `
    <div class="kv-grid" style="margin:0 0 1rem;">
      <div><div class="k">Source</div><div class="v">${esc(r.source_system)} • ${esc(r.source_reference)}</div></div>
      <div><div class="k">Observed at</div><div class="v">${esc(r.observed_at)}</div></div>
      <div><div class="k">Current status</div><div class="v">${decisionBadge(current?.decision_status)}</div></div>
      <div><div class="k">Test scenario (label)</div><div class="v" style="font-size:0.8rem;">${esc(r.scenario)}</div></div>
    </div>
    <div class="section-sub" style="margin-bottom:0.5rem;">Fresh rule-engine analysis (not yet saved):</div>
    ${renderDecisionCard(analysis, { hideAudit: true })}
    ${renderCandidateTable(analysis)}
    <div class="section-title">Review decision</div>
    <div class="form-row" style="grid-template-columns: 1fr 1fr 1fr;">
      <div><label class="mini-label" for="rv-action">Action</label>
        <select class="form-select" id="rv-action">
          <option value="CORRECT">Correct to registered plate</option>
          <option value="ACCEPT_ORIGINAL">Accept original</option>
          <option value="REJECT">Reject record</option>
        </select></div>
      <div><label class="mini-label" for="rv-plate">Corrected plate</label>
        <select class="form-select" id="rv-plate">${candidateOptions || '<option value="">No candidates</option>'}</select></div>
      <div><label class="mini-label" for="rv-reviewer">Reviewer ID</label>
        <input class="form-input" id="rv-reviewer" value="${esc(localStorageGet('reviewer') || 'officer.demo')}"></div>
    </div>
    <div style="margin-top:0.6rem;"><label class="mini-label" for="rv-note">Reason / note</label>
      <input class="form-input" id="rv-note" placeholder="e.g. verified against RC photo"></div>
    <div class="section-title">Audit history for this record</div>
    <div class="table-container"><table class="data-table">
      <thead><tr><th>Audit</th><th>Time</th><th>Status</th><th>Corrected</th><th>Reason</th><th>By</th><th>Supersedes</th></tr></thead>
      <tbody>${history}</tbody></table></div>`;

  if (analysis.suggested_plate || analysis.corrected_plate) {
    document.getElementById('rv-plate').value = analysis.corrected_plate || analysis.suggested_plate;
  }
  document.getElementById('app-modal-footer').innerHTML = `
    <button class="btn btn-secondary btn-sm" onclick="AppModal.close()">Close</button>
    <button class="btn btn-primary btn-sm" onclick="submitReview(${id})">Save review decision</button>`;
}

function localStorageGet(key) {
  try { return localStorage.getItem(`vr-matching-${key}`); } catch (e) { return null; }
}
function localStorageSet(key, value) {
  try { localStorage.setItem(`vr-matching-${key}`, value); } catch (e) { /* ignore */ }
}

async function submitReview(id) {
  const payload = {
    action: document.getElementById('rv-action').value,
    corrected_plate: document.getElementById('rv-plate').value,
    reviewer: document.getElementById('rv-reviewer').value.trim(),
    note: document.getElementById('rv-note').value.trim(),
  };
  localStorageSet('reviewer', payload.reviewer);
  const { ok, data } = await API.reviewNoisyRecord(id, payload);
  setModalWide(false);
  if (!ok) {
    AppModal.alert('Review not saved', data.error, '❌');
    return;
  }
  AppModal.alert('Review saved', `Audit entry #${data.audit_id} recorded — status ${data.current_decision.decision_status}.\nThe original record is unchanged.`, '✅');
  loadRecords();
}

// ---------------------------------------------------------------------------
// Evaluation
// ---------------------------------------------------------------------------
async function loadEvaluation() {
  const { ok, status, data } = await API.getMatchingEvaluation().catch(err => ({ ok: false, data: { error: err.message } }));
  if (!ok) {
    document.getElementById('eval-meta').textContent = status === 404
      ? 'No evaluation stored yet — run it (takes about 30 seconds).'
      : `Evaluation unavailable: ${data.error}`;
    document.getElementById('eval-body').innerHTML = '';
    return;
  }
  evaluationLoaded = true;
  renderEvaluation(data);
}

async function runEvaluation() {
  const btn = document.getElementById('btn-run-eval');
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner-inline"></span> Evaluating 4 methods × all queries…';
  const { ok, data } = await API.runMatchingEvaluation().catch(err => ({ ok: false, data: { error: err.message } }));
  btn.disabled = false;
  btn.innerHTML = '↻ Re-run evaluation (~30s)';
  if (!ok) {
    setModalWide(false);
    AppModal.alert('Evaluation failed', data.error, '❌');
    return;
  }
  evaluationLoaded = true;
  renderEvaluation(data);
}

function renderEvaluation(rep) {
  const sel = rep.methods[rep.selected_method];
  document.getElementById('eval-meta').innerHTML =
    `Run #${rep.run_id} • ${esc(rep.created_at)} • ${rep.query_count} labelled queries ` +
    `(${rep.positive_queries} noisy registered plates, ${rep.negative_queries} unregistered) against ${rep.reference_size.toLocaleString()} registered plates • ${rep.duration_s}s`;

  const methodRows = METHOD_ORDER.map(k => {
    const m = rep.methods[k];
    return `<tr class="${k === rep.selected_method ? 'selected-method' : ''}">
      <td><span class="swatch" style="display:inline-block; width:12px; height:3px; border-radius:2px; vertical-align:middle; background:${METHOD_STYLE[k].color}; margin-right:6px;"></span>${esc(m.label)}${k === rep.selected_method ? ' <span class="badge badge-success" style="font-size:0.65rem;">selected</span>' : ''}</td>
      <td class="mono">${fmt(m.best_threshold, 2)}</td>
      <td class="mono">${fmt(m.precision)}</td><td class="mono">${fmt(m.recall)}</td><td class="mono"><strong>${fmt(m.f1)}</strong></td>
      <td class="mono">${fmt(m.recall_at_5)}</td><td class="mono">${fmt(m.candidate_recall)}</td><td class="mono">${m.mean_candidates}</td>
      <td class="mono">${m.tp} / ${m.fp} / ${m.fn} / ${m.tn}</td>
    </tr>`;
  }).join('');

  const noiseRows = rep.noise_types.map(n => `
    <tr><td>${esc(n.noise_type)}<br><span style="color:var(--text-muted); font-size:0.75rem;">${esc(n.description)} (n=${n.count})</span></td>
    ${METHOD_ORDER.map(k => {
      const v = rep.methods[k].by_noise_type[n.noise_type];
      const best = Math.max(...METHOD_ORDER.map(x => rep.methods[x].by_noise_type[n.noise_type]));
      return `<td class="mono" style="${v === best ? 'font-weight:700;' : 'color:var(--text-muted);'}">${(v * 100).toFixed(0)}%</td>`;
    }).join('')}</tr>`).join('');

  const caseRows = rep.ocr_confusion_cases.map(c => `
    <tr><td class="mono">"${esc(c.raw)}"</td><td>${renderPlateDiff(c.normalized, c.truth)}</td>
    <td style="font-size:0.8rem;">${esc(c.description)}</td>
    ${METHOD_ORDER.map(k => {
      const r = c.methods[k];
      const tip = `top: ${r.top_plate} (${r.top_score}), ${r.tied_at_top} tied at top, true plate scored ${r.truth_score}`;
      return `<td title="${esc(tip)}">${r.resolved ? '<span class="badge badge-success">✓</span>' : `<span class="badge badge-danger">✗</span> <span style="font-size:0.72rem; color:var(--text-muted);">${r.tied_at_top > 1 ? r.tied_at_top + '-way tie' : esc(r.top_plate)}</span>`}</td>`;
    }).join('')}</tr>`).join('');

  const cl = rep.cleansing;
  const scenarioRows = cl ? Object.entries(cl.by_scenario).map(([s, v]) => `
    <tr><td>${esc(s)}</td><td>${decisionBadge({ ACCEPT: 'ACCEPTED', CORRECT: 'CORRECTED', REVIEW: 'PENDING_REVIEW', REJECT: 'REJECTED' }[v.expected])}</td>
    <td class="mono">${v.agree} / ${v.total}</td>
    <td style="font-size:0.8rem;">${Object.entries(v.decisions).map(([d, n]) => `${esc(d)}: ${n}`).join(', ')}</td></tr>`).join('') : '';

  const rules = (matchingConfig?.rules || []).map(r => `
    <tr><td class="mono">${esc(r.rule)}</td><td>${esc(r.condition)}</td><td>${decisionBadge({ ACCEPT: 'ACCEPTED', CORRECT: 'CORRECTED', REVIEW: 'PENDING_REVIEW', REJECT: 'REJECTED' }[r.decision])}</td><td class="mono" style="font-size:0.78rem;">${esc(r.reason_code)}</td></tr>`).join('');

  document.getElementById('eval-body').innerHTML = `
    <div class="stats-grid">
      <div class="stat-card success" style="padding:1rem;"><div class="stat-label">Selected method</div>
        <div class="stat-value" style="font-size:1.15rem;">${esc(METHOD_STYLE[rep.selected_method].short)}</div>
        <div class="stat-subtext">highest F1 at threshold ${fmt(sel.best_threshold, 2)}</div></div>
      <div class="stat-card info" style="padding:1rem;"><div class="stat-label">F1 (precision / recall)</div>
        <div class="stat-value" style="font-size:1.6rem;">${fmt(sel.f1)}</div>
        <div class="stat-subtext">P ${fmt(sel.precision)} • R ${fmt(sel.recall)}</div></div>
      <div class="stat-card info" style="padding:1rem;"><div class="stat-label">OCR-confusion queries resolved</div>
        <div class="stat-value" style="font-size:1.6rem;">${(sel.by_noise_type.ocr_1 * 100).toFixed(0)}% / ${(sel.by_noise_type.ocr_2 * 100).toFixed(0)}%</div>
        <div class="stat-subtext">1 / 2 glyph swaps (Levenshtein: ${(rep.methods.levenshtein.by_noise_type.ocr_1 * 100).toFixed(0)}% / ${(rep.methods.levenshtein.by_noise_type.ocr_2 * 100).toFixed(0)}%)</div></div>
      ${cl ? `<div class="stat-card success" style="padding:1rem;"><div class="stat-label">Cleansing decisions</div>
        <div class="stat-value" style="font-size:1.6rem;">${(cl.decision_agreement * 100).toFixed(0)}%</div>
        <div class="stat-subtext">agree with labels • correction precision ${cl.correction_precision === null ? '—' : (cl.correction_precision * 100).toFixed(0) + '%'}</div></div>` : ''}
    </div>

    <div class="section-title">Precision, recall and F1 by method</div>
    <div class="section-sub">Each method predicts the top-scoring registered plate when its score ≥ threshold and it is strictly ahead of the runner-up.
      Thresholds are swept from 0.50 to 1.00; each method is shown at its best-F1 threshold t*. R@5 = true vehicle within the top 5;
      Cand. recall / #cand. = true vehicle among, and number of, candidates listed at t*.</div>
    <div class="table-container"><table class="data-table">
      <thead><tr><th>Method</th><th>t*</th><th>Precision</th><th>Recall</th><th>F1</th><th>R@5</th><th>Cand. recall</th><th>#cand.</th><th>TP / FP / FN / TN</th></tr></thead>
      <tbody>${methodRows}</tbody></table></div>

    <div class="section-title">F1 across thresholds</div>
    <div class="section-sub">Dots mark each method's best threshold. Hover for exact values.</div>
    <div class="viz-root chart-wrap" id="f1-chart"></div>

    <div class="section-title">Correct resolution rate by noise type</div>
    <div class="section-sub">Substitutions and deletions in the number block often turn one registered plate into <em>another</em> registered plate —
      no plate-only method can detect that, which is why the cleansing rules require make/model/colour evidence before correcting.</div>
    <div class="table-container"><table class="data-table">
      <thead><tr><th>Noise type</th>${METHOD_ORDER.map(k => `<th>${METHOD_STYLE[k].short}</th>`).join('')}</tr></thead>
      <tbody>${noiseRows}</tbody></table></div>

    <div class="section-title">Common OCR errors (O vs 0, I vs 1, B vs 8 …)</div>
    <div class="section-sub">✓ = the true plate is the unique top match. Plain Levenshtein ties a glyph confusion with a genuine digit change, so several plates score equally.</div>
    <div class="table-container"><table class="data-table">
      <thead><tr><th>OCR reading</th><th>True plate</th><th>Error</th>${METHOD_ORDER.map(k => `<th>${METHOD_STYLE[k].short}</th>`).join('')}</tr></thead>
      <tbody>${caseRows}</tbody></table></div>

    ${cl ? `<div class="section-title">Cleansing rule engine vs labelled test scenarios</div>
    <div class="section-sub">${cl.records} staged records covering missing information, incorrect plates, conflicting vehicle details and multiple possible matches.
      ${cl.corrections_made} automatic corrections, ${cl.correction_precision === null ? '—' : (cl.correction_precision * 100).toFixed(0) + '%'} of them to the right vehicle.</div>
    <div class="table-container"><table class="data-table">
      <thead><tr><th>Scenario</th><th>Expected</th><th>Agreement</th><th>Engine decisions</th></tr></thead>
      <tbody>${scenarioRows}</tbody></table></div>` : ''}

    <div class="section-title">Decision rules (applied in order)</div>
    <div class="table-container"><table class="data-table">
      <thead><tr><th>Rule</th><th>Condition</th><th>Decision</th><th>Reason code</th></tr></thead>
      <tbody>${rules}</tbody></table></div>`;

  renderF1Chart(document.getElementById('f1-chart'), rep);
}

function renderF1Chart(root, rep) {
  const W = 760, H = 300, M = { top: 14, right: 18, bottom: 34, left: 44 };
  const x = t => M.left + (t - 0.5) / 0.5 * (W - M.left - M.right);
  const y = v => M.top + (1 - v) * (H - M.top - M.bottom);
  const thresholds = rep.methods[METHOD_ORDER[0]].curve.map(p => p.threshold);

  let grid = '';
  [0, 0.25, 0.5, 0.75, 1].forEach(v => {
    grid += `<line class="grid" x1="${M.left}" x2="${W - M.right}" y1="${y(v)}" y2="${y(v)}"/>`;
    grid += `<text class="axis-label" x="${M.left - 8}" y="${y(v) + 4}" text-anchor="end">${v.toFixed(2)}</text>`;
  });
  [0.5, 0.6, 0.7, 0.8, 0.9, 1.0].forEach(t => {
    grid += `<text class="axis-label" x="${x(t)}" y="${H - M.bottom + 18}" text-anchor="middle">${t.toFixed(1)}</text>`;
  });
  grid += `<text class="axis-label" x="${(M.left + W - M.right) / 2}" y="${H - 2}" text-anchor="middle">similarity threshold</text>`;
  grid += `<text class="axis-label" x="12" y="${M.top + 4}" text-anchor="start">F1</text>`;

  const series = METHOD_ORDER.map(k => {
    const pts = rep.methods[k].curve.map(p => `${x(p.threshold).toFixed(1)},${y(p.f1).toFixed(1)}`).join(' ');
    return `<polyline class="series" points="${pts}" style="stroke:${METHOD_STYLE[k].color}"/>`;
  }).join('');

  // Best-threshold markers with labels nudged apart vertically to avoid collisions
  const bests = METHOD_ORDER.map(k => ({ k, t: rep.methods[k].best_threshold, f1: rep.methods[k].f1 }))
    .map(b => ({ ...b, px: x(b.t), py: y(b.f1), ly: y(b.f1) - 10 }))
    .sort((a, b) => a.ly - b.ly);
  for (let i = 1; i < bests.length; i++) {
    if (Math.abs(bests[i].px - bests[i - 1].px) < 90 && bests[i].ly - bests[i - 1].ly < 13) bests[i].ly = bests[i - 1].ly + 13;
  }
  const markers = bests.map(b => `
    <circle class="best-dot" cx="${b.px}" cy="${b.py}" r="4.5" style="fill:${METHOD_STYLE[b.k].color}"/>
    <text class="best-label" x="${b.px - 8}" y="${b.ly}" text-anchor="end">${METHOD_STYLE[b.k].short} ${b.f1.toFixed(3)}</text>`).join('');

  root.innerHTML = `
    <div class="chart-legend">${METHOD_ORDER.map(k => `<span class="key"><span class="swatch" style="background:${METHOD_STYLE[k].color}"></span>${METHOD_STYLE[k].short}</span>`).join('')}</div>
    <svg class="chart-svg" viewBox="0 0 ${W} ${H}" role="img" aria-label="F1 score versus similarity threshold for each matching method">
      ${grid}${series}
      <line class="crosshair" id="f1-crosshair" y1="${M.top}" y2="${H - M.bottom}" x1="0" x2="0" style="display:none"/>
      ${markers}
      <rect x="${M.left}" y="${M.top}" width="${W - M.left - M.right}" height="${H - M.top - M.bottom}" fill="transparent" id="f1-hit"/>
    </svg>
    <div class="chart-tooltip" id="f1-tooltip"></div>`;

  const svg = root.querySelector('svg');
  const hit = root.querySelector('#f1-hit');
  const cross = root.querySelector('#f1-crosshair');
  const tip = root.querySelector('#f1-tooltip');
  hit.addEventListener('mousemove', e => {
    const rect = svg.getBoundingClientRect();
    const sx = (e.clientX - rect.left) * (W / rect.width);
    const t = Math.min(1, Math.max(0.5, 0.5 + (sx - M.left) / (W - M.left - M.right) * 0.5));
    const idx = thresholds.reduce((best, th, i) => Math.abs(th - t) < Math.abs(thresholds[best] - t) ? i : best, 0);
    const th = thresholds[idx];
    cross.setAttribute('x1', x(th)); cross.setAttribute('x2', x(th)); cross.style.display = '';
    tip.innerHTML = `<div style="font-weight:700; margin-bottom:0.3rem;">threshold ${th.toFixed(2)}</div>` +
      METHOD_ORDER.map(k => {
        const p = rep.methods[k].curve[idx];
        return `<div class="row"><span class="name"><span class="swatch" style="display:inline-block;width:10px;height:3px;background:${METHOD_STYLE[k].color}"></span>${METHOD_STYLE[k].short}</span><span class="mono">F1 ${p.f1.toFixed(3)}</span></div>`;
      }).join('');
    tip.style.display = 'block';
    const left = (x(th) / W) * rect.width;
    tip.style.left = `${Math.min(left + 12, rect.width - 190)}px`;
    tip.style.top = '30px';
  });
  hit.addEventListener('mouseleave', () => { cross.style.display = 'none'; tip.style.display = 'none'; });
}

// ---------------------------------------------------------------------------
// Audit trail
// ---------------------------------------------------------------------------
async function loadAudit(append) {
  const tbody = document.getElementById('audit-tbody');
  if (!append) auditOffset = 0;
  const { ok, data } = await API.getAuditTrail({ limit: 50, offset: auditOffset }).catch(err => ({ ok: false, data: { error: err.message } }));
  if (!ok) {
    tbody.innerHTML = `<tr><td colspan="12" class="empty-note" style="color:var(--status-danger);">${esc(data.error)}</td></tr>`;
    return;
  }
  const rows = data.entries.map(e => `
    <tr>
      <td class="mono">#${e.audit_id}</td>
      <td style="font-size:0.75rem;">${esc(e.created_at)}</td>
      <td class="mono">${e.record_id ?? '<span style="color:var(--text-muted);">scan</span>'}</td>
      <td style="font-size:0.75rem;">${esc(e.source_system)}</td>
      <td class="mono">${e.original_plate === null ? '<em>NULL</em>' : `"${esc(e.original_plate)}"`}</td>
      <td>${e.corrected_plate ? renderPlateDiff(e.normalized_plate, e.corrected_plate) : '—'}</td>
      <td class="mono">${e.matched_vehicle_id ?? '—'}</td>
      <td style="font-size:0.75rem;">${esc(METHOD_STYLE[e.similarity_method]?.short || e.similarity_method || '—')}<br><span class="mono">${fmt(e.similarity_score)}</span></td>
      <td>${decisionBadge(e.decision_status)}</td>
      <td class="reason-col" title="${esc(e.reason)}">${esc(e.reason_code)}</td>
      <td style="font-size:0.78rem;">${esc(e.decided_by)}</td>
      <td class="mono">${e.supersedes_audit_id ? '#' + e.supersedes_audit_id : '—'}</td>
    </tr>`).join('');
  if (!append) tbody.innerHTML = rows || '<tr><td colspan="12" class="empty-note">No decisions recorded yet.</td></tr>';
  else tbody.insertAdjacentHTML('beforeend', rows);
  auditOffset += data.entries.length;
  document.getElementById('btn-audit-more').style.display = auditOffset < data.total ? '' : 'none';
}

// ---------------------------------------------------------------------------
// Agency data: scan the five live agency databases, apply corrections, review
// ---------------------------------------------------------------------------
const AGENCY_LABEL = { VAHAN: 'VAHAN', IIB: 'IIB', POLICE: 'Police', ANPR: 'ANPR', ECHALLAN: 'e-Challan' };
const KIND_LABEL = {
  UNREGISTERED_PLATE: 'Not a registered plate',
  NON_CANONICAL_FORMAT: 'Formatting',
  MISSING_IDENTIFIER: 'Missing identifier',
  SUSPECT_REGISTRATION: 'Suspicious registry entry',
};
const ACTION_BADGE = {
  UPDATE: ['badge-info', '✏️ Correct'],
  REVIEW: ['badge-warning', '⚠️ Review'],
  REJECT: ['badge-danger', '⛔ Flag (not registered)'],
};
let agencyAnomalies = [];

async function refreshPlateIndex() {
  const btn = document.getElementById('btn-refresh-index');
  btn.disabled = true;
  await API.refreshMatchingIndex().catch(() => null);
  await loadConfig();
  btn.disabled = false;
}

async function scanAgency() {
  const tbody = document.getElementById('agency-tbody');
  const meta = document.getElementById('agency-meta');
  tbody.innerHTML = '<tr><td colspan="10" class="empty-note"><span class="spinner-inline"></span> Reading all five agency databases…</td></tr>';
  const { ok, data } = await API.scanAgencyData().catch(err => ({ ok: false, data: { error: err.message } }));
  if (!ok) {
    tbody.innerHTML = `<tr><td colspan="10" class="empty-note" style="color:var(--status-danger);">${esc(data.error)}</td></tr>`;
    return;
  }
  agencyAnomalies = data.anomalies;
  const rowsRead = data.sources.reduce((sum, s) => sum + (s.rows || 0), 0);
  const failed = data.sources.filter(s => s.error);
  meta.innerHTML = `${rowsRead.toLocaleString()} rows read from ${data.sources.length - failed.length}/${data.sources.length} databases
    against ${data.registered_vehicles.toLocaleString()} registered vehicles • ${data.duration_ms} ms`
    + (failed.length ? ` • <span style="color:var(--status-danger);">unreachable: ${failed.map(s => esc(s.key)).join(', ')}</span>` : '');
  renderAgencySummary(data.summary);
  renderAgencyRows();
  loadAgencyChanges();
}

function renderAgencySummary(s) {
  const by = s.by_action || {};
  const card = (cls, label, value, sub) => `
    <div class="stat-card ${cls}" style="padding:1rem;">
      <div class="stat-label">${label}</div>
      <div class="stat-value" style="font-size:1.6rem;">${value}</div>
      <div class="stat-subtext">${sub}</div>
    </div>`;
  document.getElementById('agency-summary').innerHTML = [
    card('info', 'Noisy identifiers', s.open, `${s.resolved_by_reviewer} already resolved by a reviewer`),
    card('info', 'Will be corrected', by.UPDATE || 0, 'enough evidence — written back on Apply'),
    card('warning', 'Need review', by.REVIEW || 0, 'conflict / ambiguity / weak evidence'),
    card('danger', 'Not registered', by.REJECT || 0, 'flagged, never deleted'),
  ].join('');
}

function renderAgencyRows() {
  const tbody = document.getElementById('agency-tbody');
  if (!agencyAnomalies.length) {
    tbody.innerHTML = '<tr><td colspan="10" class="empty-note">✅ No anomalies: every vehicle identifier in the five databases is a clean registered plate.</td></tr>';
    return;
  }
  tbody.innerHTML = agencyAnomalies.map((a, i) => {
    const s = a.assessment;
    const [cls, label] = a.resolved ? ['badge-success', '👤 Resolved'] : (ACTION_BADGE[a.action] || ['badge-info', a.action]);
    const evidence = Object.entries(a.context || {}).filter(([, v]) => v).map(([, v]) => esc(v)).join(' • ');
    const target = a.new_value
      ? renderPlateDiff(s.normalized_plate, a.new_value)
      : (s.suggested_plate ? `<span style="color:var(--text-muted); font-size:0.75rem;">suggest</span> ${renderPlateDiff(s.normalized_plate, s.suggested_plate)}` : '—');
    const status = a.latest ? `<br><span style="font-size:0.7rem; color:var(--text-muted);">${esc(a.latest.decision_status)}</span>` : '';
    return `
      <tr>
        <td style="font-size:0.8rem;"><strong>${esc(AGENCY_LABEL[a.source] || a.source)}</strong><br><span style="color:var(--text-muted);">${esc(a.table)}.${esc(a.column)}</span></td>
        <td class="mono">${a.row_id}</td>
        <td class="mono">${a.original_value === null ? '<em>NULL</em>' : `"${esc(a.original_value)}"`}</td>
        <td style="font-size:0.8rem;">${esc(KIND_LABEL[a.kind] || a.kind)}</td>
        <td style="font-size:0.78rem;">${evidence || '<span style="color:var(--text-muted);">none</span>'}${a.context_from ? `<br><span style="color:var(--text-muted);">from ${esc(a.context_from)}</span>` : ''}</td>
        <td><span class="badge ${cls}">${label}</span>${status}</td>
        <td>${target}</td>
        <td>${scoreCell(s.similarity_score)}</td>
        <td class="reason-col" title="${esc(s.reason)}">${esc(s.rule || '')} ${esc(s.reason_code || '')}</td>
        <td>${a.resolved ? '' : `<button class="btn btn-secondary btn-sm" type="button" onclick="openAgencyRow(${i})">Review</button>`}</td>
      </tr>`;
  }).join('');
}

async function cleanseAgency() {
  const btn = document.getElementById('btn-agency-cleanse');
  const original = btn.innerHTML;
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner-inline"></span> Applying…';
  const { ok, data } = await API.cleanseAgencyData().catch(err => ({ ok: false, data: { error: err.message } }));
  btn.disabled = false;
  btn.innerHTML = original;
  setModalWide(false);
  if (!ok) {
    AppModal.alert('Cleansing failed', data.error, '❌');
    return;
  }
  const lines = Object.entries(data.outcome).map(([k, v]) => `${k}: ${v}`).join('\n') || 'Nothing new to change.';
  const errors = data.errors.length ? `\n\nNot applied:\n${data.errors.join('\n')}` : '';
  AppModal.alert('Agency data cleansed',
    `${data.changed_plates.length} row(s) corrected in the agency databases (${data.duration_ms} ms).\n` +
    `${data.skipped_reviewed} row(s) already decided by a reviewer were left alone.\n\n${lines}${errors}`, '🧹');
  scanAgency();
}

function openAgencyRow(i) {
  const a = agencyAnomalies[i];
  const s = a.assessment;
  const overlay = AppModal.getOverlay();
  setModalWide(true);
  document.getElementById('app-modal-title').innerHTML =
    `<span>🗄️</span> <span>${esc(AGENCY_LABEL[a.source] || a.source)} · ${esc(a.table)} row ${a.row_id}</span>`;
  const options = (s.candidates || []).map(c =>
    `<option value="${esc(c.plate)}">${esc(c.plate)} — #${c.vehicle_id ?? '?'} ${esc(c.make)} ${esc(c.model)}, ${esc(c.color)} (${fmt(c.combined_score)})</option>`).join('');
  document.getElementById('app-modal-body').innerHTML = `
    ${renderDecisionCard({ ...s, original_plate: a.original_value, method: null }, { hideAudit: true })}
    <div class="section-title">Review decision</div>
    <div class="form-row" style="grid-template-columns: 1fr 1fr 1fr;">
      <div><label class="mini-label" for="ag-action">Action</label>
        <select class="form-select" id="ag-action">
          <option value="CORRECT">Correct to registered plate (updates ${esc(AGENCY_LABEL[a.source])})</option>
          <option value="ACCEPT_ORIGINAL">Accept original value</option>
          <option value="REJECT">Reject (keep flagged)</option>
        </select></div>
      <div><label class="mini-label" for="ag-plate">Corrected plate</label>
        <select class="form-select" id="ag-plate">${options || '<option value="">No candidates</option>'}</select></div>
      <div><label class="mini-label" for="ag-reviewer">Reviewer ID</label>
        <input class="form-input" id="ag-reviewer" value="${esc(localStorageGet('reviewer') || 'officer.demo')}"></div>
    </div>
    <div style="margin-top:0.6rem;"><label class="mini-label" for="ag-note">Reason / note</label>
      <input class="form-input" id="ag-note" placeholder="e.g. verified against the RC"></div>`;
  if (s.suggested_plate || s.corrected_plate) document.getElementById('ag-plate').value = s.corrected_plate || s.suggested_plate;
  document.getElementById('app-modal-footer').innerHTML = `
    <button class="btn btn-secondary btn-sm" onclick="AppModal.close()">Close</button>
    <button class="btn btn-primary btn-sm" onclick="submitAgencyReview(${i})">Save decision</button>`;
  overlay.classList.add('active');
}

async function submitAgencyReview(i) {
  const a = agencyAnomalies[i];
  const payload = {
    source: a.source, row_id: a.row_id, original_value: a.original_value,
    action: document.getElementById('ag-action').value,
    corrected_plate: document.getElementById('ag-plate').value,
    reviewer: document.getElementById('ag-reviewer').value.trim(),
    note: document.getElementById('ag-note').value.trim(),
  };
  localStorageSet('reviewer', payload.reviewer);
  const { ok, data } = await API.reviewAgencyRow(payload);
  setModalWide(false);
  if (!ok) {
    AppModal.alert('Decision not saved', data.error, '❌');
    return;
  }
  AppModal.alert('Decision saved', data.applied
    ? `${AGENCY_LABEL[a.source]} row ${a.row_id} updated: "${a.original_value}" → ${data.new_value}.\nChange #${data.change_id} keeps the original value.`
    : `Change #${data.change_id} recorded. The ${AGENCY_LABEL[a.source]} row was not modified.`, '✅');
  scanAgency();
}

async function loadAgencyChanges() {
  const tbody = document.getElementById('agency-changes-tbody');
  const { ok, data } = await API.getAgencyChanges({ limit: 50 }).catch(err => ({ ok: false, data: { error: err.message } }));
  if (!ok) {
    tbody.innerHTML = `<tr><td colspan="8" class="empty-note" style="color:var(--status-danger);">${esc(data.error)}</td></tr>`;
    return;
  }
  tbody.innerHTML = data.entries.map(e => `
    <tr>
      <td class="mono">#${e.change_id}</td>
      <td style="font-size:0.75rem;">${esc(e.created_at)}</td>
      <td style="font-size:0.78rem;">${esc(AGENCY_LABEL[e.source_system] || e.source_system)} · ${esc(e.table_name)} #${e.row_id}</td>
      <td class="mono">${e.original_value === null ? '<em>NULL</em>' : `"${esc(e.original_value)}"`}</td>
      <td>${e.new_value ? renderPlateDiff(normalizePlate(e.original_value), e.new_value) : '—'}</td>
      <td><span class="badge ${e.applied ? 'badge-info' : 'badge-warning'}">${esc(e.decision_status)}</span></td>
      <td class="reason-col" title="${esc(e.reason)}">${esc(e.reason_code || '')}</td>
      <td style="font-size:0.78rem;">${esc(e.decided_by)}</td>
    </tr>`).join('') || '<tr><td colspan="8" class="empty-note">No changes yet.</td></tr>';
}
