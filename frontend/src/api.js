const BASE = "/api";

async function request(path, options = {}) {
  const resp = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!resp.ok) {
    let detail;
    try {
      detail = await resp.json();
    } catch {
      detail = { detail: resp.statusText };
    }
    const err = new Error(detail.detail || `请求失败 ${resp.status}`);
    err.payload = detail;
    err.status = resp.status;
    throw err;
  }
  if (resp.status === 204) return null;
  return resp.json();
}

export const api = {
  listVoyages: () => request("/voyages/"),
  getVoyage: (id) => request(`/voyages/${id}/`),
  calculate: (id) => request(`/voyages/${id}/calculate/`, { method: "POST" }),
  settle: (id, note = "") =>
    request(`/voyages/${id}/settle/`, { method: "POST", body: JSON.stringify({ note }) }),
  listSettlements: (voyageId) => request(`/settlements/?voyage=${voyageId}`),
  finalizeSettlement: (id) => request(`/settlements/${id}/finalize/`, { method: "POST" }),
  deleteSettlement: (id) => request(`/settlements/${id}/`, { method: "DELETE" }),
  patchEvent: (id, data) =>
    request(`/events/${id}/`, { method: "PATCH", body: JSON.stringify(data) }),
  patchStoppage: (id, data) =>
    request(`/stoppages/${id}/`, { method: "PATCH", body: JSON.stringify(data) }),
};
