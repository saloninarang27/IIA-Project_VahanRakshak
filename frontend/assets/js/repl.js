/**
 * Distributed SQL REPL Engine Controller
 * Manages operator authentication, multi-hop query routing, telemetry display, and tabular results.
 */

const PRESET_QUERIES = {
  vahan: [
    { label: "Top 10 Registrations", sql: "SELECT vehicle_registration_id, owner_name, vehicle_make, vehicle_model, color, registration_status FROM vehicle_registration LIMIT 10;" },
    { label: "FK Join: Owner + Model + RTO", sql: "SELECT r.vehicle_registration_id, o.owner_name, o.city, m.make, m.model, m.segment, t.rto_name FROM vehicle_registration r JOIN owner o ON o.owner_id = r.owner_id JOIN vehicle_model m ON m.model_id = r.model_id JOIN rto_office t ON t.rto_code = r.rto_code LIMIT 10;" },
    { label: "FK Join: Ownership Transfers", sql: "SELECT r.vehicle_registration_id, f.owner_name AS previous_owner, n.owner_name AS new_owner, x.transfer_date, x.transfer_reason FROM ownership_transfer x JOIN vehicle_registration r ON r.registration_id = x.registration_id JOIN owner f ON f.owner_id = x.from_owner_id JOIN owner n ON n.owner_id = x.to_owner_id LIMIT 10;" },
    { label: "Foreign Keys (PRAGMA)", sql: "PRAGMA foreign_key_list(vehicle_registration);" }
  ],
  iib: [
    { label: "Expired Policies", sql: "SELECT registration_no, insurer_name, policy_number, policy_expiry_date, insurance_status FROM insurance_policy WHERE insurance_status = 'EXPIRED' LIMIT 10;" },
    { label: "FK Join: Policy + Insurer + Holder", sql: "SELECT p.registration_no, p.policy_number, i.insurer_name, i.irdai_reg_no, h.holder_name, h.owner_ref FROM insurance_policy p JOIN insurer i ON i.insurer_id = p.insurer_id JOIN policyholder h ON h.holder_id = p.holder_id LIMIT 10;" },
    { label: "FK Join: Claims with FIR", sql: "SELECT p.registration_no, c.claim_no, c.incident_type, c.incident_city, c.fir_reference, c.claim_amount, c.claim_status FROM claim c JOIN insurance_policy p ON p.policy_id = c.policy_id ORDER BY c.incident_date DESC LIMIT 10;" },
    { label: "Foreign Keys (PRAGMA)", sql: "PRAGMA foreign_key_list(claim);" }
  ],
  police: [
    { label: "Stolen Vehicles", sql: "SELECT vehicle_no, theft_status, theft_report_date, authority_reference FROM theft_scrap_record WHERE theft_status = 'STOLEN' LIMIT 10;" },
    { label: "FK Join: FIR + Station + Recovery", sql: "SELECT f.fir_no, f.vehicle_no, f.offence_type, s.station_name, f.case_status, r.recovery_date FROM fir f JOIN police_station s ON s.station_id = f.station_id LEFT JOIN recovery r ON r.fir_no = f.fir_no LIMIT 10;" },
    { label: "FK Join: Scrapped at RVSF", sql: "SELECT t.vehicle_no, t.scrapping_date, v.facility_name, v.licence_no FROM theft_scrap_record t JOIN rvsf_facility v ON v.rvsf_id = t.rvsf_id LIMIT 10;" },
    { label: "Foreign Keys (PRAGMA)", sql: "PRAGMA foreign_key_list(theft_scrap_record);" }
  ],
  anpr: [
    { label: "Recent Captures", sql: "SELECT plate_number, camera_id, location, captured_timestamp, confidence_score FROM vehicle_capture ORDER BY captured_timestamp DESC LIMIT 10;" },
    { label: "FK Join: Capture + Camera + Plaza", sql: "SELECT c.plate_number, c.captured_timestamp, k.camera_model, p.plaza_name, p.highway, p.city FROM vehicle_capture c JOIN camera k ON k.camera_id = c.camera_id JOIN toll_plaza p ON p.plaza_id = k.plaza_id LIMIT 10;" },
    { label: "FK Join: Hotlist Alerts", sql: "SELECT c.plate_number, a.alert_type, a.raised_at, a.alert_status, t.txn_status FROM anpr_alert a JOIN vehicle_capture c ON c.capture_id = a.capture_id LEFT JOIN toll_transaction t ON t.capture_id = c.capture_id WHERE a.alert_type LIKE 'HOTLIST%' LIMIT 10;" },
    { label: "Foreign Keys (PRAGMA)", sql: "PRAGMA foreign_key_list(anpr_alert);" }
  ],
  echallan: [
    { label: "Recent Challans", sql: "SELECT vehicle_identifier, ministry_reference, report_type, severity, report_status FROM ministry_report ORDER BY submitted_at DESC LIMIT 10;" },
    { label: "FK Join: Challan + Offence + Officer", sql: "SELECT r.vehicle_identifier, r.ministry_reference, o.mv_act_section, o.fine_amount, e.officer_name, e.city FROM ministry_report r JOIN offence_code o ON o.offence_code = r.offence_code JOIN enforcement_officer e ON e.officer_id = r.officer_id LIMIT 10;" },
    { label: "Fines Collected per Offence", sql: "SELECT o.offence_code, o.description, COUNT(p.payment_id) AS paid, SUM(p.amount) AS collected FROM offence_code o LEFT JOIN ministry_report r ON r.offence_code = o.offence_code LEFT JOIN challan_payment p ON p.report_id = r.report_id GROUP BY o.offence_code;" },
    { label: "Foreign Keys (PRAGMA)", sql: "PRAGMA foreign_key_list(ministry_report);" }
  ],
  dwh: [
    { label: "Materialized Dossiers", sql: "SELECT vehicle_identifier, make, model, risk_level, insurance_status, suspicion_status, refreshed_at FROM mv_vehicle_complete_history LIMIT 10;" },
    { label: "High & Critical Risk", sql: "SELECT vehicle_identifier, make, model, risk_level, insurance_status FROM mv_vehicle_complete_history WHERE risk_level IN ('HIGH', 'CRITICAL') LIMIT 10;" },
    { label: "Fact Events", sql: "SELECT event_key, vehicle_key, event_type, event_value, source_system FROM FACT_VEHICLE_EVENT LIMIT 10;" }
  ]
};

let currentTarget = "vahan";
let lastQueryResult = null;
let isJsonViewActive = false;

document.addEventListener("DOMContentLoaded", () => {
  initAuth();
  initTargetSelector();
  initEditor();
  initActionButtons();
  selectTarget("vahan");
});

// ---------------------------------------------------------------------------
// Authentication Handling: raw SQL needs an ADMIN session (checked again by the Mediator
// and by the agency service). Only the signed session token is kept, never the password.
// ---------------------------------------------------------------------------
function isAdminSession() {
  const s = Auth.session();
  return !!(s && s.role === "ADMIN" && Auth.token());
}

function initAuth() {
  const authGate = document.getElementById("repl-auth-gate");
  const workbench = document.getElementById("repl-workbench");
  const statusChip = document.getElementById("auth-status-chip");
  const btnUnlock = document.getElementById("btn-unlock-repl");
  const btnLogout = document.getElementById("btn-logout");
  const errBanner = document.getElementById("auth-error-banner");

  if (isAdminSession()) {
    showWorkbench(Auth.session().user);
  } else {
    showAuthGate();
    const s = Auth.session();
    if (s) showAuthError(`You are signed in as ${s.user} (${s.role}). The SQL console needs an ADMIN account.`);
  }

  btnUnlock.addEventListener("click", async () => {
    const user = document.getElementById("repl-username").value.trim();
    const pass = document.getElementById("repl-password").value;
    if (!user || !pass) {
      showAuthError("Please enter both Operator ID and Password.");
      return;
    }
    btnUnlock.disabled = true;
    btnUnlock.textContent = "Verifying...";
    errBanner.style.display = "none";
    try {
      const res = await Auth.login(user, pass);
      if (!res.ok) {
        showAuthError(res.data.error || "Authentication failed: Invalid credentials.");
      } else if (res.data.role !== "ADMIN") {
        showAuthError(`${user} is a ${res.data.role} account. The SQL console needs an ADMIN account.`);
      } else {
        location.reload();
      }
    } catch (err) {
      showAuthError(`Network error communicating with Mediator: ${err.message}`);
    } finally {
      btnUnlock.disabled = false;
      btnUnlock.textContent = "🔓 Authenticate & Unlock REPL";
    }
  });

  btnLogout.addEventListener("click", () => {
    Auth.logout();
    location.reload();
  });

  function showAuthError(msg) {
    errBanner.textContent = msg;
    errBanner.style.display = "block";
  }

  function showWorkbench(username) {
    authGate.style.display = "none";
    workbench.style.display = "grid";
    statusChip.style.display = "flex";
    document.getElementById("operator-display-name").textContent = username;
  }

  function showAuthGate() {
    authGate.style.display = "block";
    workbench.style.display = "none";
    statusChip.style.display = "none";
  }
}

// ---------------------------------------------------------------------------
// Target Microservice Selection & Presets
// ---------------------------------------------------------------------------
function initTargetSelector() {
  document.querySelectorAll(".db-card-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      const target = btn.getAttribute("data-target");
      selectTarget(target);
    });
  });
}

function selectTarget(target) {
  currentTarget = target;
  document.querySelectorAll(".db-card-btn").forEach((b) => {
    b.classList.toggle("active", b.getAttribute("data-target") === target);
  });

  const activeBtn = document.querySelector(`.db-card-btn[data-target="${target}"]`);
  const dbName = activeBtn ? activeBtn.getAttribute("data-db") : "database.db";
  const agency = activeBtn ? activeBtn.getAttribute("data-agency") : "Microservice";
  const port = activeBtn ? activeBtn.getAttribute("data-port") : "500X";

  // Update pipeline banner
  document.getElementById("flow-microservice-label").textContent = `3. ${agency} (${port})`;
  document.getElementById("flow-db-label").textContent = `4. ${dbName}`;

  // Update editor header
  document.getElementById("editor-tab-label").textContent = `Querying ${dbName} via ${agency} (Port ${port})`;

  // Render Preset Queries
  renderPresetChips(target);
}

function renderPresetChips(target) {
  const container = document.getElementById("sample-queries-chips");
  if (!container) return;

  const presets = PRESET_QUERIES[target] || [];
  container.innerHTML = presets.map((p, idx) => `
    <button class="chip" data-sql="${encodeURIComponent(p.sql)}" style="cursor:pointer; background:#eff6ff; border-color:#bfdbfe; color:#1d4ed8; font-size:0.75rem;">
      📄 ${p.label}
    </button>
  `).join("");

  container.querySelectorAll(".chip").forEach((chip) => {
    chip.addEventListener("click", () => {
      const sql = decodeURIComponent(chip.getAttribute("data-sql"));
      const textarea = document.getElementById("sql-query-input");
      textarea.value = sql;
      textarea.focus();
    });
  });

  // Auto-fill first preset query if textarea is empty or switching target
  if (presets.length > 0) {
    document.getElementById("sql-query-input").value = presets[0].sql;
  }
}

// ---------------------------------------------------------------------------
// Editor & Keyboard Shortcuts
// ---------------------------------------------------------------------------
function initEditor() {
  const textarea = document.getElementById("sql-query-input");

  textarea.addEventListener("keydown", (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
      e.preventDefault();
      runQuery();
    }
  });

  document.getElementById("btn-run-query").addEventListener("click", runQuery);
  document.getElementById("btn-clear-query").addEventListener("click", () => {
    textarea.value = "";
    textarea.focus();
  });
}

function initActionButtons() {
  const btnCopy = document.getElementById("btn-copy-json");
  const btnToggle = document.getElementById("btn-toggle-json");

  btnCopy.addEventListener("click", () => {
    if (!lastQueryResult) return;
    navigator.clipboard.writeText(JSON.stringify(lastQueryResult, null, 2));
    const orig = btnCopy.textContent;
    btnCopy.textContent = "✅ Copied!";
    setTimeout(() => { btnCopy.textContent = orig; }, 1500);
  });

  btnToggle.addEventListener("click", () => {
    isJsonViewActive = !isJsonViewActive;
    const tableWrap = document.getElementById("repl-table-container");
    const jsonWrap = document.getElementById("repl-json-container");

    if (isJsonViewActive) {
      tableWrap.style.display = "none";
      jsonWrap.style.display = "block";
      btnToggle.textContent = "📊 Show Table View";
    } else {
      tableWrap.style.display = "block";
      jsonWrap.style.display = "none";
      btnToggle.textContent = "🔄 Toggle JSON View";
    }
  });
}

// ---------------------------------------------------------------------------
// Query Execution & Telemetry Rendering
// ---------------------------------------------------------------------------
async function runQuery() {
  if (!isAdminSession()) {
    alert("Session expired. Please unlock the REPL console again.");
    location.reload();
    return;
  }

  const queryInput = document.getElementById("sql-query-input");
  const query = queryInput.value.trim();
  if (!query) {
    alert("Please enter a SQL query to execute.");
    return;
  }

  const btnRun = document.getElementById("btn-run-query");
  btnRun.disabled = true;
  btnRun.innerHTML = "⏳ Executing Hop-by-Hop...";

  const telemetryBox = document.getElementById("execution-telemetry-box");
  const resultsCard = document.getElementById("repl-results-card");
  const errAlert = document.getElementById("repl-error-alert");
  const tableWrap = document.getElementById("repl-table-container");
  const jsonWrap = document.getElementById("repl-json-container");

  errAlert.style.display = "none";
  errAlert.textContent = "";

  try {
    const payload = {
      target: currentTarget,
      query: query
    };

    const res = await API.executeSql(payload);
    const data = res.data;
    lastQueryResult = data;

    // Show telemetry & results card
    telemetryBox.style.display = "block";
    resultsCard.style.display = "block";

    // Update Telemetry Metrics
    const isRemote = !!data.is_remote;
    const targetHost = data.target_host || "127.0.0.1";
    const targetPort = data.target_port ? `:${data.target_port}` : "";

    document.getElementById("tel-target-host").textContent = `${targetHost}${targetPort}`;
    
    const remotePill = document.getElementById("tel-remote-mode");
    if (isRemote) {
      remotePill.innerHTML = `<span class="badge badge-purple" style="font-size:0.75rem;">🌐 REMOTE MICROSERVICE</span>`;
    } else {
      remotePill.innerHTML = `<span class="badge badge-success" style="font-size:0.75rem;">💻 LOCAL HOST</span>`;
    }

    document.getElementById("tel-e2e-latency").textContent = `${res.clientLatencyMs || 0} ms`;
    document.getElementById("tel-hop-latency").textContent = `${data.hop_latency_ms || 0} ms`;
    document.getElementById("tel-db-exec").textContent = `${data.remote_db_execution_ms || 0} ms`;
    document.getElementById("tel-row-count").textContent = `${data.row_count || 0}`;
    document.getElementById("results-count-badge").textContent = `${data.row_count || 0} rows`;

    // Render Multi-Hop Audit Trace
    renderAuditTrace(data.trace || []);

    if (!res.ok || data.status === "error") {
      errAlert.style.display = "block";
      errAlert.innerHTML = `
        <strong>⚠️ Query Execution Error on ${data.target || currentTarget}:</strong><br>
        <span style="font-size:0.88rem;">${data.error || "An unknown error occurred."}</span>
      `;
      tableWrap.style.display = "none";
      jsonWrap.style.display = "none";
    } else {
      // Render Table
      renderTable(data.columns || [], data.rows || []);
      jsonWrap.textContent = JSON.stringify(data, null, 2);

      if (isJsonViewActive) {
        tableWrap.style.display = "none";
        jsonWrap.style.display = "block";
      } else {
        tableWrap.style.display = "block";
        jsonWrap.style.display = "none";
      }
    }
  } catch (err) {
    telemetryBox.style.display = "none";
    resultsCard.style.display = "block";
    errAlert.style.display = "block";
    errAlert.textContent = `Network / Mediator Failure: ${err.message}`;
    tableWrap.style.display = "none";
    jsonWrap.style.display = "none";
  } finally {
    btnRun.disabled = false;
    btnRun.innerHTML = "▶️ Execute SQL Query";
  }
}

function renderAuditTrace(traceSteps) {
  const container = document.getElementById("hop-audit-trace");
  if (!container) return;

  if (!traceSteps || traceSteps.length === 0) {
    container.innerHTML = "<em>No trace telemetry returned.</em>";
    return;
  }

  container.innerHTML = traceSteps.map((s) => `
    <div style="display:flex; justify-content:space-between; padding:0.25rem 0; border-bottom:1px dashed #e2e8f0;">
      <span><strong>Hop ${s.hop}:</strong> ${s.action || s.from + " -> " + s.to}</span>
      <span style="color:#059669; font-weight:700;">${s.status || "OK"}</span>
    </div>
  `).join("");
}

function renderTable(columns, rows) {
  const thead = document.getElementById("repl-table-head");
  const tbody = document.getElementById("repl-table-body");

  if (!columns || columns.length === 0) {
    thead.innerHTML = "<tr><th>Query Result</th></tr>";
    tbody.innerHTML = "<tr><td><em>Query completed with 0 returned columns.</em></td></tr>";
    return;
  }

  thead.innerHTML = `<tr>${columns.map((c) => `<th>${escapeHtml(c)}</th>`).join("")}</tr>`;

  if (!rows || rows.length === 0) {
    tbody.innerHTML = `<tr><td colspan="${columns.length}" style="text-align:center; color:var(--text-muted); padding:2rem;">0 rows returned.</td></tr>`;
    return;
  }

  tbody.innerHTML = rows.map((row) => {
    return `<tr>${row.map((cell) => {
      if (cell === null || cell === undefined) {
        return `<td><span class="null-cell">NULL</span></td>`;
      }
      return `<td>${escapeHtml(String(cell))}</td>`;
    }).join("")}</tr>`;
  }).join("");
}

function escapeHtml(str) {
  return str
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}
