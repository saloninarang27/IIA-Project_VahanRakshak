/**
 * Vehicle Dossier Inspector & Federated Query Visualizer
 */
document.addEventListener('DOMContentLoaded', () => {
  const input = document.getElementById('plate-input');
  const btnSearch = document.getElementById('btn-search');
  const btnForceSync = document.getElementById('btn-force-sync');

  // URL params check (e.g. ?plate=DL01AB1004)
  const urlParams = new URLSearchParams(window.location.search);
  const plateParam = urlParams.get('plate');
  if (plateParam) {
    if (input) input.value = plateParam;
    inspectVehicle(plateParam, false);
  } else if (input && input.value) {
    inspectVehicle(input.value, false);
  }

  if (btnSearch) {
    btnSearch.addEventListener('click', () => {
      const plate = input.value.trim();
      if (plate) inspectVehicle(plate, false);
    });
  }

  if (btnForceSync) {
    btnForceSync.addEventListener('click', () => {
      const plate = input.value.trim();
      if (plate) inspectVehicle(plate, true);
    });
  }

  if (input) {
    input.addEventListener('keypress', (e) => {
      if (e.key === 'Enter') {
        const plate = input.value.trim();
        if (plate) inspectVehicle(plate, false);
      }
    });
  }

  // Quick chips
  document.querySelectorAll('.chip[data-plate]').forEach(chip => {
    chip.addEventListener('click', () => {
      const plate = chip.getAttribute('data-plate');
      if (input) input.value = plate;
      inspectVehicle(plate, false);
    });
  });
});

async function inspectVehicle(plate, forceSync = false) {
  const resultsContainer = document.getElementById('inspector-results');
  const emptyState = document.getElementById('inspector-empty');
  const loading = document.getElementById('inspector-loading');

  if (emptyState) emptyState.style.display = 'none';
  if (resultsContainer) resultsContainer.style.display = 'none';
  if (loading) loading.style.display = 'block';

  try {
    const res = await API.getVehicle(plate, forceSync);
    const trace = await API.getFederatedTrace(plate);

    if (loading) loading.style.display = 'none';
    if (resultsContainer) resultsContainer.style.display = 'block';

    renderDossier(res, trace);
  } catch (err) {
    if (loading) loading.style.display = 'none';
    alert(`Failed to query vehicle: ${err.message}`);
  }
}

function renderDossier(res, trace) {
  const v = res.data.vehicle;
  const source = res.data.source;
  const latency = res.data.query_latency_ms || res.data.federation_latency_ms || res.clientLatencyMs;

  // Header badges
  document.getElementById('res-plate').textContent = v.vehicle_identifier;
  document.getElementById('res-source-badge').innerHTML = source === 'CACHE_HIT'
    ? `<span class="badge badge-success">⚡ Cache Hit (${latency}ms)</span>`
    : `<span class="badge badge-purple">🌐 Live 5-API Federation (${latency}ms)</span>`;
  
  document.getElementById('res-risk-badge').innerHTML = getRiskBadge(v.risk_level);
  document.getElementById('res-insurance-badge').innerHTML = getInsuranceBadge(v.insurance_status);
  document.getElementById('res-theft-badge').innerHTML = getTheftBadge(v.theft_status);

  // Specifications
  document.getElementById('val-make-model').textContent = `${v.make || 'Unknown'} ${v.model || ''}`;
  document.getElementById('val-type-fuel').textContent = `${v.vehicle_type || 'Vehicle'} • ${v.fuel_type || 'N/A'}`;
  document.getElementById('val-color').textContent = v.color || 'Unknown';
  document.getElementById('val-owner').textContent = `${v.owner_name || 'Anonymous'} (${v.owner_id || 'N/A'})`;

  // Registration
  document.getElementById('val-reg-status').innerHTML = v.registration_status === 'ACTIVE'
    ? '<span class="badge badge-success">ACTIVE</span>'
    : '<span class="badge badge-warning">EXPIRED</span>';
  document.getElementById('val-reg-date').textContent = v.registration_date || 'N/A';
  document.getElementById('val-reg-expiry').textContent = v.registration_expiry_date || 'N/A';

  // Insurance
  document.getElementById('val-insurer').textContent = v.insurance_company || 'No insurer record';
  document.getElementById('val-policy-no').textContent = v.policy_number || 'None';
  document.getElementById('val-policy-expiry').textContent = v.insurance_expiry_date || 'N/A';

  // Road camera
  document.getElementById('val-location').textContent = v.location || 'Not sighted';
  document.getElementById('val-capture-time').textContent = v.capture_time || 'N/A';
  document.getElementById('val-cam-id').textContent = v.camera_id || 'N/A';

  // Theft & scrap
  document.getElementById('val-theft-status').textContent = v.theft_status;
  document.getElementById('val-theft-date').textContent = v.theft_report_date || 'None';
  document.getElementById('val-scrapping-status').textContent = v.scrapping_status;

  // Ministry status & e-challan button
  const challanBox = document.getElementById('challan-action-box');
  if (challanBox) {
    if (v.ministry_reference || (v.challans && v.challans.length > 0)) {
      // Challan is ALREADY issued!
      const ref = v.ministry_reference || (v.challans[0] && v.challans[0].ministry_reference) || 'MOT-NOTICE-ACTIVE';
      const status = v.ministry_report_status || (v.challans[0] && v.challans[0].report_status) || 'SUBMITTED';
      challanBox.innerHTML = `
        <div style="background:#eff6ff; border:1px solid #bfdbfe; padding:1.15rem; border-radius:var(--radius-md); display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:0.75rem;">
          <div>
            <div style="font-weight:700; color:#1d4ed8; display:flex; align-items:center; gap:0.4rem;">
              <span>📋</span> Official E-Challan Notice Active on Record
            </div>
            <div style="font-size:0.85rem; color:var(--text-secondary); margin-top:0.25rem;">
              Notice Ref: <strong style="font-family:var(--font-mono); color:var(--text-primary);">${ref}</strong> &nbsp;|&nbsp;
              Status: <span class="badge ${status === 'FINED' ? 'badge-danger' : 'badge-warning'}">${status}</span> &nbsp;|&nbsp;
              Statutory Fine: <strong>₹2,000</strong>
            </div>
          </div>
          <a href="/pages/echallan.html" class="btn btn-secondary btn-sm" style="text-decoration:none;">
            View in E-Challan Register ➔
          </a>
        </div>
      `;
    } else if (v.ministry_report_required) {
      // Violation detected, NO challan issued yet!
      challanBox.innerHTML = `
        <div style="background:#fef2f2; border:1px solid #fecaca; padding:1.15rem; border-radius:var(--radius-md); display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:0.75rem;">
          <div>
            <div style="font-weight:700; color:#b91c1c; display:flex; align-items:center; gap:0.4rem;">
              <span>⚠️</span> Motor Vehicles Act Violation Flagged (Pending Notice)
            </div>
            <div style="font-size:0.85rem; color:var(--text-secondary); margin-top:0.25rem;">Reason: ${(v.ministry_report_reasons || []).join(', ')}</div>
          </div>
          <button class="btn btn-danger btn-sm" onclick="triggerIssueChallan('${v.vehicle_identifier}')">📨 Issue E-Challan (₹2,000)</button>
        </div>
      `;
    } else {
      challanBox.innerHTML = `
        <div style="background:#f0fdf4; border:1px solid #bbf7d0; padding:1rem; border-radius:var(--radius-md); font-size:0.88rem; color:#15803d; display:flex; align-items:center; gap:0.5rem;">
          <span>✅</span> Clean Record: Compliant with Motor Vehicle Regulations. No E-Challan Required.
        </div>
      `;
    }
  }

  // Render Federation Tree
  renderFederationTree(trace.decomposed_queries);
}

function renderFederationTree(queries) {
  const container = document.getElementById('federation-cards-container');
  if (!container) return;

  container.innerHTML = Object.entries(queries).map(([key, q]) => `
    <div class="agency-card">
      <div class="agency-header">
        <span class="agency-name">${q.agency}</span>
        <span class="badge badge-success">${q.latency_ms}ms</span>
      </div>
      <div class="agency-meta">Key: <code>${q.local_attribute}</code></div>
      <div class="agency-query-badge" style="word-break:break-all;">${q.endpoint}</div>
      <details style="margin-top:0.5rem; font-size:0.75rem; color:var(--text-muted);">
        <summary style="cursor:pointer; color:var(--accent-primary);">View Raw Response</summary>
        <pre style="background:#f8fafc; border:1px solid var(--border-subtle); color:var(--text-primary); padding:0.5rem; border-radius:4px; margin-top:0.25rem; max-height:120px; overflow-y:auto; font-family:var(--font-mono);">${JSON.stringify(q.response, null, 2)}</pre>
      </details>
    </div>
  `).join('');
}

function triggerIssueChallan(plate) {
  AppModal.confirm(
    "Issue Official E-Challan Notice",
    `Confirm dispatching an official electronic violation notice (Section 196 Motor Vehicles Act) for vehicle ${plate}? This will assess a statutory ₹2,000 penalty and automatically purge the vehicle's cached dossier.`,
    async () => {
      try {
        const res = await API.issueEChallan({
          vehicle_identifier: plate,
          report_type: 'UNINSURED_VEHICLE',
          report_reason: 'Operating on road without active motor insurance policy (MV Act Section 196)',
          severity: 'HIGH'
        });
        AppModal.alert(
          "E-Challan Dispatched",
          `Official electronic notice dispatched to MoRTH Registry.\n\nNotice Ref: ${res.ministry_reference}\nVehicle: ${plate}\nStatutory Fine: ₹${res.fine_amount || '2,000'}\nStatus: SUBMITTED (Cache purged)`,
          "✅"
        );
        inspectVehicle(plate, true); // re-inspect to refresh
      } catch (err) {
        AppModal.alert("Dispatch Error", `Failed to issue challan: ${err.message}`, "❌");
      }
    },
    "Dispatch E-Challan",
    "Cancel",
    true
  );
}

