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

  async issueEChallan(payload) {
    const res = await fetch(`${MEDIATOR_BASE_URL}/echallan/issue`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    return await res.json();
  },

  async invalidateCache(plate) {
    const res = await fetch(`${MEDIATOR_BASE_URL}/sync/invalidate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ vehicle_identifier: plate })
    });
    return await res.json();
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
