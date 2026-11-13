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
    const { ok, data } = await API.discoverContext(query);
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
