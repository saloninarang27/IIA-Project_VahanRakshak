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
  const alertContainer = document.getElementById('inspector-network-alert');

  if (emptyState) emptyState.style.display = 'none';
  if (resultsContainer) resultsContainer.style.display = 'none';
  if (loading) loading.style.display = 'block';
  if (alertContainer) {
    alertContainer.style.display = 'none';
    alertContainer.innerHTML = '';
  }

  try {
    const res = await API.getVehicle(plate, forceSync);

    // If completely failed and no cache exists
    if (res.data.source === 'FEDERATION_FAILED' || !res.data.vehicle) {
      if (loading) loading.style.display = 'none';
      if (resultsContainer) resultsContainer.style.display = 'block';

      if (alertContainer) {
        alertContainer.style.display = 'block';
        alertContainer.innerHTML = `
          <div style="background:#fef2f2; border:1px solid #fecaca; padding:1.25rem; border-radius:var(--radius-md); margin-bottom:1.5rem; display:flex; align-items:flex-start; gap:0.85rem; box-shadow:0 1px 3px rgba(0,0,0,0.05);">
            <span style="font-size:1.8rem; line-height:1;">❌</span>
            <div style="flex:1;">
              <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:0.5rem;">
                <strong style="color:#991b1b; font-size:1rem;">Cannot Reach Backend APIs — No Local Cache Available</strong>
                <span class="badge badge-danger">ALL SERVICES OFFLINE</span>
              </div>
              <div style="font-size:0.88rem; color:#b91c1c; margin-top:0.35rem; line-height:1.45;">
                All 5 microservices at <code>${res.data.target_host || 'remote host'}</code> are offline or unreachable, and plate <strong>${plate}</strong> has never been cached in the local Data Warehouse.
              </div>
            </div>
          </div>
        `;
      }

      const dossierCard = document.getElementById('primary-dossier-card');
      if (dossierCard) dossierCard.style.display = 'none';

      const trace = await API.getFederatedTrace(plate).catch(() => null);
      if (trace && trace.decomposed_queries) {
        renderFederationTree(trace.decomposed_queries);
      }
      return;
    }

    const dossierCard = document.getElementById('primary-dossier-card');
    if (dossierCard) dossierCard.style.display = 'block';

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
  const failedCount = res.data.failed_count || 0;
  const targetHost = res.data.target_host || 'remote host';

  // Offline / Fallback Warning Banner
  const alertContainer = document.getElementById('inspector-network-alert');
  if (alertContainer) {
    if (source === 'CACHE_FALLBACK' || failedCount === 5) {
      alertContainer.style.display = 'block';
      alertContainer.innerHTML = `
        <div style="background:#fffbeb; border:1px solid #fcd34d; padding:1.15rem 1.25rem; border-radius:var(--radius-md); margin-bottom:1.5rem; display:flex; align-items:flex-start; gap:0.85rem; box-shadow:0 1px 3px rgba(0,0,0,0.05);">
          <span style="font-size:1.6rem; line-height:1;">⚠️</span>
          <div style="flex:1;">
            <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:0.5rem;">
              <strong style="color:#92400e; font-size:0.95rem;">Cannot Reach Backend APIs — Displaying Local Cached Record</strong>
              <span class="badge badge-danger" style="font-size:0.75rem;">HOST UNREACHABLE (${targetHost})</span>
            </div>
            <div style="font-size:0.85rem; color:#b45309; margin-top:0.35rem; line-height:1.45;">
              The 5 backend microservices at <code>${targetHost}</code> could not be reached (all requests timed out or connection refused).
              Vehicle Sentinel's <strong>Fault-Tolerant Cache-Aside Engine</strong> prevented data loss and served the last verified vehicle dossier from the <strong>Local Kimball Star Schema Data Warehouse</strong>.
            </div>
          </div>
        </div>
      `;
    } else if (source === 'PARTIAL_FEDERATION') {
      alertContainer.style.display = 'block';
      alertContainer.innerHTML = `
        <div style="background:#fef3c7; border:1px solid #fcd34d; padding:0.9rem 1.2rem; border-radius:var(--radius-md); margin-bottom:1.25rem; display:flex; align-items:flex-start; gap:0.75rem;">
          <span style="font-size:1.4rem; line-height:1;">⚠️</span>
          <div style="flex:1;">
            <strong style="color:#92400e; font-size:0.9rem;">Partial Federation: ${failedCount}/5 Services Offline</strong>
            <div style="font-size:0.83rem; color:#b45309; margin-top:0.25rem;">
              Some remote services were unreachable. Available live data was merged with cached attributes from the local warehouse.
            </div>
          </div>
        </div>
      `;
    } else {
      alertContainer.style.display = 'none';
      alertContainer.innerHTML = '';
    }
  }

  // Header badges
  document.getElementById('res-plate').textContent = v.vehicle_identifier;
  const sourceBadge = document.getElementById('res-source-badge');
  if (source === 'CACHE_FALLBACK') {
    sourceBadge.innerHTML = `<span class="badge" style="background:#fef3c7; color:#b45309; border:1px solid #fde68a; font-weight:600;">⚠️ Host Offline • Cached DWH (${latency}ms)</span>`;
  } else if (source === 'CACHE_HIT') {
    sourceBadge.innerHTML = `<span class="badge badge-success">⚡ Cache Hit (${latency}ms)</span>`;
  } else if (source === 'PARTIAL_FEDERATION') {
    sourceBadge.innerHTML = `<span class="badge badge-warning">⚠️ Partial Live Federation (${latency}ms)</span>`;
  } else {
    sourceBadge.innerHTML = `<span class="badge badge-purple">🌐 Live 5-API Federation (${latency}ms)</span>`;
  }
  
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

  // Update Visualizer Header Badge
  const fedBadge = document.getElementById('federation-status-badge');
  if (fedBadge) {
    if (source === 'CACHE_FALLBACK' || failedCount === 5) {
      fedBadge.className = 'badge badge-danger';
      fedBadge.textContent = `Backend APIs Offline (5/5 Failed at ${targetHost})`;
    } else if (failedCount > 0) {
      fedBadge.className = 'badge badge-warning';
      fedBadge.textContent = `${failedCount}/5 Services Offline`;
    } else {
      fedBadge.className = 'badge badge-success';
      fedBadge.textContent = 'Federation Operational (5/5 Online)';
    }
  }

  // Render Federation Tree
  if (trace && trace.decomposed_queries) {
    renderFederationTree(trace.decomposed_queries);
  }
}

function renderFederationTree(queries) {
  const container = document.getElementById('federation-cards-container');
  if (!container) return;

  container.innerHTML = Object.entries(queries).map(([key, q]) => {
    const isOnline = (q.status === 200) && !q.error;
    const badgeHtml = isOnline
      ? `<span class="badge badge-success">${q.latency_ms}ms</span>`
      : `<span class="badge badge-danger">OFFLINE (${q.status || 503})</span>`;

    const errorHtml = (!isOnline && q.error)
      ? `<div style="background:#fef2f2; border:1px solid #fecaca; border-radius:4px; padding:0.35rem 0.5rem; color:#b91c1c; font-size:0.75rem; margin-top:0.4rem; word-break:break-word;">
           ⚠️ <strong>Connection Error:</strong> ${q.error}
         </div>`
      : '';

    return `
      <div class="agency-card" style="${isOnline ? '' : 'border-color:#fca5a5; background:#fffafb;'}">
        <div class="agency-header">
          <span class="agency-name">${q.agency}</span>
          ${badgeHtml}
        </div>
        <div class="agency-meta">Key: <code>${q.local_attribute}</code></div>
        <div class="agency-query-badge" style="word-break:break-all;">${q.endpoint}</div>
        ${errorHtml}
        <details style="margin-top:0.5rem; font-size:0.75rem; color:var(--text-muted);">
          <summary style="cursor:pointer; color:var(--accent-primary);">View Raw Response</summary>
          <pre style="background:#f8fafc; border:1px solid var(--border-subtle); color:var(--text-primary); padding:0.5rem; border-radius:4px; margin-top:0.25rem; max-height:120px; overflow-y:auto; font-family:var(--font-mono);">${JSON.stringify(q.response || { error: q.error }, null, 2)}</pre>
        </details>
      </div>
    `;
  }).join('');
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

