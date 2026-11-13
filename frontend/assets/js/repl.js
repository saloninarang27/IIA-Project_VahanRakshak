/**
 * Distributed SQL REPL Engine Controller
 * Manages operator authentication, multi-hop query routing, telemetry display, and tabular results.
 */

const PRESET_QUERIES = {
  vahan: [
    { label: "Top 10 Registrations", sql: "SELECT vehicle_registration_id, owner_name, vehicle_make, vehicle_model, color, registration_status FROM vehicle_registration LIMIT 10;" },
    { label: "Expired RC Vehicles", sql: "SELECT vehicle_registration_id, owner_name, registration_expiry_date, registration_status FROM vehicle_registration WHERE registration_status != 'ACTIVE' LIMIT 10;" },
    { label: "Table Schema (PRAGMA)", sql: "PRAGMA table_info(vehicle_registration);" }
  ],
  iib: [
    { label: "Uninsured Policies", sql: "SELECT registration_no, insurer_name, policy_number, policy_expiry_date, insurance_status FROM insurance_policy WHERE insurance_status = 'UNINSURED' LIMIT 10;" },
    { label: "Expiring Policies", sql: "SELECT registration_no, insurer_name, policy_number, policy_expiry_date, insurance_status FROM insurance_policy ORDER BY policy_expiry_date ASC LIMIT 10;" },
    { label: "Table Schema (PRAGMA)", sql: "PRAGMA table_info(insurance_policy);" }
  ],
  police: [
    { label: "Stolen Vehicles", sql: "SELECT vehicle_no, theft_status, theft_report_date, authority_reference FROM theft_scrap_record WHERE theft_status = 'STOLEN' LIMIT 10;" },
    { label: "Scrapped Vehicles", sql: "SELECT vehicle_no, scrapping_status, scrapping_date, certificate_no FROM theft_scrap_record WHERE scrapping_status = 'SCRAPPED' LIMIT 10;" },
    { label: "Table Schema (PRAGMA)", sql: "PRAGMA table_info(theft_scrap_record);" }
  ],
  anpr: [
    { label: "Recent Captures", sql: "SELECT plate_number, camera_id, location, captured_timestamp, detected_speed_kmh FROM vehicle_capture ORDER BY captured_timestamp DESC LIMIT 10;" },
    { label: "Camera Locations", sql: "SELECT location, COUNT(*) as total_sightings FROM vehicle_capture GROUP BY location ORDER BY total_sightings DESC;" },
    { label: "Table Schema (PRAGMA)", sql: "PRAGMA table_info(vehicle_capture);" }
  ],
  echallan: [
    { label: "Recent Challans", sql: "SELECT vehicle_identifier, ministry_reference, report_type, severity, fine_amount, report_status FROM ministry_report ORDER BY submitted_at DESC LIMIT 10;" },
    { label: "Challan Statistics", sql: "SELECT report_status, COUNT(*) as count, SUM(fine_amount) as total_fines FROM ministry_report GROUP BY report_status;" },
    { label: "Table Schema (PRAGMA)", sql: "PRAGMA table_info(ministry_report);" }
  ],
  dwh: [
    { label: "Materialized Dossiers", sql: "SELECT vehicle_identifier, make, model, risk_level, insurance_status, suspicion_status, refreshed_at FROM mv_vehicle_complete_history LIMIT 10;" },
    { label: "High & Critical Risk", sql: "SELECT vehicle_identifier, make, model, risk_level, insurance_status FROM mv_vehicle_complete_history WHERE risk_level IN ('HIGH', 'CRITICAL') LIMIT 10;" },
    { label: "Fact Events", sql: "SELECT event_id, vehicle_key, event_type, source_system, captured_speed FROM FACT_VEHICLE_EVENT LIMIT 10;" }
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
