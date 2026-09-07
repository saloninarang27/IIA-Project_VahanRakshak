/* ═══════════════════════════════════════════════════════════════
   VehicleSentinel — app.js
   Frontend logic: 5-way federated lookup, visualizer, schema map,
   alerts dashboard, ANPR simulation, live persisted MoT register

   Two-page architecture:
     /         → Executive Dashboard (stats, alerts, schema, MoT register)
     /search   → Dedicated Vehicle Search Workspace (federation + results)
   ═══════════════════════════════════════════════════════════════ */

'use strict';

// ── State ──────────────────────────────────────────────────────
let allPlates   = [];
let lastResults = null;
let alertsCache = [];

// Detect which page we are on
const IS_SEARCH_PAGE = document.body.classList.contains('search-page-body');

// ── Init ───────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  // Always load these (present on both pages)
  loadStats();
  prefetchPlates();

  const plateInput = document.getElementById('plate-input');
  if (plateInput) {
    plateInput.addEventListener('keydown', e => {
      if (e.key === 'Enter') {
        IS_SEARCH_PAGE ? doLookup() : redirectToSearch();
      }
    });
    plateInput.addEventListener('input', onPlateInput);
  }

  document.addEventListener('click', e => {
    if (!e.target.closest('#search-wrapper')) closeAutocomplete();
  });

  if (IS_SEARCH_PAGE) {
    // Search page: auto-run if ?plate= param present
    const urlPlate = new URLSearchParams(window.location.search).get('plate');
    if (urlPlate) {
      plateInput.value = urlPlate.toUpperCase();
      doLookup();
    }
  } else {
    // Dashboard page: load all dashboard sections
    loadSchema();
    loadAlerts();
    loadMotReports();
    setReportDate();
  }
});

function setReportDate() {
  const el = document.getElementById('report-date');
  if (!el) return;
  const d = new Date();
  el.textContent = `Date: ${d.toLocaleDateString('en-IN', { dateStyle: 'long' })}`;
}

// ── Autocomplete ───────────────────────────────────────────────
async function prefetchPlates() {
  try {
    const r = await fetch('/api/all-plates');
    const j = await r.json();
    allPlates = j.plates || [];
  } catch (_) {}
}

function onPlateInput(e) {
  const q   = e.target.value.toUpperCase().trim();
  const box = document.getElementById('autocomplete-list');
  if (!q || q.length < 2) { box.classList.remove('open'); return; }

  const matches = allPlates.filter(p => p.startsWith(q)).slice(0, 8);
  if (!matches.length) { box.classList.remove('open'); return; }

  box.innerHTML = matches.map(p =>
    `<div class="auto-item" onclick="${IS_SEARCH_PAGE ? `quickSearch('${p}')` : `redirectToSearch('${p}')`}">${p}</div>`
  ).join('');
  box.classList.add('open');
}
function closeAutocomplete() {
  const box = document.getElementById('autocomplete-list');
  if (box) box.classList.remove('open');
}

// ── Dashboard: redirect to search page ─────────────────────────
function redirectToSearch(plate) {
  const p = plate || document.getElementById('plate-input')?.value?.toUpperCase().trim();
  if (p) {
    window.location.href = `/search?plate=${encodeURIComponent(p)}`;
  } else {
    window.location.href = '/search';
  }
}

// ── Search page: quick search in-page ──────────────────────────
function quickSearch(plate) {
  const input = document.getElementById('plate-input');
  if (!IS_SEARCH_PAGE) {
    // On dashboard: redirect to search page
    window.location.href = `/search?plate=${encodeURIComponent(plate)}`;
    return;
  }
  input.value = plate;
  closeAutocomplete();
  doLookup();
}


// ── Main Lookup ────────────────────────────────────────────────
async function doLookup() {
  const plate = document.getElementById('plate-input').value.toUpperCase().trim();
  if (!plate) return;

  closeAutocomplete();
  setSearchLoading(true);
  resetFedNodes();

  // Hide empty state on search page
  const emptyState = document.getElementById('search-empty-state');
  if (emptyState) emptyState.style.display = 'none';

  try {
    const res  = await fetch(`/api/lookup/${encodeURIComponent(plate)}`);
    const data = await res.json();
    lastResults = data;

    renderRiskBanner(data);
    renderProfile(data);
    renderFederation(data);
    renderDbCards(data);

    // Update page title with searched plate
    document.title = `${plate} — VehicleSentinel Search`;

    // Update URL with plate param without reloading
    const newUrl = `/search?plate=${encodeURIComponent(plate)}`;
    window.history.replaceState(null, '', newUrl);

    loadStats();

    const resultsEl = document.getElementById('results-section');
    if (resultsEl) {
      resultsEl.style.display = 'block';
      resultsEl.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
  } catch (err) {
    alert('Error contacting server: ' + err.message);
    if (emptyState) emptyState.style.display = 'block';
  } finally {
    setSearchLoading(false);
  }
}

function setSearchLoading(on) {
  const btn     = document.getElementById('search-btn');
  if (!btn) return;
  const spinner = document.getElementById('btn-spinner');
  const txt     = btn.querySelector('.btn-text');
  if (on) { if (txt) txt.textContent = 'Searching…'; if (spinner) spinner.hidden = false; }
  else    { if (txt) txt.textContent = 'Search';     if (spinner) spinner.hidden = true;  }
}

// ── Risk Banner ────────────────────────────────────────────────
function renderRiskBanner(data) {
  const { integrated } = data;
  const risk  = integrated.risk;
  const plate = integrated.plate;

  const banner = document.getElementById('risk-banner');
  banner.style.borderColor = risk.color + '44';
  banner.style.background  = `linear-gradient(135deg, var(--card), ${risk.color}11)`;

  document.getElementById('risk-plate').textContent = plate;
  document.getElementById('risk-label').textContent = `${risk.level} RISK`;
  document.getElementById('risk-label').style.color = risk.color;

  // Factors
  const fDiv = document.getElementById('risk-factors');
  fDiv.innerHTML = risk.factors.map(([desc, , sev]) =>
    `<span class="rfactor ${sev}">${desc}</span>`
  ).join('');

  // Ring
  const fill  = document.getElementById('ring-fill');
  const score = document.getElementById('ring-score');
  const pct   = risk.score / 100;
  const circ  = 201;
  fill.style.stroke            = risk.color;
  fill.style.strokeDashoffset  = circ - circ * pct;
  score.textContent            = risk.score;
  score.style.color            = risk.color;
}

// ── Vehicle Profile ────────────────────────────────────────────
function renderProfile(data) {
  const { integrated, mot_filing } = data;
  const rto  = integrated.rto;
  const ins  = integrated.insurance;
  const anpr = integrated.anpr;
  const theft= integrated.theft;

  const rows = [];

  // Automated MoT Write-Back Status (Rubric Point 7)
  if (mot_filing) {
    if (mot_filing.is_new) {
      rows.push([
        'MoT Write-Back',
        `<span class="mot-filing-badge mot-filed-new">🚨 NEW Notice #${mot_filing.report_id} Auto-Filed into MoT (${mot_filing.status})</span>`,
        true
      ]);
    } else {
      rows.push([
        'MoT Write-Back',
        `<span class="mot-filing-badge mot-deduped">ℹ Active MoT Notice #${mot_filing.report_id} already on record</span>`,
        true
      ]);
    }
  }

  if (rto) {
    rows.push(['Owner',        rto.owner_fullname]);
    rows.push(['Date of Birth', rto.owner_dob]);
    rows.push(['Address',      rto.address, true]);
    rows.push(['Make / Model', `${rto.vehicle_make} ${rto.vehicle_model} (${rto.year_of_mfg})`]);
    rows.push(['Fuel Type',    rto.fuel_type]);
    rows.push(['Registered On', rto.registered_on]);
    rows.push(['Fitness Expiry', colorDate(rto.fitness_expiry)]);
    rows.push(['Tax Paid Till',  colorDate(rto.tax_paid_till)]);
    rows.push(['Chassis No.',  rto.chassis_no]);
    rows.push(['Engine No.',   rto.engine_no]);
  }
  if (ins) {
    rows.push(['Insurer',      ins.insurer_name]);
    rows.push(['Policy No.',   ins.policy_number]);
    rows.push(['Policy Type',  ins.policy_type]);
    rows.push(['Policy Expiry', ins.is_active
      ? `<span style="color:#16a34a;font-weight:600">${ins.expiry_date} ✓</span>`
      : `<span style="color:#dc2626;font-weight:700">${ins.expiry_date} ✗ EXPIRED</span>`]);
    rows.push(['Premium',      `₹${Number(ins.premium_amount).toLocaleString('en-IN')}`]);
  }
  if (!ins) {
    rows.push(['Insurance', '<span style="color:#dc2626;font-weight:700">NOT INSURED ✗</span>']);
  }
  if (anpr) {
    rows.push(['Last Seen',      anpr.captured_at]);
    rows.push(['Camera Location', anpr.camera_location, true]);
    rows.push(['Vehicle Color',   anpr.vehicle_color]);
    rows.push(['Total Sightings', anpr.total_sightings]);
  }
  if (theft) {
    rows.push(['Theft Status', `<span style="color:#dc2626;font-weight:700">${theft.status}</span>`]);
    rows.push(['FIR Number',   theft.fir_number]);
    rows.push(['Police Station', theft.police_station, true]);
    rows.push(['Reported',     theft.reported_date]);
    if (theft.reward_amount > 0)
      rows.push(['Reward Amount', `₹${Number(theft.reward_amount).toLocaleString('en-IN')}`]);
  }

  // MoT History
  if (integrated.mot_history && integrated.mot_history.length > 0) {
    rows.push([
      'MoT Register',
      `${integrated.mot_history.length} formal compliance record(s) persisted in MoT DB`,
      true
    ]);
  }

  const grid = document.getElementById('profile-grid');
  if (!rows.length) {
    grid.innerHTML = '<div class="profile-placeholder">No records found in any database for this plate.</div>';
    return;
  }

  grid.innerHTML = rows.map(([k, v, full]) =>
    `<div class="pf-item ${full ? 'pf-full' : ''}">
       <div class="pf-key">${k}</div>
       <div class="pf-val">${v ?? '—'}</div>
     </div>`
  ).join('');

  const owner = integrated.owner;
  if (owner) document.getElementById('profile-owner-tag').textContent = owner;
}

function colorDate(dateStr) {
  if (!dateStr) return '—';
  const d = new Date(dateStr);
  if (d < new Date()) return `<span style="color:#dc2626;font-weight:600">${dateStr} ✗</span>`;
  return `<span style="color:#16a34a;font-weight:600">${dateStr} ✓</span>`;
}

// ── Federation Visualizer (5 Sources) ──────────────────────────
const DB_MAP = {
  'anpr_camera':       { t: 'ft-anpr',  s: 'fs-anpr',  n: 'fn-anpr'  },
  'insurance_company': { t: 'ft-ins',   s: 'fs-ins',   n: 'fn-ins'   },
  'rto_registration':  { t: 'ft-rto',   s: 'fs-rto',   n: 'fn-rto'   },
  'theft_shredding':   { t: 'ft-theft', s: 'fs-theft', n: 'fn-theft' },
  'mot_reports':       { t: 'ft-mot',   s: 'fs-mot',   n: 'fn-mot'   },
};

function resetFedNodes() {
  Object.values(DB_MAP).forEach(({ t, s, n }) => {
    const tEl = document.getElementById(t);
    const sEl = document.getElementById(s);
    const nEl = document.getElementById(n);
    if (tEl) tEl.textContent = '—';
    if (sEl) sEl.textContent = '⟳';
    if (nEl) nEl.classList.remove('found', 'not-found');
  });
}

function renderFederation(data) {
  const raw = data.raw_results;
  Object.entries(raw).forEach(([db, res]) => {
    const ids = DB_MAP[db];
    if (!ids) return;
    const tEl = document.getElementById(ids.t);
    const sEl = document.getElementById(ids.s);
    const nEl = document.getElementById(ids.n);
    if (!tEl || !sEl || !nEl) return;

    tEl.textContent = `${res.elapsed_ms} ms`;
    if (res.row_count > 0) {
      sEl.textContent = `✓ ${res.row_count} row`;
      nEl.classList.add('found');
    } else {
      sEl.textContent = '○ not found';
      nEl.classList.add('not-found');
    }
  });
}

// ── Per-DB Cards (5 Sources) ───────────────────────────────────
const DB_CARD_MAP = {
  'anpr_camera':       { time: 'dbt-anpr',  status: 'dbs-anpr',  body: 'dbb-anpr'  },
  'insurance_company': { time: 'dbt-ins',   status: 'dbs-ins',   body: 'dbb-ins'   },
  'rto_registration':  { time: 'dbt-rto',   status: 'dbs-rto',   body: 'dbb-rto'   },
  'theft_shredding':   { time: 'dbt-theft', status: 'dbs-theft', body: 'dbb-theft' },
  'mot_reports':       { time: 'dbt-mot',   status: 'dbs-mot',   body: 'dbb-mot'   },
};

function renderDbCards(data) {
  const raw = data.raw_results;
  Object.entries(raw).forEach(([db, res]) => {
    const ids = DB_CARD_MAP[db];
    if (!ids) return;

    const timeEl  = document.getElementById(ids.time);
    const statEl  = document.getElementById(ids.status);
    const bodyEl  = document.getElementById(ids.body);

    if (timeEl)  timeEl.textContent  = `${res.elapsed_ms} ms`;
    if (statEl)  statEl.textContent  = `${res.elapsed_ms} ms · ${res.row_count} row(s)`;
    if (!bodyEl) return;

    if (!res.rows || !res.rows.length) {
      bodyEl.innerHTML = '<div class="dbc-empty">No record found in this database.</div>';
      return;
    }

    bodyEl.innerHTML = res.rows.map(row =>
      `<div class="db-row">${
        Object.entries(row).map(([k, v]) =>
          `<div class="db-kv">
             <span class="db-key">${k}</span>
             <span class="db-val">${v ?? '—'}</span>
           </div>`
        ).join('')
      }</div>`
    ).join('<hr style="border-color:var(--border);margin:6px 0">');
  });
}


// ── Stats (6 Metrics) ──────────────────────────────────────────
async function loadStats() {
  try {
    const r = await fetch('/api/stats');
    const s = await r.json();
    animateCount('sv-spotted',    s.total_vehicles_spotted || 0);
    animateCount('sv-flagged',    s.flagged_vehicles || 0);
    animateCount('sv-uninsured',  Math.max(0, (s.total_vehicles_spotted || 0) - (s.active_policies || 0)));
    animateCount('sv-stolen',     s.active_stolen || 0);
    animateCount('sv-registered', s.total_registered || 0);
    animateCount('sv-mot',        s.total_mot_reports || 0);
  } catch (_) {}
}

function animateCount(id, target) {
  const el = document.getElementById(id);
  if (!el) return;
  const dur = 800;
  const step= 16;
  const inc = target / (dur / step);
  let cur   = 0;
  const iv  = setInterval(() => {
    cur = Math.min(cur + inc, target);
    el.textContent = Math.round(cur);
    if (cur >= target) clearInterval(iv);
  }, step);
}

// ── Schema Map ─────────────────────────────────────────────────
async function loadSchema() {
  if (!document.getElementById('schema-table-wrapper')) return;
  try {
    const r = await fetch('/api/schema-map');
    const d = await r.json();
    renderSchemaHighlight(d);
    renderSchemaTable(d);
  } catch (_) {
    const el = document.getElementById('schema-table-wrapper');
    if (el) el.innerHTML = '<div class="loading-msg">Could not load schema (is Flask running?)</div>';
  }
}


function renderSchemaHighlight(d) {
  const m = d.vid_cols || {};
  const set = (id, db) => {
    const el = document.getElementById(id);
    if (el && m[db]) el.textContent = m[db].column;
  };
  set('sch-col-anpr',  'anpr_camera');
  set('sch-col-ins',   'insurance_company');
  set('sch-col-rto',   'rto_registration');
  set('sch-col-theft', 'theft_shredding');
  set('sch-col-mot',   'mot_reports');
}

function renderSchemaTable(d) {
  const schemas  = d.schemas || {};
  const vid_cols = d.vid_cols || {};
  const wrapper  = document.getElementById('schema-table-wrapper');

  let html = '';
  for (const [dbKey, sch] of Object.entries(schemas)) {
    const vid = vid_cols[dbKey]?.column;
    html += `
      <h4 style="margin:1.5rem 0 0.5rem;font-size:0.85rem;color:var(--text2)">
        ${sch.display} &nbsp;·&nbsp; <code style="font-family:var(--mono);font-size:0.75rem">${sch.file}</code>
        &nbsp;·&nbsp; Table: <code style="font-family:var(--mono);font-size:0.75rem">${sch.table}</code>
      </h4>
      <table class="schema-full-table">
        <thead>
          <tr><th>#</th><th>Column Name</th><th>Type</th><th>NOT NULL</th><th>PK</th><th>Role</th></tr>
        </thead>
        <tbody>
          ${sch.columns.map((col, i) => `
            <tr>
              <td>${i + 1}</td>
              <td class="${col.name === vid ? 'vid-col' : ''}">${col.name}</td>
              <td>${col.type || 'TEXT'}</td>
              <td>${col.not_null ? '✓' : ''}</td>
              <td>${col.pk ? '<span class="pk-badge">PK</span>' : ''}</td>
              <td>${col.name === vid
                ? `<strong style="color:var(--blue)">🔑 Vehicle Identifier (link key)</strong>`
                : ''}</td>
            </tr>
          `).join('')}
        </tbody>
      </table>`;
  }
  wrapper.innerHTML = html || '<div class="loading-msg">No schema data.</div>';
}

// ── Alerts ────────────────────────────────────────────────
async function loadAlerts() {
  const list = document.getElementById('alerts-list');
  if (!list) return;
  list.innerHTML = '<div class="loading-msg">Loading alerts…</div>';
  try {
    const r = await fetch('/api/alerts');
    const d = await r.json();
    alertsCache = d.alerts || [];
    renderAlerts(alertsCache);
  } catch (_) {
    list.innerHTML = '<div class="loading-msg">Could not load alerts (is Flask running?)</div>';
  }
}

function renderAlerts(alerts) {
  const list = document.getElementById('alerts-list');
  if (!list) return;
  if (!alerts.length) {
    list.innerHTML = '<div class="loading-msg">No flagged vehicles found.</div>';
    return;
  }
  list.innerHTML = alerts.map(a => {
    const badges = [];
    if (a.stolen)  badges.push('<span class="abadge abadge-stolen">🚨 STOLEN</span>');
    if (!a.insured) badges.push('<span class="abadge abadge-unins">❌ UNINSURED</span>');
    else            badges.push('<span class="abadge abadge-expired">⚠ CHECK POLICY</span>');
    return `
      <a class="alert-row" href="/search?plate=${a.plate}" style="text-decoration:none;display:flex;">
        <div class="alert-plate">${a.plate}</div>
        <div class="alert-info">
          <div class="alert-loc">📍 ${a.location || '—'}</div>
          <div class="alert-time">Last seen: ${a.last_seen || '—'}</div>
          ${a.owner ? `<div class="alert-time">Owner: ${a.owner}</div>` : ''}
        </div>
        <div class="alert-badges">${badges.join('')}</div>
        <div class="alert-risk" style="color:${a.risk_color}">${a.risk_score}</div>
        <div class="alert-action"><span style="font-size:0.78rem;color:var(--blue);font-weight:700">🔍 Inspect →</span></div>
      </a>`;
  }).join('');
}

// ── Ministry of Transport Compliance Register (Real Persisted Data) ────────────
async function loadMotReports() {
  const wrap = document.getElementById('report-table-wrap');
  if (!wrap) return;
  wrap.innerHTML = '<div class="loading-msg">Loading official MoT compliance records…</div>';
  try {
    const r = await fetch('/api/mot-reports');
    const d = await r.json();
    renderMotReportsTable(d.reports || []);
  } catch (_) {
    wrap.innerHTML = '<div class="loading-msg">Could not load MoT reports (is Flask running?)</div>';
  }
}

function renderMotReportsTable(reports) {
  const wrap = document.getElementById('report-table-wrap');
  if (!reports || !reports.length) {
    wrap.innerHTML = '<div class="loading-msg">No compliance reports currently on file.</div>';
    return;
  }

  wrap.innerHTML = `
    <table class="report-table">
      <thead>
        <tr>
          <th>ID</th>
          <th>Plate Number</th>
          <th>Violation Type</th>
          <th>Risk</th>
          <th>Reported At</th>
          <th>Status</th>
          <th>Recommended Action</th>
        </tr>
      </thead>
      <tbody>
        ${reports.map(r => {
          let statusStyle = 'background:#eff6ff;color:#1d4ed8;border:1px solid #bfdbfe;';
          if (r.status === 'Notice Issued') statusStyle = 'background:#fef2f2;color:#b91c1c;border:1px solid #fecaca;';
          if (r.status === 'Escalated to Police') statusStyle = 'background:#fef2f2;color:#7f1d1d;border:1px solid #f87171;font-weight:bold;';

          return `
            <tr>
              <td><strong>#${r.report_id}</strong></td>
              <td><a href="/search?plate=${r.target_plate}" class="table-action-link">${r.target_plate} 🔍</a></td>
              <td>${r.violation_type}</td>
              <td style="font-weight:700;color:${r.risk_score >= 70 ? '#dc2626' : (r.risk_score >= 40 ? '#ea580c' : '#16a34a')}">${r.risk_score}/100</td>
              <td>${r.reported_at}</td>
              <td><span style="font-size:0.72rem;padding:3px 8px;border-radius:100px;${statusStyle}">${r.status}</span></td>
              <td style="font-size:0.78rem">${r.action_recommended || '—'}</td>
            </tr>
          `;
        }).join('')}
      </tbody>
    </table>
    <p style="margin-top:1rem;font-size:0.75rem;color:var(--text3)">
      Showing ${reports.length} persisted compliance reports in <code>mot_reports.db</code>. Auto-generated by VehicleSentinel Cross-Database Federation Engine.
    </p>`;
}

// ── ANPR Simulation ────────────────────────────────────────────
async function addSighting() {
  const plate    = document.getElementById('sim-plate').value.trim().toUpperCase();
  const location = document.getElementById('sim-location').value.trim();
  const result   = document.getElementById('sim-result');

  if (!plate) { alert('Enter a plate number'); return; }

  try {
    const r = await fetch('/api/add-sighting', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({ plate, location }),
    });
    const d = await r.json();

    result.style.display = 'block';
    if (d.flagged) {
      result.style.background = '#fef2f2';
      result.style.color      = '#b91c1c';
      result.textContent      = `⚠ ${plate} flagged! Risk: ${d.risk.level} (${d.risk.score}/100) — MoT Notice Auto-Filing Triggered`;
    } else {
      result.style.background = '#f0fdf4';
      result.style.color      = '#16a34a';
      result.textContent      = `✓ ${plate} sighting recorded. Risk: ${d.risk.level} (${d.risk.score}/100)`;
    }

    loadStats();
    loadMotReports();
    quickSearch(plate);
  } catch (err) {
    alert('Error: ' + err.message);
  }
}
