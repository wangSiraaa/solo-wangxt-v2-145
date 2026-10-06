const BASE = "/api";

async function request(path, options) {
  const resp = await fetch(BASE + path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!resp.ok) throw new Error(`${resp.status} ${await resp.text()}`);
  return resp.json();
}

export const api = {
  listVoyages: () => request("/voyages/"),
  getTimeline: (id) => request(`/voyages/${id}/timeline/`),
  calculate: (id) => request(`/voyages/${id}/calculate/`, { method: "POST" }),
  listSettlements: (voyageId) => request(`/settlements/?voyage=${voyageId}`),
};
