/**
 * Fleet Intelligence: Server-Side Paginated Table Controller (<5ms)
 */
let currentPage = 1;
let currentLimit = 15;

document.addEventListener('DOMContentLoaded', () => {
  loadFleetTable();

  document.getElementById('filter-insurance')?.addEventListener('change', () => { currentPage = 1; loadFleetTable(); });
  document.getElementById('filter-theft')?.addEventListener('change', () => { currentPage = 1; loadFleetTable(); });
  document.getElementById('filter-location')?.addEventListener('change', () => { currentPage = 1; loadFleetTable(); });
  
  const searchInput = document.getElementById('filter-search');
  if (searchInput) {
    let debounceTimer;
    searchInput.addEventListener('input', () => {
      clearTimeout(debounceTimer);
      debounceTimer = setTimeout(() => {
        currentPage = 1;
        loadFleetTable();
      }, 300);
    });
  }

  document.getElementById('btn-prev-page')?.addEventListener('click', () => {
    if (currentPage > 1) {
      currentPage--;
      loadFleetTable();
    }
  });

  document.getElementById('btn-next-page')?.addEventListener('click', () => {
    currentPage++;
    loadFleetTable();
  });
});

async function loadFleetTable() {
  const tableBody = document.getElementById('fleet-tbody');
  const pageIndicator = document.getElementById('fleet-page-indicator');
  const latencyBadge = document.getElementById('fleet-latency-badge');
  const btnPrev = document.getElementById('btn-prev-page');
  const btnNext = document.getElementById('btn-next-page');

  const insurance = document.getElementById('filter-insurance')?.value || 'All';
  const theft = document.getElementById('filter-theft')?.value || 'All';
  const location = document.getElementById('filter-location')?.value || 'All';
  const search = document.getElementById('filter-search')?.value.trim() || '';

  if (tableBody) tableBody.innerHTML = `<tr><td colspan="8" style="text-align:center; padding:2rem; color:var(--text-muted);">Querying global warehouse...</td></tr>`;

  try {
    const res = await API.getFleetDetections({
      page: currentPage,
      limit: currentLimit,
      insurance_status: insurance,
      theft_status: theft,
      location: location,
      search: search
    });

    if (latencyBadge) {
      latencyBadge.textContent = `⚡ Server-side SQL query: ${res.clientLatencyMs}ms (${res.total.toLocaleString()} total rows)`;
    }

    if (pageIndicator) {
      pageIndicator.textContent = `Page ${res.page} of ${res.pages || 1} • Showing ${res.rows.length} records`;
    }

    if (btnPrev) btnPrev.disabled = res.page <= 1;
    if (btnNext) btnNext.disabled = res.page >= res.pages;

    if (!res.rows || res.rows.length === 0) {
      tableBody.innerHTML = `<tr><td colspan="8" style="text-align:center; padding:2rem; color:var(--text-muted);">No records match these criteria.</td></tr>`;
      return;
    }

    tableBody.innerHTML = res.rows.map(r => `
      <tr>
        <td><a href="/pages/inspector.html?plate=${r.vehicle_identifier}" style="color:var(--accent-primary); font-weight:700; text-decoration:none; font-family:var(--font-mono);">${r.vehicle_identifier}</a></td>
        <td><strong>${r.make || ''} ${r.model || ''}</strong></td>
        <td>${r.location || 'Unknown'}</td>
        <td><span style="font-family:var(--font-mono); font-size:0.8rem;">${r.capture_time || 'N/A'}</span></td>
        <td>${getInsuranceBadge(r.insurance_status)}</td>
        <td>${getTheftBadge(r.theft_status)}</td>
        <td>${getRiskBadge(r.risk_level)}</td>
        <td>
          <a href="/pages/inspector.html?plate=${r.vehicle_identifier}" class="btn btn-secondary btn-sm">Inspect</a>
        </td>
      </tr>
    `).join('');

  } catch (err) {
    if (tableBody) tableBody.innerHTML = `<tr><td colspan="8" style="text-align:center; padding:2rem; color:#ef4444;">Error fetching data: ${err.message}</td></tr>`;
  }
}
