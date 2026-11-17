/**
 * Global App Helpers and Navigation Management
 */
document.addEventListener('DOMContentLoaded', () => {
  initNavbarActive();
  checkSystemHealth();
  renderSessionChip();
  if (!Auth.token()) showLoginGate();
});

// ---------------------------------------------------------------------------
// Login gate: every Mediator call needs a session; what you can see depends on your role.
// ---------------------------------------------------------------------------
function showLoginGate(message) {
  if (document.getElementById('login-gate')) return;
  const gate = document.createElement('div');
  gate.id = 'login-gate';
  gate.className = 'modal-overlay active';
  gate.style.zIndex = '10000';
  gate.innerHTML = `
    <div class="modal-card" style="max-width:380px;">
      <div class="modal-header"><div class="modal-title">🔐 Sign in to VahanRakshak</div></div>
      <div class="modal-body">
        <p style="font-size:0.85rem;color:var(--text-secondary);margin-bottom:1rem;">
          Access is need-to-know: police, insurer and admin accounts see different data.</p>
        <div id="login-error" style="display:none;background:#fef2f2;border:1px solid #fecaca;color:#b91c1c;padding:0.6rem;border-radius:6px;font-size:0.83rem;margin-bottom:0.8rem;"></div>
        <input id="login-user" class="search-input" style="width:100%;margin-bottom:0.6rem;" placeholder="Username" autocomplete="username">
        <input id="login-pass" class="search-input" type="password" style="width:100%;margin-bottom:1rem;" placeholder="Password" autocomplete="current-password">
        <button id="login-btn" class="btn btn-primary" style="width:100%;">Sign in</button>
      </div>
    </div>`;
  document.body.appendChild(gate);
  const err = gate.querySelector('#login-error');
  if (message) { err.textContent = message; err.style.display = 'block'; }
  const submit = async () => {
    const btn = gate.querySelector('#login-btn');
    btn.disabled = true;
    try {
      const res = await Auth.login(gate.querySelector('#login-user').value.trim(), gate.querySelector('#login-pass').value);
      if (res.ok) { location.reload(); return; }
      err.textContent = res.data.error || 'Login failed.';
    } catch (e) {
      err.textContent = `Cannot reach the Mediator: ${e.message}`;
    }
    err.style.display = 'block';
    btn.disabled = false;
  };
  gate.querySelector('#login-btn').addEventListener('click', submit);
  gate.querySelector('#login-pass').addEventListener('keydown', e => { if (e.key === 'Enter') submit(); });
  gate.querySelector('#login-user').focus();
}

function renderSessionChip() {
  const s = Auth.session();
  if (!s) return;
  const chip = document.createElement('div');
  chip.style.cssText = 'position:fixed;bottom:12px;right:12px;z-index:9000;background:#fff;border:1px solid #e2e8f0;border-radius:999px;padding:0.35rem 0.8rem;font-size:0.8rem;box-shadow:0 2px 8px rgba(0,0,0,0.08);';
  chip.innerHTML = `👤 <strong></strong> <span class="badge badge-info"></span> <a href="#" style="margin-left:0.4rem;">Log out</a>`;
  chip.querySelector('strong').textContent = s.user;
  chip.querySelector('.badge').textContent = s.role;
  chip.querySelector('a').addEventListener('click', e => { e.preventDefault(); Auth.logout(); location.reload(); });
  document.body.appendChild(chip);
}

function initNavbarActive() {
  const currentPath = window.location.pathname;
  document.querySelectorAll('nav.main-nav a').forEach(link => {
    const href = link.getAttribute('href');
    if (href === currentPath || (currentPath === '/' && href === '/')) {
      link.classList.add('active');
    } else if (href !== '/' && currentPath.endsWith(href)) {
      link.classList.add('active');
    }
  });
}

async function checkSystemHealth() {
  const pill = document.getElementById('global-health-pill');
  if (!pill) return;

  try {
    const health = await API.getHealth();
    if (health.status === 'UP') {
      const services = Object.values(health.services);
      const online = services.filter(s => s.online).length;
      if (online === services.length) {
        pill.innerHTML = `<span class="status-dot"></span> ${online} Services Online (${health.cache_records_count} Cached)`;
        pill.style.borderColor = 'rgba(16, 185, 129, 0.3)';
        pill.style.color = '#10b981';
      } else {
        pill.innerHTML = `<span class="status-dot" style="background:#f59e0b;box-shadow:0 0 8px #f59e0b;"></span> Partial Outage: ${online}/${services.length} online`;
        pill.style.borderColor = 'rgba(245, 158, 11, 0.3)';
        pill.style.color = '#f59e0b';
      }
    }
  } catch (err) {
    pill.innerHTML = `<span class="status-dot" style="background:#ef4444;box-shadow:0 0 8px #ef4444;"></span> Mediator Offline`;
    pill.style.borderColor = 'rgba(239, 68, 68, 0.3)';
    pill.style.color = '#ef4444';
  }
}

function getInsuranceBadge(status) {
  if (status === 'INSURED') return '<span class="badge badge-success">✅ Insured</span>';
  if (status === 'EXPIRED') return '<span class="badge badge-warning">⚠️ Expired</span>';
  return '<span class="badge badge-danger">🚫 Uninsured</span>';
}

function getRiskBadge(level) {
  if (level === 'CRITICAL') return '<span class="badge badge-danger">🚨 CRITICAL</span>';
  if (level === 'HIGH') return '<span class="badge badge-warning">⚠️ HIGH</span>';
  if (level === 'MEDIUM') return '<span class="badge badge-info">ℹ️ MEDIUM</span>';
  return '<span class="badge badge-success">✅ LOW</span>';
}

function getTheftBadge(status) {
  if (status === 'STOLEN') return '<span class="badge badge-danger">🚨 STOLEN</span>';
  if (status === 'SCRAPPED' || status === 'SHREDDED') return '<span class="badge badge-danger">⚙️ SCRAPPED</span>';
  if (status === 'RECOVERED') return '<span class="badge badge-info">🔄 RECOVERED</span>';
  return '<span class="badge badge-success">CLEAN</span>';
}

/**
 * Clean Light-Theme Modal Management System
 * Replaces native browser alerts/prompts/confirms with custom enterprise modals
 */
const AppModal = {
  getOverlay() {
    let overlay = document.getElementById('app-modal-overlay');
    if (!overlay) {
      overlay = document.createElement('div');
      overlay.id = 'app-modal-overlay';
      overlay.className = 'modal-overlay';
      overlay.innerHTML = `
        <div class="modal-card" id="app-modal-card">
          <div class="modal-header">
            <div class="modal-title" id="app-modal-title">Notice</div>
            <button class="modal-close-btn" onclick="AppModal.close()">&times;</button>
          </div>
          <div class="modal-body" id="app-modal-body"></div>
          <div class="modal-footer" id="app-modal-footer"></div>
        </div>
      `;
      document.body.appendChild(overlay);

      overlay.addEventListener('click', (e) => {
        if (e.target === overlay) AppModal.close();
      });

      document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') AppModal.close();
      });
    }
    return overlay;
  },

  close() {
    const overlay = document.getElementById('app-modal-overlay');
    if (overlay) overlay.classList.remove('active');
  },

  alert(title, message, icon = 'ℹ️') {
    const overlay = this.getOverlay();
    document.getElementById('app-modal-title').innerHTML = `<span>${icon}</span> <span>${title}</span>`;
    document.getElementById('app-modal-body').innerHTML = `
      <div style="font-size:0.95rem; color:var(--text-secondary); line-height:1.6; white-space:pre-line;">
        ${message}
      </div>
    `;
    document.getElementById('app-modal-footer').innerHTML = `
      <button class="btn btn-primary btn-sm" onclick="AppModal.close()">Understood</button>
    `;
    overlay.classList.add('active');
  },

  confirm(title, message, onConfirm, confirmText = 'Confirm', cancelText = 'Cancel', isDanger = false) {
    const overlay = this.getOverlay();
    document.getElementById('app-modal-title').innerHTML = `<span>⚠️</span> <span>${title}</span>`;
    document.getElementById('app-modal-body').innerHTML = `
      <div style="font-size:0.95rem; color:var(--text-secondary); line-height:1.6;">
        ${message}
      </div>
    `;
    document.getElementById('app-modal-footer').innerHTML = `
      <button class="btn btn-secondary btn-sm" onclick="AppModal.close()">${cancelText}</button>
      <button class="btn ${isDanger ? 'btn-danger' : 'btn-primary'} btn-sm" id="app-modal-confirm-btn">${confirmText}</button>
    `;

    document.getElementById('app-modal-confirm-btn').onclick = () => {
      AppModal.close();
      if (typeof onConfirm === 'function') onConfirm();
    };

    overlay.classList.add('active');
  },

  showNoticeDetails(notice) {
    const overlay = this.getOverlay();
    document.getElementById('app-modal-title').innerHTML = `<span>🏛️</span> <span>Official E-Challan Notice</span>`;
    document.getElementById('app-modal-body').innerHTML = `
      <div style="background:var(--bg-subtle); padding:1rem; border-radius:var(--radius-md); border:1px solid var(--border-subtle); margin-bottom:1.25rem;">
        <div style="font-size:0.75rem; color:var(--text-muted); text-transform:uppercase; font-weight:600;">Ministry Reference ID</div>
        <div style="font-size:1.4rem; font-weight:800; color:var(--accent-primary); font-family:var(--font-mono);">${notice.ministry_reference}</div>
      </div>

      <div class="modal-info-row">
        <span class="modal-info-label">Vehicle Registration</span>
        <span class="modal-info-val"><a href="/pages/inspector.html?plate=${notice.vehicle_identifier}" style="color:var(--accent-primary); text-decoration:none;">${notice.vehicle_identifier} ➔</a></span>
      </div>
      <div class="modal-info-row">
        <span class="modal-info-label">Violation Category</span>
        <span class="modal-info-val">${notice.report_type || notice.violation_category || 'UNINSURED_VEHICLE'}</span>
      </div>
      <div class="modal-info-row">
        <span class="modal-info-label">Statutory Penalty</span>
        <span class="modal-info-val" style="color:var(--status-danger);">₹2,000 (MV Act Sec 196)</span>
      </div>
      <div class="modal-info-row">
        <span class="modal-info-label">Dispatched Date</span>
        <span class="modal-info-val" style="font-size:0.8rem; font-weight:normal;">${notice.submitted_at || notice.dispatched_date || 'N/A'}</span>
      </div>
      <div class="modal-info-row">
        <span class="modal-info-label">Enforcement Status</span>
        <span class="modal-info-val"><span class="badge ${notice.report_status === 'FINED' ? 'badge-danger' : 'badge-warning'}">${notice.report_status}</span></span>
      </div>
      <div class="modal-info-row" style="flex-direction:column; gap:0.25rem; align-items:flex-start;">
        <span class="modal-info-label">Official Violation Description</span>
        <span style="font-size:0.85rem; color:var(--text-secondary);">${notice.report_reason || 'Operating vehicle on public road without active third-party motor insurance coverage.'}</span>
      </div>
    `;

    document.getElementById('app-modal-footer').innerHTML = `
      <a href="/pages/inspector.html?plate=${notice.vehicle_identifier}" class="btn btn-secondary btn-sm">Inspect Vehicle Dossier</a>
      <button class="btn btn-primary btn-sm" onclick="AppModal.close()">Close</button>
    `;

    overlay.classList.add('active');
  },

  showIssueChallanModal(prefillPlate = '', onIssued = null) {
    const overlay = this.getOverlay();
    document.getElementById('app-modal-title').innerHTML = `<span>➕</span> <span>Dispatch Official E-Challan Notice</span>`;
    document.getElementById('app-modal-body').innerHTML = `
      <form id="issue-challan-form" onsubmit="return false;">
        <div class="form-group">
          <label class="form-label">Vehicle Registration Number</label>
          <input type="text" id="modal-challan-plate" class="form-input" style="font-family:var(--font-mono); text-transform:uppercase; font-weight:700;" placeholder="e.g. DL01AB1003" value="${prefillPlate}" required>
        </div>

        <div class="form-group">
          <label class="form-label">Violation Category</label>
          <select id="modal-challan-type" class="form-select">
            <option value="UNINSURED_VEHICLE">Section 196: Driving Without Insurance (₹2,000 Fine)</option>
            <option value="STOLEN_VEHICLE">Police BOLO: Stolen Vehicle Detected on Road</option>
            <option value="EXPIRED_REGISTRATION">Section 39/192: Expired Vehicle RC Registration</option>
            <option value="SCRAPPED_VEHICLE_DETECTED">Section 55: Scrapped Vehicle Operating Illegally</option>
          </select>
        </div>

        <div class="form-group">
          <label class="form-label">Statutory Fine / Action</label>
          <div style="background:var(--bg-subtle); border:1px solid var(--border-subtle); padding:0.65rem 0.85rem; border-radius:var(--radius-md); font-weight:700; color:var(--status-danger); font-family:var(--font-mono);">
            ₹2,000 Penalty / Mandatory Court Summons
          </div>
        </div>

        <div class="form-group">
          <label class="form-label">Violation Description & Evidence</label>
          <textarea id="modal-challan-reason" class="form-textarea" rows="3">Vehicle detected by automated highway ANPR camera with zero active third-party insurance policy on record in IRDAI IIB registry.</textarea>
        </div>
      </form>
    `;

    document.getElementById('app-modal-footer').innerHTML = `
      <button class="btn btn-secondary btn-sm" onclick="AppModal.close()">Cancel</button>
      <button class="btn btn-danger btn-sm" id="btn-submit-modal-challan">Dispatch Notice ➔</button>
    `;

    document.getElementById('btn-submit-modal-challan').onclick = async () => {
      const plate = document.getElementById('modal-challan-plate').value.trim().toUpperCase();
      const type = document.getElementById('modal-challan-type').value;
      const reason = document.getElementById('modal-challan-reason').value.trim();

      if (!plate) {
        alert("Please enter a valid vehicle registration plate number.");
        return;
      }

      const btn = document.getElementById('btn-submit-modal-challan');
      btn.disabled = true;
      btn.textContent = "Dispatching...";

      try {
        const res = await API.issueEChallan({
          vehicle_identifier: plate,
          report_type: type,
          report_reason: reason,
          severity: type === 'STOLEN_VEHICLE' || type === 'SCRAPPED_VEHICLE_DETECTED' ? 'CRITICAL' : 'HIGH'
        });

        AppModal.close();
        AppModal.alert(
          "E-Challan Dispatched Successfully!",
          `Official electronic notice dispatched to MoRTH Registry.\n\nNotice Ref: ${res.ministry_reference}\nTarget Vehicle: ${plate}\nPenalty: ₹${res.fine_amount || '2,000'}\nCache Status: Automatically purged for vehicle.`,
          "✅"
        );

        if (typeof onIssued === 'function') onIssued(res);
      } catch (err) {
        btn.disabled = false;
        btn.textContent = "Dispatch Notice ➔";
        AppModal.alert("Dispatch Error", `Failed to issue e-Challan: ${err.message}`, "❌");
      }
    };

    overlay.classList.add('active');
  }
};

