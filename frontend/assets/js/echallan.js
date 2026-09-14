/**
 * MoRTH E-Challan & Notice Portal Controller
 */
let challanPage = 1;
let loadedChallansMap = {};

document.addEventListener('DOMContentLoaded', () => {
  loadChallans();

  document.getElementById('challan-status-filter')?.addEventListener('change', () => {
    challanPage = 1;
    loadChallans();
  });

  document.getElementById('btn-issue-custom-challan')?.addEventListener('click', () => {
    AppModal.showIssueChallanModal('', () => {
      challanPage = 1;
      loadChallans();
    });
  });
});

async function loadChallans() {
  const tbody = document.getElementById('challan-tbody');
  const filter = document.getElementById('challan-status-filter')?.value || '';
  const host = window.location.hostname || '127.0.0.1';

  if (tbody) tbody.innerHTML = `<tr><td colspan="7" style="text-align:center; padding:2rem; color:var(--text-muted);">Fetching E-Challan records...</td></tr>`;

  try {
    const url = `http://${host}:5006/api/v1/challans?page=${challanPage}&limit=15${filter ? `&status=${filter}` : ''}`;
    const res = await fetch(url);
    const data = await res.json();

    if (!data.challans || data.challans.length === 0) {
      tbody.innerHTML = `<tr><td colspan="7" style="text-align:center; padding:2rem; color:var(--text-muted);">No challans found.</td></tr>`;
      return;
    }

    loadedChallansMap = {};
    data.challans.forEach(c => {
      loadedChallansMap[c.report_id] = c;
    });

    tbody.innerHTML = data.challans.map(c => `
      <tr>
        <td><strong style="font-family:var(--font-mono); color:var(--accent-primary);">${c.ministry_reference}</strong></td>
        <td><a href="/pages/inspector.html?plate=${c.vehicle_identifier}" style="color:var(--text-primary); font-family:var(--font-mono); text-decoration:none; font-weight:700;">${c.vehicle_identifier}</a></td>
        <td>${c.report_type}</td>
        <td><span style="font-size:0.8rem; color:var(--text-muted);">${c.submitted_at}</span></td>
        <td><span class="badge ${c.severity === 'CRITICAL' ? 'badge-danger' : 'badge-warning'}">${c.severity}</span></td>
        <td>
          <select class="btn btn-secondary btn-sm" onchange="updateChallanStatus(${c.report_id}, this.value)">
            <option value="SUBMITTED" ${c.report_status === 'SUBMITTED' ? 'selected' : ''}>SUBMITTED</option>
            <option value="UNDER_REVIEW" ${c.report_status === 'UNDER_REVIEW' ? 'selected' : ''}>UNDER REVIEW</option>
            <option value="FINED" ${c.report_status === 'FINED' ? 'selected' : ''}>FINED (₹2,000)</option>
            <option value="RESOLVED" ${c.report_status === 'RESOLVED' || c.report_status === 'CLOSED' ? 'selected' : ''}>RESOLVED</option>
          </select>
        </td>
        <td>
          <button class="btn btn-secondary btn-sm" onclick="showChallanDetails(${c.report_id})">Details</button>
        </td>
      </tr>
    `).join('');

  } catch (err) {
    if (tbody) tbody.innerHTML = `<tr><td colspan="7" style="text-align:center; padding:2rem; color:#ef4444;">Error: ${err.message}</td></tr>`;
  }
}

function showChallanDetails(reportId) {
  const notice = loadedChallansMap[reportId];
  if (notice) {
    AppModal.showNoticeDetails(notice);
  }
}

async function updateChallanStatus(reportId, newStatus) {
  const host = window.location.hostname || '127.0.0.1';
  try {
    const res = await fetch(`http://${host}:5006/api/v1/challans/${reportId}/status`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ status: newStatus })
    });
    const data = await res.json();
    AppModal.alert("Status Updated", `Notice #${reportId} status changed to ${newStatus}.\nMediator cache has been purged automatically.`, "✅");
    loadChallans();
  } catch (err) {
    AppModal.alert("Update Failed", `Could not update status: ${err.message}`, "❌");
  }
}

