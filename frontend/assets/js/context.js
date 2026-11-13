/**
 * Federated context discovery page: query -> rounds across the five agency databases -> context.
 */
const CTX_EXAMPLES = [
  'Is DL01AB1004 stolen? any insurance claim?',
  'DL01A81004 theft claim',
  'accident claim FIR70001',
  'stolen Nexon Gurugram',
];

const esc = (v) => String(v ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

document.addEventListener('DOMContentLoaded', () => {
  const box = document.getElementById('ctx-examples');
  CTX_EXAMPLES.forEach(q => {
    const a = document.createElement('a');
    a.href = '#';
    a.className = 'ctx-chip';
    a.textContent = q;
    a.addEventListener('click', e => { e.preventDefault(); document.getElementById('ctx-query').value = q; runContext(); });
    box.appendChild(a);
  });
  document.getElementById('ctx-run').addEventListener('click', runContext);
  document.getElementById('ctx-method').addEventListener('change', () => { if (document.getElementById('ctx-query').value.trim()) runContext(); });
  document.getElementById('doc-add').addEventListener('click', addDocument);
  document.getElementById('ctx-query').addEventListener('keydown', e => { if (e.key === 'Enter') runContext(); });
  const q = new URLSearchParams(location.search).get('q');
  if (q) { document.getElementById('ctx-query').value = q; runContext(); }
});

async function runContext() {
  const query = document.getElementById('ctx-query').value.trim();
  if (!query) return;
  const btn = document.getElementById('ctx-run');
  const err = document.getElementById('ctx-error');
  btn.disabled = true;
  btn.textContent = 'Federating…';
  err.style.display = 'none';
  try {
    const { ok, data } = await API.discoverContext(query, document.getElementById('ctx-method').value);
    if (!ok || data.status === 'error') throw new Error(data.error || 'Context discovery failed');
    render(data);
  } catch (e) {
    err.textContent = e.message;
    err.style.display = 'block';
    document.getElementById('ctx-result').style.display = 'none';
  } finally {
    btn.disabled = false;
    btn.textContent = 'Discover context';
  }
}

function chips(list, fmt) {
  return (list || []).map(x => `<span class="ctx-chip">${fmt(x)}</span>`).join('') || '<span style="color:var(--text-muted)">—</span>';
}

function render(d) {
  document.getElementById('ctx-result').style.display = 'block';
  renderIntegrated(d);
  renderDocuments(d.documents);
  const p = d.parsed;
  const seeds = Object.entries(p.seeds).map(([k, v]) => `<span class="ctx-chip">${esc(k)}: ${esc(v.join(', '))}</span>`).join('');
  const resolution = (p.plate_resolution || []).map(r => r.resolved_to
    ? `<div>🧩 noisy plate <b>${esc(r.query_plate)}</b> → <b>${esc(r.resolved_to)}</b> (${esc(r.rule)}: ${esc(r.reason)})</div>`
    : `<div>⚠️ <b>${esc(r.query_plate)}</b> not resolved (${esc(r.decision)}); candidates: ${esc((r.candidates || []).join(', '))}</div>`).join('');
  let focus = '';
  if (d.text_focus) {
    focus = `<div style="margin-top:0.6rem; font-size:0.8rem;">No key in the query, so round 1 was a text search. Vehicles ranked by how many query words their facts cover across all databases:
      <table class="data-table" style="margin-top:0.4rem;"><thead><tr><th>Vehicle</th><th>Coverage</th><th>Words</th><th>Score</th></tr></thead><tbody>
      ${d.text_focus.ranking.slice(0, 6).map(r => `<tr${d.text_focus.chosen_plates.includes(r.plate) ? ' style="background:#ecfdf5"' : ''}>
        <td class="mono">${esc(r.plate)}</td><td>${esc(r.coverage)}</td><td>${esc(r.words_covered.join(', '))}</td><td>${r.score}</td></tr>`).join('')}
      </tbody></table>Continued with: <b>${esc(d.text_focus.chosen_plates.join(', '))}</b></div>`;
  }
  document.getElementById('ctx-parsed').innerHTML = `
    <dl class="ctx-kv">
      <dt>Query</dt><dd>${esc(d.query)}</dd>
      <dt>Mode</dt><dd>${d.mode === 'keys' ? 'keys found in the query' : 'text search'}</dd>
      <dt>Seed keys</dt><dd>${seeds}</dd>
      <dt>Query terms</dt><dd>${chips(p.terms, esc)}</dd>
      <dt>Your role</dt><dd><span class="badge badge-info">${esc(d.role)}</span></dd>
    </dl>${resolution ? `<div style="margin-top:0.6rem; font-size:0.8rem;">${resolution}</div>` : ''}${focus}`;

  const agencies = Object.entries(d.facts_by_agency).map(([a, n]) => `<span class="ctx-chip">${esc(a)} <b>${n}</b></span>`).join('');
  const reached = d.rounds.reduce((n, r) => n + r.agencies.filter(a => a.status === 200).length, 0);
  document.getElementById('ctx-summary').innerHTML = `
    <dl class="ctx-kv">
      <dt>Rounds</dt><dd>${d.rounds.length} (${reached} sub-queries answered)</dd>
      <dt>Facts kept</dt><dd>${d.facts.length} (score ≥ ${d.settings.min_fact_score}, max ${d.settings.max_facts})</dd>
      <dt>From</dt><dd>${agencies || '—'}</dd>
      <dt>Context terms</dt><dd>${chips(d.context_terms.slice(0, 18), t => `${esc(t.term)}<b>${t.weight}</b>`)}</dd>
      <dt>Time</dt><dd>${d.latency_ms} ms</dd>
    </dl>`;

  document.getElementById('ctx-rounds').innerHTML = d.rounds.map(r => `
    <div class="ctx-round"><h4>Round ${r.round}${r.round > 1 ? ' — keys found in round ' + (r.round - 1) + ' sent to the databases that hold them' : ' — sub-query sent to all five databases in parallel'}</h4>
      <div class="ctx-agency head"><div>Agency</div><div>Endpoint (machine)</div><div>Sent</div><div>Keys found → next round</div><div>Facts</div></div>
      ${r.agencies.map(a => `<div class="ctx-agency">
        <div><span class="ctx-agency-tag">${esc(a.agency)}</span><div style="color:var(--text-muted)">${a.status === 200 ? a.latency_ms + ' ms' : '<span style="color:#b91c1c">' + esc(a.error || a.status) + '</span>'}</div></div>
        <div class="mono">${esc(a.endpoint.replace('/api/v1/context', ''))}</div>
        <div>${chips(Object.entries(a.seeds_sent), ([k, v]) => `${esc(k)}: ${esc(v.join(', '))}`)}</div>
        <div>${chips(Object.entries(a.keys_found), ([k, v]) => `${esc(k)}: ${esc(v.slice(0, 4).join(', '))}${v.length > 4 ? ' …' : ''}`)}</div>
        <div>${a.facts}${a.stats ? `<div style="color:var(--text-muted)">${a.stats.tables_reached.length} tables</div>` : ''}</div>
      </div>`).join('')}
    </div>`).join('');

  document.getElementById('ctx-entities').innerHTML = `<dl class="ctx-kv">${Object.entries(d.entities).map(([g, items]) =>
    `<dt>${esc(g.replace('_', ' '))}</dt><dd>${chips(items.slice(0, 12), i => `${esc(i.value)}<b>${i.weight}</b>`)}</dd>`).join('')}</dl>`;

  document.getElementById('ctx-facts').innerHTML = `<div class="table-container"><table class="data-table">
    <thead><tr><th>Score</th><th>Agency</th><th>Fact</th><th>Found via (FK → PK)</th><th>Round / hop</th><th>Data</th></tr></thead><tbody>
    ${d.facts.map(f => `<tr>
      <td><b>${f.score}</b>${f.matched_terms.length ? `<div style="font-size:0.7rem;color:var(--text-muted)">${esc(f.matched_terms.join(', '))}</div>` : ''}</td>
      <td><span class="ctx-agency-tag">${esc(f.agency)}</span></td>
      <td>${esc(f.label)}${f.redacted ? ' <span class="badge badge-warning" title="Your role may not see this table: only its keys are shown">keys only</span>' : ''}</td>
      <td class="ctx-via">${esc(f.via)}</td>
      <td>${f.round} / ${f.hop}</td>
      <td class="ctx-row">${esc(Object.entries(f.row).filter(([, v]) => v !== null && v !== '').slice(0, 7).map(([k, v]) => `${k}=${v}`).join('  ·  '))}</td>
    </tr>`).join('')}
    </tbody></table></div>`;
}


// ---------------------------------------------------------------------------
// Rubric 3: documents + integration
// ---------------------------------------------------------------------------
const FINDING_STYLE = {
  NEW_LEAD: ['badge-danger', '🚨 New lead'], STATUS_CONFLICT: ['badge-warning', '⚠️ Conflict'],
  UNREPORTED_THEFT: ['badge-warning', '⚠️ Unreported theft'], UNCLAIMED_INCIDENT: ['badge-warning', '⚠️ Not claimed'],
  NO_FIR: ['badge-warning', '⚠️ No FIR'], NOISY_PLATE: ['badge-info', '🧩 Noisy plate'],
};

function marked(text) {
  return esc(text).replace(/\[\[(.+?)\]\]/g, '<mark>$1</mark>');
}

function renderIntegrated(d) {
  const box = document.getElementById('ctx-integrated');
  const plates = Object.keys(d.structured || {});
  if (!plates.length) { box.innerHTML = '<span style="color:var(--text-muted)">No vehicle identified.</span>'; return; }
  box.innerHTML = plates.map(p => {
    const v = d.structured[p] || {};
    const i = (d.integration || {})[p] || { findings: [], timeline: [], documents: [] };
    const kv = [['Vehicle', `${v.make || ''} ${v.model || ''} ${v.color ? '(' + v.color + ')' : ''}`], ['Owner', v.owner_name],
      ['Registration', v.registration_status],
      ['Insurance', `${v.insurance_status || ''}${v.insurance_company ? ' · ' + v.insurance_company : ''}${v.insurance_expiry_date ? ' · till ' + v.insurance_expiry_date : ''}`],
      ['Theft / scrap', `${v.suspicion_status || ''}${v.theft_report_date ? ' since ' + v.theft_report_date : ''}`],
      ['Last camera sighting', v.capture_time ? `${v.capture_time} · ${v.location}` : 'never'], ['Open challans', v.open_challans],
      ['Risk', v.risk_level]];
    const findings = i.findings.length ? i.findings.map(f => {
      const [cls, label] = FINDING_STYLE[f.type] || ['badge-info', f.type];
      return `<div style="margin:0.25rem 0; font-size:0.83rem;"><span class="badge ${cls}">${label}</span> ${esc(f.detail)} <a href="#doc-${f.doc_id}" style="font-size:0.75rem;">doc #${f.doc_id}</a></div>`;
    }).join('') : '<span style="color:var(--text-muted); font-size:0.83rem;">The documents agree with the databases.</span>';
    const timeline = i.timeline.map(t => `<tr${t.origin === 'document' ? ' style="background:#fffbeb"' : ''}>
      <td class="mono">${esc(t.date)}</td><td>${esc(t.event.replace(/_/g, ' '))}</td><td>${esc(t.detail)}</td>
      <td>${t.origin === 'document' ? '📄 ' : '🗄️ '}${esc(t.source)}</td></tr>`).join('');
    return `<div style="border:1px solid #e2e8f0; border-radius:8px; padding:0.9rem; margin-bottom:1rem;">
      <div style="font-weight:700; font-family:var(--font-mono); margin-bottom:0.5rem;">${esc(p)} <span style="font-weight:400; color:var(--text-muted); font-family:inherit; font-size:0.8rem;">${i.documents.length} document(s) about this vehicle</span></div>
      <div class="ctx-grid" style="gap:1rem;">
        <dl class="ctx-kv">${kv.map(([k, val]) => `<dt>${k}</dt><dd>${esc(val ?? '—')}</dd>`).join('')}</dl>
        <div><div style="font-weight:600; font-size:0.85rem; margin-bottom:0.3rem;">Findings from the documents</div>${findings}</div>
      </div>
      <details style="margin-top:0.6rem;" open><summary style="cursor:pointer; font-size:0.85rem; color:var(--accent-primary);">Timeline (🗄️ databases + 📄 documents)</summary>
        <table class="data-table" style="margin-top:0.4rem;"><thead><tr><th>Date</th><th>Event</th><th>Detail</th><th>Source</th></tr></thead><tbody>${timeline}</tbody></table>
      </details></div>`;
  }).join('');
}

function renderDocuments(docs) {
  const meta = document.getElementById('ctx-doc-meta');
  const box = document.getElementById('ctx-docs');
  if (!docs || docs.status !== 200) {
    meta.textContent = '';
    box.innerHTML = `<span style="color:#b91c1c">Document store unreachable: ${esc(docs && docs.error)}</span>`;
    return;
  }
  meta.textContent = `${docs.method} · searched ${docs.searched} documents at ${docs.endpoint.replace('/api/v1/search', '')}` +
    (docs.hidden_by_role ? ` · ${docs.hidden_by_role} not visible to your role` : '') + ` · ${docs.latency_ms} ms`;
  const ctx = docs.search_context || {};
  const ctxLine = `<div style="font-size:0.78rem; color:var(--text-muted); margin-bottom:0.6rem;">Searched with: plates ${esc((ctx.plates || []).join(', ') || '—')} ·
    ids ${esc((ctx.ids || []).join(', ') || '—')} · places ${esc((ctx.cities || []).join(', ') || '—')} · vehicle ${esc((ctx.vehicle_words || []).join(' ') || '—')}
    · ${(ctx.terms || []).length} weighted context terms</div>`;
  box.innerHTML = ctxLine + (docs.results.length ? docs.results.map((r, n) => {
    const b = r.breakdown || {};
    const parts = [`text ${b.text}`];
    if (b.plate !== undefined) {
      parts.push(`plate ${b.plate}${b.plate_match ? ` (“${esc(b.plate_match.in_text)}” ≈ ${esc(b.plate_match.context_plate)})` : ''}`);
      if (b.ids && b.ids.length) parts.push(`ids ${esc(b.ids.join(', '))}`);
      if (b.places && b.places.length) parts.push(`place ${esc(b.places.join(', '))}`);
      if (b.dates && b.dates.length) parts.push(`date ${esc(b.dates.join(', '))}`);
    }
    return `<div id="doc-${r.doc_id}" style="border-bottom:1px dashed #e2e8f0; padding:0.55rem 0;">
      <div style="display:flex; justify-content:space-between; gap:1rem;">
        <div><b>#${n + 1}</b> <span class="ctx-agency-tag">${esc(r.doc_type.replace('_', ' '))}</span> <b>${esc(r.title)}</b>
          <span style="color:var(--text-muted); font-size:0.78rem;">· ${esc(r.source)} · ${esc(r.published_on)} · doc #${r.doc_id}</span></div>
        <div style="white-space:nowrap;"><b>${r.score}</b></div>
      </div>
      <div style="font-size:0.83rem; margin:0.25rem 0;">${marked(r.snippet)}</div>
      <div style="font-size:0.72rem; color:var(--text-muted);">score = ${parts.join(' · ')}</div>
    </div>`;
  }).join('') : '<span style="color:var(--text-muted)">No matching documents.</span>');
}

async function addDocument() {
  const body = document.getElementById('doc-body').value.trim();
  const msg = document.getElementById('doc-add-msg');
  if (!body) { msg.textContent = 'Write the document text first.'; return; }
  const { ok, data } = await API.addDocument({ doc_type: document.getElementById('doc-type').value, body });
  msg.textContent = ok ? `Added as doc #${data.doc_id} (${data.visibility}). Running the query again…` : (data.error || 'Failed');
  msg.style.color = ok ? '#047857' : '#b91c1c';
  if (ok && document.getElementById('ctx-query').value.trim()) runContext();
}
