const HOSTNAME = (typeof window !== 'undefined' && window.location.hostname) ? window.location.hostname : '127.0.0.1';
const MEDIATOR_BASE_URL = `http://${HOSTNAME}:5001/api/v1`;

const API = {
  async getHealth() {
    const res = await fetch(`${MEDIATOR_BASE_URL}/health`);
    return await res.json();
  },

  async getVehicle(plate, forceSync = false) {
    const url = `${MEDIATOR_BASE_URL}/vehicles/${encodeURIComponent(plate)}?force_sync=${forceSync}`;
    const start = performance.now();
    const res = await fetch(url);
    const elapsed = Math.round(performance.now() - start);
    const data = await res.json();
    return { data, status: res.status, headers: res.headers, clientLatencyMs: elapsed };
  },

  async getFederatedTrace(plate) {
    const res = await fetch(`${MEDIATOR_BASE_URL}/vehicles/${encodeURIComponent(plate)}/trace`);
    return await res.json();
  },

  async getFleetKpis() {
    const res = await fetch(`${MEDIATOR_BASE_URL}/fleet/kpis`);
    return await res.json();
  },

  async getFleetDetections(params = {}) {
    const query = new URLSearchParams(params).toString();
    const start = performance.now();
    const res = await fetch(`${MEDIATOR_BASE_URL}/fleet/detections?${query}`);
    const elapsed = Math.round(performance.now() - start);
    const data = await res.json();
    return { ...data, clientLatencyMs: elapsed };
  },

  async getFleetCities() {
    const res = await fetch(`${MEDIATOR_BASE_URL}/fleet/cities`);
    return await res.json();
  },

  async getChallans(params = {}) {
    const query = new URLSearchParams(params).toString();
    const res = await fetch(`${MEDIATOR_BASE_URL}/echallan/challans${query ? `?${query}` : ''}`);
    return await res.json();
  },

  async updateChallanStatus(reportId, status) {
    const res = await fetch(`${MEDIATOR_BASE_URL}/echallan/challans/${reportId}/status`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ status })
    });
    return await res.json();
  },

  async issueEChallan(payload) {
    const res = await fetch(`${MEDIATOR_BASE_URL}/echallan/issue`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    return await res.json();
  },

  // ---- Approximate matching & data cleansing (/api/v1/matching) ----
  async _matching(path, options = {}) {
    const res = await fetch(`${MEDIATOR_BASE_URL}/matching${path}`, options);
    let data = null;
    try { data = await res.json(); } catch (e) { data = { error: `HTTP ${res.status}` }; }
    return { ok: res.ok, status: res.status, data };
  },

  _json(method, body) {
    return { method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body || {}) };
  },

  getMatchingConfig() { return this._matching('/config'); },

  ocrPlateImage(file) {
    const form = new FormData();
    form.append('image', file);
    return this._matching('/ocr', { method: 'POST', body: form });
  },

  searchPlate(payload) { return this._matching('/search', this._json('POST', payload)); },

  getNoisyRecords(params = {}) {
    const q = new URLSearchParams(Object.entries(params).filter(([, v]) => v)).toString();
    return this._matching(`/noisy-records${q ? `?${q}` : ''}`);
  },

  getNoisyRecord(id, method) {
    return this._matching(`/noisy-records/${id}${method ? `?method=${encodeURIComponent(method)}` : ''}`);
  },

  reviewNoisyRecord(id, payload) { return this._matching(`/noisy-records/${id}/review`, this._json('POST', payload)); },

  runCleansing(payload) { return this._matching('/cleanse', this._json('POST', payload)); },

  getAuditTrail(params = {}) {
    const q = new URLSearchParams(params).toString();
    return this._matching(`/audit${q ? `?${q}` : ''}`);
  },

  getMatchingEvaluation() { return this._matching('/evaluation'); },

  runMatchingEvaluation() { return this._matching('/evaluation/run', { method: 'POST' }); },

  refreshMatchingIndex() { return this._matching('/index/refresh', { method: 'POST' }); },

  scanAgencyData() { return this._matching('/agency/scan'); },

  cleanseAgencyData() { return this._matching('/agency/cleanse', this._json('POST', {})); },

  reviewAgencyRow(payload) { return this._matching('/agency/review', this._json('POST', payload)); },

  getAgencyChanges(params = {}) {
    const q = new URLSearchParams(params).toString();
    return this._matching(`/agency/changes${q ? `?${q}` : ''}`);
  },

  async verifySqlAuth(credentials) {
    const res = await fetch(`${MEDIATOR_BASE_URL}/sql/auth`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(credentials)
    });
    const data = await res.json();
    return { ok: res.ok, status: res.status, data };
  },

  async executeSql(payload) {
    const start = performance.now();
    const res = await fetch(`${MEDIATOR_BASE_URL}/sql/execute`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    const clientElapsed = Math.round(performance.now() - start);
    const data = await res.json();
    return { ok: res.ok, status: res.status, data, clientLatencyMs: clientElapsed };
  }
};
